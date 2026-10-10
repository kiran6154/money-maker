#!/usr/bin/env python3
"""NIFTY 1-minute candles from ICICI Breeze into a compact Parquet store (standalone; does not import lab).

Layout under --root (default D:/nifty_data):
    index/1minute/<YYYY>/<YYYY-MM>.parquet                   unit = calendar month (NIFTY index)
    futures/1minute/<YYYY>/<expiry>.parquet                  unit = one monthly contract, its sessions
    options/1minute/<YYYY>/<expiry>/<from>__<to>.parquet     unit = (expiry, 2-session chunk), every identified contract
                                                             (see options_units: whole contracts, 45 / 75 days)
    _meta/ledger.sqlite, _meta/expiry_overrides.json (optional, read only), _missing/missing.csv

Partial files: the current month of the index is fetched only up to yesterday and written as
<YYYY-MM>.partial.parquet; it is refetched on every run until the month is over, then the final file is written.
The partial file is left on disk and ignored by readers (nothing is removed). Open futures contracts and open
options expiries (expiry on or after today) are written as <name>.partial.parquet the same way; once the expiry has
passed, the final file is written and that expiry's partial files are removed.

Rules: Breeze rows are stored as returned (type conversion only: no gap filling, resampling, time filter or rounding).
Exact key repeats inside a unit are dropped and counted in the ledger. Requests that return nothing are never written
as data; they go to empty_requests and _missing/missing.csv. A unit whose final file exists is never fetched again.

    python breeze_store.py --plan                       # no login, no network
    python breeze_store.py --probe --from 2019-01-01 --to 2025-01-01   # needs login; writes no data
    python breeze_store.py                              # fetch index, futures, options (resumable)
    python breeze_store.py --verify                     # no network
    python breeze_store.py --selftest                   # fake client in a temp directory

Credentials come only from the environment (BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION_TOKEN) and are
never printed or written. breeze_connect is imported only when a request is about to be made.
"""
import argparse
import bisect
import csv
import datetime as dt
import glob
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict

import pyarrow as pa
import pyarrow.parquet as pq

DEFAULT_ROOT = "D:/nifty_data"
DEFAULT_DAY_CAP = 4800
MIN_GAP = 0.65            # seconds between two Breeze calls (a module global so the selftest can skip the waits)
BACKOFF = 5               # seconds x attempt after an exception
ATTEMPTS = 4
TRUNCATE_AT = 1000        # a response this long may be cut short: the range is refetched one calendar day at a time
PROGRESS_EVERY = 50
EARLY_STOP = 4            # an options unit whose first 4 requests all return nothing is marked no_data_at_source
PER_REQUEST = 2           # sessions per options / futures request chunk
STRIKE_STEP = 50
WINGS = 5
WEEKLY_DAYS = 45          # calendar days of history fetched for every identified contract of a weekly expiry
MONTHLY_DAYS = 75         # ... of a monthly expiry
PRUNE_AFTER = 2           # going back in time, a contract with no candles in this many chunks in a row is not asked again
PRUNE = True
SKIP_NOTE = "not asked: no candles in the later chunks"
TIME_LO, TIME_HI = 9 * 60 + 15, 15 * 60 + 29       # 09:15 .. 15:29 inclusive = 375 one-minute candles
FULL_SESSION = 375
PHASES = ("index", "futures", "options")
ONE_DAY = dt.timedelta(days=1)
THU, TUE = 3, 1
SELFTEST_CAP = 120

LEDGER_SCHEMA = """
CREATE TABLE IF NOT EXISTS units (unit_id TEXT PRIMARY KEY, kind TEXT, status TEXT, requests INT, rows INT,
    dup_dropped INT, file TEXT, finished_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS empty_requests (unit_id TEXT, kind TEXT, expiry TEXT, strike INT, right TEXT,
    from_date TEXT, to_date TEXT, message TEXT, asked_at TEXT);
CREATE TABLE IF NOT EXISTS calls (day TEXT PRIMARY KEY, n INT);
"""


class DayCapReached(Exception):
    pass


# ----------------------------------------------------------------------------- dates and the expiry calendar

def to_date(s):
    return dt.date.fromisoformat(s)


def last_weekday(y, m, wd):
    first_next = dt.date(y + (m == 12), m % 12 + 1, 1)
    d = first_next - ONE_DAY
    while d.weekday() != wd:
        d -= ONE_DAY
    return d


def rule_monthly():
    """Last Thursday up to and including August 2025, last Tuesday from September 2025 on."""
    return [last_weekday(y, m, THU if (y, m) <= (2025, 8) else TUE)
            for y in range(2017, 2031) for m in range(1, 13)]


def rule_weekly():
    """Every Thursday 2019-02-14 .. 2025-08-28, every Tuesday from 2025-09-02 (generated to 2030-12-31)."""
    out = []
    d = dt.date(2019, 2, 14)
    while d <= dt.date(2025, 8, 28):
        out.append(d)
        d += dt.timedelta(days=7)
    d = dt.date(2025, 9, 2)
    while d <= dt.date(2030, 12, 31):
        out.append(d)
        d += dt.timedelta(days=7)
    return out


def actual_date(rule, sessions, sset):
    """A rule date that is not a session moves to the nearest earlier session. Dates after the last session stay."""
    if not sessions or rule > sessions[-1] or rule in sset:
        return rule
    i = bisect.bisect_left(sessions, rule)
    return sessions[i - 1] if i > 0 else rule


