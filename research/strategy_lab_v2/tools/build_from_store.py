#!/usr/bin/env python3
"""Candle files for lab v2 from the Breeze Parquet store (D:/nifty_data, written by strategy_lab/tools/breeze_store.py).

Reads the store (never writes to it) and writes, under cache/store/ (generated, git-ignored), the files core.py reads:
    nifty50_minute.csv / nifty50_5minute.csv                 the NIFTY index
    niftyfut_nearmonth_minute.csv / ..._5minute.csv          the near-month futures (contract, expiry, front_month)
    options/nifty_options_1minute/<YYYY>/<expiry>/NIFTY_<expiry>_<CE|PE>_1minute.csv + manifest.json
    options/nifty_options/<YYYY>/<expiry>/NIFTY_<expiry>_<CE|PE>_5minute.csv + manifest.json
    build.json                                               what was built, from what, and every exception below

Rules (each one counted in build.json):
  - Rows are taken as the store has them. Only candles from 09:15 to 15:29 are kept (the store also holds pre-open and
    post-close rows; the old files did not), and the store's *.partial.parquet files are used for the months / contracts
    still open (the store itself ignores them for readers; here they extend the data to the last downloaded day).
  - Near-month futures: on each session, the monthly contract with the earliest expiry on or after that day. A contract
    the store does not have yet is taken from the store's _superseded/futures_missing_a_session copy (one session short)
    and, failing that, from the old CSV (config/data.v1.json): never from the next month's contract.
  - 5-minute files are the 1-minute candles grouped into 09:15-aligned 5-minute candles.
  - Options: one expiry is exported when every one of its store files is final (the expiry has passed). Its manifest
    carries "full_chain" (the store fetches every identified contract around the money) and the first session it covers.

    python tools/build_from_store.py                # build / refresh everything
    python tools/build_from_store.py --root D:/nifty_data --no-options
"""
import argparse, datetime as dt, glob, json, os, sys, time

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, "cache", "store")
LO, HI = 9 * 60 + 15, 15 * 60 + 29


def in_session(df):
    m = df["datetime"].dt.hour * 60 + df["datetime"].dt.minute
    return df[(m >= LO) & (m <= HI)]


def read_many(files):
    return pd.concat([pq.read_table(f).to_pandas() for f in files], ignore_index=True) if files else pd.DataFrame()


def units(root, kind):
    """Final files plus the partial file of a unit that has no final file yet."""
    final = sorted(f for f in glob.glob(f"{root}/{kind}/1minute/*/*.parquet") if ".partial." not in f)
    done = {os.path.basename(f)[:-8] for f in final}
    part = sorted(f for f in glob.glob(f"{root}/{kind}/1minute/*/*.partial.parquet") if os.path.basename(f)[:-16] not in done)
    return final, part


