"""tools/zeiierman_vwap_range.py - "VWAP Range Breakout (Zeiierman)" (Pine v6 indicator, pasted by the user 2026-10-28),
ported at its defaults and traded on NIFTY near-month futures (S157).

Port (defaults: Re-anchor 3, Equilibrium 20, Deviation memory 100, Width 4.0; Smart Trend VWAP length 200, Sensitivity 1.5;
volume = the futures volume, 1 when 0; tick 0.05). The range: on a new range, mid = the 3-bar VWAP of hlc3, hi / lo = mid +/-
width, width = max(4 x the volume-weighted deviation of hlc3 from the 20-bar VWAP over 100 bars, the bar's own reach from
mid); a new range forms when a whole candle closes beyond it (low crosses over hi = breakout up; high crosses under lo =
breakout down). Interior lines hiMid / loMid halfway to mid. Arrows: buy = low crosses over loMid, sell = high crosses
under hiMid, while the range is unchanged. X: high crosses back under hi (failed upper), low back over lo (failed lower).
Retest: within 12 bars of a breakout, a bar touching the broken boundary +/- 0.15 ATR and closing beyond it the break's way
with a candle that way. Smart Trend: the script's step-structure on the 200-bar VWAP with the ATR-adaptive step, the
reversal VWAP, two bars of agreement -> trend +1 / -1, else 0.

Trades, fixed before the run (signals on a closed bar, in at the next bar's open; entries 09:20 - 14:30; everything out at
the open of the first bar starting at or after 15:20; one position at a time; 1 lot of 65; costs = tools/bandlab.evaluate):
  BRK   breakout circles: long on a breakout up, short on a breakout down; out on the opposite breakout (and reverse) or EOD
  BRK+T the same, only when the Smart Trend agrees at the signal (the script's own trend)
  RET   retests: long on a bullish retest, short on a bearish one; out on the opposite breakout, a close back past the broken
        boundary, or EOD
  ARR   arrows (mean reversion inside the range): buy arrow long / sell arrow short; out at a close past the range centre
        (target), any new range (breakout), or EOD
  XF    X markers (fakeouts): failed upper -> short, failed lower -> long; out as ARR
  timeframes 1, 5, 15 minutes; pick = the best 2018-22 PF with >= 200 trades; 2023-26 and 2026 read without re-picking.
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from numba import njit
import core, bandlab as BL
f, MIN1, cut1, ses1, year1 = BL.data()
TICK = 0.05


@njit(cache=True)
def _rsum(x, n):
    out = np.full(len(x), np.nan); s = 0.0
    for i in range(len(x)):
        s += x[i]
        if i >= n: s -= x[i - n]
        if i >= n - 1: out[i] = s
    return out


@njit(cache=True)
def _rma(x, n):
    out = np.full(len(x), np.nan); a = 0.0; s = 0.0
    for i in range(len(x)):
        if i < n:
            s += x[i]
            if i == n - 1: a = s / n; out[i] = a
        else:
            a = (a * (n - 1) + x[i]) / n; out[i] = a
    return out


@njit(cache=True)
def _sma_std(x, n):
    m = np.full(len(x), np.nan); sd = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        w = x[i - n + 1:i + 1]
        if np.isnan(w).any(): continue
        mu = w.mean(); m[i] = mu; sd[i] = np.sqrt(((w - mu) ** 2).mean())
    return m, sd


@njit(cache=True)
def engine(h, l, c, o, v):
    n = len(c)
    wt = np.where(v > 0, v, 1.0); hlc3 = (h + l + c) / 3.0; pv = hlc3 * wt
    seedPV = _rsum(pv, 34); seedV = _rsum(wt, 34)
    baseVW = _rsum(pv, 3) / np.maximum(_rsum(wt, 3), 1e-8)
    eqVW = _rsum(pv, 20) / np.maximum(_rsum(wt, 20), 1e-8)
    res = hlc3 - eqVW
    rr = np.where(np.isnan(res), 0.0, wt * res * res)
    dev = np.sqrt(np.maximum(0.0, _rsum(rr, 100) / np.maximum(_rsum(wt, 100), 1e-8)))
    tr = np.empty(n)
    for i in range(n):
        tr[i] = h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    aFast = _rma(tr, 14); aSlow = _rma(tr, 56); aMean, aDev = _sma_std(aFast, 120)
    trVW = _rsum(pv, 200) / np.maximum(_rsum(wt, 200), 1e-8)
    MID = np.full(n, np.nan); HI = np.full(n, np.nan); LO = np.full(n, np.nan); HM = np.full(n, np.nan); LM = np.full(n, np.nan)
    brU = np.zeros(n, np.bool_); brD = np.zeros(n, np.bool_); buy = np.zeros(n, np.bool_); sell = np.zeros(n, np.bool_)
    fU = np.zeros(n, np.bool_); fD = np.zeros(n, np.bool_); rU = np.zeros(n, np.bool_); rD = np.zeros(n, np.bool_)
    TREND = np.zeros(n, np.int8); BRL = np.full(n, np.nan)
    mid = np.nan; hi = np.nan; lo = np.nan; hm = np.nan; lm = np.nan; sumPV = np.nan; sumV = np.nan
    tHi = np.nan; tLo = np.nan; d = 0; dprev = 0; revPV = np.nan; revV = np.nan
    upS = 0; dnS = 0; trend = 0
    brDir = 0; brLvl = np.nan; brBar = 0
    for i in range(1, n):
        width = max(max(dev[i] * 4.0, TICK * 2), max(abs(h[i] - baseVW[i]), abs(l[i] - baseVW[i])) + TICK)
        ready = i >= 100 and not np.isnan(baseVW[i])
        hi_p, lo_p = hi, lo                                        # range as carried into this bar
        # crossover(low, hi) before this bar's update: hi now = hi[1] = HI[i-1]
        bu = (not np.isnan(hi_p)) and l[i] > hi_p and l[i - 1] <= hi_p
        bd = (not np.isnan(lo_p)) and h[i] < lo_p and h[i - 1] >= lo_p
        brU[i] = bu; brD[i] = bd
        new = ready and (np.isnan(mid) or bu or bd)
        if new:
            mid = baseVW[i]; hi = mid + width; lo = mid - width; hm = (mid + hi) / 2; lm = (mid + lo) / 2
            sumPV = seedPV[i]; sumV = seedV[i]
        elif not np.isnan(sumPV):
            sumPV += pv[i]; sumV += wt[i]
        MID[i] = mid; HI[i] = hi; LO[i] = lo; HM[i] = hm; LM[i] = lm
        rngVW = sumPV / max(sumV, 1e-8) if not np.isnan(sumPV) else np.nan
        # smart trend
        trReady = not np.isnan(trVW[i]) and not np.isnan(aMean[i])
        flip = False
        if trReady:
            z = (aFast[i] - aMean[i]) / aDev[i] if aDev[i] > 0 else 0.0
            vr = aFast[i] / aSlow[i] if aSlow[i] > 0 else 1.0
            x = 4.0 * (vr - 1.0) + 0.75 * min(3.0, max(-3.0, z))
            step = aFast[i] * 1.5 * (0.5 + 1.5 / (1.0 + np.exp(-x)))
            if step > 0:
                dprev = d
                if np.isnan(tHi):
                    tHi = trVW[i]; tLo = trVW[i] - step; d = 1
                else:
                    eu = trVW[i] > tHi + step; ed = trVW[i] < tLo - step
                    nd = 1 if eu else (-1 if ed else d)
                    if eu or ed:
                        ref = tHi if nd == 1 else tLo
                        k = max(1, int(np.floor(abs(trVW[i] - ref) / step)))
                        if nd == 1:
                            tLo = tHi + (k - 1) * step; tHi = tHi + k * step
                        else:
                            tHi = tLo - (k - 1) * step; tLo = tLo - k * step
                        d = nd
                flip = d != 0 and dprev != 0 and d != dprev
                if flip or np.isnan(revPV):
                    revPV = pv[i]; revV = wt[i]
                else:
                    revPV += pv[i]; revV += wt[i]
        atr = aFast[i] if not np.isnan(aFast[i]) else TICK
        revVW = revPV / revV if (not np.isnan(revV) and revV > 0) else np.nan
        anch = trReady and not np.isnan(rngVW) and not np.isnan(revVW)
        upA = anch and d == 1 and c[i] > rngVW and c[i] > revVW + atr * 0.05
        dnA = anch and d == -1 and c[i] < rngVW and c[i] < revVW - atr * 0.05
        upS = upS + 1 if upA else 0; dnS = dnS + 1 if dnA else 0
        if flip: trend = 0
        if upS >= 2: trend = 1
        elif dnS >= 2: trend = -1
        elif trend == 1 and (d != 1 or (not np.isnan(revVW) and c[i] < revVW - atr * 0.15)): trend = 0
        elif trend == -1 and (d != -1 or (not np.isnan(revVW) and c[i] > revVW + atr * 0.15)): trend = 0
        TREND[i] = trend
        # signals while the range is unchanged
        steady = (not np.isnan(mid)) and (not np.isnan(MID[i - 1])) and mid == MID[i - 1]
        if steady and i >= 2:
            buy[i] = l[i] > lm and l[i - 1] <= LM[i - 1]
            sell[i] = h[i] < hm and h[i - 1] >= HM[i - 1]
            fU[i] = h[i] < hi and h[i - 1] >= HI[i - 1]
            fD[i] = l[i] > lo and l[i - 1] <= LO[i - 1]
        # retests
        if bu or bd:
            brDir = 1 if bu else -1; brLvl = hi_p if bu else lo_p; brBar = i
        elif brDir != 0:
            tol = atr * 0.15
            if i - brBar > 12:
                brDir = 0
            else:
                ru = brDir == 1 and l[i] >= brLvl - tol and l[i] <= brLvl + tol and c[i] > brLvl and c[i] > o[i]
                rd = brDir == -1 and h[i] >= brLvl - tol and h[i] <= brLvl + tol and c[i] < brLvl and c[i] < o[i]
                rU[i] = ru; rD[i] = rd
                if ru or rd:
                    BRL[i] = brLvl; brDir = 0
    return MID, HI, LO, brU, brD, buy, sell, fU, fD, rU, rD, TREND, BRL


def series(tf):
    B, last = BL.tf_bars(tf)
    t = np.asarray(B.t)
    return (np.asarray(B.o, float), np.asarray(B.h, float), np.asarray(B.l, float), np.asarray(B.c, float),
            np.asarray(B.v, float), t // core.DAY, (t % core.DAY) // 60, last)


def simulate(tf, kind, S):
    o, h, l, c, v, day, smin, last = S["bars"]
    MID, HI, LO, brU, brD, buy, sell, fU, fD, rU, rD, TR, BRL = S["eng"]
    n = len(c); out = []; pos = 0
    first1 = np.r_[0, last[:-1] + 1]
    def fin(e, x, why):
        out.append((pos, int(first1[e]), int(first1[x]), o[e], o[x], why))
    for i in range(200, n - 1):
        j = i + 1
        if pos:
            if day[j] != day[i] or smin[j] >= 920:
                fin(e, j if day[j] == day[i] else i, "eod") if day[j] == day[i] else out.append((pos, int(first1[e]), int(last[i]), o[e], c[i], "eod")); pos = 0; continue
            why = None
            if kind in ("BRK", "BRK+T", "RET"):
                if (pos > 0 and brD[i]) or (pos < 0 and brU[i]): why = "opposite break"
                elif kind == "RET" and ((pos > 0 and c[i] < lvl) or (pos < 0 and c[i] > lvl)): why = "back inside"
            else:
                if brU[i] or brD[i]: why = "new range"
                elif (pos > 0 and c[i] >= MID[i]) or (pos < 0 and c[i] <= MID[i]): why = "centre"
            if why:
                fin(e, j, why); old = pos; pos = 0
                if why == "opposite break" and kind in ("BRK", "BRK+T") and 560 <= smin[i] <= 870:
                    s = -old
                    if kind == "BRK" or TR[i] == s: pos, e = s, j
                continue
        if pos or not (560 <= smin[i] <= 870) or day[j] != day[i]: continue
        s = 0
        if kind == "BRK": s = 1 if brU[i] else -1 if brD[i] else 0
        elif kind == "BRK+T": s = 1 if brU[i] and TR[i] == 1 else -1 if brD[i] and TR[i] == -1 else 0
        elif kind == "RET":
            s = 1 if rU[i] else -1 if rD[i] else 0
            if s: lvl = BRL[i]
        elif kind == "ARR": s = 1 if buy[i] else -1 if sell[i] else 0
        elif kind == "XF": s = -1 if fU[i] else 1 if fD[i] else 0
        if s: pos, e = s, j
    return out


if __name__ == "__main__":
    print("| Timeframe | Rule | Trades | Avg hold, min | Gross pts / trade | Win % | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ | Max DD 2023-26 ₹ |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    R = {}
    for tf in (1, 5, 15):
        bars = series(tf); o, h, l, c, v, day, smin, last = bars
        S = dict(bars=bars, eng=engine(h, l, c, o, v))
        brU, brD = S["eng"][3], S["eng"][4]
        print(f"<!-- {tf}m: ranges formed {int(brU.sum() + brD.sum())} breaks over {len(np.unique(day))} days -->", flush=True)
        for kind in ("BRK", "BRK+T", "RET", "ARR", "XF"):
            r = BL.evaluate(simulate(tf, kind, S), f"{tf}m {kind}"); R[(tf, kind)] = r
            if not r.get("n"): print(f"| {tf}m | {kind} | 0 |"); continue
            print(f"| {tf}m | {kind} | {r['n']} | {r['hold_min']:.0f} | {r['gross_pts']:+.2f} | {r['win']:.0f} | {r['pfA']:.2f} | {r['pfB']:.2f} | {r['pf26']:.2f} | "
                  f"{r['netA']:+,.0f} | {r['netB']:+,.0f} | {r['net26']:+,.0f} | {r['ddB']:+,.0f} |", flush=True)
    pick = max((k for k in R if R[k].get("nA", 0) >= 200), key=lambda k: R[k]["pfA"])
    print(f"\npick (best 2018-22 PF, >= 200 trades): **{pick[0]}m {pick[1]}**")
