#!/usr/bin/env python3
"""MCX crude oil (Breeze stock code CRUDE) futures and options, 1-minute, the last DAYS calendar days of every
contract, into a Parquet store of its own (default D:/crude_data). Same rules as breeze_store.py: nothing is changed
but types, a duplicate timestamp keeps the first copy (counted in the ledger), errors are never recorded as "no data",
failed requests are retried at the end of the run and listed in _missing/failed.csv.

    python tools/crude_store.py --plan                 # what is done / to do, no Breeze calls
    python tools/crude_store.py [--from 2018-01 --gap 0.25 --workers 4]

Phases, in order (each resumes where it stopped):
  expiries   Breeze files old crude contracts under its own expiry dates (the last Thursday of the month up to
             early 2023, the real MCX date after), so every month's futures and options expiry is found by asking
             daily candles for each possible date. -> _meta/expiries.json
  futures    per contract: daily candles over the window (which sessions traded), then one 1-minute request per
             traded session (an MCX session is at most 895 minutes, under Breeze's 1,000-candle cap).
             -> futures/1day/<expiry>.parquet, futures/1minute/<YYYY>/<expiry>.parquet
  ostrikes   per options expiry: daily candles for every 50-rupee strike, CE and PE, from the futures' range over the
             window outwards until STOP_EMPTY strikes in a row have no candle on either side.
             -> options/1day/<YYYY>/<expiry>.parquet (the strike list and the traded days)
  options    per options expiry and traded session: one 1-minute request for every contract with a daily candle that
             session. -> options/1minute/<YYYY>/<expiry>/<session>.parquet

A contract whose expiry is not yet past is written as *.partial.parquet and asked again on the next run.
"""
import argparse
import calendar
import csv
import datetime as dt
import json
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import breeze_store as bs  # noqa: E402  (client, keep-awake, network-error test)

ROOT = "D:/crude_data"
CODE = "CRUDE"
DAYS = 60                 # calendar days of history before each expiry (asked for 2026-10-28)
STEP = 50                 # strike step in rupees
STOP_EMPTY = 20           # strikes in a row with no candle on either side before a side of the chain stops
GAP, WORKERS = 0.25, 4
ATTEMPTS, BACKOFF, NET_TRIES, NET_WAIT, LIMIT_TRIES, LIMIT_WAIT = 4, 5, 120, 60, 30, 60
RETRY_PASSES = 3
ASK_ZERO_VOLUME = False   # --zero-volume: also ask 1-minute candles for option contract-days with no daily volume

PRICE = [pa.field("open", pa.float64()), pa.field("high", pa.float64()), pa.field("low", pa.float64()),
         pa.field("close", pa.float64()), pa.field("volume", pa.int64()), pa.field("open_interest", pa.int64())]
FUT_SCHEMA = pa.schema([pa.field("datetime", pa.timestamp("s")), pa.field("expiry", pa.string())] + PRICE)
OPT_SCHEMA = pa.schema([pa.field("datetime", pa.timestamp("s")), pa.field("expiry", pa.string()),
                        pa.field("strike", pa.float64()), pa.field("right", pa.string())] + PRICE)
LEDGER = """
CREATE TABLE IF NOT EXISTS units(unit_id TEXT PRIMARY KEY, status TEXT, requests INT, rows INT, dup_dropped INT,
                                 file TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS failed_requests(unit_id TEXT, request TEXT, error TEXT, at TEXT);
CREATE TABLE IF NOT EXISTS calls(day TEXT PRIMARY KEY, n INT);
"""


class RequestFailed(Exception):
    pass


SPEED_FILE = None         # <root>/_meta/speed.json {"gap": s} re-read every 20 s: the pace changes without a restart
_speed = [0.0, None]


