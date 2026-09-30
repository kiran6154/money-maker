"""Data layer for the wave-lifecycle study (PREREG.md §1-2).

Loads the Breeze option folders, marks filler bars, resamples, picks the scanned contracts per session
from the 09:20 index reference (no hindsight), and builds the put-call-parity forward.
Everything is cached under research/strategy_lab/cache/waves/ (git-ignored).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
LAB = HERE.parents[1]
CACHE = LAB / "cache" / "waves"
CACHE.mkdir(parents=True, exist_ok=True)

SPOT5 = "D:/nifty/nifty50_5minute_2019-01-01_to_2026-09-26.csv"
OPT5 = "D:/nifty/data/nifty_options"
OPT1 = "D:/nifty/data/nifty_options_1minute"
# period by the front expiry's year (PREREG §1)
SOURCES = {2024: (OPT5, "5minute"), 2025: (OPT1, "1minute"), 2026: (OPT1, "1minute")}
PERIOD = {2024: "dev", 2025: "val", 2026: "blind"}
R = 0.065
GRID = 100
USECOLS = ["datetime", "strike_price", "option_right", "open", "high", "low", "close", "volume"]


def expiry_calendar() -> list[pd.Timestamp]:
    """Every expiry the folders know of (with or without data) - used to find the true front expiry."""
    out = set()
    for root in (OPT5, OPT1):
        for y in os.listdir(root):
            for d in os.listdir(f"{root}/{y}"):
                try:
                    out.add(pd.Timestamp(d))
                except ValueError:
                    pass
    return sorted(out)


def _ref_time(man: dict) -> pd.Timestamp | None:
    t = man.get("reference_time") or man.get("atm_reference_time")
    return pd.Timestamp(t) if t else None


def load_year(year: int) -> pd.DataFrame:
    """All option rows whose expiry falls in `year`, from that year's source, at the source interval."""
    path = CACHE / f"raw_{year}.parquet"
    if path.exists():
        # streamed in batches and cut to the 100-pt grid the study uses (memory: the machine is shared)
        import pyarrow.parquet as pq
        parts = []
        for batch in pq.ParquetFile(path).iter_batches(batch_size=500_000):
            x = batch.to_pandas()
            parts.append(x[x.strike % GRID == 0])
        return pd.concat(parts, ignore_index=True)
    root, iv = SOURCES[year]
    frames = []
    for d in sorted(os.listdir(f"{root}/{year}")):
        folder = f"{root}/{year}/{d}"
        files = os.listdir(folder)
        ce = [f for f in files if f.endswith(f"_CE_{iv}.csv")]
        pe = [f for f in files if f.endswith(f"_PE_{iv}.csv")]
        if not ce or not pe:
            continue
        man = json.load(open(f"{folder}/manifest.json")) if "manifest.json" in files else {}
        ref = _ref_time(man)
        for f in ce + pe:
            x = pd.read_csv(f"{folder}/{f}", usecols=USECOLS, parse_dates=["datetime"])
            x = x[(x.datetime.dt.time >= pd.Timestamp("09:15").time()) & (x.datetime.dt.time < pd.Timestamp("15:30").time())]
            x["expiry"] = pd.Timestamp(d)
            x["ref_time"] = ref
            frames.append(x)
    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={"datetime": "dt", "strike_price": "strike", "option_right": "right"})
    df["right"] = (df["right"].str.upper() == "PE").astype(np.int8)  # 0 CE, 1 PE
    df = df.drop_duplicates(["expiry", "strike", "right", "dt"]).sort_values(["expiry", "strike", "right", "dt"])
    df = df.reset_index(drop=True)
    # filler: no volume and a flat bar at the previous close (a forward-filled print)
    prev = df.groupby(["expiry", "strike", "right"])["close"].shift(1)
    flat = (df.open == df.high) & (df.high == df.low) & (df.low == df.close)
    df["filler"] = (df.volume == 0) & flat & ((df.close == prev) | prev.isna())
    df["interval"] = iv
    df.to_parquet(path)
    return df