def expiries(sessions, overrides=None):
    """(weekly, monthly) expiry lists as ISO strings. overrides = {"replace": {rule: actual}, "drop": [...]}, applied last."""
    sessions = sorted(set(sessions))
    sset = set(sessions)
    ov = overrides or {}
    rep = ov.get("replace", {})
    drop = set(ov.get("drop", []))

    def build(rules):
        out = set()
        for r in rules:
            ri = r.isoformat()
            a = rep.get(ri, actual_date(ri, sessions, sset))
            if ri in drop or a in drop:
                continue
            out.add(a)
        return sorted(out)

    return build(rule_weekly()), build(rule_monthly())


class Calendar:
    def __init__(self, weekly, monthly):
        self.monthly = monthly
        self.combined = sorted(set(weekly) | set(monthly))

    def tiers(self, d):
        """{1: nearest weekly-or-monthly >= d, 2: nearest monthly >= d if different, 3: the expiry after tier 1}."""
        i = bisect.bisect_left(self.combined, d)
        if i >= len(self.combined):
            return {}
        t1 = self.combined[i]
        out = {1: t1}
        j = bisect.bisect_left(self.monthly, d)
        if j < len(self.monthly) and self.monthly[j] != t1:
            out[2] = self.monthly[j]
        if i + 1 < len(self.combined):
            out[3] = self.combined[i + 1]
        return out

    def near_month(self, d):
        j = bisect.bisect_left(self.monthly, d)
        return self.monthly[j] if j < len(self.monthly) else None


def load_overrides(root):
    p = os.path.join(root, "_meta", "expiry_overrides.json")
    if not os.path.exists(p):
        return {}
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError as ex:
        sys.exit(f"{p} is not valid JSON: {ex}")


# ----------------------------------------------------------------------------- what is on disk

def index_files(root):
    return sorted(glob.glob(os.path.join(root, "index", "1minute", "*", "*.parquet")))


class IndexDays:
    """Sessions in the index files (final and partial) and each session's low / high between 09:15 and 15:29."""

    def __init__(self, root):
        sessions = set()
        self.lohi = {}
        for f in index_files(root):
            t = pq.read_table(f, columns=["datetime", "low", "high"]).to_pydict()
            for ts, lo, hi in zip(t["datetime"], t["low"], t["high"]):
                d = ts.date().isoformat()
                sessions.add(d)
                if TIME_LO <= ts.hour * 60 + ts.minute <= TIME_HI:
                    cur = self.lohi.get(d)
                    if cur is None:
                        self.lohi[d] = [lo, hi]
                    else:
                        cur[0] = min(cur[0], lo)
                        cur[1] = max(cur[1], hi)
        # sessions the source has no index candles for but does trade (futures / options exist): calendar only
        p = os.path.join(root, "_meta", "extra_sessions.json")
        if sessions and os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                sessions |= set(json.load(fh).get("sessions", []))
        self.sessions = sorted(sessions)


def calendar_for(root, sessions):
    return Calendar(*expiries(sessions, load_overrides(root)))


# ----------------------------------------------------------------------------- units

class Unit:
    """One file. requests = [(from_date, to_date, meta)] in the order they are asked."""

    def __init__(self, uid, kind, final_path, partial_path, is_final, requests, expiry=None, tier=0, start="",
                 early_stop=False):
        self.uid, self.kind = uid, kind
        self.final_path, self.partial_path = final_path, partial_path
        self.is_final = is_final
        self.requests = requests
        self.expiry, self.tier, self.start = expiry, tier, start
        self.early_stop = early_stop
        self.later = []


def day_chunks(lo, hi):
    """Calendar chunks inside [lo, hi]: [Mon,Tue], [Wed,Thu], [Fri,Sat,Sun] of each week, clipped to the range."""
    spans = []
    d = lo
    while d <= hi:
        wd = d.weekday()
        key = (d - dt.timedelta(days=wd), 0 if wd <= 1 else 1 if wd <= 3 else 2)
        if spans and spans[-1][0] == key:
            spans[-1][2] = d
        else:
            spans.append([key, d, d])
        d += ONE_DAY
    return [(a.isoformat(), b.isoformat()) for _, a, b in spans]


def pair_chunks(ds):
    return [(ds[i], ds[min(i + PER_REQUEST, len(ds)) - 1]) for i in range(0, len(ds), PER_REQUEST)]


def index_units(root, frm, to, today):
    yesterday = today - ONE_DAY
    out = []
    m = frm.replace(day=1)
    while m <= to:
        nxt = dt.date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        mend = nxt - ONE_DAY
        lo, hi = max(m, frm), min(mend, to, yesterday)
        if lo <= hi:
            ym = f"{m.year:04d}-{m.month:02d}"
            d = os.path.join(root, "index", "1minute", f"{m.year:04d}")
            reqs = [(a, b, None) for a, b in day_chunks(lo, hi)]
            is_final = mend < today and hi == mend and lo == m     # a month clipped by --from / --to is never final
            out.append(Unit(f"index|{ym}", "index", os.path.join(d, ym + ".parquet"),
                            os.path.join(d, ym + ".partial.parquet"), is_final, reqs))
        m = nxt
    return out


