"""S176 - a session regime from the cumulative change in open interest (dOI) of the ATM CE and PE, and the Supertrend /
CHoCH-BOS BUY books traded with it (the user, 2026-10-30: "find dOI of both ATM legs at the candle close, cumulate this
throughout the day as and when ATM changes ... mark the regime based on cumulative CE dOI and PE dOI ... trade based on the
regime and previous ruleset"; answers: the Supertrend / CHoCH-BOS buy books, 1-minute candles).

Per session, per 1-min candle close t (09:15 .. 15:29):
    ATM(t)   = NIFTY index 1-min close rounded to 50
    dOI      = OI(ATM(t), t) - OI(ATM(t), t - 1) of the CE and of the PE of the nearest expiry on or after the day (expiry day
               included) - the strike that is ATM at t, so when the ATM moves the sum carries on with the new strike's own
               change (the gap between two strikes' OI is never counted); OI = 0 / missing carries the strike's last print
               of the day; the first minute of the day adds 0
    cumCE, cumPE = the running sums from 09:15
    regime   bullish (put writing leads)  cumPE - cumCE >  10 % of (|cumCE| + |cumPE|)
             bearish (call writing leads) cumCE - cumPE >  10 % of (|cumCE| + |cumPE|)
             neutral                      otherwise (and before any OI change)
Trading: the BUY trades of the handoff books (results/nifty_bt): G2 = ST152 (= ST159's BUY leg), G4 = ST154 (= ST158's BUY
leg), G7 = ST157. The regime is read at the signal minute (the last 1-min close at or before `sig`). A bought CE is "with"
the regime when it is bullish, a bought PE when it is bearish; "against" the opposite; "neutral". The trades themselves are
the books' own - the regime only selects them (positional trades keep their own exits).
EDA: NIFTY's move over the next 30 minutes from every 15th minute, by the regime at that minute.

    python tools/oi_regime.py      (from research/strategy_lab_v2)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain

data.FILES = ("", ".wide", ".wide3k"); data._zip_members.cache_clear(); data.expiries.cache_clear()
OUT = os.path.join(chain.CACHE, "oi_regime")
os.makedirs(OUT, exist_ok=True)
RES = chain.CACHE
MARGIN = 0.10
BOOKS = {"G2 (ST152, ST159 BUY)": "golden/G2.csv", "G4 (ST154, ST158 BUY)": "golden/G4.csv", "G7 (ST157)": "golden/G7.csv"}


def regimes():
    f = os.path.join(OUT, "minutes.parquet")
    if os.path.exists(f): return pd.read_parquet(f)
    idx = data.index_1m_all()
    jobs = {}
    for D in sorted(idx.date.unique()):
        e = chain.trade_expiry(D, strictly_after=False)
        if e: jobs.setdefault(e, []).append(D)
    out = []
    for e in sorted(jobs):
        ds = jobs[e]; sp = idx[idx.date.isin(ds)]
        ks = set(range(int(sp.close.min() // 50 * 50) - 50, int(sp.close.max()) + 100, 50))
        X = data.read_expiry(e, columns=("datetime", "strike", "right", "open_interest"), strikes=ks)
        if X is None: continue
        X["open_interest"] = X.open_interest.astype(float).where(X.open_interest > 0)
        for D in ds:
            g = idx[idx.date == D]
            if len(g) < 300: continue
            tods = g.tod.values; atm = (np.round(g.close.values / 50) * 50).astype(int)
            x = X[X.date == D]
            row = dict(date=[], tod=[], atm=[], cum_ce=[], cum_pe=[])
            cum = {}
            for r in ("CE", "PE"):
                P = x[x.right == r].pivot_table(index="tod", columns="strike", values="open_interest", aggfunc="last").reindex(tods).ffill()
                d = P.diff().fillna(0.0)
                pick = np.array([d.at[t, k] if k in d.columns else 0.0 for t, k in zip(tods, atm)])
                cum[r] = np.nan_to_num(pick).cumsum()
            out.append(pd.DataFrame(dict(date=D, tod=tods, atm=atm, spot=g.close.values, cum_ce=cum["CE"], cum_pe=cum["PE"])))
        print(e, len(out), flush=True)
    M = pd.concat(out, ignore_index=True)
    net = M.cum_pe - M.cum_ce; sc = M.cum_ce.abs() + M.cum_pe.abs()
    M["regime"] = np.where((sc > 0) & (net > MARGIN * sc), "bullish", np.where((sc > 0) & (net < -MARGIN * sc), "bearish", "neutral"))
    M.to_parquet(f)
    return M


def summ(x):
    n = len(x)
    if not n: return dict(trades=0)
    v = x.net; y = pd.to_datetime(x.entry_time).dt.year
    pf = lambda s: round(s[s > 0].sum() / max(-s[s < 0].sum(), 1), 2)
    return dict(trades=n, win=round((v > 0).mean() * 100, 1), net=round(v.sum()), avg=round(v.mean()), PF=pf(v), PF_18_22=pf(v[y <= 2022]),
                PF_23_26=pf(v[y >= 2023]), t=round(v.mean() / (v.std() / np.sqrt(n)), 2) if n > 2 else np.nan,
                yrs_pos=f"{(v.groupby(y).sum() > 0).sum()}/{y.nunique()}")


if __name__ == "__main__":
    pd.set_option("display.width", 230); pd.set_option("display.max_rows", 200)
    M = regimes()
    print("minutes", len(M), "sessions", M.date.nunique())
    print("\nregime share of minutes (%) by hour:")
    M["hr"] = M.tod // 60
    print((M.groupby("hr").regime.value_counts(normalize=True).unstack() * 100).round(1).to_string())
    # EDA: index move over the next 30 minutes by regime, from every 15th minute 09:30 - 14:45
    E = M[(M.tod >= 570) & (M.tod <= 885) & ((M.tod - 555) % 15 == 0)].copy()
    nxt = M.set_index(["date", "tod"]).spot
    E["m30"] = nxt.reindex(list(zip(E.date, E.tod + 30))).values - E.spot.values
    print("\nNIFTY over the next 30 minutes by regime (points; up % = share of rises):")
    print(E.groupby("regime").m30.agg(n="size", avg="mean", up=lambda s: (s > 0).mean() * 100).round(2).to_string())
    print(E.groupby([np.where(E.date.dt.year <= 2022, "2018-22", "2023-26"), "regime"]).m30.agg(avg="mean", up=lambda s: (s > 0).mean() * 100).round(2).unstack(0).to_string())
    # the BUY books
    key = M.set_index(["date", "tod"])
    rows = []
    allT = []
    for name, fn in BOOKS.items():
        T = pd.read_csv(os.path.join(RES, fn), parse_dates=["sig", "entry_time", "exit_time"])
        T = T[T.side == 1].copy()
        T["date"] = T.sig.dt.normalize(); T["tod"] = (T.sig.dt.hour * 60 + T.sig.dt.minute - 1).clip(lower=555)
        reg = key.regime.reindex(list(zip(T.date, T.tod)))
        T["regime"] = reg.values
        T["fit"] = np.where(T.regime.isna(), "no OI data", np.where(T.regime == "neutral", "neutral",
                   np.where(((T.right == "CE") & (T.regime == "bullish")) | ((T.right == "PE") & (T.regime == "bearish")), "with regime", "against regime")))
        allT.append(T.assign(book=name))
        rows.append(dict(book=name, take="all", **summ(T)))
        for k in ("with regime", "neutral", "against regime", "no OI data"):
            rows.append(dict(book=name, take=k, **summ(T[T.fit == k])))
        rows.append(dict(book=name, take="with + neutral", **summ(T[T.fit.isin(["with regime", "neutral"])])))
    S = pd.DataFrame(rows); S.to_csv(os.path.join(OUT, "books.csv"), index=False)
    print("\nBUY books by the regime at the signal:"); print(S.to_string(index=False))
    A = pd.concat(allT); A.to_parquet(os.path.join(OUT, "book_trades.parquet"))
    print("\nby right (all three books):")
    print(A.groupby(["right", "fit"]).apply(lambda g: pd.Series(summ(g)), include_groups=False).to_string())