def five(df, keys=()):
    """1-minute rows -> 09:15-aligned 5-minute candles (per `keys`)."""
    m = df["datetime"].dt.hour * 60 + df["datetime"].dt.minute
    b = df["datetime"].dt.normalize() + pd.to_timedelta(LO + ((m - LO) // 5) * 5, unit="m")
    g = df.assign(datetime=b).groupby([*keys, "datetime"], sort=True, observed=True)
    agg = dict(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"))
    for extra in ("oi", "open_interest", "contract", "expiry", "front_month"):
        if extra in df: agg[extra] = (extra, "last")
    return g.agg(**agg).reset_index()


def write_csv(df, path, cols):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = df[cols].copy(); out["datetime"] = out["datetime"].dt.strftime("%Y-%m-%d %H:%M:%S")
    tmp = path + ".tmp"; out.to_csv(tmp, index=False); os.replace(tmp, path)


def build_index(root, note):
    final, part = units(root, "index")
    raw = read_many(final + part)
    df = in_session(raw).drop_duplicates("datetime").sort_values("datetime").reset_index(drop=True)
    df["oi"] = ""
    note["index"] = dict(files=len(final), partial_files=len(part), rows_in_store=len(raw), rows_kept=len(df),
                         dropped_outside_0915_1529=len(raw) - len(in_session(raw)),
                         first=str(df.datetime.min()), last=str(df.datetime.max()), sessions=int(df.datetime.dt.normalize().nunique()))
    write_csv(df, os.path.join(OUT, "nifty50_minute.csv"), ["datetime", "open", "high", "low", "close", "volume", "oi"])
    f5 = five(df); f5["oi"] = ""
    write_csv(f5, os.path.join(OUT, "nifty50_5minute.csv"), ["datetime", "open", "high", "low", "close", "volume", "oi"])
    return df


def build_futures(root, note, old_cfg):
    final, part = units(root, "futures")
    raw = read_many(final + part); raw["src"] = "store"
    sup = sorted(glob.glob(f"{root}/_superseded/futures_missing_a_session/*.parquet"))
    have = {os.path.basename(f)[:10] for f in final + part}
    sup = [f for f in sup if os.path.basename(f)[:10] not in have]
    if sup:
        s = read_many(sup); s["src"] = "superseded"; raw = pd.concat([raw, s], ignore_index=True)
    df = in_session(raw).copy()
    df["day"] = df.datetime.dt.normalize(); df["exp"] = pd.to_datetime(df["expiry"])
    df = df[df.exp >= df.day]
    df = df[df.exp == df.groupby("day").exp.transform("min")]
    # a session whose nearest contract in hand is not the nearest monthly expiry in the store's own list = a contract the
    # store lacks: those sessions are dropped here (never traded on the next month) and filled from the old CSV if it has them
    exps = np.array(sorted(pd.to_datetime(sorted({os.path.basename(f)[:10] for f in final + part + sup}))), dtype="datetime64[ns]")
    filled = []
    if old_cfg and os.path.exists(old_cfg["futures"]["minute"]):
        old = pd.read_csv(old_cfg["futures"]["minute"], parse_dates=["datetime"])
        old["day"] = old.datetime.dt.normalize()
        miss = old[~old.day.isin(df.day.unique())]
        if len(miss):
            miss = miss.assign(exp=pd.to_datetime(miss["expiry"]), open_interest=miss["oi"], src="old_csv")
            filled = sorted(str(d.date()) for d in miss.day.unique())
            df = pd.concat([df, miss[["datetime", "open", "high", "low", "close", "volume", "open_interest", "day", "exp", "src"]]], ignore_index=True)
    df = df.drop_duplicates("datetime").sort_values("datetime").reset_index(drop=True)
    df["expiry"] = df.exp.dt.strftime("%Y-%m-%d")
    df["contract"] = "NIFTY" + df.exp.dt.strftime("%y%b").str.upper() + "FUT"
    df["front_month"] = 1; df["oi"] = df["open_interest"].fillna(0).astype("int64")
    gaps = []                                              # sessions the index has and the futures do not
    note["futures"] = dict(files=len(final), partial_files=len(part), superseded_files_used=[os.path.basename(f) for f in sup],
                           rows_kept=len(df), rows_by_source={k: int(v) for k, v in df.src.value_counts().items()},
                           sessions_filled_from_old_csv=filled, first=str(df.datetime.min()), last=str(df.datetime.max()),
                           sessions=int(df.day.nunique()), contracts=int(df.contract.nunique()))
    cols = ["datetime", "open", "high", "low", "close", "volume", "oi", "contract", "expiry", "front_month"]
    write_csv(df, os.path.join(OUT, "niftyfut_nearmonth_minute.csv"), cols)
    write_csv(five(df), os.path.join(OUT, "niftyfut_nearmonth_5minute.csv"), cols)
    return df


def expected_chunks(e, sessions):
    """The store's units of one expiry (breeze_store options_units): the sessions of the last 45 calendar days up to a
    weekly expiry, 75 for a monthly (the month's last expiry), in 2-session chunks."""
    d = dt.date.fromisoformat(e)
    monthly = (d + dt.timedelta(days=7)).month != d.month
    start = (d - dt.timedelta(days=75 if monthly else 45)).isoformat()
    ds = [x for x in sessions if start <= x <= e]
    return [(ds[i], ds[min(i + 1, len(ds) - 1)]) for i in range(0, len(ds), 2)]


def build_options(root, note, sessions):
    import sqlite3
    today = dt.date.today().isoformat(); done = []; skipped = []
    led = os.path.join(root, "_meta", "ledger.sqlite"); status = {}
    if os.path.exists(led):
        con = sqlite3.connect(f"file:{led}?mode=ro", uri=True)
        status = dict(con.execute("SELECT unit_id, status FROM units WHERE kind='options'").fetchall()); con.close()
    for edir in sorted(glob.glob(f"{root}/options/1minute/*/*")):
        e = os.path.basename(edir)
        files = sorted(glob.glob(edir + "/*.parquet"))
        if not files: continue
        if e >= today or any(".partial." in f for f in files):
            skipped.append(dict(expiry=e, why="not expired yet / partial files")); continue
        have = {os.path.basename(f)[:-8] for f in files}
        todo = [f"{a}__{b}" for a, b in expected_chunks(e, sessions)
                if f"{a}__{b}" not in have and status.get(f"options|{e}|{a}|{b}") not in ("empty", "no_data_at_source")]
        if todo:
            skipped.append(dict(expiry=e, why=f"download in progress: {len(todo)} of its chunks not fetched yet (earliest missing {todo[0]})")); continue
        sig = [[os.path.basename(f), os.path.getsize(f), int(os.path.getmtime(f))] for f in files]
        man1 = os.path.join(OUT, "options", "nifty_options_1minute", e[:4], e, "manifest.json")
        if os.path.exists(man1) and json.load(open(man1, encoding="utf-8")).get("store_files") == sig:
            done.append(e); continue
        df = in_session(read_many(files))
        df["right"] = df["right"].astype(str)
        df = df.drop_duplicates(["strike", "right", "datetime"]).sort_values(["right", "strike", "datetime"])
        df = df.assign(stock_code="NIFTY", exchange_code="NFO", expiry_date=e, strike_price=df["strike"], option_right=df["right"])
        cols = ["datetime", "stock_code", "exchange_code", "expiry_date", "strike_price", "option_right", "open", "high", "low",
                "close", "volume", "open_interest"]
        days = sorted(str(d.date()) for d in df.datetime.dt.normalize().unique())
        man = dict(source="breeze_store", store_root=root, store_files=sig, expiry=e, first_session=days[0], last_session=days[-1],
                   sessions=len(days), strikes=sorted(int(k) for k in df.strike.unique()), rows=len(df),
                   full_chain=dict(note="every contract the store identified around the money (breeze_store options_units)",
                                   from_session=days[0]))
        f5 = five(df, keys=("right", "strike")).assign(stock_code="NIFTY", exchange_code="NFO", expiry_date=e)
        f5["strike_price"] = f5["strike"]; f5["option_right"] = f5["right"]
        for sub, tf, d_ in (("nifty_options_1minute", "1minute", df), ("nifty_options", "5minute", f5)):
            base = os.path.join(OUT, "options", sub, e[:4], e)
            for right in ("CE", "PE"):
                write_csv(d_[d_["right"] == right], os.path.join(base, f"NIFTY_{e}_{right}_{tf}.csv"), cols)
            json.dump(man, open(os.path.join(base, "manifest.json"), "w", encoding="utf-8"), indent=1)
        done.append(e)
    note["options"] = dict(expiries_exported=done, skipped=skipped)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="D:/nifty_data"); ap.add_argument("--no-options", action="store_true")
    a = ap.parse_args()
    if not os.path.isdir(a.root): sys.exit(f"no store at {a.root}")
    os.makedirs(OUT, exist_ok=True)
    v1 = os.path.join(HERE, "config", "data.v1.json")
    old_cfg = json.load(open(v1, encoding="utf-8")) if os.path.exists(v1) else None
    note = dict(built_at=dt.datetime.now().isoformat(timespec="seconds"), store=a.root); t0 = time.time()
    idx = build_index(a.root, note); print("index  ", note["index"])
    fut = build_futures(a.root, note, old_cfg); print("futures", note["futures"])
    di, df_ = set(idx.datetime.dt.normalize().unique()), set(fut.day.unique())
    note["sessions_index_only"] = sorted(str(pd.Timestamp(d).date()) for d in di - df_)
    note["sessions_futures_only"] = sorted(str(pd.Timestamp(d).date()) for d in df_ - di)
    print("sessions only in the index:", note["sessions_index_only"]); print("sessions only in the futures:", note["sessions_futures_only"])
    if not a.no_options:
        ex = os.path.join(a.root, "_meta", "extra_sessions.json")
        extra = json.load(open(ex, encoding="utf-8"))["sessions"] if os.path.exists(ex) else []
        sess = sorted({str(pd.Timestamp(d).date()) for d in di} | set(extra))
        build_options(a.root, note, sess); print("options", note["options"])
    json.dump(note, open(os.path.join(OUT, "build.json"), "w", encoding="utf-8"), indent=1)
    print(f"done in {time.time() - t0:.1f}s -> {OUT}")


if __name__ == "__main__":
    main()
