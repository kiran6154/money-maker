"""S179 - a Supertrend BUY signal on the option's 1-minute chart held until the Supertrend turns, and the dOI regime over
that whole stretch (the user, 2026-10-30: "when there is a supertrend buy signal, from that time till supertrend change,
check the regime").

Contracts and window exactly as S178 / G2: the p100 option of the next expiry (G2's 09:19 pick) on its watched days, entries
09:20 - 15:00. Supertrend(4,3) and (10,3) on the premium's 1-minute candles. A flip to up at bar i = the BUY signal; the
trade enters at the next 1-minute open and exits at the open after the bar where the Supertrend turns down (positional, or
the expiry's 15:15 close) - no other stop. "intraday" also exits at 15:25 of the entry day.
Regime (tools/oi_regime.py's minutes.parquet): a 1-min bar knows the regime of its own close; per bar "with" = bullish for a
CE / bearish for a PE, "against" the opposite.
Tradable variants (one open trade per leg, nifty_bt.engine.sequence):
    A  every flip
    B  only flips with the regime at the signal
    C  delayed: the first bar of the up-segment at which the regime is with (B's trades plus the later ones), same exit
    D  B, and out at the next open once the regime turns against
    E  C with D's exit
Descriptive (uses the whole segment - hindsight, not tradable): A's trades by the share of their minutes the regime was with /
against, and whether it turned against before the Supertrend did.

    python tools/st_segment_regime.py      (from research/strategy_lab_v2; run tools/oi_regime.py first)
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, engine as E, indicators as I
from nifty_bt.costs import net
from nifty_bt.golden import _picks
from oi_regime import OUT, summ

STS = ((4, 3.0), (10, 3.0))
MODES = ("positional", "intraday")


def trades_of(C, reg, p, m):
    """reg = the regime fit (+1 with / 0 / -1 against) of each 1-min row of C, known at the row's close."""
    d = I.st_dir(C.bars(1), p, m).astype(int); n = len(d); dt = C.dt
    ups = np.flatnonzero((d[1:] == 1) & (d[:-1] == -1)) + 1
    dn = np.flatnonzero(d == -1)
    out = []
    for i in ups:
        j = dn[np.searchsorted(dn, i)] if np.searchsorted(dn, i) < len(dn) else n - 1    # the bar the Supertrend turns down
        seg = np.arange(i, j)                                                           # rows of the up-segment
        cand = {"A": i, "B": i if reg[i] > 0 else None}
        w = seg[reg[seg] > 0]; cand["C"] = w[0] if len(w) else None
        for v, k in (("A", cand["A"]), ("B", cand["B"]), ("C", cand["C"]), ("D", cand["B"]), ("E", cand["C"])):
            if k is None: continue
            i0 = C.entry_at(dt[k] + np.timedelta64(1, "m"))
            if i0 is None: continue
            for mode in MODES:
                tx = min(dt[j] + np.timedelta64(1, "m"), C.exp_close)
                if mode == "intraday": tx = min(tx, C.dday[i0] + np.timedelta64(925, "m"))
                why = "st down"
                if v in ("D", "E"):
                    ag = np.flatnonzero(reg[k:j] < 0)
                    if len(ag) and dt[k + ag[0]] + np.timedelta64(1, "m") < tx: tx, why = dt[k + ag[0]] + np.timedelta64(1, "m"), "regime against"
                if tx == C.exp_close: why = "expiry"
                elif mode == "intraday" and tx == C.dday[i0] + np.timedelta64(925, "m"): why = "15:25"
                i1, px = C.state_exit(i0, tx)
                if i1 <= i0: continue
                held = reg[i0:i1]
                out.append(dict(v=v, mode=mode, st=f"1m ST({p},{m:g})", side=1, right=C.r, sig=dt[k] + np.timedelta64(1, "m"),
                                entry_time=dt[i0], exit_time=dt[i1], entry=C.op[i0], exit=px, why=why, net=net(C.op[i0], px, 1),
                                expiry=C.e, strike=C.K, fit0=int(reg[k]), lag=int(k - i), w_share=float((held > 0).mean()),
                                a_share=float((held < 0).mean()), turned=bool((held < 0).any())))
    return out


def build():
    f = os.path.join(OUT, "seg_trades.parquet")
    if os.path.exists(f): return pd.read_parquet(f)
    M = pd.read_parquet(os.path.join(OUT, "minutes.parquet"))
    rg = M.set_index(["date", "tod"]).regime.map({"bullish": 1, "bearish": -1, "neutral": 0})
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
            raw = rg.reindex(list(zip(C.g.date, C.g.tod))).fillna(0).values.astype(int)
            reg = raw if r == "CE" else -raw
            for p, m in STS: out += trades_of(C, reg, p, m)
        if n % 25 == 0: print(n, e, len(out), f"{time.time() - t0:.0f}s", flush=True)
    T = pd.DataFrame(out); T.to_parquet(f)
    return T


if __name__ == "__main__":
    pd.set_option("display.width", 230); pd.set_option("display.max_rows", 200)
    T = build()
    rows = []
    for (st, mode, v), x in T.groupby(["st", "mode", "v"]):
        S = E.sequence(x.reset_index(drop=True))
        r = dict(st=st, mode=mode, v=v, **summ(S))
        r["exit_regime"] = round((S.why == "regime against").mean() * 100, 1); r["avg_min"] = round(((S.exit_time - S.entry_time).dt.total_seconds() / 60).median())
        rows.append(r)
    R = pd.DataFrame(rows); R.to_csv(os.path.join(OUT, "seg_books.csv"), index=False); print(R.to_string(index=False))
    print("\nA (every flip, sequenced) by the regime over the held minutes - hindsight, descriptive:")
    rows = []
    for (st, mode), x in T[T.v == "A"].groupby(["st", "mode"]):
        S = E.sequence(x.reset_index(drop=True))
        S["at_signal"] = S.fit0.map({1: "with", 0: "neutral", -1: "against"})
        S["held_with"] = pd.cut(S.w_share, [-0.01, 0.25, 0.5, 0.75, 1.0], labels=["<25%", "25-50%", "50-75%", ">75%"])
        for col in ("at_signal", "held_with", "turned"):
            for k, g in S.groupby(col, observed=True):
                rows.append(dict(st=st, mode=mode, split=col, group=str(k), **{a: b for a, b in summ(g).items() if a in ("trades", "win", "net", "avg", "PF", "PF_18_22", "PF_23_26")}))
        # entered with the regime: did it stay with, or turn against before the Supertrend turned?
        for k, g in S[S.fit0 == 1].groupby("turned"):
            rows.append(dict(st=st, mode=mode, split="with at signal: turned against later", group=str(k), **{a: b for a, b in summ(g).items() if a in ("trades", "win", "net", "avg", "PF", "PF_18_22", "PF_23_26")}))
    D = pd.DataFrame(rows); D.to_csv(os.path.join(OUT, "seg_regime_desc.csv"), index=False); print(D.to_string(index=False))
