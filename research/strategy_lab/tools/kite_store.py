#!/usr/bin/env python3
"""Zerodha (Kite MCP) candles into the Parquet store, kept apart from the Breeze files: <root>/zerodha/...

The Kite MCP tool get_historical_data saves each large answer as a JSON text file; this script only reads those
files (no network), stores the candles as returned (type conversion only, exact repeats of a timestamp dropped and
counted) and compares the result with the Breeze index.

    python tools/kite_store.py index <folder with the saved answers>      # -> zerodha/index/1minute/<YYYY>/<YYYY-MM>.parquet
    python tools/kite_store.py compare                                    # Zerodha index against Breeze index
"""
import datetime as dt
import glob
import json
import os
import sys
from collections import defaultdict

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = "D:/nifty_data"
SCHEMA = pa.schema([("datetime", pa.timestamp("s")), ("open", pa.float64()), ("high", pa.float64()),
                    ("low", pa.float64()), ("close", pa.float64()), ("volume", pa.int64())])


def build_index(folder):
    rows, dup, differ, files = {}, 0, 0, 0
    for f in sorted(glob.glob(os.path.join(folder, "*get_historical_data*.txt"))):
        with open(f, encoding="utf-8") as fh:
            try:
                data = json.load(fh)
            except ValueError:
                print(f"skipped (not JSON): {os.path.basename(f)}")
                continue
        if not data or "date" not in data[0]:
            continue
        files += 1
        for x in data:
            ts = dt.datetime.fromisoformat(x["date"][:19])              # +05:30 dropped: naive IST, like the Breeze files
            r = (ts, float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]), int(x.get("volume") or 0))
            if ts in rows:
                dup += 1
                differ += rows[ts] != r
            else:
                rows[ts] = r
    by = defaultdict(list)
    for ts in sorted(rows):
        by[f"{ts.year:04d}-{ts.month:02d}"].append(rows[ts])
    for ym, recs in by.items():
        path = os.path.join(ROOT, "zerodha", "index", "1minute", ym[:4], ym + ".parquet")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        t = pa.Table.from_arrays([pa.array(list(c), type=f.type) for f, c in zip(SCHEMA, zip(*recs))], schema=SCHEMA)
        pq.write_table(t, path + ".tmp", compression="zstd", compression_level=9, row_group_size=len(recs))
        os.replace(path + ".tmp", path)
    ks = sorted(rows)
    print(f"{files} answer files, {len(rows):,} candles, {ks[0]} .. {ks[-1]}, {len(by)} month files; "
          f"repeated timestamps dropped {dup} (with different values: {differ})")


def load(sub):
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, sub, "index", "1minute", "*", "*.parquet"))):
        if f.endswith(".partial.parquet") and os.path.exists(f.replace(".partial.parquet", ".parquet")):
            continue
        t = pq.read_table(f).to_pydict()
        for i, ts in enumerate(t["datetime"]):
            out[ts] = (t["open"][i], t["high"][i], t["low"][i], t["close"][i])
    return out


def compare():
    z, b = load("zerodha"), load("")
    hours = lambda ts: 555 <= ts.hour * 60 + ts.minute <= 929           # 09:15 .. 15:29
    zs, bs_ = defaultdict(int), defaultdict(int)
    for ts in z:
        if hours(ts): zs[ts.date()] += 1
    for ts in b:
        if hours(ts): bs_[ts.date()] += 1
    days = sorted(set(zs) | set(bs_))
    print(f"sessions: Zerodha {len(zs)}, Breeze {len(bs_)}")
    print("sessions only at Zerodha:", [str(d) for d in days if d not in bs_])
    print("sessions only at Breeze: ", [str(d) for d in days if d not in zs])
    print("Zerodha sessions under 375 candles:", [(str(d), zs[d]) for d in days if 0 < zs[d] < 375])
    print("Breeze sessions under 375 candles: ", [(str(d), bs_[d]) for d in days if 0 < bs_[d] < 375])
    both = [ts for ts in z if ts in b and hours(ts)]
    exact = sum(1 for ts in both if z[ts] == b[ts])
    close_ = sum(1 for ts in both if abs(z[ts][3] - b[ts][3]) <= 0.05)
    big = sorted(((abs(z[ts][3] - b[ts][3]), ts) for ts in both), reverse=True)[:10]
    print(f"candles in both (09:15-15:29): {len(both):,}; all four prices identical: {exact:,} ({100 * exact / len(both):.2f}%); "
          f"close within 0.05: {close_:,} ({100 * close_ / len(both):.2f}%)")
    by_year = defaultdict(lambda: [0, 0])
    for ts in both:
        by_year[ts.year][0] += 1
        by_year[ts.year][1] += abs(z[ts][3] - b[ts][3]) <= 0.05
    print("close within 0.05 by year:", {y: f"{100 * v[1] / v[0]:.2f}%" for y, v in sorted(by_year.items())})
    print("largest close differences:", [(str(ts), round(d, 2), z[ts][3], b[ts][3]) for d, ts in big])
    only_b = sum(1 for ts in b if hours(ts) and ts not in z)
    only_z = sum(1 for ts in z if hours(ts) and ts not in b)
    print(f"in-hours candles only at Breeze: {only_b:,}; only at Zerodha: {only_z:,}")
    print("Breeze timestamps outside 09:15-15:29:", sum(1 for ts in b if not hours(ts)),
          "; Zerodha:", sum(1 for ts in z if not hours(ts)))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "index":
        build_index(sys.argv[2])
    elif len(sys.argv) > 1 and sys.argv[1] == "compare":
        compare()
    else:
        sys.exit(__doc__)
