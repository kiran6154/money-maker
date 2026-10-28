"""tools/multi_ma_jma.py - TradeAutomation's "Multi MA Trend Following Strategy" (Pine v5, pasted by the user 2026-10-28) at
its defaults, on NIFTY near-month futures (S156).

The script at its defaults: Trend = JMA(close, length 200, phase -45, power 2) (Everget's JMA as written in the script);
long when the JMA turns up (crossover of JMA*1000 with its previous value), close when it turns down; shorts off by
default (also run here, mirrored); orders at the signal bar's close (process_orders_on_close); positions held across
sessions (no intraday exit). Fixed before the run:
  timeframes 5m, 15m, 60m (09:15-aligned) and daily; positional as written, plus an intraday variant (flat at 15:20,
  no carry) for the intraday timeframes; long only (the default), short only, long + short (reversing).
  Futures rolls: on the first bar of a new contract the gap between contracts is not counted (the bar's open-to-close
  is), and a roll costs one more round trip. Costs per round trip: 1 point slippage + the dated futures charges, 1 lot of 65.
  The first 1,000 bars of each series are warm-up (the script starts its JMA at 0).
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
def jma(src, length, phase, power):
    pr = 0.5 if phase < -100 else 2.5 if phase > 100 else phase / 100 + 1.5
    beta = 0.45 * (length - 1) / (0.45 * (length - 1) + 2); alpha = beta ** power
    out = np.zeros(len(src)); e0 = 0.0; e1 = 0.0; e2 = 0.0; J = 0.0
    for i in range(len(src)):
        e0 = (1 - alpha) * src[i] + alpha * e0
        e1 = (src[i] - e0) * (1 - beta) + beta * e1
        e2 = (e0 + pr * e1 - J) * (1 - alpha) ** 2 + alpha ** 2 * e2
        J = e2 + J; out[i] = J
    return out


def bars(tf):
    if tf == "D":
        a, z = cut[:-1], cut[1:]
        return (f.o[a], np.maximum.reduceat(f.h, a), np.minimum.reduceat(f.l, a), f.c[z - 1], EXP[z - 1], f.day[a], np.full(len(a), 925), z - 1)
    B, last = BL.tf_bars(tf)
    t = np.asarray(B.t)
    return (np.asarray(B.o, float), None, None, np.asarray(B.c, float), EXP[last], t // core.DAY, (t % core.DAY) // 60 + tf, last)


def run(tf, side, intraday):
    o, _, _, c, ex, day, endmin, last = bars(tf)
    J = jma(c.astype(float), 200, -45, 2)
    up = np.r_[False, J[1:] > J[:-1]]; dn = np.r_[False, J[1:] < J[:-1]]
    tu = up & ~np.r_[False, up[:-1]]; td = dn & ~np.r_[False, dn[:-1]]   # turn up / turn down (crossover / crossunder)
    pos = 0; tr = []; cur = None
    def close(i):
        nonlocal pos, cur
        cur["x"] = i; tr.append(cur); pos = 0; cur = None
    for i in range(1000, len(c)):
        if pos:
            if ex[i] != ex[i - 1]:
                cur["pts"] += pos * (c[i] - o[i]); cur["rolls"] += 1
            else:
                cur["pts"] += pos * (c[i] - c[i - 1])
            if intraday and day[i] != day[i - 1]:      # cannot happen (closed at 15:20) - safety
                pass
        if pos and ((pos > 0 and td[i]) or (pos < 0 and tu[i])): close(i)
        if intraday and pos and (i + 1 >= len(c) or day[i + 1] != day[i]): close(i)
        if pos == 0:
            want = 1 if tu[i] and side in ("long", "both") else -1 if td[i] and side in ("short", "both") else 0
            if want and not (intraday and (i + 1 >= len(c) or day[i + 1] != day[i])):
                pos = want; cur = dict(e=i, s=want, px=c[i], pts=0.0, rolls=0)
    if cur: close(len(c) - 1)
    rows = []
    for t_ in tr:
        d = core.dstr(int(day[t_["e"]]))
        cost = (1.0 + JF._charges(d, "FUT", t_["px"], t_["px"], LOT)["total"] / LOT) * (1 + t_["rolls"])
        rows.append(dict(yy=int(d[:4]), side=t_["s"], bars=t_["x"] - t_["e"], gross=t_["pts"], net=(t_["pts"] - cost) * LOT))
    return pd.DataFrame(rows)


def pf(x):
    w = x[x > 0].sum(); L_ = -x[x <= 0].sum(); return w / L_ if L_ else float("inf")


print("| Timeframe | Hold | Side | Trades | Avg bars held | Gross pts / trade | Win % | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ | Max drawdown ₹ |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for tf in (5, 15, 60, "D"):
    for intraday in ((False, True) if tf != "D" else (False,)):
        for side in ("long", "short", "both"):
            T = run(tf, side, intraday)
            if not len(T): continue
            A, Bq, Z = T.yy <= 2022, T.yy >= 2023, T.yy == 2026
            eq = T.net.cumsum(); dd = (eq - eq.cummax()).min()
            print(f"| {tf if tf == 'D' else str(tf) + 'm'} | {'intraday' if intraday else 'positional'} | {side} | {len(T)} | {T.bars.mean():.0f} | {T.gross.mean():+.1f} | "
                  f"{(T.net > 0).mean() * 100:.0f} | {pf(T.net[A]):.2f} | {pf(T.net[Bq]):.2f} | {pf(T.net[Z]):.2f} | {T.net[A].sum():+,.0f} | {T.net[Bq].sum():+,.0f} | {T.net[Z].sum():+,.0f} | {dd:+,.0f} |", flush=True)
