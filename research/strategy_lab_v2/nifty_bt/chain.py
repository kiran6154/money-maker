"""Contract selection (spec §3.1-3.2): the trade expiry per session, the 09:19 chain snapshot, the pick rules, and the
picked contracts' 1-min history. Results are cached under results/nifty_bt/ (git-ignored)."""
import os, collections
import numpy as np, pandas as pd
from . import data

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "nifty_bt" + (f"_parity{data.PARITY_DAYS}" if data.PARITY_DAYS else ""))
GAP = (pd.Timestamp("2018-02-23"), pd.Timestamp("2018-03-28"))       # the 2018-03-28 folder is missing: skip, never substitute
MAX_DAYS = 35


def sessions():
    s = data.spot_0915().index
    return [d for d in s if pd.Timestamp("2018-01-01") <= d <= pd.Timestamp(data.END or "2100-01-01")]


def trade_expiry(D, strictly_after=True):
    """§3.1: nearest expiry strictly after D (positional scan) or on / after D (front, the older ATM study); within 35 days."""
    if GAP[0] <= D <= GAP[1]: return None
    ex = np.array([np.datetime64(e) for e in data.expiries()])
    i = np.searchsorted(ex, np.datetime64(D), side="right" if strictly_after else "left")
    if i >= len(ex): return None
    e = data.expiries()[i]
    return e if (pd.Timestamp(e) - D).days <= MAX_DAYS else None


def plan(strictly_after=True):
    return {D: e for D in sessions() if (e := trade_expiry(D, strictly_after))}


def chain_0919():
    """every strike's 09:19 close of the trade expiry, per session (§3.2), with the 09:15 five-minute spot."""
    f = os.path.join(CACHE, "chain_0919.parquet")
    if os.path.exists(f): return pd.read_parquet(f)
    by = collections.defaultdict(list)
    for D, e in plan().items(): by[e].append(D)
    out = []
    for e, days in sorted(by.items()):
        for kind, p, m in data._sources(e):
            import io, zipfile
            try:
                d = pd.read_parquet(p if kind == "file" else io.BytesIO(zipfile.ZipFile(p).read(m)), columns=["datetime", "strike", "right", "close"])
            except Exception:
                continue
            d["datetime"] = d.datetime.astype("datetime64[ns]")
            d = d[(d.datetime.dt.hour == 9) & (d.datetime.dt.minute == 19)]
            d = d[d.datetime.dt.normalize().isin(days) & data.in_window(e, d.datetime.dt.normalize())]
            if len(d): out.append(d.assign(expiry=e, right=d.right.astype(str), strike=d.strike.astype(int)))
    S = pd.concat(out, ignore_index=True).drop_duplicates(["datetime", "strike", "right"])
    S["date"] = S.datetime.dt.normalize(); S["spot"] = S.date.map(data.spot_0915())
    os.makedirs(CACHE, exist_ok=True); S.to_parquet(f)
    return S


PICKS = {   # name -> (filter on the 09:19 chain g, chooser)
    "p100":   (lambda g: g[(g.close >= 100) & (g.close <= 500)], lambda c: c.loc[c.close.idxmin()]),
    "p300":   (lambda g: g[(g.close >= 100) & (g.close <= 500)], lambda c: c.iloc[(c.close - 300).abs().argmin()]),
    "p500":   (lambda g: g[(g.close >= 100) & (g.close <= 500)], lambda c: c.loc[c.close.idxmax()]),
    "p500up": (lambda g: g[g.close >= 500], lambda c: c.loc[c.close.idxmin()]),
    "p750":   (lambda g: g[g.close >= 500], lambda c: c.iloc[(c.close - 750).abs().argmin()]),
    "u50":    (lambda g: g[g.otm & (g.close < 50) & (g.close >= 2)], lambda c: c.loc[c.close.idxmax()]),
    "p40":    (lambda g: g[g.otm & (g.close < 50) & (g.close >= 2)], lambda c: c.iloc[(c.close - 40).abs().argmin()]),
    "u30":    (lambda g: g[g.otm & (g.close < 30) & (g.close >= 2)], lambda c: c.loc[c.close.idxmax()]),
    "u15":    (lambda g: g[g.otm & (g.close < 30) & (g.close >= 2)], lambda c: c.iloc[(c.close - 15).abs().argmin()]),
}


def picks(names=("p100", "p500up")):
    """one row per (date, right, pick): expiry, strike, premium at 09:19."""
    S = chain_0919(); S = S[S.close > 0].reset_index(drop=True)
    S["otm"] = np.where(S.right == "CE", S.strike > S.spot, S.strike < S.spot)
    rows = []
    for (d, r), g in S.groupby(["date", "right"]):
        sp = g.spot.iloc[0]
        if "ATM" in names:
            a = g.iloc[(g.strike - sp).abs().argmin()]; rows.append((d, r, "ATM", a.expiry, int(a.strike), a.close, sp))
        for n in names:
            if n == "ATM": continue
            flt, ch = PICKS[n]; c = flt(g)
            if len(c): x = ch(c); rows.append((d, r, n, x.expiry, int(x.strike), x.close, sp))
    return pd.DataFrame(rows, columns=["date", "right", "pick", "expiry", "strike", "prem", "spot"])


def contracts(P):
    """per expiry: {(strike, right): {"days": watched days, "first": first watched day}} from a picks frame."""
    out = collections.defaultdict(dict)
    for (e, k, r), g in P.groupby(["expiry", "strike", "right"]):
        out[e][(int(k), r)] = dict(days=set(g.date), first=g.date.min())
    return out


def load_picked(e, cons, warm_days=7):
    """the picked contracts of expiry e, 1-min, from a week before each contract's first pick (§3.3 trims to 3 sessions)."""
    X = data.read_expiry(e, strikes={k for k, _ in cons})
    if X is None: return {}
    out = {}
    for (k, r), g in X.groupby(["strike", "right"]):
        c = cons.get((int(k), r))
        if c is None: continue
        g = g[g.date >= c["first"] - pd.Timedelta(days=warm_days)]
        if len(g): out[(int(k), r)] = g.reset_index(drop=True)
    return out


def front_atm_plan():
    """the older ATM study (§6.1): front expiry incl. expiry day, strike = 09:15 spot rounded to 50."""
    sp = data.spot_0915(); out = []
    for D in sessions():
        e = trade_expiry(D, strictly_after=False)
        if e: out.append((D, e, int(round(sp[D] / 50.0) * 50)))
    return out