def speed_check():
    """Gap between request starts from speed.json; worker counts are fixed per pool, so only the gap is live."""
    global GAP
    now = time.monotonic()
    if not SPEED_FILE or now - _speed[0] < 20:
        return
    _speed[0] = now
    try:
        mt = os.path.getmtime(SPEED_FILE)
        if mt == _speed[1]:
            return
        _speed[1] = mt
        gap = float(json.load(open(SPEED_FILE, encoding="utf-8"))["gap"])
        if gap != GAP:
            print(f"  {dt.datetime.now():%H:%M:%S} speed.json: gap {GAP:.2f} -> {gap:.2f} s", flush=True)
            GAP = gap
    except (OSError, ValueError, KeyError) as ex:
        print(f"  speed.json not read: {ex}", flush=True)


class Client:
    """Breeze calls: starts at least GAP apart across all threads, network waits, rate-limit back-off, 4 attempts."""

    def __init__(self, root):
        self.br = bs.make_client()
        self.lock = threading.Lock()
        self.last = 0.0
        self.n = 0
        self.db = sqlite3.connect(os.path.join(root, "_meta", "ledger.sqlite"), check_same_thread=False, timeout=120)
        self.db.executescript(LEDGER)
        self.dblock = threading.Lock()

    def count(self):
        self.n += 1
        with self.dblock:
            self.db.execute("INSERT INTO calls(day, n) VALUES(?, 1) ON CONFLICT(day) DO UPDATE SET n = n + 1",
                            (dt.date.today().isoformat(),))
            self.db.commit()
        if self.n % 100 == 0:
            print(f"  {dt.datetime.now():%H:%M:%S} {self.n} requests this run", flush=True)

    def get(self, interval, a, b, expiry, kind, strike=None, right=None):
        global GAP
        kw = dict(interval=interval, from_date=f"{a}T08:59:00.000Z", to_date=f"{b}T23:59:00.000Z", stock_code=CODE,
                  exchange_code="MCX", product_type=kind, expiry_date=f"{expiry}T07:00:00.000Z",
                  right="others" if kind == "futures" else ("call" if right == "CE" else "put"),
                  strike_price="0" if kind == "futures" else str(int(strike)))
        attempt = net = limited = 0
        while True:
            attempt += 1
            with self.lock:
                speed_check()
                w = GAP - (time.monotonic() - self.last)
                if w > 0:
                    time.sleep(w)
                self.last = time.monotonic()
            self.count()
            try:
                r = self.br.get_historical_data_v2(**kw)
                if not isinstance(r, dict):
                    raise RuntimeError(f"unexpected response {str(r)[:200]}")
                if not r.get("Success"):
                    st, et = r.get("Status"), str(r.get("Error") or "")
                    if st not in (200, None) or (et and "no data" not in et.lower()):
                        raise RuntimeError(f"Breeze status {st}: {et[:200]}")
                rows = r.get("Success") or []
                if len(rows) >= 1000:
                    print(f"  warning: {len(rows)} rows for {kw} (may be cut short)", flush=True)
                return rows
            except Exception as ex:
                if bs.is_network_error(ex) and net < NET_TRIES:
                    net += 1
                    attempt -= 1
                    print(f"  {dt.datetime.now():%H:%M:%S} no network ({net}/{NET_TRIES}), waiting {NET_WAIT} s: "
                          f"{str(ex)[:120]}", flush=True)
                    time.sleep(NET_WAIT)
                    continue
                if "limit" in str(ex).lower() and limited < LIMIT_TRIES:
                    limited += 1
                    attempt -= 1
                    GAP = min(0.65, GAP * 1.5)
                    print(f"  {dt.datetime.now():%H:%M:%S} rate limited ({limited}/{LIMIT_TRIES}), waiting "
                          f"{LIMIT_WAIT} s, gap now {GAP:.2f} s", flush=True)
                    time.sleep(LIMIT_WAIT)
                    continue
                print(f"  retry {attempt}/{ATTEMPTS} {kind} {expiry} {strike} {right} {a}..{b}: {str(ex)[:300]}",
                      flush=True)
                if attempt == ATTEMPTS:
                    if any(k in str(ex).lower() for k in bs.FATAL):
                        sys.exit("giving up: the Breeze login failed; run again with a new session to resume")
                    raise RequestFailed(f"{kind} {expiry} {strike} {right} {a}..{b}: {str(ex)[:300]}")
                time.sleep(BACKOFF * attempt)

    def done(self, uid):
        with self.dblock:
            r = self.db.execute("SELECT status FROM units WHERE unit_id=?", (uid,)).fetchone()
        return bool(r) and r[0] in ("done", "empty")

    def mark(self, uid, status, requests, rows, dups, f):
        with self.dblock:
            self.db.execute("INSERT OR REPLACE INTO units VALUES(?,?,?,?,?,?,?)",
                            (uid, status, requests, rows, dups, f, dt.datetime.now().isoformat(timespec="seconds")))
            self.db.commit()

    def fail(self, uid, err):
        with self.dblock:
            self.db.execute("INSERT INTO failed_requests VALUES(?,?,?,?)",
                            (uid, err.split(":")[0], err, dt.datetime.now().isoformat(timespec="seconds")))
            self.db.commit()


