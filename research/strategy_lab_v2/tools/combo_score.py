"""tools/combo_score.py - the combined book of S142 plus the best 15-minute option-selling book (Strategy 142, G_hardstop K5),
one position per SIDE (bullish: long futures / a sold PE; bearish: short futures / a sold CE), the first entry on a side
wins; then a confluence score per trade: how many of the OTHER books hold a position the same way (+1 each) or the
other way (-1 each) at the trade's entry minute (their standalone books - a position open then is known then).

    python tools/combo_score.py
"""
import io
import os
import runpy
import sys
import contextlib
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
from collections import Counter, defaultdict
import numpy as np
import pandas as pd
import core

_out = sys.stdout; sys.stdout = open(os.devnull, "w", encoding="utf-8")
try: G = runpy.run_path(os.path.join(HERE, "tools", "combo_book.py"), run_name="combo")
finally: sys.stdout.close(); sys.stdout = _out
BOOKS = {k: [dict(t, dir=t["side"]) for t in v] for k, v in G["BOOKS"].items()}

# ---- the option-selling book: Strategy 142 (G_hardstop, K = 5), its standalone trades
F = core.family("optsell15")
ts = lambda x: int(pd.Timestamp(x).value // 10**9)
opt = []
for t in F.s11_book("G_hardstop", 5).itertuples(index=False):
    et = ts(t.fill_t) + 900
    xt = ts(pd.Timestamp(t.exp)) + 15 * 3600 + 30 * 60 if t.reason == "expiry" else ts(t.exit_t) + (900 if t.reason == "rainbow" else 0)
    opt.append(dict(name="Opt sell (ST142)", dir=1 if t.side == "PE" else -1, entry_time=et, exit_time=xt, net=float(t.net),
                    label=f"SELL {t.strike} {t.side}"))
BOOKS["Opt sell (ST142)"] = opt
NAMES = list(BOOKS)

def pf(x):
    w = sum(v for v in x if v > 0); l = -sum(v for v in x if v <= 0); return w / l if l else float("inf")
Y = lambda t: core.tstr(t["entry_time"])[:4]

# ---- confluence score of every standalone trade
open_by = {k: sorted((t["entry_time"], t["exit_time"], t["dir"]) for t in v) for k, v in BOOKS.items()}
def score(t):
    a = o = 0
    for k, iv in open_by.items():
        if k == t["name"]: continue
        d = 0
        for e, x, dr in iv:                                 # a position of book k open at t's entry minute
            if e > t["entry_time"]: break
            if e < t["entry_time"] < x or (e == t["entry_time"] and False): d = dr
        if d == t["dir"]: a += 1
        elif d == -t["dir"]: o += 1
    return a, o
ALL = [t for v in BOOKS.values() for t in v]
for t in ALL: t["agree"], t["oppose"] = score(t); t["score"] = t["agree"] - t["oppose"]

def row(nm, X, extra=""):
    n = [t["net"] * t.get("lots", 1) for t in X]
    if not n: print(f"| {nm} | 0 |"); return
    a = [t["net"] * t.get("lots", 1) for t in X if Y(t) <= "2022"]; b = [t["net"] * t.get("lots", 1) for t in X if Y(t) >= "2023"]
    eq = pk = dd = 0
    for t in sorted(X, key=lambda t: t["exit_time"]): eq += t["net"] * t.get("lots", 1); pk = max(pk, eq); dd = min(dd, eq - pk)
    print(f"| {nm} | {len(X)} | {100 * sum(v > 0 for v in n) / len(n):.1f} | {sum(n) / len(n):+,.0f} | {pf(n):.3f} | {pf(a):.2f} / {pf(b):.2f} | {sum(a):+,.0f} / {sum(b):+,.0f} | {sum(n):+,.0f} | {dd:,.0f} |{extra}")
HD = "| Book | Trades | Win % | Avg net ₹ | PF | PF 2018-22 / 2023-26 | Net 2018-22 / 2023-26 ₹ | Net ₹ | Max DD ₹ |"

print("#### Standalone books\n" + HD + "\n|---|---|---|---|---|---|---|---|---|")
for k in NAMES: row(k, BOOKS[k])

print("\n#### Every standalone trade by confluence score (others the same way minus others the other way, at its entry)\n" + HD + "\n|---|---|---|---|---|---|---|---|---|")
for lo, hi, nm in ((-9, -2, "score <= -2"), (-1, -1, "score -1"), (0, 0, "score 0"), (1, 1, "score +1"), (2, 9, "score >= +2")):
    row(nm, [t for t in ALL if lo <= t["score"] <= hi])
print("\nper book, PF (trades) by score  < 0 | = 0 | > 0, 2018-22 / 2023-26:")
for k in NAMES:
    cells = []
    for f_ in (lambda s: s < 0, lambda s: s == 0, lambda s: s > 0):
        X = [t for t in BOOKS[k] if f_(t["score"])]
        a = [t["net"] for t in X if Y(t) <= "2022"]; b = [t["net"] for t in X if Y(t) >= "2023"]
        cells.append(f"{pf(a):.2f} ({len(a)}) / {pf(b):.2f} ({len(b)})")
    print(f"  {k:18s} " + " | ".join(cells))

# ---- the combined book: one position per side, first entry wins; rules on the score
PRIO = NAMES
def book(rule):
    allt = sorted((t for t in ALL), key=lambda t: (t["entry_time"], PRIO.index(t["name"])))
    busy = {1: -1, -1: -1}; taken = []; skipped = Counter()
    for t in allt:
        lots = rule(t)
        if not lots: continue
        if t["entry_time"] < busy[t["dir"]]: skipped[t["name"]] += 1; continue
        taken.append(dict(t, lots=lots)); busy[t["dir"]] = t["exit_time"]
    return taken, skipped
RULES = {
    "every signal (1 lot)": lambda t: 1,
    "skip when more books oppose (score < 0)": lambda t: 0 if t["score"] < 0 else 1,
    "only with agreement (score > 0)": lambda t: 1 if t["score"] > 0 else 0,
    "2 lots when score > 0, else 1": lambda t: 2 if t["score"] > 0 else 1,
    "2 lots when score > 0, 1 at 0, skip < 0": lambda t: 2 if t["score"] > 0 else 1 if t["score"] == 0 else 0,
}
print("\n#### Combined book - one position per side (bullish / bearish), first entry wins\n" + HD + " Skipped (side busy) |\n|---|---|---|---|---|---|---|---|---|---|")
res = {}
for nm, rule in RULES.items():
    T, sk = book(rule)
    res[nm] = T
    row(nm, T, f" {sum(sk.values())} |")
base = res["every signal (1 lot)"]
print("\nevery-signal book, by book:")
print(HD + "\n|---|---|---|---|---|---|---|---|---|")
for k in NAMES: row(f"- {k}", [t for t in base if t["name"] == k])
yr = defaultdict(float)
for t in base: yr[Y(t)] += t["net"]
print("every-signal book by year:", {y: round(v) for y, v in sorted(yr.items())})
both = 0
# how often both sides were open at once (a hedge)
ev = sorted([(t["entry_time"], 1) for t in base] + [(t["exit_time"], -1) for t in base])
cur = mx = 0; overlap = 0
iv = sorted((t["entry_time"], t["exit_time"]) for t in base)
for i in range(1, len(iv)):
    if iv[i][0] < iv[i - 1][1]: overlap += 1
print(f"trades that opened while the other side was already open: {overlap} of {len(base)}")

# ---- the rule chosen on 2018-22 alone (return over drawdown), read on 2023-26
def rod(T, lo, hi):
    X = sorted([t for t in T if lo <= Y(t) <= hi], key=lambda t: t["exit_time"]); eq = pk = dd = 0
    for t in X: eq += t["net"] * t["lots"]; pk = max(pk, eq); dd = min(dd, eq - pk)
    return eq / -dd if dd < 0 else float("inf"), eq
sel = {nm: rod(T, "2018", "2022") for nm, T in res.items()}
best = max(sel, key=lambda k: sel[k][0])
print("\nreturn / max drawdown on 2018-22 (the selection rule, set before reading):", {k: round(v[0], 2) for k, v in sel.items()})
print(f"chosen: **{best}** - 2023-26 return/DD {rod(res[best], '2023', '2026')[0]:.2f}, net {rod(res[best], '2023', '2026')[1]:+,.0f}"
      f" (every signal: {rod(base, '2023', '2026')[0]:.2f}, {rod(base, '2023', '2026')[1]:+,.0f})")
