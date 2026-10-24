"""Read-only access to the Breeze Parquet store (D:/nifty_data) for the Charts page.

The store is written by research/strategy_lab/tools/breeze_store.py and is never written here. Layout read:
    index/1minute/<YYYY>/<YYYY-MM>[.partial].parquet                       datetime, open, high, low, close, volume
    futures/1minute/<YYYY>/<expiry>[.partial].parquet                      ... + open_interest, expiry (one monthly contract)
    options/1minute/<YYYY>/<expiry>/<from>__<to>[.partial].parquet          datetime, strike, right, OHLC, volume, open_interest, expiry
Partial files (the month / contract still downloading) are read too, so the chart reaches the last downloaded minute.
Only the regular session (09:15 - 15:29) is kept. Candles of a coarser timeframe are built from the 1-minute ones,
09:15-aligned; open interest is the last value inside each candle. Times are the lab's: the exchange time read as UTC.
"""
import glob
import os

import numpy as np
import pandas as pd
import pyarrow.dataset as ds
import pyarrow.parquet as pq

ROOT = os.environ.get("NIFTY_STORE", "D:/nifty_data")
LO, HI = 9 * 60 + 15, 15 * 60 + 29
TF_MIN = {"minute": 1, "3minute": 3, "5minute": 5, "15minute": 15, "30minute": 30, "60minute": 60}
_CACHE = {}


def _files(*parts):
    return sorted(glob.glob(os.path.join(ROOT, *parts)))


def _read(paths, columns=None, flt=None):
    """One DataFrame from parquet files (cached by path and modification time)."""
    key = (tuple((p, os.path.getmtime(p)) for p in paths), tuple(columns or ()), str(flt))
    if key in _CACHE: return _CACHE[key]
    if not paths: df = pd.DataFrame()
    else:
        df = ds.dataset(paths, format="parquet").to_table(columns=columns, filter=flt).to_pandas()
    while len(_CACHE) > 40: del _CACHE[next(iter(_CACHE))]
    _CACHE[key] = df
    return df


def _session(df):
    m = df["datetime"].dt.hour * 60 + df["datetime"].dt.minute
    return df[(m >= LO) & (m <= HI)]


def _span(paths, frm, to):
    """The files whose name (a month, an expiry, or a from__to range) can hold days frm..to."""
    out = []
    for p in paths:
        n = os.path.basename(p).replace(".partial", "").replace(".parquet", "")
        if "__" in n: a, z = n.split("__")
        elif len(n) == 7: a, z = n + "-01", n + "-31"
        else: a, z = "0000", n
        if a <= to and z >= frm: out.append(p)
    return out


