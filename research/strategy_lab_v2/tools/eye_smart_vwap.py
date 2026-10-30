"""tools/eye_smart_vwap.py - "Eye Smart VWAP [EyeAlgo]" (Pine v6, source pasted by the user 2026-10-29) ported at its defaults
and its retest setups traded on NIFTY near-month futures (S160).

Port (preset "Auto by timeframe"): <= 5m -> swing 6, min gap 8 bars between anchors, stretch 2.0 sigma; 15m-60m -> 10 / 10 / 1.5.
  * swings = ta.pivothigh / pivotlow(swingLen, swingLen), known swingLen bars later; a swing is "used" once broken / swept
  * anchor events (in priority): structure break up (close > unused swing high) -> anchor at the lowest low since that
    swing (<= 300 bars); break down mirror; liquidity sweep (wick >= 0.25 ATR(14) beyond an unused swing, close back
    inside) -> anchor on that bar; at least `gap` bars since the last event
  * Smart VWAP = hlc3 weighted by volume (futures have it; range if a bar has none) from the anchor bar, sigma = weighted
    standard deviation; Daily / Weekly VWAP from the session / week start
  * retest setup: long if the anchor was bullish, price was >= stretch sigma above the VWAP within the last 30 bars
    (measured >= 10 bars after the anchor with sigma >= 0.3 ATR), this bar's low comes within 0.25 sigma of the VWAP and it
    closes above it as a green candle, close above the Daily and the Weekly VWAP, VWAP above its value 3 bars back,
    first retest of this anchor, no setup open; short mirror
  * stop = 1 sigma beyond the VWAP (at least 0.5 ATR from entry); half out at 1R and the stop to entry; rest at 2R; time
    exit after 60 bars. Entry at the signal bar's close (as the script's tE = close).
Trading it (fixed before the run): one setup = 2 lots of 65 (one per half). Stops / targets checked on the tf bars as the
script does (stop first if a bar touches both), filled at the worse of open / stop and at the target (or the open if it
gapped through). Costs per lot per round trip: 1 point slippage + dated futures charges. Variants: as written (held
across sessions; closed at the last bar of a futures contract), and intraday (no entry after 15:00, flat at the 15:15 bar's
open). Sides: both, long only, short only. Charts 1 / 5 / 15 / 60 minutes. Pick = best 2018-22 PF (>= 50 setups), read on
2023-26 and 2026 without re-picking.
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from numba import njit
import core, bandlab as BL
JF = BL.JF
f, MIN1, cut, ses, year1 = BL.data()
EXP = np.asarray(f.extra["expiry"])
LOT = 65


@njit(cache=True)
def _rma_atr(h, l, c, n):
    out = np.zeros(len(c)); a = 0.0
    for i in range(len(c)):
        tr = h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        if i < n: a = (a * i + tr) / (i + 1)          # Pine ta.atr seeds with the SMA of the first n
        else: a = (a * (n - 1) + tr) / n
        out[i] = a
    return out


@njit(cache=True)
def _pivots(h, l, L):
    """ph[i] / pl[i] = the pivot value confirmed at bar i (pivot at i - L), else nan. Pine: left strictly lower, right not higher."""
    n = len(h); ph = np.full(n, np.nan); pl = np.full(n, np.nan)
    for i in range(2 * L, n):
        p = i - L; okh = True; okl = True
        for k in range(p - L, p + L + 1):
            if k == p: continue
            if k < p:
                if h[k] >= h[p]: okh = False
                if l[k] <= l[p]: okl = False
            else:
                if h[k] > h[p]: okh = False
                if l[k] < l[p]: okl = False
        if okh: ph[i] = h[p]
        if okl: pl[i] = l[p]
    return ph, pl


@njit(cache=True)
def _engine(o, h, l, c, w, src, atr, newD, newW, ph, pl, sLen, gapN, awayN):
    """per bar: signal (+1 / -1 / 0), vw, sd at the signal, daily / weekly VWAP."""
    n = len(c); sig = np.zeros(n, np.int8); VW = np.full(n, np.nan); SD = np.full(n, np.nan); AID = np.full(n, -1, np.int64)
    dW = 0.0; dP = 0.0; wW = 0.0; wP = 0.0
    shP = np.nan; shB = -1; shUsed = True; slP = np.nan; slB = -1; slUsed = True
    lastEvt = -1; aBar = -1; aW = 0.0; aP = 0.0; aP2 = 0.0; aDir = 0
    seg = np.full(n, np.nan)                         # Smart VWAP value per bar of the current segment
    segStart = -1
    awayUp = -1; awayDn = -1; nA = -1
    for i in range(n):
        if newD[i]: dW = 0.0; dP = 0.0
        if newW[i]: wW = 0.0; wP = 0.0
        dW += w[i]; dP += w[i] * src[i]; wW += w[i]; wP += w[i] * src[i]
        dV = dP / dW; wV = wP / wW
        if not np.isnan(ph[i]): shP = ph[i]; shB = i - sLen; shUsed = False
        if not np.isnan(pl[i]): slP = pl[i]; slB = i - sLen; slUsed = False
        bosUp = (not np.isnan(shP)) and (not shUsed) and c[i] > shP
        bosDn = (not np.isnan(slP)) and (not slUsed) and c[i] < slP
        swpBu = (not np.isnan(slP)) and (not slUsed) and l[i] < slP and c[i] > slP and (slP - l[i]) >= 0.25 * atr[i]
        swpBe = (not np.isnan(shP)) and (not shUsed) and h[i] > shP and c[i] < shP and (h[i] - shP) >= 0.25 * atr[i]
        if bosUp or swpBe: shUsed = True
        if bosDn or swpBu: slUsed = True
        canAnchor = lastEvt < 0 or i - lastEvt >= gapN
        evBar = -1; evDir = 0
        if canAnchor:
            if bosUp:
                lb = min(i - shB, 300); idx = 0; lo = l[i]
                for k in range(0, lb + 1):
                    if i - k >= 0 and l[i - k] < lo: lo = l[i - k]; idx = k
                evBar = i - idx; evDir = 1
            elif bosDn:
                lb = min(i - slB, 300); idx = 0; hi = h[i]
                for k in range(0, lb + 1):
                    if i - k >= 0 and h[i - k] > hi: hi = h[i - k]; idx = k
                evBar = i - idx; evDir = -1
            elif swpBu: evBar = i; evDir = 1
            elif swpBe: evBar = i; evDir = -1
        newAnchor = evBar >= 0
        if newAnchor:
            aW = 0.0; aP = 0.0; aP2 = 0.0
            for k in range(evBar, i + 1):
                aW += w[k]; aP += w[k] * src[k]; aP2 += w[k] * src[k] * src[k]; seg[k] = aP / aW
            segStart = evBar; aBar = evBar; lastEvt = i; aDir = evDir; nA += 1
        elif aBar >= 0:
            aW += w[i]; aP += w[i] * src[i]; aP2 += w[i] * src[i] * src[i]; seg[i] = aP / aW
        vw = aP / aW if aW > 0 else np.nan
        sd = np.sqrt(max(aP2 / aW - vw * vw, 0.0)) if aW > 0 else np.nan
        z = (c[i] - vw) / sd if (aW > 0 and sd > 0) else np.nan
        VW[i] = vw; SD[i] = sd
        statOk = lastEvt >= 0 and (not newAnchor) and i - lastEvt >= 10 and sd >= 0.3 * atr[i]
        if newAnchor: awayUp = -1; awayDn = -1
        AID[i] = nA
        wasUp = awayUp >= 0 and i - awayUp <= 30
        wasDn = awayDn >= 0 and i - awayDn <= 30
        if statOk and z >= awayN: awayUp = i
        if statOk and z <= -awayN: awayDn = i
        vw3 = seg[i - 3] if (i - 3 >= segStart and segStart >= 0) else np.nan
        baseOk = aBar >= 0 and sd > 0 and statOk           # "max 1 retest per anchor" and "no setup open" are applied in run()
        if baseOk:
            if aDir == 1 and l[i] <= vw + 0.25 * sd and c[i] > vw and c[i] > o[i] and wasUp and c[i] > dV and c[i] > wV and (not np.isnan(vw3)) and vw > vw3:
                sig[i] = 1
            elif aDir == -1 and h[i] >= vw - 0.25 * sd and c[i] < vw and c[i] < o[i] and wasDn and c[i] < dV and c[i] < wV and (not np.isnan(vw3)) and vw < vw3:
                sig[i] = -1
    return sig, VW, SD, AID


def bars(tf):
    B, last = BL.tf_bars(tf)
    o, h, l, c = (np.asarray(x, float) for x in (B.o, B.h, B.l, B.c)); v = np.asarray(B.v, float)
    day = f.day[last]; t = np.asarray(B.t)
    wk = np.array([pd.Timestamp(core.dstr(int(d))).isocalendar()[1] + 100 * pd.Timestamp(core.dstr(int(d))).year for d in day])
    newD = np.r_[True, day[1:] != day[:-1]]; newW = np.r_[True, wk[1:] != wk[:-1]]
    mins = (t % core.DAY) // 60                                  # bar start minute of day
    return o, h, l, c, v, day, newD, newW, mins, EXP[last]


def run(tf, intraday, sides):
    o, h, l, c, v, day, newD, newW, mins, ex = bars(tf)
    sLen, gapN, awayN = (6, 8, 2.0) if tf <= 5 else (10, 10, 1.5)
    rng = h - l; w = np.where(v > 0, v, rng); w = np.maximum(w, 1e-10)
    atr = _rma_atr(h, l, c, 14); ph, pl = _pivots(h, l, sLen)
    sig, VW, SD, AID = _engine(o, h, l, c, w, (h + l + c) / 3, atr, newD, newW, ph, pl, sLen, gapN, awayN)
    n = len(c); trades = []; i = 0
    lastbar = np.r_[day[1:] != day[:-1], True]; lastc = np.r_[ex[1:] != ex[:-1], True]
    # the script opens a setup only when none is open (a trade closing on this bar frees it) and counts a retest only when
    # a setup opens: max 1 per anchor
    busy = -1; used = set()
    for i in np.nonzero(sig)[0]:
        d = int(sig[i])
        if i < busy or d not in sides or AID[i] in used: continue
        if intraday and (mins[i] + tf > 900 or lastbar[i]): continue
        if lastc[i]: continue
        E = c[i]; slRaw = VW[i] - d * SD[i]; dist = max(abs(E - slRaw), 0.5 * atr[i])
        SL = E - d * dist; T1 = E + d * dist; T2 = E + d * 2 * dist
        hit1 = False; legs = []; j = i + 1; stop = SL
        while j < n:
            if intraday and (mins[j] >= 915 or day[j] != day[i]):
                px = o[j] if day[j] == day[i] else c[j - 1]
                legs += [px] * (2 - len(legs)); break
            hs = (l[j] <= stop) if d > 0 else (h[j] >= stop)
            h1 = (h[j] >= T1) if d > 0 else (l[j] <= T1)
            h2 = (h[j] >= T2) if d > 0 else (l[j] <= T2)
            fill = lambda lv: (min(o[j], lv) if d > 0 else max(o[j], lv))
            tfill = lambda lv: (max(o[j], lv) if d > 0 else min(o[j], lv))
            if not hit1:
                if hs: legs = [fill(stop), fill(stop)]; break
                if h2: legs = [tfill(T1), tfill(T2)]; break
                if h1: legs = [tfill(T1)]; hit1 = True; stop = E
            else:
                if hs: legs.append(fill(stop)); break
                if h2: legs.append(tfill(T2)); break
            if j - i >= 60: legs += [c[j]] * (2 - len(legs)); break
            if lastc[j] and not intraday: legs += [c[j]] * (2 - len(legs)); break
            j += 1
        if len(legs) < 2: legs += [c[min(j, n - 1)]] * (2 - len(legs))
        j = min(j, n - 1)
        dd = core.dstr(int(day[i])); ch = JF._charges(dd, "FUT", E, E, LOT)["total"] / LOT + 1.0
        pts = sum(d * (x - E) for x in legs)
        trades.append(dict(yy=int(dd[:4]), day=dd, side=d, bars=j - i, pts=pts, R=pts / 2 / dist, net=(pts - 2 * ch) * LOT,
                           out="stop" if legs[0] == legs[1] and abs(legs[0] - SL) < 1e-9 else "other"))
        busy = j; used.add(AID[i])
    return pd.DataFrame(trades)


def pf(x):
    if not len(x): return np.nan
    w_ = x[x > 0].sum(); l_ = -x[x <= 0].sum(); return w_ / l_ if l_ else np.inf


if __name__ == "__main__":
    rows = []
    for tf in (1, 5, 15, 60):
        for intraday in (False, True):
            for sname, sides in (("both", (1, -1)), ("long", (1,)), ("short", (-1,))):
                T = run(tf, intraday, sides)
                if not len(T): continue
                A, B_, Z = T[T.yy <= 2022].net, T[T.yy >= 2023].net, T[T.yy == 2026].net; eq = T.net.cumsum()
                rows.append(dict(chart=f"{tf}m", hold="intraday" if intraday else "as written", side=sname, setups=len(T), per_yr=round(len(T) / 8.8),
                                 win=round((T.net > 0).mean() * 100), avgR=round(T.R.mean(), 2), gross_pts=round(T.pts.mean(), 1),
                                 pfA=round(pf(A), 2), pfB=round(pf(B_), 2), pf26=round(pf(Z), 2), netA=round(A.sum()), netB=round(B_.sum()),
                                 net26=round(Z.sum()), dd=round((eq - eq.cummax()).min()), t=round(T.net.mean() / T.net.std() * np.sqrt(len(T)), 2)))
                print(rows[-1], flush=True)
    G = pd.DataFrame(rows); os.makedirs("results/eye_smart_vwap", exist_ok=True); G.to_csv("results/eye_smart_vwap/summary.csv", index=False)
    print("\n| Chart | Hold | Side | Setups | /yr | Win % | Avg R | Gross pts | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ | Max DD ₹ | t |\n|" + "---|" * 16)
    for r in G.itertuples():
        print(f"| {r.chart} | {r.hold} | {r.side} | {r.setups} | {r.per_yr} | {r.win} | {r.avgR:+.2f} | {r.gross_pts:+.1f} | {r.pfA:.2f} | {r.pfB:.2f} | {r.pf26:.2f} | {r.netA:+,} | {r.netB:+,} | {r.net26:+,} | {r.dd:+,} | {r.t} |")
    P = G[G.setups >= 50].sort_values("pfA", ascending=False).iloc[0]
    print(f"\npick (best 2018-22 PF, >= 50 setups): {P.chart} {P.hold} {P.side}: PF {P.pfA} / {P.pfB} / {P.pf26}, net {P.netA:+,} / {P.netB:+,} / {P.net26:+,}")