# ----------------------------------------------------------------------------- records and files

def rec(x, expiry, strike=None, right=None):
    t = dt.datetime.fromisoformat(str(x["datetime"]).replace("T", " ")[:19])
    p = [float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"]),
         int(float(x.get("volume") or 0)), int(float(x.get("open_interest") or 0))]
    return (t, expiry, *p) if strike is None else (t, expiry, float(strike), right, *p)


def write(path, recs, schema):
    """Sort, keep the first copy of a repeated key, write atomically. Returns the number of repeats dropped."""
    nkey = 2 if schema is FUT_SCHEMA else 4
    seen, out = set(), []
    for r in recs:
        k = (r[0],) + tuple(r[2:nkey]) if nkey == 4 else (r[0],)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    out.sort(key=lambda r: (r[2], r[3], r[0]) if nkey == 4 else r[0])
    cols = list(zip(*out)) if out else [[] for _ in schema]
    t = pa.Table.from_arrays([pa.array(list(c), type=f.type) for f, c in zip(schema, cols)], schema=schema)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pq.write_table(t, path + ".tmp", compression="zstd", compression_level=9, use_dictionary=True,
                   row_group_size=max(1, len(out)))
    os.replace(path + ".tmp", path)
    return len(recs) - len(out)


def target(path, final):
    return path if final else path.replace(".parquet", ".partial.parquet")


# ----------------------------------------------------------------------------- phases

