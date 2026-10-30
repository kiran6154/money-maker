"""Data access for nifty_bt (spec §1): NIFTY index 1-min, option expiry folders (regular + wide files, zip archives), all
read-only from the Breeze store (D:/nifty_data, or $NIFTY_STORE).

Parity with the handoff research (golden trades) needs the same file set it had:
  * the regular `<d1>__<d2>.parquet` and `.wide.parquet` files; the later `.wide3k.parquet` files are excluded by default
    (FILES = ("", ".wide"); add ".wide3k" for the wider chain);
  * 2026 zip archives (`options/1minute/2026/*.zip`, members `<expiry>/<file>.parquet`) are read too and, as in the
    reference, their rows win over the folder's on a duplicate (datetime, strike, right);
  * option prices are rounded through float32, as the reference stored them.
"""
import os, glob, io, zipfile, functools
import numpy as np, pandas as pd

ROOT = os.environ.get("NIFTY_STORE", "D:/nifty_data")
OPT = os.path.join(ROOT, "options", "1minute")
FILES = ("", ".wide")                       # file kinds read from an expiry folder
END = "2026-10-19"                          # the handoff's data end (golden trades); None = everything
PARITY_DAYS = int(os.environ.get("NBT_PARITY_DAYS", "0")) or None
# The store was re-downloaded (2026-10-25) with far longer per-expiry history than the handoff had: from 2019 its folders held
# only about the last two weeks before expiry. PARITY_DAYS = 14 keeps only rows dated >= expiry - 14 days for expiries from
# 2019 (2018 monthlies were complete) - use it to reproduce the golden trades; leave it off for research.


def in_window(e, dates):
    """mask of rows the parity window keeps (all True when PARITY_DAYS is off)."""
    if not PARITY_DAYS or e < "2019-01-01": return np.ones(len(dates), bool)
    return (pd.to_datetime(dates) >= pd.Timestamp(e) - pd.Timedelta(days=PARITY_DAYS)).values


def _kind(name):
    n = name[:-8]                                                     # strip .parquet
    for k in (".wide3k", ".wide", ".partial"):
        if n.endswith(k): return k if k != ".partial" else ""
    return ""


@functools.lru_cache(None)
def _zip_members():
    """expiry -> [(zip path, member)] for the 2026 archives."""
    out = {}
    for z in sorted(glob.glob(os.path.join(OPT, "*", "*.zip"))):
        for m in zipfile.ZipFile(z).namelist():
            if m.endswith(".parquet") and "/" in m and _kind(os.path.basename(m)) in FILES:
                out.setdefault(m.split("/")[0], []).append((z, m))
    return out


@functools.lru_cache(None)
def expiries():
    """every expiry folder (or zip-only expiry), sorted."""
    s = {os.path.basename(d) for d in glob.glob(os.path.join(OPT, "*", "20??-??-??")) if os.path.isdir(d)}
    return tuple(sorted(s | set(_zip_members())))


def _sources(e):
    """(sort key, reader) per file, in the reference's order: zip archive paths first, then the folder's files sorted."""
    src = [("/home/claude/optzip/" + m, ("zip", z, m)) for z, m in _zip_members().get(e, [])]
    for f in glob.glob(os.path.join(OPT, e[:4], e, "*.parquet")):
        if _kind(os.path.basename(f)) in FILES: src.append(("/mnt/user-data/" + os.path.basename(f), ("file", f, None)))
    return [s for _, s in sorted(src)]


def read_expiry(e, columns=("datetime", "strike", "right", "open", "high", "low", "close"), strikes=None, f32=True):
    """every row of expiry e (session minutes 09:15-15:29), first file wins on duplicates. strikes: optional set filter."""
    parts = []
    for kind, p, m in _sources(e):
        try:
            d = pd.read_parquet(p if kind == "file" else io.BytesIO(zipfile.ZipFile(p).read(m)), columns=list(columns))
        except Exception:
            continue
        if strikes is not None: d = d[d.strike.isin(strikes)]
        d = d[in_window(e, d.datetime.astype("datetime64[ns]").dt.normalize())]
        if len(d): parts.append(d)
    if not parts: return None
    X = pd.concat(parts, ignore_index=True); X["right"] = X.right.astype(str); X["strike"] = X.strike.astype(int)
    X["datetime"] = X.datetime.astype("datetime64[ns]")
    X = X.drop_duplicates(["strike", "right", "datetime"])
    tod = X.datetime.dt.hour * 60 + X.datetime.dt.minute
    X = X[(tod >= 555) & (tod <= 929)].copy()
    X["tod"] = (X.datetime.dt.hour * 60 + X.datetime.dt.minute).astype("int16")
    X["date"] = X.datetime.dt.normalize()
    if f32:
        for c in ("open", "high", "low", "close"):
            if c in X: X[c] = X[c].astype("float32").astype(float)
    return X.sort_values(["strike", "right", "datetime"]).reset_index(drop=True)


@functools.lru_cache(None)
def index_1m_all():
    """NIFTY index 1-min, session minutes only, the 2026-08-03 15:15-15:29 prints dropped (§1)."""
    fs = sorted(glob.glob(os.path.join(ROOT, "index", "1minute", "*", "*.parquet")))
    d = pd.concat([pd.read_parquet(f, columns=["datetime", "open", "high", "low", "close"]) for f in fs], ignore_index=True)
    d["datetime"] = d.datetime.astype("datetime64[ns]")
    d = d.drop_duplicates("datetime", keep="last").sort_values("datetime").reset_index(drop=True)
    d["tod"] = d.datetime.dt.hour * 60 + d.datetime.dt.minute; d["date"] = d.datetime.dt.normalize()
    d = d[(d.tod >= 555) & (d.tod <= 929)]
    d = d[~((d.date >= pd.Timestamp("2026-08-03")) & (d.tod >= 915))]
    if END: d = d[d.date <= pd.Timestamp(END)]
    return d.reset_index(drop=True)


def index_1m():
    """the index as the reference's load_1m(): sessions with >= 300 one-minute bars."""
    d = index_1m_all(); n = d.groupby("date").size()
    return d[d.date.isin(n[n >= 300].index)].reset_index(drop=True)


@functools.lru_cache(None)
def spot_0915():
    """NIFTY 09:15 five-minute close per session (the 09:19 one-minute close), known at 09:20."""
    d = index_1m_all(); x = d[(d.tod >= 555) & (d.tod <= 559)].groupby("date").close.last()
    return x