def futures_units(root, cal, sessions, frm, to, today):
    """Units are always built from every index session, so a contract's file never depends on --from / --to;
    the range only selects which contracts run."""
    by = defaultdict(list)
    for d in sessions:
        e = cal.near_month(d)
        if e:
            by[e].append(d)
    out = []
    for e in sorted(by):
        ds = sorted(by[e])
        if ds[-1] < frm.isoformat() or ds[0] > to.isoformat():
            continue
        reqs = [(a, b, e) for a, b in pair_chunks(ds)]
        is_final = e < today.isoformat() and e <= sessions[-1]
        d = os.path.join(root, "futures", "1minute", e[:4])
        out.append(Unit(f"futures|{e}", "futures", os.path.join(d, e + ".parquet"),
                        os.path.join(d, e + ".partial.parquet"), is_final, reqs, expiry=e))
    return out


def session_strikes(lo, hi, wings):
    start = math.floor(lo / STRIKE_STEP) * STRIKE_STEP - wings * STRIKE_STEP
    end = math.ceil(hi / STRIKE_STEP) * STRIKE_STEP + wings * STRIKE_STEP
    return list(range(start, end + 1, STRIKE_STEP))


def options_units(root, cal, idx, frm, to, today, tiers, wings, weekly_days=WEEKLY_DAYS, monthly_days=MONTHLY_DAYS):
    """Whole contracts. A contract (expiry, strike, right) is IDENTIFIED when its strike is inside a session's band
    (day low - wings .. day high + wings, 50-point strikes) on a session where that expiry is the nearest expiry
    (weekly or monthly) or the nearest monthly. Every identified contract is then fetched over the expiry's whole
    window: the sessions of the last `weekly_days` calendar days up to a weekly expiry, `monthly_days` for a monthly.
    Only expired expiries are planned (an open one is not complete: its strike set and its sessions still grow), so
    every file is final. Files = (expiry, 2-session chunk), all identified contracts. Tier 1 = weekly, 2 = monthly.
    Order: newest expiry first, inside an expiry newest chunk first (the pruning in run_unit relies on that)."""
    lo_s, hi_s, today_s = frm.isoformat(), to.isoformat(), today.isoformat()
    monthly = set(cal.monthly)
    ident, mids = defaultdict(set), defaultdict(list)
    for d in idx.sessions:
        if d not in idx.lohi:
            continue
        lo, hi = idx.lohi[d]
        ks = session_strikes(lo, hi, wings)
        for e in {cal.tiers(d).get(1), cal.near_month(d)} - {None}:
            ident[e].update(ks)
            mids[e].append((lo + hi) / 2)
    out = []
    for e in sorted(ident, reverse=True):
        if e >= today_s or e > idx.sessions[-1] or not (lo_s <= e <= hi_s):
            continue
        tier = 2 if e in monthly else 1
        if tier not in tiers:
            continue
        start = (to_date(e) - dt.timedelta(days=monthly_days if tier == 2 else weekly_days)).isoformat()
        ds = [d for d in idx.sessions if start <= d <= e]
        m = sum(mids[e]) / len(mids[e])
        order = sorted(((k, r) for k in ident[e] for r in ("CE", "PE")),
                       key=lambda kr: (abs(kr[0] - m), kr[0], kr[1] != "CE"))
        folder = os.path.join(root, "options", "1minute", e[:4], e)
        chunks = [ds[i:i + PER_REQUEST] for i in range(0, len(ds), PER_REQUEST)]
        uids = [f"options|{e}|{c[0]}|{c[-1]}" for c in chunks]
        for i in range(len(chunks) - 1, -1, -1):
            a, b = chunks[i][0], chunks[i][-1]
            u = Unit(uids[i], "options", os.path.join(folder, f"{a}__{b}.parquet"),
                     os.path.join(folder, f"{a}__{b}.partial.parquet"), True, [(a, b, (e, k, r)) for k, r in order],
                     expiry=e, tier=tier, start=a, early_stop=True)
            u.later = uids[i + 1:i + 1 + PRUNE_AFTER]      # the chunks just after this one in time
            out.append(u)
    return out


def phase_units(root, phase, frm, to, today, tiers, wings):
    if phase == "index":
        return index_units(root, frm, to, today)
    idx = IndexDays(root)
    if not idx.sessions:
        print(f"no index files under {root}: the {phase} units need the index first")
        return []
    # sessions, expiry shifts and chunk pairs all come from the index: it must be whole from its first month on
    gaps = [u.uid for u in index_units(root, to_date(idx.sessions[0]).replace(day=1), to, today)
            if u.is_final and not os.path.exists(u.final_path)]
    if gaps:
        sys.exit(f"the index is incomplete ({len(gaps)} month(s) missing, first {gaps[0]}): "
                 f"finish --phase index before {phase}")
    cal = calendar_for(root, idx.sessions)
    if phase == "futures":
        return futures_units(root, cal, idx.sessions, frm, to, today)
    return options_units(root, cal, idx, frm, to, today, tiers, wings)


def is_done(st, u):
    if not u.is_final:
        return False
    if os.path.exists(u.final_path):
        return True
    row = st.db.execute("SELECT status FROM units WHERE unit_id=?", (u.uid,)).fetchone()
    return bool(row) and row[0] in ("empty", "no_data_at_source")


# ----------------------------------------------------------------------------- Breeze

def make_client():
    key, secret, token = (os.environ.get(v) for v in ("BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN"))
    if not (key and secret and token):
        sys.exit("set BREEZE_API_KEY, BREEZE_API_SECRET and BREEZE_SESSION_TOKEN in the environment")
    try:
        from breeze_connect import BreezeConnect
    except ImportError:
        sys.exit("breeze_connect is not installed: pip install breeze-connect")
    br = BreezeConnect(api_key=key)
    br.generate_session(api_secret=secret, session_token=token)
    return br