def _candles(df, tf, oi=True):
    """[[t, o, h, l, c, v, oi]] at `tf` from 1-minute rows (sorted, de-duplicated)."""
    if df.empty: return []
    df = _session(df).sort_values("datetime").drop_duplicates("datetime", keep="last")
    t = df["datetime"].to_numpy().astype("datetime64[s]").astype("int64")      # whatever unit pandas gave it
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v = df["volume"].to_numpy(float) if "volume" in df else np.zeros(len(df))
    q = df["open_interest"].to_numpy(float) if oi and "open_interest" in df else None
    m = TF_MIN[tf]
    if m > 1:
        tod = t % 86400; b = t - tod + (555 + ((tod // 60 - 555) // m) * m) * 60
        cut = np.concatenate([[0], np.nonzero(np.diff(b))[0] + 1, [len(t)]]); q0, q1 = cut[:-1], cut[1:] - 1
        t, o, h, l, c, v = b[q0], o[q0], np.maximum.reduceat(h, q0), np.minimum.reduceat(l, q0), c[q1], np.add.reduceat(v, q0)
        if q is not None: q = q[q1]
    return [[int(t[i]), float(o[i]), float(h[i]), float(l[i]), float(c[i]), float(v[i])] + ([float(q[i])] if q is not None else [])
            for i in range(len(t))]


# ---------------------------------------------------------------- what the store holds
def coverage():
    """First / last day of the index, the futures and the options in the store."""
    def ends(paths, col="datetime"):
        if not paths: return None, None
        a = pq.read_table(paths[0], columns=[col]).column(0).to_pandas().min()
        z = pq.read_table(paths[-1], columns=[col]).column(0).to_pandas().max()
        return str(a)[:10], str(z)[:10]
    idx = _files("index", "1minute", "*", "*.parquet"); fut = _files("futures", "1minute", "*", "*.parquet")
    exps = expiries()
    return dict(root=ROOT, index=ends(idx), futures=ends(fut),
                options=(exps[-1]["expiry"], exps[0]["expiry"]) if exps else (None, None), expiries=len(exps))


def expiries():
    """Every option expiry folder, newest first: expiry, monthly (the last of its month among the folders), files."""
    out = []
    for d in _files("options", "1minute", "*", "*"):
        if not os.path.isdir(d): continue
        e = os.path.basename(d)
        if len(e) != 10 or not glob.glob(os.path.join(d, "*.parquet")): continue      # an expiry not downloaded yet
        out.append(dict(expiry=e, files=len(glob.glob(os.path.join(d, "*.parquet"))),
                        partial=bool(glob.glob(os.path.join(d, "*.partial.parquet")))))
    last = {}
    for x in out: last[x["expiry"][:7]] = max(last.get(x["expiry"][:7], ""), x["expiry"])
    for x in out: x["monthly"] = x["expiry"] == last[x["expiry"][:7]]
    return sorted(out, key=lambda x: x["expiry"], reverse=True)


def _exp_files(expiry):
    return _files("options", "1minute", expiry[:4], expiry, "*.parquet")


def strikes(expiry, date=None):
    """One expiry's strikes per right with each one's first / last day, and the strike nearest the index on `date`."""
    df = _read(_exp_files(expiry), columns=["datetime", "strike", "right"])
    if df.empty: raise ValueError(f"no option candles for {expiry} in the store")
    df = df.assign(day=df["datetime"].dt.strftime("%Y-%m-%d"))
    g = df.assign(right=df["right"].astype(str)).groupby(["right", "strike"], observed=True)["day"].agg(["min", "max"]).reset_index()
    first, last = df["day"].min(), df["day"].max()
    d = min(max(date or last, first), last)
    spot = None
    ix = index_candles(d, d, "minute")
    if ix: spot = ix[-1][4]
    out = dict(expiry=expiry, first=first, last=last, date=d, index_close=spot, strikes={}, lives={}, atm={})
    for r in ("CE", "PE"):
        gr = g[g["right"] == r].sort_values("strike")
        out["strikes"][r] = [int(k) for k in gr["strike"]]
        out["lives"][r] = {str(int(k)): [a, z] for k, a, z in zip(gr["strike"], gr["min"], gr["max"])}
        alive = [int(k) for k, a, z in zip(gr["strike"], gr["min"], gr["max"]) if a <= d <= z] or out["strikes"][r]
        out["atm"][r] = min(alive, key=lambda k: abs(k - spot)) if alive and spot is not None else (alive[0] if alive else None)
    return out


# ---------------------------------------------------------------- candles
def index_candles(frm, to, tf="minute"):
    paths = _span(_files("index", "1minute", "*", "*.parquet"), frm, to)
    df = _read(paths)
    if df.empty: return []
    df = df[(df["datetime"] >= pd.Timestamp(frm)) & (df["datetime"] < pd.Timestamp(to) + pd.Timedelta(days=1))]
    return _candles(df, tf, oi=False)


def futures_candles(frm, to, tf="minute"):
    """The near-month futures: on each day the contract with the earliest expiry on or after it."""
    paths = [p for p in _files("futures", "1minute", "*", "*.parquet")
             if os.path.basename(p)[:10] >= frm]                  # contracts expiring on or after the first day
    paths = sorted(paths, key=lambda p: os.path.basename(p)[:10])[:6]
    df = _read(paths)
    if df.empty: return [], []
    df = df[(df["datetime"] >= pd.Timestamp(frm)) & (df["datetime"] < pd.Timestamp(to) + pd.Timedelta(days=1))].copy()
    df["day"] = df["datetime"].dt.normalize(); df["exp"] = pd.to_datetime(df["expiry"])
    df = df[df["exp"] >= df["day"]]
    near = df.groupby("day")["exp"].transform("min"); df = df[df["exp"] == near]
    used = sorted({str(x)[:10] for x in df["exp"].unique()})
    return _candles(df.drop(columns=["day", "exp"]), tf), used


def option_candles(expiry, strike, right, frm, to, tf="minute"):
    paths = _span(_exp_files(expiry), frm, to)
    df = _read(paths, flt=(ds.field("strike") == int(strike)) & (ds.field("right") == right))
    if df.empty: return []
    df = df[(df["datetime"] >= pd.Timestamp(frm)) & (df["datetime"] < pd.Timestamp(to) + pd.Timedelta(days=1))]
    return _candles(df, tf)


def candles(inst, frm, to, tf="minute", expiry=None, strike=None, right=None):
    """The Charts page's request: dict(name, candles [[t, o, h, l, c, v(, oi)]], oi, contracts)."""
    if tf not in TF_MIN: raise ValueError(f"tf must be one of {tuple(TF_MIN)}")
    if inst == "INDEX":
        c = index_candles(frm, to, tf); name, has_oi, extra = "NIFTY 50 index (store)", False, {}
    elif inst == "FUT":
        c, used = futures_candles(frm, to, tf); name, has_oi, extra = "NIFTY near-month futures (store)", True, dict(contracts=used)
    elif inst == "OPT":
        if right not in ("CE", "PE"): raise ValueError("right is CE or PE")
        c = option_candles(expiry, strike, right, frm, to, tf); has_oi, extra = True, {}
        name = f"NIFTY {pd.Timestamp(expiry):%d%b%y} {int(strike)} {right} (store)".upper()
    else: raise ValueError("inst is INDEX, FUT or OPT")
    if not c: raise ValueError(f"{name}: no candles in the store from {frm} to {to}")
    return dict(name=name, inst=inst, tf=tf, frm=frm, to=to, oi=has_oi, candles=c, **extra)
