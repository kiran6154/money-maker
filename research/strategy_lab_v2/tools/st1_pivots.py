"""tools/st1_pivots.py - Strategy 1's trades against the classic daily pivots (S152).

Pivots from the previous session's near-month futures high / low / close: P = (H + L + C) / 3, R1 = 2P - L, S1 = 2P - H,
R2 = P + (H - L), S2 = P - (H - L). Every saved Strategy 1 futures trade (results/ST1/all-data_1m/FUT) is placed by its entry
price: inside S1 - R1, above R1 (up to R2 / beyond), below S1 (down to S2 / beyond); and by whether it trades with the
pivot side (a long above P, a short below P). Failed = net <= 0.
"""
import os, sys, json
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd, core
JF = core.family("jilly")
f = JF._store_bars("fut")
cut = np.concatenate([[0], np.nonzero(np.diff(f.day))[0] + 1, [len(f.t)]])
piv, prev = {}, None
for a, z in zip(cut[:-1], cut[1:]):
    d = core.dstr(int(f.day[a]))
    if prev is not None:
        H, L, C = prev; P = (H + L + C) / 3
        piv[d] = dict(P=P, R1=2 * P - L, S1=2 * P - H, R2=P + (H - L), S2=P - (H - L))
    prev = (float(f.h[a:z].max()), float(f.l[a:z].min()), float(f.c[z - 1]))
j = json.load(open("results/ST1/all-data_1m/FUT/-.json", encoding="utf-8")); C = {k: i for i, k in enumerate(j["cols"])}
rows = []
for r in j["trades"]:
    d = r[C["entry_time"]][:10]
    if d not in piv: continue
    p = piv[d]; e = float(r[C["entry_px"]]); long = r[C["position"]] == "LONG"
    zone = ("above R2" if e > p["R2"] else "R1 - R2" if e > p["R1"] else "inside S1 - R1" if e >= p["S1"] else "S1 - S2" if e >= p["S2"] else "below S2")
    rows.append(dict(year=d[:4], long=long, net=float(r[C["net"]]), zone=zone, with_pivot=(e > p["P"]) == long,
                     band="inside S1 - R1" if zone == "inside S1 - R1" else "outside"))
D = pd.DataFrame(rows)
def pf(x):
    w = x[x > 0].sum(); l = -x[x <= 0].sum(); return w / l if l else np.inf
def tab(col, order=None):
    print(f"\n| {col} | Trades | Failed | Fail % | Net ₹ | PF | PF 2018-22 | PF 2023-26 | Avg net ₹ |\n|---|---|---|---|---|---|---|---|---|")
    keys = order or sorted(D[col].unique())
    for k in keys:
        g = D[D[col] == k]
        if not len(g): continue
        a, b = g[g.year <= "2022"].net, g[g.year >= "2023"].net
        print(f"| {k} | {len(g)} | {(g.net <= 0).sum()} | {(g.net <= 0).mean() * 100:.1f} | {g.net.sum():+,.0f} | {pf(g.net):.2f} | {pf(a):.2f} | {pf(b):.2f} | {g.net.mean():+,.0f} |")
print(f"Strategy 1 futures trades with a pivot: {len(D)} of {len(j['trades'])}, failed {(D.net <= 0).sum()} ({(D.net <= 0).mean() * 100:.1f}%)")
tab("band", ["inside S1 - R1", "outside"])
tab("zone", ["above R2", "R1 - R2", "inside S1 - R1", "S1 - S2", "below S2"])
D["dir_zone"] = np.where(D.long, "LONG ", "SHORT ") + D.zone
tab("dir_zone", [f"{s} {z}" for s in ("LONG", "SHORT") for z in ("above R2", "R1 - R2", "inside S1 - R1", "S1 - S2", "below S2")])
D["pivot_side"] = np.where(D.with_pivot, "with the pivot (long above P / short below P)", "against the pivot")
tab("pivot_side", ["with the pivot (long above P / short below P)", "against the pivot"])
