#!/usr/bin/env python3
"""Keep the second copies Breeze sent: for every file whose download dropped repeated timestamps, ask Breeze again
and store every candle version that differs from the one in the store file, beside nothing it reads:

    <root>/_duplicates/<same path as the store file, .parquet -> .dups.parquet>

The store files are not changed. Same columns as the store file. Breeze sometimes sends one minute twice with
different values (seen around 2024-04-15..22 and 2025-06-20); the store keeps the first copy of a download, so a
copy here is "another version of a candle the store already has", never a candle the store is missing.

    python tools/breeze_dups.py --plan
    python tools/breeze_dups.py [--gap 0.25 --workers 4]
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor

import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breeze_store as bs  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=bs.DEFAULT_ROOT)
    p.add_argument("--gap", type=float, default=0.25)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--plan", action="store_true")
    a = p.parse_args()
    bs.MIN_GAP = a.gap
    db = sqlite3.connect(f"file:{a.root}/_meta/ledger.sqlite?mode=ro", uri=True, timeout=60)
    want = {u: f for u, f in db.execute("SELECT unit_id, file FROM units WHERE dup_dropped > 0 AND file IS NOT NULL")}
    skipped = {}
    for u, k, r in db.execute("SELECT unit_id, strike, right FROM empty_requests WHERE message = ?", (bs.SKIP_NOTE,)):
        skipped.setdefault(u, set()).add((k, r))
    db.close()
    today, frm = dt.date.today(), dt.date(2018, 1, 1)
    units = {}
    for ph, start in (("futures", frm), ("options", frm), ("wide", dt.date(2024, 9, 1))):
        for u in bs.phase_units(a.root, ph, start, today, today, (1, 2), bs.WINGS):
            if u.uid in want:
                units[u.uid] = u
    jobs = []
    for uid, f in sorted(want.items()):
        u = units.get(uid)
        if u is None:
            print(f"{uid}: not in the current plan, skipped")
            continue
        out = os.path.join(a.root, "_duplicates", f.replace(".parquet", ".dups.parquet"))
        reqs = [r for r in u.requests if u.kind != "options" or (r[2][1], r[2][2]) not in skipped.get(uid, set())]
        jobs.append((u, os.path.join(a.root, f), out, reqs))
    todo = [j for j in jobs if not os.path.exists(j[2])]
    print(f"{len(jobs)} files with dropped repeats, {len(todo)} to do, {sum(len(j[3]) for j in todo)} requests")
    if a.plan or not todo:
        return
    st = bs.Store(a.root, 10 ** 9, write=True)
    st.client = bs.make_client()
    total = 0
    for u, src, out, reqs in todo:
        st.cur_unit = u.uid
        with ThreadPoolExecutor(max(1, a.workers)) as pool:
            got = list(pool.map(lambda r: (r, st.fetch(u.kind, *r)), reqs))
        recs = [bs.to_record(u.kind, x, r[2]) for r, pieces in got for _, _, rows, _ in pieces for x in rows]
        have = {}
        t = pq.read_table(src).to_pylist()
        for row in t:                                   # the store file's own version of each candle
            rec = bs.to_record(u.kind, dict(row, datetime=row["datetime"].isoformat(sep=" "),
                                            strike_price=row.get("strike")), (u.expiry, row.get("strike"), row.get("right"))
                               if u.kind == "options" else u.expiry)
            have[bs.rec_key(u.kind, rec)] = rec
        other = sorted({r for r in recs if have.get(bs.rec_key(u.kind, r)) != r}, key=lambda r: bs.rec_sort(u.kind, r))
        new_keys = sum(1 for r in other if bs.rec_key(u.kind, r) not in have)
        if other:
            bs.write_parquet(out, u.kind, other)
            total += len(other)
        print(f"{u.uid}: {len(recs):,} rows asked again, {len(other):,} other versions kept"
              + (f" ({new_keys} timestamps the store file lacks)" if new_keys else ""), flush=True)
    st.close()
    print(f"done: {total:,} other candle versions in {os.path.join(a.root, '_duplicates')}")


if __name__ == "__main__":
    main()
