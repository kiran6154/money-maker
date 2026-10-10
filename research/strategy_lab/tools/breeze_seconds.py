#!/usr/bin/env python3
"""1-second candles from ICICI Breeze for the last N sessions: NIFTY index, the near-month future and the ATM options.

    python tools/breeze_seconds.py --days 5 --plan
    python tools/breeze_seconds.py --days 5

ATM options: for each session, every strike that was the ATM strike (index 1-minute close rounded to 50) at some
minute between 09:15 and 15:29, CE and PE, nearest expiry; each of those contracts is fetched for the whole session.
Breeze answers at most 1,000 one-second candles per request and reads the request times as IST, so a session is
asked in 1,000-second windows (23 per contract per session). Stored as returned (type conversion only):

    <root>/seconds/index/<date>.parquet
    <root>/seconds/futures/<expiry>/<date>.parquet
    <root>/seconds/options/<expiry>/<date>.parquet        (all that session's ATM contracts)

A file that exists is not fetched again. Contracts with no candles are listed in <root>/_missing/missing_seconds.csv.
Needs the 1-minute index files of tools/breeze_store.py for the sessions asked. Credentials: the same environment
variables. Requests are counted in the shared ledger.
"""
import argparse
import csv
import datetime as dt
import os
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breeze_store as bs  # noqa: E402

WINDOW = 1000                                   # seconds per request (Breeze returns at most 1,000 candles)
DAY_START, DAY_END = 9 * 3600 + 15 * 60, 15 * 3600 + 30 * 60        # 09:15:00 .. 15:30:00


def hms(sec):
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def windows():
    return [(a, min(a + WINDOW - 1, DAY_END)) for a in range(DAY_START, DAY_END + 1, WINDOW)]


def ask(st, gap, day, a, b, **kw):
    """One request; only a clean empty answer counts as no data."""
    for attempt in range(1, bs.ATTEMPTS + 1):
        wait = gap - (time.monotonic() - st.last_call)
        if wait > 0:
            time.sleep(wait)
        st.last_call = time.monotonic()
        st._count()
        try:
            r = st.client.get_historical_data_v2(interval="1second", from_date=f"{day}T{hms(a)}.000Z",
                                                 to_date=f"{day}T{hms(b)}.000Z", stock_code="NIFTY", **kw)
            if not isinstance(r, dict):
                raise RuntimeError(f"unexpected response {str(r)[:200]}")
            rows = r.get("Success") or []
            if not rows:
                status, etext = r.get("Status"), str(r.get("Error") or "")
                if status not in (200, None) or (etext and "no data" not in etext.lower()):
                    raise RuntimeError(f"Breeze status {status}: {etext[:200]}")
            lo, hi = f"{day} {hms(a)}", f"{day} {hms(b)}"
            bad = [x["datetime"] for x in rows if not (lo <= x["datetime"][:19] <= hi)]
            if bad:                               # the window was not read as IST after all: stop, store nothing
                sys.exit(f"rows outside the asked window {lo} .. {hi}: {bad[:3]}")
            if len(rows) >= WINDOW and b - a + 1 > WINDOW:
                sys.exit("a window longer than 1,000 seconds came back full: possible truncation")
            return rows
        except Exception as ex:
            print(f"  retry {attempt}/{bs.ATTEMPTS} {day} {hms(a)}: {type(ex).__name__}: {ex}")
            if attempt == bs.ATTEMPTS:
                sys.exit("giving up after repeated errors; run again to resume")
            time.sleep(bs.BACKOFF * attempt)


def record(x, extra):
    return (bs.parse_dt(x["datetime"]), float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]),
            int(float(x.get("volume") or 0)), int(float(x.get("open_interest") or 0))) + extra


