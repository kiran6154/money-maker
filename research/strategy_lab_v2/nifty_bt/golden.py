"""Acceptance tests (handoff README / spec §0): rebuild the seven golden books G1-G7 and compare with spec/golden_trades/.
Pass = trade count and net within +-1 %, and the first 20 trades' entry / exit time and price identical.

    python -m nifty_bt.golden            (from research/strategy_lab_v2)   -> results/nifty_bt/golden/*.csv + report
"""
import os, sys, glob, time
import numpy as np, pandas as pd
from . import data, chain, engine as E, filters as F

HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(HERE, "spec", "golden_trades")
OUT = os.path.join(chain.CACHE, "golden")


def _picks():
    f = os.path.join(chain.CACHE, "picks.parquet")
    if not os.path.exists(f):
        chain.picks(("ATM", "p100", "p300", "p500", "p500up", "p750", "u50", "p40", "u30", "u15")).to_parquet(f)
    return pd.read_parquet(f)


def option_books(log=print):
    """G1, G2, G3, G4, G6, G7 - all on the p100 (₹100+) pick of the next expiry."""
    P = _picks()
    scan1 = P[P.pick.isin(["ATM", "p100", "p300", "p500"])]                         # the reference's picks.parquet (loading warm-up)
    load_first = scan1.groupby(["expiry", "strike", "right"]).date.min().to_dict()
    p100 = P[P.pick == "p100"]
    wd = p100.groupby(["expiry", "strike", "right"]).date.apply(set).to_dict()
    first = p100.groupby(["expiry", "strike", "right"]).date.min().to_dict()
    first3 = P[P.pick.isin(["ATM", "p100", "p300"])].groupby(["expiry", "strike", "right"]).date.min().to_dict()   # conf_sim's watch list
    cand = {k: [] for k in ("G1", "G2", "G3", "G4", "G6", "G7")}
    t0 = time.time(); exps = sorted(p100.expiry.unique())
    for n, e in enumerate(exps):
        keys = [(k, r) for (e2, k, r) in wd if e2 == e]
        X = data.read_expiry(e, strikes={k for k, _ in keys})
        if X is None: continue
        for (k, r), g in X.groupby(["strike", "right"]):
            key = (e, int(k), r)
            if key not in wd: continue
            g = g[g.date >= load_first[key] - pd.Timedelta(days=7)].reset_index(drop=True)
            C = E.Contract(e, int(k), r, g, wd[key], first[key])
            if C.ok():
                cand["G1"] += [x for x in E.stswing(C, 5, 4, 3.0) if x["side"] < 0]
                cand["G2"] += [x for x in E.stswing(C, 15, 4, 3.0) if x["side"] > 0 and x["kind"] == "CHoCH"]
                cand["G4"] += E.conf_buy(C, 4, 3.0, ("5m",), ("st_dn",), ("lock_exp",))
                cand["G6"] += [x for x in E.chochst(C, 15, 2, 10, 3.0) if x["side"] < 0]               # CHoCH + BOS
                cand["G7"] += E.intraday(C, 1, 15, 10, 3.0, ("5m",), ("ema20",), ("none",))
            C3 = E.Contract(e, int(k), r, g, wd[key], first3[key])
            if C3.ok(): cand["G3"] += E.conf_sell(C3, 4, 3.0, ("5m",), ("st_up",), ("tgt50",))
        if n % 25 == 0: log(f"{n}/{len(exps)} {e} " + " ".join(f"{k}:{len(v)}" for k, v in cand.items()) + f" {time.time() - t0:.0f}s")
    books = {}
    for k, v in cand.items():
        x = pd.DataFrame(v)
        if k == "G7": x = x[F.chop_ok(x.sig, x.side, x.right)]
        books[k] = E.sequence(x.reset_index(drop=True))
    return books