def resample(df: pd.DataFrame, minutes: int, base_minutes: int) -> pd.DataFrame:
    """Aggregate base bars into `minutes` bars anchored at 09:15 each session. Filler = every constituent filler."""
    if minutes == base_minutes:
        return df.copy()
    assert minutes % base_minutes == 0, (minutes, base_minutes)
    d = df.copy()
    sess = d.dt.dt.normalize()
    mins = (d.dt - sess - pd.Timedelta("9h15min")).dt.total_seconds() // 60
    d["bar"] = sess + pd.Timedelta("9h15min") + pd.to_timedelta((mins // minutes) * minutes, unit="m")
    # true volume only from traded bars; a filler bar's OHLC is the stale close
    d["tr"] = ~d.filler
    g = d.groupby(["expiry", "strike", "right", "bar"], sort=True)
    live = d[d.tr]
    gl = live.groupby(["expiry", "strike", "right", "bar"], sort=True)
    out = pd.DataFrame({
        "open": g.open.first(), "high": g.high.max(), "low": g.low.min(), "close": g.close.last(),
        "volume": g.volume.sum(), "filler": ~g.tr.any(), "ref_time": g.ref_time.first(),
    })
    # prefer traded-bar extremes when any trade happened (a stale filler print must not set a high / low)
    hl = pd.DataFrame({"h2": gl.high.max(), "l2": gl.low.min(), "o2": gl.open.first()})
    out = out.join(hl)
    m = out.h2.notna()
    out.loc[m, "high"] = out.loc[m, ["h2"]].values.ravel()
    out.loc[m, "low"] = out.loc[m, ["l2"]].values.ravel()
    out.loc[m, "open"] = out.loc[m, ["o2"]].values.ravel()
    out = out.drop(columns=["h2", "l2", "o2"]).reset_index().rename(columns={"bar": "dt"})
    return out


def spot_reference() -> pd.DataFrame:
    """Per session: 09:20 reference (close of the 09:15 5-minute bar), session open, close, high, low (long index file)."""
    path = CACHE / "spot_ref.parquet"
    if path.exists():
        return pd.read_parquet(path)
    s = pd.read_csv(SPOT5, parse_dates=["datetime"])
    s["date"] = s.datetime.dt.normalize()
    g = s.groupby("date")
    ref = s[s.datetime.dt.strftime("%H:%M") == "09:15"].set_index("date").close.rename("ref")
    out = pd.DataFrame({"s_open": g.open.first(), "s_close": g.close.last(), "s_high": g.high.max(), "s_low": g.low.min()})
    out = out.join(ref)
    out["range_pct"] = (out.s_high / out.s_low - 1) * 100
    out["prev_range_pct"] = out.range_pct.shift(1)
    out["prev_range_med20"] = out.range_pct.shift(1).rolling(20, min_periods=10).median()
    out.to_parquet(path)
    return out


def spot5() -> pd.DataFrame:
    path = CACHE / "spot5.parquet"
    if path.exists():
        return pd.read_parquet(path)
    s = pd.read_csv(SPOT5, parse_dates=["datetime"]).rename(columns={"datetime": "dt"})
    s.to_parquet(path)
    return s


def forward(df: pd.DataFrame) -> pd.DataFrame:
    """Put-call-parity forward per (expiry, bar): median over strikes where both legs traded, nearest 3 strikes to the
    previous estimate (approximated by the strikes with the smallest |C - P|)."""
    x = df[~df.filler].pivot_table(index=["expiry", "dt", "strike"], columns="right", values="close", aggfunc="last")
    x = x.dropna()
    x.columns = ["C", "P"]
    x = x.reset_index()
    T = ((x.expiry + pd.Timedelta("15h30min")) - x.dt).dt.total_seconds() / (365 * 86400)
    x["F"] = x.strike + (x.C - x.P) * np.exp(R * T.clip(lower=0))
    x["gap"] = (x.C - x.P).abs()
    x = x.sort_values(["expiry", "dt", "gap"])
    x = x.groupby(["expiry", "dt"]).head(3)
    return x.groupby(["expiry", "dt"]).F.median().rename("F").reset_index()


def sessions(year: int, df: pd.DataFrame, cal: list[pd.Timestamp]) -> pd.DataFrame:
    """One row per (session date, role) with the chosen expiry, DTE and the strike-set hindsight flag."""
    ref = spot_reference()
    cal = np.array(cal, dtype="datetime64[ns]")
    have = {e: g for e, g in df.groupby("expiry")}
    rows = []
    dates = sorted(df.dt.dt.normalize().unique())
    for d in dates:
        d = pd.Timestamp(d)
        later = cal[cal >= np.datetime64(d)]
        if len(later) == 0 or d not in ref.index or pd.isna(ref.loc[d, "ref"]):
            continue
        for role, i in (("front", 0), ("next", 1)):
            if len(later) <= i:
                continue
            e = pd.Timestamp(later[i])
            if e.year != year or e not in have:
                rows.append(dict(date=d, role=role, expiry=e, available=False))
                continue
            g = have[e]
            rt = g.ref_time.iloc[0]
            rows.append(dict(date=d, role=role, expiry=e, available=True,
                             dte=(e - d).days, spot_ref=ref.loc[d, "ref"],
                             atm=int(round(ref.loc[d, "ref"] / GRID) * GRID),
                             strike_set_hindsight=bool(rt is not None and pd.notna(rt) and d < pd.Timestamp(rt).normalize())))
    return pd.DataFrame(rows)


def dte_bucket(dte: int) -> str:
    return "0" if dte == 0 else "1" if dte == 1 else "2" if dte == 2 else "3-4" if dte <= 4 else "5+"


# the scanned contracts: moneyness label -> strike offset for CE (PE mirrors)
MONEYNESS = {"ATM": 0, "OTM1": 1, "OTM2": 2, "ITM1": -1}


def contract_strike(atm: int, right: int, money: str) -> int:
    off = MONEYNESS[money] * GRID
    return atm + off if right == 0 else atm - off