def write(path, recs, with_contract):
    f64, i64 = pa.float64(), pa.int64()
    fields = [("datetime", pa.timestamp("s")), ("open", f64), ("high", f64), ("low", f64), ("close", f64),
              ("volume", i64), ("open_interest", i64)]
    if with_contract:
        fields += [("strike", pa.int32()), ("right", pa.dictionary(pa.int32(), pa.string()))]
        recs = sorted(set(recs), key=lambda r: (r[7], r[8], r[0]))
    else:
        recs = sorted(set(recs))
    sch = pa.schema(fields)
    t = pa.Table.from_arrays([pa.array(list(c), type=f.type) for f, c in zip(sch, zip(*recs))], schema=sch)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pq.write_table(t, path + ".tmp", compression="zstd", compression_level=9, row_group_size=len(recs))
    os.replace(path + ".tmp", path)
    return len(recs)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=bs.DEFAULT_ROOT)
    p.add_argument("--days", type=int, default=5)
    p.add_argument("--gap", type=float, default=1.5, help="seconds between requests (another download may be running)")
    p.add_argument("--plan", action="store_true")
    a = p.parse_args()

    days = bs.IndexDays(a.root)
    sessions = [d for d in days.sessions if d in days.lohi][-a.days:]
    cal = bs.calendar_for(a.root, days.sessions)
    atm = {d: set() for d in sessions}
    for f in bs.index_files(a.root):
        if not any(d[:7] in f for d in sessions):
            continue
        t = pq.read_table(f, columns=["datetime", "close"]).to_pydict()
        for ts, c in zip(t["datetime"], t["close"]):
            d = ts.date().isoformat()
            if d in atm and bs.TIME_LO <= ts.hour * 60 + ts.minute <= bs.TIME_HI:
                atm[d].add(int(round(c / bs.STRIKE_STEP) * bs.STRIKE_STEP))
    w = windows()
    jobs = []                                     # (kind, day, expiry, [(strike, right)], path)
    for d in sessions:
        fe, oe = cal.near_month(d), cal.tiers(d).get(1)
        jobs.append(("index", d, None, [None], os.path.join(a.root, "seconds", "index", d + ".parquet")))
        jobs.append(("futures", d, fe, [None], os.path.join(a.root, "seconds", "futures", fe, d + ".parquet")))
        jobs.append(("options", d, oe, [(k, r) for k in sorted(atm[d]) for r in ("CE", "PE")],
                     os.path.join(a.root, "seconds", "options", oe, d + ".parquet")))
    todo = [j for j in jobs if not os.path.exists(j[4])]
    for kind, d, e, cs, path in jobs:
        print(f"{d} {kind:8}{' ' + e if e else '':12} contracts {len(cs):2}  requests {len(cs) * len(w):4}  "
              f"{'done' if os.path.exists(path) else 'to do'}" + (f"  ATM strikes {sorted(atm[d])}" if kind == "options" else ""))
    n = sum(len(j[3]) * len(w) for j in todo)
    print(f"requests to make: {n} (about {n * a.gap / 60:.0f} minutes at one per {a.gap} s)")
    if a.plan or not todo:
        return

    st = bs.Store(a.root, 10 ** 9, write=True)
    st.client = bs.make_client()
    missing = []
    for kind, d, e, cs, path in todo:
        recs = []
        for c in cs:
            if kind == "index":
                kw, extra = dict(exchange_code="NSE", product_type="cash"), ()
            elif kind == "futures":
                kw, extra = dict(exchange_code="NFO", product_type="futures", expiry_date=f"{e}T07:00:00.000Z",
                                 right="others", strike_price="0"), ()
            else:
                kw, extra = dict(exchange_code="NFO", product_type="options", expiry_date=f"{e}T07:00:00.000Z",
                                 right="call" if c[1] == "CE" else "put", strike_price=str(c[0])), c
            got = 0
            for s0, s1 in w:
                rows = ask(st, a.gap, d, s0, s1, **kw)
                got += len(rows)
                recs += [record(x, extra) for x in rows]
            if not got:
                missing.append([kind, d, e or "", c[0] if c else "", c[1] if c else ""])
            print(f"  {d} {kind} {e or ''} {'' if not c else str(c[0]) + c[1]}: {got} candles")
        if recs:
            print(f"{d} {kind}: wrote {write(path, recs, kind == 'options'):,} rows -> {os.path.relpath(path, a.root)}")
    st.close()
    if missing:
        mp = os.path.join(a.root, "_missing", "missing_seconds.csv")
        new = not os.path.exists(mp)
        with open(mp, "a", newline="", encoding="utf-8") as fh:
            wr = csv.writer(fh)
            if new:
                wr.writerow(["kind", "date", "expiry", "strike", "right"])
            wr.writerows(missing)
        print(f"{len(missing)} contract-day(s) with no candles -> _missing/missing_seconds.csv")


if __name__ == "__main__":
    main()