def atm_book(tf=60, p=4, m=3.0, log=print):
    """G5: §6.1 ATM positional SELL, front expiry incl. expiry day."""
    plan = chain.front_atm_plan()
    need = {}
    for D, e, K in plan: need.setdefault(e, set()).add(K)
    watched = set(); ents = {"CE": [], "PE": []}
    for e in sorted(need):
        X = data.read_expiry(e, strikes=need[e], f32=False)                     # the ATM study kept float64 prices
        if X is None: continue
        days = {(D, K) for D, e2, K in plan if e2 == e}
        have = X[[(d, k) in days for d, k in zip(X.date, X.strike)]][["date", "strike", "right"]].drop_duplicates()
        watched |= {(d, e, int(k), r) for d, k, r in have.values}
        for (k, r), g in X.groupby(["strike", "right"]):
            for t, (gg, up) in E.possell(g.reset_index(drop=True), e, int(k), r, watched, tf, p, m):
                ents[r].append((t, e, int(k), gg, up))
    rows = []
    for r in ("CE", "PE"):
        free = pd.Timestamp("1900-01-01")
        for t, e, k, g, up in sorted(ents[r], key=lambda x: (x[0], x[1], x[2])):
            if t < free: continue
            x = E.possell_trade(g, up, t, e)
            if x is None: continue
            rows.append(dict(right=r, expiry=e, strike=k, **x)); free = x["exit_time"]
    T = pd.DataFrame(rows); T["sig"] = T.entry_time; T["year"] = pd.to_datetime(T.entry_time).dt.year
    return T


def compare(name, T):
    f = glob.glob(os.path.join(GOLD, name + "_*.csv"))[0]; G = pd.read_csv(f)
    for c in ("entry_time", "exit_time"): G[c] = pd.to_datetime(G[c])
    T = T.copy()
    for c in ("entry_time", "exit_time"): T[c] = pd.to_datetime(T[c])
    a = G.sort_values(["entry_time", "right"]).head(20).reset_index(drop=True); b = T.sort_values(["entry_time", "right"]).head(20).reset_index(drop=True)
    same20 = len(b) == 20 and all((a[c] == b[c]).all() for c in ("entry_time", "exit_time", "right")) and \
        np.allclose(a.entry, b.entry, atol=1e-6) and np.allclose(a.exit, b.exit, atol=1e-6)
    m = G.merge(T, on=["right", "entry_time"], how="outer", suffixes=("_g", "_t"), indicator=True)
    both = m[m._merge == "both"]
    exact = ((both.exit_time_g == both.exit_time_t) & (np.abs(both.exit_g - both.exit_t) < 1e-6)).mean() if len(both) else 0
    r = dict(book=name, golden_trades=len(G), trades=len(T), d_trades=f"{(len(T) / len(G) - 1) * 100:+.2f}%",
             golden_net=round(G.net.sum()), net=round(T.net.sum()), d_net=f"{(T.net.sum() / G.net.sum() - 1) * 100:+.2f}%",
             first20_exact=bool(same20), matched_entries=len(both), only_golden=int((m._merge == "left_only").sum()),
             only_ours=int((m._merge == "right_only").sum()), same_exit_of_matched=f"{exact * 100:.1f}%",
             PASS=bool(abs(len(T) / len(G) - 1) <= 0.01 and abs(T.net.sum() / G.net.sum() - 1) <= 0.01 and same20))
    return r


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    which = sys.argv[1:] or ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    books = {}
    if set(which) - {"G5"}: books.update(option_books(lambda s: print(s, flush=True)))
    if "G5" in which: books["G5"] = atm_book()
    rows = []
    for k in which:
        books[k].to_csv(os.path.join(OUT, f"{k}.csv"), index=False)
        rows.append(compare(k, books[k])); print(rows[-1], flush=True)
    R = pd.DataFrame(rows); R.to_csv(os.path.join(OUT, "golden_report.csv"), index=False)
    print(R.to_string(index=False))