def breeze_args(kind, a, b, meta):
    base = dict(interval="1minute", from_date=f"{a}T07:00:00.000Z", to_date=f"{b}T18:00:00.000Z", stock_code="NIFTY")
    if kind == "index":
        return dict(base, exchange_code="NSE", product_type="cash")
    if kind == "futures":
        return dict(base, exchange_code="NFO", product_type="futures", expiry_date=f"{meta}T07:00:00.000Z",
                    right="others", strike_price="0")
    e, k, right = meta
    return dict(base, exchange_code="NFO", product_type="options", expiry_date=f"{e}T07:00:00.000Z",
                right="call" if right == "CE" else "put", strike_price=str(k))


def meta_fields(kind, meta):
    if kind == "index":
        return None, None, None
    if kind == "futures":
        return meta, None, None
    return meta


def parse_dt(s):
    return dt.datetime.fromisoformat(str(s).replace("T", " ")[:19])


def to_record(kind, x, meta):
    """Type conversion only: prices float, volume / open interest int(float(x or 0))."""
    ts = parse_dt(x["datetime"])
    o, h, lo, c = float(x["open"]), float(x["high"]), float(x["low"]), float(x["close"])
    vol = int(float(x.get("volume") or 0))
    if kind == "index":
        return (ts, o, h, lo, c, vol)
    oi = int(float(x.get("open_interest") or 0))
    if kind == "futures":
        return (ts, o, h, lo, c, vol, oi, to_date(meta))
    e, k, right = meta
    return (ts, k, right, o, h, lo, c, vol, oi, to_date(e))


def rec_key(kind, r):
    return r[0] if kind != "options" else (r[0], r[1], r[2])


def rec_sort(kind, r):
    return r[0] if kind != "options" else (r[1], r[2], r[0])


def dedupe(kind, recs):
    seen, dropped, differing = {}, 0, 0
    for r in recs:
        k = rec_key(kind, r)
        if k in seen:
            dropped += 1
            if seen[k] != r:
                differing += 1
        else:
            seen[k] = r
    return list(seen.values()), dropped, differing


def schema(kind):
    ts, f64, i64 = pa.timestamp("s"), pa.float64(), pa.int64()
    ohlc = [("open", f64), ("high", f64), ("low", f64), ("close", f64)]
    if kind == "index":
        fields = [("datetime", ts)] + ohlc + [("volume", i64)]
    elif kind == "futures":
        fields = [("datetime", ts)] + ohlc + [("volume", i64), ("open_interest", i64), ("expiry", pa.date32())]
    else:
        fields = ([("datetime", ts), ("strike", pa.int32()), ("right", pa.dictionary(pa.int32(), pa.string()))]
                  + ohlc + [("volume", i64), ("open_interest", i64), ("expiry", pa.date32())])
    return pa.schema(fields)


def write_parquet(path, kind, recs):
    recs = sorted(recs, key=lambda r: rec_sort(kind, r))
    sch = schema(kind)
    cols = list(zip(*recs))
    arrays = [pa.array(list(col), type=field.type) for field, col in zip(sch, cols)]
    table = pa.Table.from_arrays(arrays, schema=sch)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    pq.write_table(table, tmp, compression="zstd", compression_level=9, use_dictionary=True,
                   row_group_size=len(recs))
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- the store (ledger + Breeze wrapper)

