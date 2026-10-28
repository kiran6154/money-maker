"""Spec §9 validation checks that do not need the golden lists: look-ahead (HTF mapping, truncation), strike selection,
raw-candle trade checks, lock behaviour, sequencing.   python -m nifty_bt.validate"""
import numpy as np, pandas as pd
from . import data, chain, indicators as I, engine as E
from .costs import costs, LOT


def check_htf_and_truncation():
    b = data.index_1m(); b = b[b.date == b.date.unique()[100]].reset_index(drop=True)
    B5 = I.agg(b, 5); B15 = I.agg(b, 15)
    t = pd.Timestamp(b.date.iloc[0]) + pd.Timedelta(hours=10, minutes=3)            # a bar is known once its close time ct <= now
    seen5 = B5[B5.ct <= t].bk.iloc[-1]
    assert seen5.strftime("%H:%M") == "09:55", seen5
    d15 = I.st_dir(B15, 4, 3.0); t2 = t.normalize() + pd.Timedelta(hours=10, minutes=14)
    j = np.searchsorted(B15.ct.values, np.datetime64(t2), side="right") - 1
    assert B15.bk.iloc[j].strftime("%H:%M") == "09:45", B15.bk.iloc[j]
    full = I.st_dir(B5, 4, 3.0); sfull = I.pivot_structure(B5, 3)["ev"]
    for k in np.random.default_rng(0).integers(20, len(B5), 10):
        assert (I.st_dir(B5.iloc[:k], 4, 3.0) == full[:k]).all()
        assert (I.pivot_structure(B5.iloc[:k], 3)["ev"][:k - 3] == sfull[:k - 3]).all()        # pivots need N bars to confirm
    return "look-ahead: 10:03 sees the 09:55 5-min bar; 10:14 uses the 09:45 15-min bar; ST / structure truncation OK"


def check_strikes():
    S = chain.chain_0919()
    assert (S.datetime.dt.strftime("%H:%M") == "09:19").all()
    P = pd.read_parquet(chain.CACHE + "/picks.parquet")
    assert (pd.to_datetime(P.expiry) > P.date).all()
    return f"strike selection: {len(P)} picks, all from 09:19 closes, expiry never the trade day"


def check_trades(T, X_by_exp, side, n=3):
    """entry = next 1-min open after the signal; net = pts x lot - charges recomputed."""
    rng = np.random.default_rng(1); msgs = []
    for r in T.iloc[rng.choice(len(T), n, replace=False)].itertuples():
        X = X_by_exp(r.expiry, {r.strike}); g = X[(X.strike == r.strike) & (X.right == r.right)].set_index("datetime")
        assert g.index[g.index.searchsorted(pd.Timestamp(r.sig))] == pd.Timestamp(r.entry_time)
        assert abs(g.loc[pd.Timestamp(r.entry_time)].open - r.entry) < 1e-6
        assert abs(side * (r.exit - r.entry) * LOT - costs(r.entry, r.exit, side) - r.net) < 1e-6
        msgs.append(f"{r.right} {r.entry_time} ok")
    return "raw-candle checks: " + ", ".join(msgs)


def check_sequencing(T):
    for r, y in T.groupby("right"):
        y = y.sort_values("entry_time"); assert (y.entry_time.values[1:] >= y.exit_time.values[:-1]).all()
    return "sequencing: no overlapping trades within a leg"


if __name__ == "__main__":
    print(check_htf_and_truncation()); print(check_strikes())
    import os
    for k, side in (("G3", -1), ("G4", 1)):
        f = os.path.join(chain.CACHE, "golden", f"{k}.csv")
        if os.path.exists(f):
            T = pd.read_csv(f, parse_dates=["sig", "entry_time", "exit_time"])
            print(k, check_trades(T, lambda e, ks: data.read_expiry(e, strikes=ks), side)); print(k, check_sequencing(T))
            if "locked" in T or k == "G4":
                L = T[T.why.astype(str).str.startswith("locked")]
                print(k, f"locked trades {len(L)}: exits", L.why.value_counts().to_dict())
