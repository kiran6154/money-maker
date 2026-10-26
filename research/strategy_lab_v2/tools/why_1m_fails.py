"""tools/why_1m_fails.py - why 1-minute CHoCH / BOS trades lose on days the Jilly noise band breaks (S150).

The trades: tools/jilly_break_struct.py's "plain CHoCH/BOS 1m, break side only" (the first close outside UB / LB arms the day;
every later 1-minute CHoCH / BOS that way enters at the next open; out at the next opposite CHoCH, the last swing as the stop,
or 15:20). Compared on the same days with simply holding the break: in at the minute after the break, out at 15:20.
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
from collections import defaultdict
import numpy as np, pandas as pd, core
sys.path.insert(0, os.path.join(HERE, "tools"))
import jilly_break_struct as JB
JX, JF = JB.JX, JB.JF
R = JB.SYS["plain CHoCH/BOS 1m"]
JX._J.engine = JB.band_break_engine
try:
    f, T = JX.trades_of(dict(R, sides="jilly"))
    _, keyv, E = JB.band_break_engine(dict(core.load_strategies()["ST111"].SPEC["jilly"]))
finally:
    JX._J.engine = JB._orig_engine
MIN = (f.t % core.DAY) // 60
rows = []
for day, d, ei, xi, xp, why, stop, lab, fill, oei, oxi in T:
    seg = slice(ei, max(xi, ei + 1))
    mfe = (f.h[seg].max() - fill) if d > 0 else (fill - f.l[seg].min())
    mae = (fill - f.l[seg].min()) if d > 0 else (f.h[seg].max() - fill)
    rows.append(dict(day=day, d=d, ei=ei, xi=xi, fill=fill, xp=xp, why=why, pts=d * (xp - fill), mfe=mfe, mae=mae,
                     risk=abs(fill - stop) if stop is not None else np.nan, hold=xi - ei, hour=int(MIN[ei] // 60),
                     cost=JF._charges(day, "FUT", fill, fill, 65)["total"] / 65 + 1.0))
D = pd.DataFrame(rows); D["net_pts"] = D.pts - D.cost; D["year"] = D.day.str[:4]
# the day's "hold the break" result
hold = {}
for r in E:
    if r.get("signal") is None: continue
    i, a, z, s = r["i"], r["a"], r["z"], r["signal"]
    j = next((q for q in range(i + 1, z) if MIN[q] >= 920), z - 1)
    hold[r["day"]] = dict(side=s, pts=s * (f.o[j] - f.o[i + 1]), brk=i, rng=f.h[a:z].max() - f.l[a:z].min(),
                          best=(f.h[i + 1:j + 1].max() - f.o[i + 1]) if s > 0 else (f.o[i + 1] - f.l[i + 1:j + 1].min()))
H = pd.DataFrame.from_dict(hold, orient="index")
G = D.groupby("day").agg(n=("pts", "size"), gross=("pts", "sum"), cost=("cost", "sum"), net=("net_pts", "sum"), first_ei=("ei", "min"))
J = H.join(G, how="inner")
J["trend"] = pd.cut(J.pts, [-1e9, -50, 50, 1e9], labels=["break failed (hold < -50)", "flat (-50..+50)", "trend held (hold > +50)"])
print(f"#### Why 1-minute CHoCH / BOS loses after a noise-band break - {len(D)} trades on {len(J)} days, 2018-01 - 2026-10\n")
print("| Day type (holding the break to 15:20) | Days | Hold the break, pts / day | 1m structure trades / day | Their gross pts / day | Their cost pts / day | Their net pts / day | Share of the day's best move the trades kept |\n|---|---|---|---|---|---|---|---|")
for k, g in J.groupby("trend", observed=True):
    keep = (g.gross / g.best.clip(lower=1)).median()
    print(f"| {k} | {len(g)} | {g.pts.mean():+.1f} | {g.n.mean():.1f} | {g.gross.mean():+.1f} | {g.cost.mean():.1f} | {g.net.mean():+.1f} | {keep * 100:.0f}% (median) |")
print(f"| all | {len(J)} | {J.pts.mean():+.1f} | {J.n.mean():.1f} | {J.gross.mean():+.1f} | {J.cost.mean():.1f} | {J.net.mean():+.1f} | |")

print("\n#### The trades themselves\n")
print("| Exit | Trades | Share | Avg pts | Avg best move before the exit (MFE) | Avg hold, min |\n|---|---|---|---|---|---|")
for k, g in D.groupby("why"):
    print(f"| {k} | {len(g)} | {len(g) / len(D) * 100:.0f}% | {g.pts.mean():+.1f} | {g.mfe.mean():.1f} | {g.hold.mean():.0f} |")
L = D[D.pts <= 0]; W = D[D.pts > 0]
print(f"\nwinners {len(W)} ({len(W) / len(D) * 100:.0f}%) avg {W.pts.mean():+.1f} pts, held {W.hold.median():.0f} min (median); losers {len(L)} avg {L.pts.mean():+.1f} pts, held {L.hold.median():.0f} min")
print(f"losers that were ahead by more than their round-trip cost at some point: {(L.mfe > L.cost).mean() * 100:.0f}% (their median best: {L.mfe.median():.1f} pts)")
print(f"risk to the stop at entry (the last swing): median {D.risk.median():.1f} pts; a 1-minute bar's median range: {np.median(f.h - f.l):.1f} pts; the cost: {D.cost.median():.1f} pts")
D = D.sort_values(["day", "ei"])
same = D.groupby("day").shift(1)
re = D[same.xi.notna()]
chase = (re.d * (re.fill - same.loc[re.index, "xp"])).median()
print(f"re-entries the same day: {len(re)}; median price paid above (long) / below (short) the previous exit: {chase:+.1f} pts")
first = D.groupby("day").head(1); later = D.drop(first.index)
print(f"first trade of the day: {len(first)} trades, avg {first.pts.mean():+.2f} pts gross; later trades: {len(later)}, avg {later.pts.mean():+.2f}")
mins_after = (first.ei - J.loc[first.day, "brk"].values)
print(f"first trade's entry: median {np.median(mins_after):.0f} minutes after the break")
print("\nby period, avg gross pts / trade:", D.groupby(D.year <= "2022").pts.mean().rename({True: "2018-22", False: "2023-26"}).round(2).to_dict(),
      "| trades / day:", D.groupby([D.year <= "2022", "day"]).size().groupby(level=0).mean().rename({True: "2018-22", False: "2023-26"}).round(1).to_dict())