class Store:
    def __init__(self, root, day_cap, client=None, day=None, write=True):
        self.root, self.cap, self.client = root, day_cap, client
        self.day = day or dt.date.today().isoformat()
        self.write = write
        self.last_call = 0.0
        self.calls_total = 0
        self.cur_unit, self.cur_rows, self.unit_calls = "", 0, 0
        self.padded = 0
        path = os.path.join(root, "_meta", "ledger.sqlite")
        if write:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            self.db = sqlite3.connect(path)
        elif os.path.exists(path):
            self.db = sqlite3.connect(path)
        else:
            self.db = sqlite3.connect(":memory:")
        self.db.executescript(LEDGER_SCHEMA)
        row = self.db.execute("SELECT n FROM calls WHERE day=?", (self.day,)).fetchone()
        self.calls_today = row[0] if row else 0

    def close(self):
        self.db.close()

    def _count(self):
        self.calls_total += 1
        self.unit_calls += 1
        self.calls_today += 1
        if self.write:
            self.db.execute("INSERT INTO calls(day, n) VALUES(?, 1) ON CONFLICT(day) DO UPDATE SET n = n + 1",
                            (self.day,))
            self.db.commit()
        if self.calls_total % PROGRESS_EVERY == 0:
            print(f"  {self.calls_today} calls today ({self.day}); unit {self.cur_unit}; rows so far {self.cur_rows}")

    def call(self, kind, a, b, meta):
        """One Breeze request: >= MIN_GAP apart, 4 attempts with growing back-off. Returns (rows, error_text)."""
        if self.client is None:
            self.client = make_client()
        kw = breeze_args(kind, a, b, meta)
        resp = None
        for attempt in range(1, ATTEMPTS + 1):
            wait = MIN_GAP - (time.monotonic() - self.last_call)
            if wait > 0:
                time.sleep(wait)
            self.last_call = time.monotonic()
            self._count()
            try:
                resp = self.client.get_historical_data_v2(**kw)
                # only a clean "no candles" answer may count as missing data: a throttle, an expired session or
                # any other failure must never be recorded as "does not exist at source"
                if not isinstance(resp, dict):
                    raise RuntimeError(f"unexpected response {str(resp)[:200]}")
                if not resp.get("Success"):
                    status, etext = resp.get("Status"), str(resp.get("Error") or "")
                    if status not in (200, None) or (etext and "no data" not in etext.lower()):
                        raise RuntimeError(f"Breeze status {status}: {etext[:200]}")
                break
            except Exception as ex:
                print(f"  retry {attempt}/{ATTEMPTS} {kind} {a}..{b}: {type(ex).__name__}: {ex}")
                if attempt == ATTEMPTS:
                    if self.write:
                        self.db.commit()
                    sys.exit("giving up after repeated errors; run again to resume")
                time.sleep(BACKOFF * attempt)
        rows = resp.get("Success") if isinstance(resp, dict) else None
        if not isinstance(rows, list):
            rows = []
        err = resp.get("Error") if isinstance(resp, dict) else None
        return rows, (str(err) if err else "")

    def fetch(self, kind, a, b, meta):
        """One request. A response of TRUNCATE_AT rows or more is refetched one calendar day at a time and those
        rows are used instead. Returns [(from, to, rows, error_text)] for every request made."""
        rows, err = self.call(kind, a, b, meta)
        if len(rows) < TRUNCATE_AT or a == b:
            if len(rows) >= TRUNCATE_AT:
                print(f"  {len(rows)} rows for the single day {a}: kept as returned (cannot refetch smaller)")
            return [(a, b, rows, err)]
        self.padded += 1
        out = []
        day = to_date(a)
        while day <= to_date(b):
            s = day.isoformat()
            r2, e2 = self.call(kind, s, s, meta)
            out.append((s, s, r2, e2))
            day += ONE_DAY
        print(f"  {len(rows)} rows for {a}..{b} (possible truncation): refetched day by day, {len(out)} requests")
        return out

    def dead_contracts(self, uid):
        """{(strike, right)} with no candles in a finished options unit; "all" for a unit that had none at all;
        None when the unit is not finished (then nothing may be pruned on its account)."""
        row = self.db.execute("SELECT status FROM units WHERE unit_id=?", (uid,)).fetchone()
        if not row:
            return None
        if row[0] in ("empty", "no_data_at_source"):
            return "all"
        return {(k, r) for k, r in self.db.execute("SELECT strike, right FROM empty_requests WHERE unit_id=?", (uid,))}

    def record_unit(self, u, status, requests, rows, dup, fname, notes, empties):
        if not self.write:
            return
        now = dt.datetime.now().isoformat(timespec="seconds")
        self.db.execute("DELETE FROM empty_requests WHERE unit_id=?", (u.uid,))
        for sa, sb, meta, msg in empties:
            e, k, r = meta_fields(u.kind, meta)
            self.db.execute("INSERT INTO empty_requests VALUES (?,?,?,?,?,?,?,?,?)",
                            (u.uid, u.kind, e, k, r, sa, sb, msg or "", now))
        self.db.execute("INSERT OR REPLACE INTO units VALUES (?,?,?,?,?,?,?,?,?)",
                        (u.uid, u.kind, status, requests, rows, dup, fname, now, "; ".join(notes)))
        self.db.commit()


def run_unit(st, u):
    if is_done(st, u):
        return "skip"
    n = len(u.requests)
    if n > st.cap:
        sys.exit(f"unit {u.uid} needs {n} requests, more than --day-cap {st.cap}: raise --day-cap")
    if st.calls_today + n > st.cap:
        raise DayCapReached()
    st.cur_unit, st.cur_rows, st.unit_calls = u.uid, 0, 0
    recs, empties, status = [], [], None
    requests = u.requests
    if PRUNE and len(u.later) == PRUNE_AFTER:
        # walking back from the expiry: a contract with no candles in each of the next chunks is not asked again
        # (recorded as not asked, never as data). An option that has stopped trading going back does not restart.
        later = [st.dead_contracts(uid) for uid in u.later]
        dead = None
        if all(d is not None for d in later):
            sets = [d for d in later if d != "all"]
            dead = set.intersection(*sets) if sets else "all"
        if dead is not None:
            everything = dead == "all"
            for a, b, meta in u.requests:
                if everything or (meta[1], meta[2]) in dead:
                    empties.append((a, b, meta, SKIP_NOTE))
            requests = [] if everything else [r for r in u.requests if (r[2][1], r[2][2]) not in dead]
    for i, (a, b, meta) in enumerate(requests, 1):
        got = 0
        for sa, sb, rows, err in st.fetch(u.kind, a, b, meta):
            got += len(rows)
            if not rows and u.kind != "options":
                empties.append((sa, sb, meta, err))
            for x in rows:
                recs.append(to_record(u.kind, x, meta))
        if u.kind == "options" and not got:          # one line per contract with no candles in the whole chunk
            empties.append((a, b, meta, err))
        st.cur_rows = len(recs)
        if u.early_stop and i == EARLY_STOP and not recs:
            status = "no_data_at_source"
            break
    if status is None:
        status = "ok" if recs else "empty"
    uniq, dup, differing = dedupe(u.kind, recs)
    notes = []
    if dup:
        notes.append(f"dup_dropped={dup}")
    if differing:
        notes.append(f"dup_with_different_values={differing}")
    if not u.is_final:
        notes.append("partial")
    if status == "no_data_at_source":
        notes.append(f"first {EARLY_STOP} requests returned nothing")
    if len(requests) < len(u.requests):
        notes.append(f"{len(u.requests) - len(requests)} of {len(u.requests)} contracts {SKIP_NOTE}")
    fname = None
    if uniq:
        path = u.final_path if u.is_final else u.partial_path
        write_parquet(path, u.kind, uniq)
        fname = os.path.relpath(path, st.root).replace(os.sep, "/")
    st.record_unit(u, status, st.unit_calls, len(uniq), dup, fname, notes, empties)
    return status


