"""tools/thinkmarkets4.py - the four community strategies of the ThinkMarkets article "Best community TradingView strategies
to trade in 2026", from the user's build guides (C:/Users/Admin/Downloads/*_Strategy.md, 2026-10-29), on NIFTY near-month
futures 2018-01 - 2026-10 (S161).

The guides are sketches, not the scripts' full sources; each is coded as its guide writes it, at the guide's defaults, plus
only the variants the guide itself names:
  DSAV  Dynamic Swing Anchored VWAP: pivots(swing period, both sides); regime bullish when the newest confirmed pivot is a
        low; long when the regime turns bullish, flat when it turns bearish (the strategy is long-only; the short mirror
        is also run). Swing period 50 (default), 20, 100. (The VWAP itself does not drive the orders in the guide.)
  ICT   Holy Trinity: swing length 10; liquidity sweep = low below the last confirmed swing low by >= 0.5 ATR(14) and a
        close back above it; structure = close > SMA 50 (the guide's skeleton) or the last break of structure upward
        (close beyond the last swing high, a proper BOS); trend = close > EMA 200. Long on the sweep candle's close when
        all three hold; stop at the sweep candle's low; target 2R (3R also run). Shorts mirror.
  DIAM  Diamond-Triangle: EMA 10 / 20 cloud; higher low = low > lowest(low,3)[1] and low == lowest(low,3) (the guide's
        formula), lower high mirror; chop filter |EMA10 - EMA20| / close > 0.1 %; diamond = the structure on the wrong
        side of the cloud, triangle = the right side; long on either; stop entry - 2 ATR(14) fixed (the skeleton) or
        trailed at close - 2 ATR ("dynamic trailing"). Shorts mirror; an opposite signal reverses.
  DMI   DMI Toolbox: DMI(14) with Wilder ADX; long when +DI crosses above -DI and ADX > 25; exit when -DI crosses above
        +DI or ADX turns down (adx < adx[1] and adx[1] > adx[2]). Long-only (the script) and the short mirror; ADX 20 / 25 /
        30 / no filter (the guide's test list).
Common, fixed before the run: signals on a bar's close, orders at the next bar's open (TradingView's default); stops and
targets intrabar, stop first if a bar touches both, stops at the worse of open / stop, targets at the level (or the open
past it). Charts 5m / 15m / 60m (09:15-aligned) and daily. Hold: positional (as the scripts; at a futures roll the bar's
open-to-close counts and the roll costs a round trip) and intraday (5m-60m: no entry after 15:00, flat at the 15:15 bar's
open). Costs per round trip: 1 point slippage + the dated futures charges, 1 lot of 65. Pick = best 2018-22 PF with >= 100
trades, judged on 2023-26 and 2026 without re-picking.
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
import core, bandlab as BL
JF = BL.JF
f, MIN1, cut, ses, year1 = BL.data()
EXP = np.asarray(f.extra["expiry"])
LOT = 65


def bars(tf):
    if tf == "D":
        a, z = cut[:-1], cut[1:]
        return (f.o[a].astype(float), np.maximum.reduceat(f.h, a).astype(float), np.minimum.reduceat(f.l, a).astype(float), f.c[z - 1].astype(float),
                f.day[a], np.full(len(a), 555), EXP[z - 1])
    B, last = BL.tf_bars(tf); t = np.asarray(B.t)
    return (np.asarray(B.o, float), np.asarray(B.h, float), np.asarray(B.l, float), np.asarray(B.c, float), f.day[last], (t % core.DAY) // 60, EXP[last])


# ---------------------------------------------------------------- indicators (Pine semantics)
def rma(x, n):
    out = np.full(len(x), np.nan); s = 0.0
    for i in range(len(x)):
        if i < n - 1: s += x[i]; continue
        if i == n - 1: s += x[i]; out[i] = s / n
        else: out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


def tr(h, l, c):
    pc = np.r_[c[0], c[:-1]]; t = np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)]); t[0] = h[0] - l[0]; return t


def ema(x, n): return pd.Series(x).ewm(span=n, adjust=False).mean().values


def pivots(h, l, L):
    """value confirmed at bar i for a pivot at i - L (left strictly lower / higher, right not beyond)."""
    n = len(h); ph = np.full(n, np.nan); pl = np.full(n, np.nan)
    H = pd.Series(h); Lw = pd.Series(l)
    lh = H.shift(1).rolling(L).max().values; rh = H[::-1].shift(1).rolling(L).max()[::-1].values
    ll = Lw.shift(1).rolling(L).min().values; rl = Lw[::-1].shift(1).rolling(L).min()[::-1].values
    with np.errstate(invalid="ignore"):
        isph = (h > lh) & (h >= rh); ispl = (l < ll) & (l <= rl)
    for p in np.nonzero(isph)[0]:
        if p + L < n: ph[p + L] = h[p]
    for p in np.nonzero(ispl)[0]:
        if p + L < n: pl[p + L] = l[p]
    return ph, pl


def dmi(h, l, c, n=14):
    up = np.r_[0, np.diff(h)]; dn = np.r_[0, -np.diff(l)]
    pdm = np.where((up > dn) & (up > 0), up, 0.0); ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = rma(tr(h, l, c), n)
    with np.errstate(all="ignore"):
        pdi = 100 * rma(pdm, n) / atr; ndi = 100 * rma(ndm, n) / atr
        dx = 100 * np.abs(pdi - ndi) / (pdi + ndi)
    adx = rma(np.nan_to_num(dx), n); adx[: 2 * n - 2] = np.nan
    return pdi, ndi, adx


# ---------------------------------------------------------------- generic simulator
def simulate(o, h, l, c, day, mins, ex, tf, enter, exit_long, exit_short, stop_fn=None, tgt_R=None, trail=None, intraday=False):
    """enter: int8 array (+1 / -1 / 0) on bar close -> order at the next open. exit_long / exit_short: bool arrays (state exits
    on bar close -> next open). stop_fn(i_signal, side, entry) -> initial stop or None. trail(i, side, stop) -> new stop."""
    n = len(c); pos = 0; T = []; cur = None; pend = 0; pend_exit = False
    last_bar = np.r_[day[1:] != day[:-1], True]; tfm = 1440 if tf == "D" else tf
    def close(i, px, why):
        nonlocal pos, cur
        cur.update(x=i, xp=px, why=why); T.append(cur); pos = 0; cur = None
    for i in range(1, n):
        # orders decided on bar i-1's close fill at bar i's open
        if pos and pend_exit: close(i, o[i], "signal"); pend_exit = False
        if pend and (pos != pend):
            if pos: close(i, o[i], "reverse")
            if not (intraday and (day[i] != day[i - 1] or mins[i] >= 915)):
                pos = pend; E = o[i]; cur = dict(e=i, s=pos, ep=E, rolls=0, pts_roll=0.0)
                cur["stop"] = stop_fn(i - 1, pos, E) if stop_fn else None
                cur["tgt"] = E + pos * tgt_R * abs(E - cur["stop"]) if (tgt_R and cur["stop"] is not None) else None
        pend = 0; pend_exit = False
        if not pos: pass
        else:
            if intraday and mins[i] >= 915 and tfm < 1440: close(i, o[i], "eod")
            else:
                if ex[i] != ex[i - 1]:                                   # futures roll: this bar's open-to-close counts
                    cur["pts_roll"] += pos * (c[i - 1] - cur.get("anchor", cur["ep"])) ; cur["anchor"] = o[i]; cur["rolls"] += 1
                st, tg = cur["stop"], cur["tgt"]
                if st is not None and ((pos > 0 and l[i] <= st) or (pos < 0 and h[i] >= st)):
                    close(i, min(o[i], st) if pos > 0 else max(o[i], st), "stop")
                elif tg is not None and ((pos > 0 and h[i] >= tg) or (pos < 0 and l[i] <= tg)):
                    close(i, max(o[i], tg) if pos > 0 else min(o[i], tg), "target")
                elif intraday and last_bar[i] and tfm < 1440: close(i, c[i], "eod")
                elif trail is not None: cur["stop"] = trail(i, pos, cur["stop"])
        # signals on bar i's close
        if pos and ((pos > 0 and exit_long[i]) or (pos < 0 and exit_short[i])): pend_exit = True
        if enter[i] and enter[i] != pos and not (intraday and (mins[i] + tfm > 900)): pend = int(enter[i])
    if cur: close(n - 1, c[n - 1], "end")
    rows = []
    for t in T:
        a = t.get("anchor", t["ep"]); pts = t["pts_roll"] + t["s"] * (t["xp"] - a)
        d = core.dstr(int(day[t["e"]])); ch = JF._charges(d, "FUT", t["ep"], t["ep"], LOT)["total"] / LOT + 1.0
        rows.append(dict(yy=int(d[:4]), side=t["s"], bars=t["x"] - t["e"], pts=pts, net=(pts - ch * (1 + t["rolls"])) * LOT, why=t["why"]))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- the four strategies
def strat(name, o, h, l, c, var):
    n = len(c); none = np.zeros(n, bool); atr = rma(tr(h, l, c), 14)
    if name == "DSAV":
        P, sides = var
        ph, pl = pivots(h, l, P); lastH = -1; lastL = -1; bull = np.zeros(n, bool)
        for i in range(n):
            if not np.isnan(ph[i]): lastH = i
            if not np.isnan(pl[i]): lastL = i
            bull[i] = lastL > lastH
        turnU = bull & ~np.r_[False, bull[:-1]]; turnD = ~bull & np.r_[False, bull[:-1]]
        en = np.where(turnU, 1, np.where(turnD & (sides == "both"), -1, 0)).astype(np.int8)
        return dict(enter=en, exit_long=turnD, exit_short=turnU)
    if name == "ICT":
        struct, R = var
        ph, pl = pivots(h, l, 10); sma50 = pd.Series(c).rolling(50).mean().values; e200 = ema(c, 200)
        en = np.zeros(n, np.int8); lsh = np.nan; lsl = np.nan; bos = 0; shx = True; slx = True
        for i in range(n):
            if not np.isnan(ph[i]): lsh = ph[i]; shx = False
            if not np.isnan(pl[i]): lsl = pl[i]; slx = False
            if not shx and c[i] > lsh: bos = 1; shx = True
            if not slx and c[i] < lsl: bos = -1; slx = True
            if np.isnan(atr[i]) or i < 200: continue
            sweepL = (not np.isnan(lsl)) and l[i] < lsl - 0.5 * atr[i] and c[i] > lsl
            sweepS = (not np.isnan(lsh)) and h[i] > lsh + 0.5 * atr[i] and c[i] < lsh
            stL = (c[i] > sma50[i]) if struct == "sma50" else bos == 1
            stS = (c[i] < sma50[i]) if struct == "sma50" else bos == -1
            if sweepL and stL and c[i] > e200[i]: en[i] = 1
            elif sweepS and stS and c[i] < e200[i]: en[i] = -1
        return dict(enter=en, exit_long=none, exit_short=none, stop_fn=lambda i, s, E: l[i] if s > 0 else h[i], tgt_R=R)
    if name == "DIAM":
        mode = var
        ef, es = ema(c, 10), ema(c, 20); lo3 = pd.Series(l).rolling(3).min().values; hi3 = pd.Series(h).rolling(3).max().values
        with np.errstate(invalid="ignore"):
            hl = (l > np.r_[np.nan, lo3[:-1]]) & (l == lo3); lh = (h < np.r_[np.nan, hi3[:-1]]) & (h == hi3)
            chop = np.abs(ef - es) / c * 100 > 0.1
        above = c > np.maximum(ef, es); below = c < np.minimum(ef, es)
        L_ = hl & (above | below) & chop; S_ = lh & (above | below) & chop
        en = np.where(L_, 1, np.where(S_, -1, 0)).astype(np.int8)
        tr_fn = (lambda i, s, st: max(st, c[i] - 2 * atr[i]) if s > 0 else min(st, c[i] + 2 * atr[i])) if mode == "trail" else None
        return dict(enter=en, exit_long=none, exit_short=none, stop_fn=lambda i, s, E: E - s * 2 * atr[i], trail=tr_fn)
    if name == "DMI":
        th, sides = var
        pdi, ndi, adx = dmi(h, l, c, 14)
        with np.errstate(invalid="ignore"):
            cu = (pdi > ndi) & np.r_[False, pdi[:-1] <= ndi[:-1]]; cd = (pdi < ndi) & np.r_[False, pdi[:-1] >= ndi[:-1]]
            strong = (adx > th) if th else np.ones(n, bool)
            turn = (adx < np.r_[np.nan, adx[:-1]]) & (np.r_[np.nan, adx[:-1]] > np.r_[np.nan, np.nan, adx[:-2]])
        en = np.where(cu & strong, 1, np.where(cd & strong & (sides == "both"), -1, 0)).astype(np.int8)
        return dict(enter=en, exit_long=cd | turn, exit_short=cu | turn)


VARIANTS = {"DSAV": [((50, "long"), "P50 long (default)"), ((50, "both"), "P50 long+short"), ((20, "long"), "P20 long"), ((100, "long"), "P100 long")],
            "ICT": [(("sma50", 2.0), "SMA50 structure, 2R (skeleton)"), (("bos", 2.0), "BOS structure, 2R"), (("sma50", 3.0), "SMA50, 3R"), (("bos", 3.0), "BOS, 3R")],
            "DIAM": [("fixed", "fixed 2 ATR stop (skeleton)"), ("trail", "trailing 2 ATR")],
            "DMI": [((25, "long"), "ADX>25 long (default)"), ((20, "long"), "ADX>20 long"), ((30, "long"), "ADX>30 long"), ((0, "long"), "no ADX filter long"), ((25, "both"), "ADX>25 long+short")]}


def pf(x):
    if not len(x): return np.nan
    w = x[x > 0].sum(); l_ = -x[x <= 0].sum(); return w / l_ if l_ else np.inf


if __name__ == "__main__":
    rows = []
    for tf in (5, 15, 60, "D"):
        o, h, l, c, day, mins, ex = bars(tf)
        for name, vs in VARIANTS.items():
            for var, lab in vs:
                S = strat(name, o, h, l, c, var)
                for intraday in ((False, True) if tf != "D" else (False,)):
                    T = simulate(o, h, l, c, day, mins, ex, tf, S["enter"], S["exit_long"], S["exit_short"], S.get("stop_fn"), S.get("tgt_R"), S.get("trail"), intraday)
                    if not len(T): continue
                    A, B_, Z = T[T.yy <= 2022].net, T[T.yy >= 2023].net, T[T.yy == 2026].net; eq = T.net.cumsum(); yr = T.groupby("yy").net.sum()
                    rows.append(dict(strategy=name, variant=lab, chart=f"{tf}m" if tf != "D" else "D", hold="intraday" if intraday else "positional",
                                     trades=len(T), win=round((T.net > 0).mean() * 100), gross_pts=round(T.pts.mean(), 1), pfA=round(pf(A), 2), pfB=round(pf(B_), 2),
                                     pf26=round(pf(Z), 2), netA=round(A.sum()), netB=round(B_.sum()), net26=round(Z.sum()), dd=round((eq - eq.cummax()).min()),
                                     yrs_pos=f"{(yr > 0).sum()}/{len(yr)}", t=round(T.net.mean() / T.net.std() * np.sqrt(len(T)), 2) if len(T) > 1 else np.nan))
                    print(rows[-1], flush=True)
    G = pd.DataFrame(rows); os.makedirs("results/thinkmarkets4", exist_ok=True); G.to_csv("results/thinkmarkets4/summary.csv", index=False)
    print(f"\nPF > 1 in both halves (>= 100 trades): {((G.pfA > 1) & (G.pfB > 1) & (G.trades >= 100)).sum()} of {len(G)}")
    for name in VARIANTS:
        x = G[(G.strategy == name) & (G.trades >= 100)]
        if not len(x): continue
        P = x.sort_values("pfA", ascending=False).iloc[0]
        print(f"pick {name}: {P.variant} {P.chart} {P.hold} - {P.trades} trades, PF {P.pfA} / {P.pfB} / {P.pf26}, net {P.netA:+,} / {P.netB:+,} / {P.net26:+,}, DD {P.dd:+,}, t {P.t}")
