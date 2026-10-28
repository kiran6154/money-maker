"""tools/st_optbuy_report.py - the S158 grid report from results/optbuy_grid/trades.parquet (tools/st_optbuy_grid.py)."""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE)
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd

R = pd.read_parquet(sys.argv[1] if len(sys.argv) > 1 else "results/optbuy_grid/trades.parquet")
R["ret"] = R.net / (R.prem * 65)
R["set"] = R.tf.astype(str) + "m ST(" + R.atr.astype(str) + "," + R.mult.map(lambda x: f"{x:g}") + ")"
EXN = {"I": "intraday", "I2x": "intraday + 2x", "P": "positional", "P2x": "positional + 2x", "E": "to expiry", "E2x": "to expiry + 2x"}


def pf(x):
    if not len(x): return np.nan
    w = x[x > 0].sum(); l = -x[x <= 0].sum(); return w / l if l else np.inf


def agg(g):
    A, B, Z = g[g.yy <= 2022].net, g[g.yy >= 2023].net, g[g.yy == 2026].net
    eq = g.sort_values("day").net.cumsum()
    return pd.Series(dict(n=len(g), win=(g.net > 0).mean() * 100, ret=g.ret.mean() * 100, x2=(g.why == "2x").mean() * 100,
                          pfA=pf(A), pfB=pf(B), pf26=pf(Z), netA=A.sum(), netB=B.sum(), net26=Z.sum(), dd=(eq - eq.cummax()).min()))


G = R.groupby(["set", "mode", "exit"]).apply(agg).reset_index()
print(f"#### {len(R):,} trades, {len(G)} combinations, {R.day.min()} - {R.day.max()}\n")
print("**Every combination profitable in BOTH 2018-22 and 2023-26 (PF > 1 in each, >= 100 trades):**\n")
ok = G[(G.pfA > 1) & (G.pfB > 1) & (G.n >= 100)].sort_values("pfB", ascending=False)
H = "| Signal | Strike | Exit | Trades | Win % | Avg return on premium | Hit 2x | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ | Max DD ₹ |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
def row(r):
    print(f"| {r.set} | {r['mode']} | {EXN[r.exit]} | {int(r.n)} | {r.win:.0f} | {r.ret:+.0f}% | {r.x2:.0f}% | {r.pfA:.2f} | {r.pfB:.2f} | {r.pf26:.2f} | {r.netA:+,.0f} | {r.netB:+,.0f} | {r.net26:+,.0f} | {r.dd:+,.0f} |")
print(H); [row(r) for _, r in ok.iterrows()]
if not len(ok): print("| none | |")
pickA = G[G.n >= 100].sort_values("pfA", ascending=False).head(10)
print("\n**Top 10 on 2018-22 PF (>= 100 trades) and how they did after:**\n"); print(H); [row(r) for _, r in pickA.iterrows()]
print("\n**By strike x exit (all 16 signal sets pooled):**\n\n| Strike | Exit | Trades | Win % | Avg return | Hit 2x | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ |\n|---|---|---|---|---|---|---|---|---|---|---|")
for (m, e), g in R.groupby(["mode", "exit"]):
    a = agg(g); print(f"| {m} | {EXN[e]} | {int(a.n):,} | {a.win:.0f} | {a.ret:+.0f}% | {a.x2:.0f}% | {a.pfA:.2f} | {a.pfB:.2f} | {a.pf26:.2f} | {a.netA:+,.0f} | {a.netB:+,.0f} |")
print("\n**By signal timeframe x config (all strikes and exits pooled):**\n\n| Signal | Trades | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ |\n|---|---|---|---|---|---|---|")
for s, g in R.groupby("set"):
    a = agg(g); print(f"| {s} | {int(a.n):,} | {a.pfA:.2f} | {a.pfB:.2f} | {a.pf26:.2f} | {a.netA:+,.0f} | {a.netB:+,.0f} |")
print(f"\ncombinations with PF > 1 in 2018-22: {(G.pfA > 1).sum()} of {len(G)}; in 2023-26: {(G.pfB > 1).sum()}; both: {((G.pfA > 1) & (G.pfB > 1)).sum()}")
G.to_csv("results/optbuy_grid/combinations.csv", index=False)