def run_phases(st, phases, frm, to, tiers, wings):
    today = dt.date.today()
    for ph in phases:
        units = phase_units(st.root, ph, frm, to, today, tiers, wings)
        todo = sum(1 for u in units if not is_done(st, u))
        print(f"phase {ph}: {len(units)} units, {todo} to do")
        for u in units:
            run_unit(st, u)
        if ph == "options":
            drop_stale_partials(st, units, today)


def drop_stale_partials(st, units, today):
    """Once every unit of an expiry that has passed is final, its partial files are superseded: remove them."""
    by = defaultdict(list)
    for u in units:
        if u.expiry:
            by[u.expiry].append(u)
    for e, us in by.items():
        if e >= today.isoformat() or not all(is_done(st, u) for u in us):
            continue
        for p in glob.glob(os.path.join(os.path.dirname(us[0].final_path), "*.partial.parquet")):
            os.remove(p)


def run_all(st, phases, frm, to, tiers, wings):
    """True when every phase finished; False when the day cap stopped the run."""
    try:
        run_phases(st, phases, frm, to, tiers, wings)
        return True
    except DayCapReached:
        print("day cap reached, run again tomorrow")
        return False


def write_missing(st):
    if not st.write:
        return
    path = os.path.join(st.root, "_missing", "missing.csv")
    rows = []
    for uid, kind, exp, k, r, a, b, msg, at in st.db.execute(
            "SELECT unit_id, kind, expiry, strike, right, from_date, to_date, message, asked_at "
            "FROM empty_requests ORDER BY unit_id, from_date"):
        rows.append(["request", uid, kind, "", exp or "", "" if k is None else k, r or "", a, b, msg or "", at])
    for uid, kind, status, note in st.db.execute(
            "SELECT unit_id, kind, status, note FROM units WHERE status IN ('empty','no_data_at_source') "
            "ORDER BY unit_id"):
        rows.append(["unit", uid, kind, status, "", "", "", "", "", note or "", ""])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "unit_id", "kind", "status", "expiry", "strike", "right", "from_date", "to_date",
                    "message", "asked_at"])
        w.writerows(rows)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------- CLI modes

def plan(root, frm, to, phases, tiers, wings, cap):
    st = Store(root, cap, write=False)
    today = dt.date.today()
    for ph in phases:
        units = phase_units(root, ph, frm, to, today, tiers, wings)
        if not units and ph != "index":
            continue
        todo = [u for u in units if not is_done(st, u)]
        reqs = sum(len(u.requests) for u in todo)
        print(f"{ph}: {len(units)} units in range, {len(todo)} to do, {reqs} requests to do, "
              f"about {math.ceil(reqs / cap)} day(s) at a cap of {cap}")
        if ph == "options" and todo:
            per_tier, per_year = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
            for u in todo:
                per_tier[u.tier][0] += 1
                per_tier[u.tier][1] += len(u.requests)
                per_year[u.expiry[:4]][0] += 1
                per_year[u.expiry[:4]][1] += len(u.requests)
            for t in sorted(per_tier):
                print(f"   {('', 'weekly expiries', 'monthly expiries')[t]}: {per_tier[t][0]} units, "
                      f"{per_tier[t][1]} requests at most (contracts that stop trading going back are not asked)")
            for y in sorted(per_year):
                print(f"   expiry year {y}: {per_year[y][0]} units, {per_year[y][1]} requests")
    st.close()


def probe_dates(frm, to):
    """The 15th (or the next weekday) of every 6th month, starting with the --from month, up to --to."""
    out = []
    y, m = frm.year, frm.month
    while True:
        d = dt.date(y, m, 15)
        while d.weekday() >= 5:
            d += ONE_DAY
        if d > to:
            break
        if d >= frm:
            out.append(d)
        m += 6
        while m > 12:
            m -= 12
            y += 1
    return out


def probe(root, frm, to, cap):
    st = Store(root, cap, write=True)
    cal = Calendar(*expiries([], None))
    print(f"{'date':<12}{'index':>8}{'future':>8}{'option':>8}  strike / expiry")
    for d in probe_dates(frm, to):
        s = d.isoformat()
        irows, ierr = st.call("index", s, s, None)
        frows = orows = 0
        detail = f"index: {ierr}" if ierr else ""
        if irows:
            atm = int(round(float(irows[0]["close"]) / STRIKE_STEP) * STRIKE_STEP)
            fe = cal.near_month(s)
            frows = len(st.call("futures", s, s, fe)[0]) if fe else 0
            oe = cal.tiers(s).get(1)
            if oe:
                orows = len(st.call("options", s, s, (oe, atm, "CE"))[0])
                detail = f"{atm} CE / {oe}"
        print(f"{s:<12}{len(irows):>8}{frows:>8}{orows:>8}  {detail}")
    st.close()
    print("probe wrote no data files (calls counted in the ledger)")


