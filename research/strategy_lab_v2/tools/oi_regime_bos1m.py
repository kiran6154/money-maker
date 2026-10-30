"""S178 - S177 on the option's 1-minute chart: Supertrend-segment BOS (and CHoCH) BUYs from 1-minute bars, with and without
S176's cumulative ATM dOI regime (the user, 2026-10-30: "is that checked with 1min" -> "check that").

Exactly nifty_bt's G2 construction (golden.option_books: the p100 contracts of the next expiry, each loaded from a week
before its first pick and trimmed to 3 sessions, signals only on its watched days 09:20 - 15:00, entry at the next 1-min open,
stop at the segment swing, positional, trail + lock50, one open trade per leg) with the Supertrend structure read on
1-minute bars: ST(4,3) and ST(10,3). Books: BOS buys, CHoCH buys, both. Regime and "with / neutral / against" as
tools/oi_regime.py.

    python tools/oi_regime_bos1m.py      (from research/strategy_lab_v2; run tools/oi_regime.py first)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain, engine as E
from nifty_bt.golden import _picks
from oi_regime import OUT, summ
from oi_regime_bos import tag

STS = ((4, 3.0), (10, 3.0))


def candidates():
    f = os.path.join(OUT, "cand_1m.parquet")
    if os.path.exists(f): return pd.read_parquet(f)
    P = _picks()
    load_first = P[P.pick.isin(["ATM", "p100", "p300", "p500"])].groupby(["expiry", "strike", "right"]).date.min().to_dict()
    p100 = P[P.pick == "p100"]
    wd = p100.groupby(["expiry", "strike", "right"]).date.apply(set).to_dict()
    first = p100.groupby(["expiry", "strike", "right"]).date.min().to_dict()
    out, t0 = [], time.time()
    for n, e in enumerate(sorted(p100.expiry.unique())):
        keys = [(k, r) for (e2, k, r) in wd if e2 == e]
        X = data.read_expiry(e, strikes={k for k, _ in keys})
        if X is None: continue
        for (k, r), g in X.groupby(["strike", "right"]):
            key = (e, int(k), r)
            if key not in wd: continue
            g = g[g.date >= load_first[key] - pd.Timedelta(days=7)].reset_index(drop=True)
            C = E.Contract(e, int(k), r, g, wd[key], first[key])
            if not C.ok(): continue
            for p, m in STS:
                out += [x for x in E.stswing(C, 1, p, m) if x["side"] > 0]
        if n % 25 == 0: print(n, e, len(out), f"{time.time() - t0:.0f}s", flush=True)
    T = pd.DataFrame(out); T.to_parquet(f)
    return T


if __name__ == "__main__":
    pd.set_option("display.width", 230); pd.set_option("display.max_rows", 200)
    c = candidates()
    key = pd.read_parquet(os.path.join(OUT, "minutes.parquet")).set_index(["date", "tod"])
    rows = []
    for st in sorted(c.st.unique()):
        for kinds, name in ((("BOS",), "BOS"), (("CHoCH",), "CHoCH"), (("BOS", "CHoCH"), "CHoCH + BOS")):
            x = c[(c.st == st) & c.kind.isin(kinds)]
            T = tag(E.sequence(x.reset_index(drop=True)), key)
            b = f"{st} {name}"
            rows.append(dict(book=b, take="all", **summ(T)))
            for k in ("with regime", "neutral", "against regime"):
                rows.append(dict(book=b, take=k, **summ(T[T.fit == k])))
            T.to_parquet(os.path.join(OUT, f"trades_1m_{st.replace(' ', '_').replace('(', '').replace(')', '').replace(',', '-')}_{name.replace(' + ', '_')}.parquet"))
    S = pd.DataFrame(rows); S.to_csv(os.path.join(OUT, "bos_1m_books.csv"), index=False); print(S.to_string(index=False))