def months(frm, to):
    y, m = frm.year, frm.month
    while (y, m) <= (to.year, to.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def last_thursday(y, m):
    d = dt.date(y, m, calendar.monthrange(y, m)[1])
    while d.weekday() != 3:
        d -= dt.timedelta(days=1)
    return d


def ask_from(d, today):
    return min(d - dt.timedelta(days=25), today - dt.timedelta(days=10)).isoformat()


def find_expiries(c, root, frm, today):
    """{YYYY-MM: {"futures": date, "options": date}} for every month that has a contract. A month already found is
    not asked again, except the months that could still change (expiry not yet past or not found and recent)."""
    path = os.path.join(root, "_meta", "expiries.json")
    known = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    end = today + dt.timedelta(days=100)
    for y, m in months(frm, end):
        key = f"{y}-{m:02d}"
        k = known.get(key)
        if k and k.get("futures") and k["futures"] < today.isoformat() and "options_all" in k:
            continue                                       # past contract: found once (options may be empty)
        if k and k.get("none") and dt.date(y, m, 28) < today - dt.timedelta(days=40):
            continue
        n = calendar.monthrange(y, m)[1]
        lt = last_thursday(y, m)
        order = [lt] + [dt.date(y, m, d) for d in range(15, 23)] + [dt.date(y, m, d) for d in range(1, n + 1)]
        seen, fut, close = set(), None, None
        if k and k.get("futures"):                         # futures already found: one request for the price
            order = [dt.date.fromisoformat(k["futures"])]
        for d in order:
            if d in seen:
                continue
            seen.add(d)
            rows = c.get("1day", ask_from(d, today), min(d, today).isoformat(), d.isoformat(), "futures")
            if rows:
                fut, close = d, float(rows[-1]["close"])
                break
        if not fut:
            known[key] = {"none": True}
            print(f"{key}: no crude futures contract on Breeze", flush=True)
            json.dump(known, open(path, "w", encoding="utf-8"), indent=1, sort_keys=True)
            continue
        # Breeze files some months' options under two dates (2022-01: the 17th and the 27th) and some under the
        # futures date, so every date of the month (and of the futures' month, when that differs) is asked and every
        # date with candles is kept as an expiry of its own
        atm = list(dict.fromkeys([round(close / STEP) * STEP, round(close / 100) * 100]))
        cand = [dt.date(y, m, d) for d in range(1, n + 1)]
        opts = []

        def has(d):
            return any(c.get("1day", ask_from(d, today), min(d, today).isoformat(), d.isoformat(), "options", s, r)
                       for s in atm for r in ("CE", "PE"))

        with ThreadPoolExecutor(WORKERS) as pool:
            for d, ok in zip(cand, pool.map(has, cand)):
                if ok:
                    opts.append(d.isoformat())
        known[key] = {"futures": fut.isoformat(), "options_all": opts}
        print(f"{key}: futures expiry {fut}, options expiries {opts or 'none'}", flush=True)
        json.dump(known, open(path, "w", encoding="utf-8"), indent=1, sort_keys=True)
    return known


def window(e, today):
    a = e - dt.timedelta(days=DAYS)
    return a, min(e, today)


def do_futures(c, root, exp, today, frm):
    out = []
    for key in sorted(exp, reverse=True):
        e = exp[key].get("futures")
        if not e or e < frm.isoformat():
            continue
        e = dt.date.fromisoformat(e)
        a, b = window(e, today)
        if a > today:
            continue
        final = e < today
        uid = f"fut|{e}"
        if final and c.done(uid):
            continue
        out.append((uid, e, a, b, final))
    print(f"futures: {len(out)} contracts to do", flush=True)
    failed = []
    for uid, e, a, b, final in out:
        try:
            daily = c.get("1day", a.isoformat(), b.isoformat(), e.isoformat(), "futures")
            days = sorted({str(x["datetime"])[:10] for x in daily})
            with ThreadPoolExecutor(WORKERS) as pool:
                got = list(pool.map(lambda d: c.get("1minute", d, d, e.isoformat(), "futures"), days))
        except RequestFailed as ex:
            c.fail(uid, str(ex))
            failed.append(uid)
            continue
        write(target(os.path.join(root, "futures", "1day", f"{e}.parquet"), final),
              [rec(x, e.isoformat()) for x in daily], FUT_SCHEMA)
        recs = [rec(x, e.isoformat()) for rows in got for x in rows]
        f = target(os.path.join(root, "futures", "1minute", str(e.year), f"{e}.parquet"), final)
        dups = write(f, recs, FUT_SCHEMA)
        c.mark(uid, "done" if final else "partial", 1 + len(days), len(recs), dups, os.path.relpath(f, root))
        print(f"{uid}: {len(days)} sessions, {len(recs):,} candles, {dups} repeats dropped", flush=True)
    return failed


def opt_expiries(exp, today, frm):
    for key in sorted(exp, reverse=True):
        f = exp[key].get("futures")
        for o in sorted(exp[key].get("options_all") or [], reverse=True):
            if o >= frm.isoformat():
                yield dt.date.fromisoformat(o), dt.date.fromisoformat(f)


def fut_range(root, fexp, a, b):
    """Low and high of the month's futures over the options window, from the stored daily file."""
    for name in (f"{fexp}.parquet", f"{fexp}.partial.parquet"):
        p = os.path.join(root, "futures", "1day", name)
        if os.path.exists(p):
            t = pq.read_table(p).to_pylist()
            t = [r for r in t if a <= r["datetime"].date() <= b] or t
            if t:
                return min(r["low"] for r in t), max(r["high"] for r in t)
    return None


def do_strikes(c, root, exp, today, frm):
    failed = []
    todo = []
    for e, fe in opt_expiries(exp, today, frm):
        a, b = window(e, today)
        if a > today:
            continue
        final = e < today
        uid = f"ostrikes|{e}"
        if final and c.done(uid):
            continue
        todo.append((uid, e, fe, a, b, final))
    print(f"option strikes: {len(todo)} expiries to do", flush=True)
    for uid, e, fe, a, b, final in todo:
        rng = fut_range(root, fe, a, b)
        if not rng:
            print(f"{uid}: no futures daily file for {fe} yet, skipped", flush=True)
            continue
        lo, hi = int(rng[0] // STEP * STEP), int(-(-rng[1] // STEP) * STEP)
        found, n = {}, 0

        def ask(k):
            return k, {r: c.get("1day", a.isoformat(), b.isoformat(), e.isoformat(), "options", k, r)
                       for r in ("CE", "PE")}

        try:
            with ThreadPoolExecutor(WORKERS) as pool:
                for k, got in pool.map(ask, range(lo, hi + STEP, STEP)):
                    n += 2
                    found.update({(k, r): v for r, v in got.items() if v})
                for direction in (-1, 1):                         # outwards until STOP_EMPTY empty strikes in a row
                    k, empty = (lo if direction < 0 else hi), 0
                    while empty < STOP_EMPTY and k > 0:
                        batch = [k + direction * STEP * i for i in range(1, WORKERS + 1)]
                        batch = [x for x in batch if x > 0]
                        if not batch:
                            break
                        for kk, got in pool.map(ask, batch):
                            n += 2
                            hit = {(kk, r): v for r, v in got.items() if v}
                            found.update(hit)
                            empty = 0 if hit else empty + 1
                        k = batch[-1]
        except RequestFailed as ex:
            c.fail(uid, str(ex))
            failed.append(uid)
            continue
        recs = [rec(x, e.isoformat(), k, r) for (k, r), rows in found.items() for x in rows]
        f = target(os.path.join(root, "options", "1day", str(e.year), f"{e}.parquet"), final)
        dups = write(f, recs, OPT_SCHEMA)
        ks = sorted({k for k, _ in found})
        c.mark(uid, "done" if final else "partial", n, len(recs), dups, os.path.relpath(f, root))
        print(f"{uid}: {n} requests, {len(found)} contracts traded, strikes {ks[0] if ks else '-'}.."
              f"{ks[-1] if ks else '-'}, {len(recs):,} contract-days", flush=True)
    return failed


def option_units(root, exp, today, frm):
    """(uid, expiry, session, [(strike, right)], final) for every traded session of every options expiry."""
    out = []
    for e, _ in opt_expiries(exp, today, frm):
        for name in (f"{e}.parquet", f"{e}.partial.parquet"):
            p = os.path.join(root, "options", "1day", str(e.year), name)
            if not os.path.exists(p):
                continue
            final = name == f"{e}.parquet"
            per = {}
            for r in pq.read_table(p, columns=["datetime", "strike", "right", "volume"]).to_pylist():
                # a contract-day with no volume on its daily candle is not asked (decided 2026-10-29: of 57,994 such
                # days asked, 99.8% returned no 1-minute candle and the rest only volume-0 marks); still in 1day
                if ASK_ZERO_VOLUME or r["volume"] > 0:
                    per.setdefault(r["datetime"].date(), []).append((r["strike"], r["right"]))
            for d in sorted(per, reverse=True):
                out.append((f"opt|{e}|{d}", e, d, sorted(per[d]), final and d < today))
    return out


def do_options(c, root, exp, today, frm):
    units = [u for u in option_units(root, exp, today, frm) if not (u[4] and c.done(u[0]))]
    print(f"options 1-minute: {len(units)} expiry-sessions to do, {sum(len(u[3]) for u in units):,} requests",
          flush=True)
    failed = []
    for uid, e, d, contracts, final in units:
        try:
            with ThreadPoolExecutor(WORKERS) as pool:
                got = list(pool.map(lambda kr: (kr, c.get("1minute", d.isoformat(), d.isoformat(), e.isoformat(),
                                                          "options", kr[0], kr[1])), contracts))
        except RequestFailed as ex:
            c.fail(uid, str(ex))
            failed.append(uid)
            continue
        recs = [rec(x, e.isoformat(), k, r) for (k, r), rows in got for x in rows]
        f = target(os.path.join(root, "options", "1minute", str(e.year), str(e), f"{d}.parquet"), final)
        dups = write(f, recs, OPT_SCHEMA)
        c.mark(uid, "done" if final else "partial", len(contracts), len(recs), dups, os.path.relpath(f, root))
        print(f"{uid}: {len(contracts)} contracts, {len(recs):,} candles, {dups} repeats dropped", flush=True)
    return failed


def write_failed(c, root):
    os.makedirs(os.path.join(root, "_missing"), exist_ok=True)
    rows = c.db.execute("SELECT f.unit_id, f.request, f.error, f.at FROM failed_requests f JOIN units u "
                        "ON u.unit_id = f.unit_id WHERE u.status NOT IN ('done','empty') UNION ALL "
                        "SELECT f.unit_id, f.request, f.error, f.at FROM failed_requests f WHERE f.unit_id NOT IN "
                        "(SELECT unit_id FROM units)").fetchall()
    with open(os.path.join(root, "_missing", "failed.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["unit_id", "request", "error", "at"])
        w.writerows(rows)


def main():
    global GAP, WORKERS, ASK_ZERO_VOLUME, SPEED_FILE
    p = argparse.ArgumentParser()
    p.add_argument("--root", default=ROOT)
    p.add_argument("--from", dest="frm", default="2018-01")
    p.add_argument("--phase", default="all", choices=["expiries", "futures", "ostrikes", "options", "all"])
    p.add_argument("--gap", type=float, default=GAP)
    p.add_argument("--workers", type=int, default=WORKERS)
    p.add_argument("--plan", action="store_true")
    p.add_argument("--zero-volume", action="store_true")
    a = p.parse_args()
    GAP, WORKERS, ASK_ZERO_VOLUME = a.gap, max(1, a.workers), a.zero_volume
    SPEED_FILE = os.path.join(a.root, "_meta", "speed.json")
    if not os.path.exists(SPEED_FILE):
        json.dump({"gap": GAP}, open(SPEED_FILE, "w", encoding="utf-8"))
    _speed[1] = os.path.getmtime(SPEED_FILE)              # the command line wins at start; later edits take over
    frm = dt.date.fromisoformat(a.frm + "-01" if len(a.frm) == 7 else a.frm)
    today = dt.date.today()
    os.makedirs(os.path.join(a.root, "_meta"), exist_ok=True)
    if a.plan:
        path = os.path.join(a.root, "_meta", "expiries.json")
        exp = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
        print(f"{len(exp)} months known, {sum(1 for v in exp.values() if v.get('futures'))} with contracts")
        u = option_units(a.root, exp, today, frm)
        print(f"options 1-minute: {len(u)} expiry-sessions known, {sum(len(x[3]) for x in u):,} requests")
        return
    c = Client(a.root)
    phases = ["expiries", "futures", "ostrikes", "options"] if a.phase == "all" else [a.phase]
    exp = find_expiries(c, a.root, frm, today)                  # every phase needs the expiry dates
    steps = {"futures": do_futures, "ostrikes": do_strikes, "options": do_options}
    for ph in phases[1:] if phases[0] == "expiries" else phases:
        failed = steps[ph](c, a.root, exp, today, frm)
        for n in range(RETRY_PASSES):
            if not failed:
                break
            print(f"{ph}: retry pass {n + 1} for {len(failed)} unit(s)", flush=True)
            failed = steps[ph](c, a.root, exp, today, frm)
        if failed:
            print(f"{ph}: {len(failed)} unit(s) still failing; listed in _missing/failed.csv", flush=True)
    write_failed(c, a.root)
    print(f"all requested phases are complete; {c.n} requests this run", flush=True)


if __name__ == "__main__":
    main()