def verify(root):
    files = []
    tmps = []
    for kind in PHASES:
        for dp, _, fns in os.walk(os.path.join(root, kind)):
            files += [os.path.join(dp, fn) for fn in fns if fn.endswith(".parquet")]
            tmps += [os.path.join(dp, fn) for fn in fns if fn.endswith(".tmp")]
    if not files:
        print(f"no parquet files under {root}")
        return 0
    total_rows = total_dups = total_bytes = total_short = 0
    for f in sorted(files):
        rel = os.path.relpath(f, root).replace(os.sep, "/")
        kind = rel.split("/")[0]
        t = pq.read_table(f).to_pydict()
        times = t["datetime"]
        n = len(times)
        keys = list(zip(times, t["strike"], t["right"])) if kind == "options" else times
        dups = n - len(set(keys))
        total_rows += n
        total_dups += dups
        total_bytes += os.path.getsize(f)
        short = []
        if kind != "options" and n:
            per = defaultdict(int)
            for ts in times:
                if TIME_LO <= ts.hour * 60 + ts.minute <= TIME_HI:
                    per[ts.date().isoformat()] += 1
            short = sorted(d for d, c in per.items() if c < FULL_SESSION)
        total_short += len(short)
        span = f"{min(times)} .. {max(times)}" if n else "-"
        extra = f", sessions under {FULL_SESSION} candles: {len(short)} {short[:5]}" if short else ""
        print(f"{rel}: rows {n}, duplicate keys {dups}, {span}{extra}")
    print(f"TOTAL files {len(files)}, rows {total_rows}, duplicate keys {total_dups}, "
          f"short sessions {total_short}, bytes on disk {total_bytes} ({total_bytes / 1e6:.1f} MB)")
    if tmps:
        print(f"warning: {len(tmps)} leftover .tmp file(s)")
    print("VERIFY FAILED: duplicate keys" if total_dups else "verify passed")
    return 1 if total_dups else 0


# ----------------------------------------------------------------------------- selftest (fake client, temp dir)

def spot_at(day, minute):
    return round(10000 + 300 * math.sin(day.toordinal() * 0.37 + minute * 0.011), 2)


class FakeBreeze:
    def __init__(self):
        self.requests = []
        self.padded = 0

    def get_historical_data_v2(self, **kw):
        self.requests.append(kw)
        a, b = to_date(kw["from_date"][:10]), to_date(kw["to_date"][:10])
        kind = {"cash": "index", "futures": "futures", "options": "options"}[kw["product_type"]]
        if kind == "options" and kw["expiry_date"].startswith("2018-"):
            return {"Success": [], "Error": "No data for this request"}
        rows = []
        day = a
        while day <= b:
            if day.weekday() < 5:
                rows += fake_rows(kind, day, kw)
            day += ONE_DAY
        if kind == "index" and rows and a != b and self.padded == 0:
            self.padded = 1                                     # one truncated-looking response of 1000 rows
            rows = rows[:TRUNCATE_AT] if len(rows) >= TRUNCATE_AT else rows + [dict(rows[-1]) for _ in
                                                                                 range(TRUNCATE_AT - len(rows))]
        return {"Success": rows, "Error": None if rows else "No data"}


def fake_rows(kind, day, kw):
    rows = []
    for minute in range(TIME_LO, TIME_HI + 1):
        ts = f"{day.isoformat()} {minute // 60:02d}:{minute % 60:02d}:00"
        s = spot_at(day, minute)
        if kind == "index":
            rows.append({"datetime": ts, "open": f"{s:.2f}", "high": f"{s + 2:.2f}", "low": f"{s - 2:.2f}",
                         "close": f"{s + 1:.2f}", "volume": "0"})
        elif kind == "futures":
            p = s + 40
            rows.append({"datetime": ts, "open": f"{p:.2f}", "high": f"{p + 2:.2f}", "low": f"{p - 2:.2f}",
                         "close": f"{p + 1:.2f}", "volume": f"{1000 + minute}.0", "open_interest": "50000"})
        else:
            k = int(kw["strike_price"])
            if abs(k - s) > 300:
                continue
            p = max(0.05, 300 - abs(k - s))
            rows.append({"datetime": ts, "open": f"{p:.2f}", "high": f"{p:.2f}", "low": f"{p:.2f}",
                         "close": f"{p:.2f}", "volume": "10", "open_interest": "100"})
    return rows


def check_calendar():
    assert dt.date(2019, 2, 14).weekday() == THU
    assert dt.date(2025, 8, 28).weekday() == THU and dt.date(2025, 9, 2).weekday() == TUE
    assert last_weekday(2018, 12, THU) == dt.date(2018, 12, 27)
    assert last_weekday(2025, 9, TUE) == dt.date(2025, 9, 30)
    sessions = []
    d = dt.date(2018, 12, 1)
    while d <= dt.date(2019, 3, 31):
        if d.weekday() < 5 and d != dt.date(2019, 1, 31):    # Jan 31 2019 (monthly expiry) is not a session
            sessions.append(d.isoformat())
        d += ONE_DAY
    wk, mo = expiries(sessions)
    assert "2019-01-30" in mo and "2018-12-27" in mo and "2019-01-31" not in mo, mo
    wk2, mo2 = expiries(sessions, {"drop": ["2019-02-28"]})
    assert "2019-02-28" not in mo2
    cal = Calendar(wk, mo)
    t = cal.tiers("2019-01-02")          # no weekly before 2019-02-14: tier 1 is the monthly, no tier 2, tier 3 the weekly
    assert t == {1: "2019-01-30", 3: "2019-02-14"}, t
    t = cal.tiers("2019-02-15")
    assert t[1] == "2019-02-21" and t[2] == "2019-02-28" and t[3] == "2019-02-28", t


