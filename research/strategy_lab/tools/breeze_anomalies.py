#!/usr/bin/env python3
"""List impossible values in the Breeze Parquet store, without changing any file.

    python tools/breeze_anomalies.py            # -> <root>/_missing/anomalies.csv and a summary

Checked on every candle: price <= 0, high < low, open or close outside low..high, volume < 0, open interest < 0.
Index candles have no volume, so volume is not checked there. One output row per (file, candle, issue).
"""
import csv
import glob
import os
import sys
from collections import Counter

import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = "D:/nifty_data"


def checks(t):
    o, h, l, c = (t[k] for k in ("open", "high", "low", "close"))
    out = [("price <= 0", pc.or_(pc.or_(pc.less_equal(o, 0), pc.less_equal(h, 0)),
                                  pc.or_(pc.less_equal(l, 0), pc.less_equal(c, 0)))),
           ("high < low", pc.less(h, l)),
           ("open outside low..high", pc.or_(pc.less(o, l), pc.greater(o, h))),
           ("close outside low..high", pc.or_(pc.less(c, l), pc.greater(c, h)))]
    if "volume" in t.column_names:
        out.append(("volume < 0", pc.less(t["volume"], 0)))
    if "open_interest" in t.column_names:
        out.append(("open interest < 0", pc.less(t["open_interest"], 0)))
    return out


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else ROOT
    files = sorted(glob.glob(os.path.join(root, "**", "*.parquet"), recursive=True))
    files = [f for f in files if os.sep + "_" not in f.replace(root, "")]      # not _superseded / _duplicates
    rows, per = [], Counter()
    for n, f in enumerate(files, 1):
        t = pq.read_table(f)
        rel = os.path.relpath(f, root).replace(os.sep, "/")
        kind = rel.split("/")[0]
        for issue, mask in checks(t):
            if kind == "index" and issue.startswith("volume"):
                continue
            hit = t.filter(mask)
            if not hit.num_rows:
                continue
            per[(kind if kind != "seconds" else "seconds", issue)] += hit.num_rows
            d = hit.to_pydict()
            for i in range(hit.num_rows):
                rows.append([rel, d["datetime"][i], d.get("strike", [""] * hit.num_rows)[i],
                             d.get("right", [""] * hit.num_rows)[i], issue, d["open"][i], d["high"][i], d["low"][i],
                             d["close"][i], d.get("volume", [""] * hit.num_rows)[i],
                             d.get("open_interest", [""] * hit.num_rows)[i]])
        if n % 1000 == 0:
            print(f"  {n}/{len(files)} files, {len(rows)} anomalies so far", flush=True)
    out = os.path.join(root, "_missing", "anomalies.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out + ".tmp", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "datetime", "strike", "right", "issue", "open", "high", "low", "close", "volume",
                    "open_interest"])
        w.writerows(rows)
    os.replace(out + ".tmp", out)
    print(f"{len(files)} files checked, {len(rows)} anomalies -> {out}")
    for (kind, issue), k in sorted(per.items()):
        print(f"   {kind:8} {issue:26} {k:,}")


if __name__ == "__main__":
    main()