def selftest():
    global MIN_GAP
    MIN_GAP = 0.0
    check_calendar()
    root = tempfile.mkdtemp(prefix="breeze_store_selftest_")
    frm, to = dt.date(2018, 12, 1), dt.date(2019, 3, 31)
    db = None
    try:
        fake = FakeBreeze()
        day = dt.date(2099, 1, 1)               # simulated run days, so the day cap resets between runs
        runs = 0
        while True:
            runs += 1
            assert runs <= 500, "selftest did not converge"
            st = Store(root, SELFTEST_CAP, client=fake, day=day.isoformat())
            try:
                done = run_all(st, PHASES, frm, to, (1, 2, 3), WINGS)
            finally:
                write_missing(st)
                st.close()
            if done:
                break
            day += ONE_DAY
        print(f"selftest: complete after {runs} run(s) at a day cap of {SELFTEST_CAP}; "
              f"{len(fake.requests)} fake Breeze requests in all")
        assert runs > 1, "day cap never reached: stop/resume not exercised"
        assert fake.padded == 1, "truncation refetch not exercised"

        before = len(fake.requests)
        day += ONE_DAY
        st = Store(root, SELFTEST_CAP, client=fake, day=day.isoformat())
        try:
            assert run_all(st, PHASES, frm, to, (1, 2, 3), WINGS)
        finally:
            write_missing(st)
            st.close()
        # the only unit still open is the April 2019 future (its sessions run past --to): a partial, refetched each run
        new = fake.requests[before:]
        assert all(r["product_type"] == "futures" and r["expiry_date"][:10] == "2019-04-25" for r in new), new
        print(f"selftest: rerun made {len(new)} new request(s), all for the open April 2019 future; "
              f"0 for finished units")

        assert verify(root) == 0
        db = sqlite3.connect(os.path.join(root, "_meta", "ledger.sqlite"))
        dup = db.execute("SELECT COALESCE(SUM(dup_dropped), 0) FROM units").fetchone()[0]
        assert dup == 0, f"duplicates dropped: {dup}"
        no_data = [r[0] for r in db.execute(
            "SELECT unit_id FROM units WHERE kind='options' AND status='no_data_at_source'")]
        assert no_data, "no 2018 option units marked no_data_at_source"
        assert all(u.split("|")[1].startswith("2018-") for u in no_data), no_data
        with open(os.path.join(root, "_missing", "missing.csv"), encoding="utf-8") as fh:
            missing = fh.read()
        assert all(u in missing for u in no_data), "missing.csv does not list the 2018 option units"
        assert not glob.glob(os.path.join(root, "options", "1minute", "2018", "**", "*.parquet"), recursive=True)
        assert os.path.exists(os.path.join(root, "index", "1minute", "2018", "2018-12.parquet"))
        print(f"selftest: {len(no_data)} option units marked no_data_at_source (2018 expiries), missing.csv lists them")
        print("selftest: plan on the temp root after completion:")
        plan(root, frm, to, PHASES, (1, 2, 3), WINGS, SELFTEST_CAP)
        print("SELFTEST PASSED")
        return 0
    finally:
        if db is not None:
            db.close()
        shutil.rmtree(root, ignore_errors=True)


# ----------------------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(description="Breeze NIFTY 1-minute candles into a Parquet store.")
    p.add_argument("--root", default=DEFAULT_ROOT)
    p.add_argument("--phase", default="all", choices=["index", "futures", "options", "all"])
    p.add_argument("--from", dest="frm", default="2018-01-01")
    p.add_argument("--to", default=None)
    p.add_argument("--day-cap", type=int, default=DEFAULT_DAY_CAP)
    p.add_argument("--tiers", default="1,2", help="options: 1 = weekly expiries, 2 = monthly expiries")
    p.add_argument("--no-prune", action="store_true", help="options: ask every contract in every chunk")
    p.add_argument("--wings", type=int, default=WINGS)
    p.add_argument("--plan", action="store_true")
    p.add_argument("--probe", action="store_true")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args(argv)

    if args.selftest:
        return selftest()
    if args.verify:
        return verify(args.root)
    frm = dt.date.fromisoformat(args.frm)
    to = dt.date.fromisoformat(args.to) if args.to else dt.date.today()
    tiers = tuple(sorted({int(x) for x in args.tiers.split(",")}))
    if not set(tiers) <= {1, 2}:
        sys.exit("--tiers takes a subset of 1,2")
    global PRUNE
    PRUNE = not args.no_prune
    phases = PHASES if args.phase == "all" else (args.phase,)
    if args.plan:
        return plan(args.root, frm, to, phases, tiers, args.wings, args.day_cap)
    if args.probe:
        return probe(args.root, frm, to, args.day_cap)

    st = Store(args.root, args.day_cap, write=True)
    try:
        if run_all(st, phases, frm, to, tiers, args.wings):
            print("all requested phases are complete")
    finally:
        write_missing(st)
        print(f"requests this run: {st.calls_total}; today ({st.day}) in all: {st.calls_today}")
        st.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
