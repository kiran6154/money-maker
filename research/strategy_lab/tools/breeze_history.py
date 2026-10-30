"""Longer candle history for the strategy lab from ICICI Breeze (which serves expired contracts): 1-minute NIFTY near-month
futures and the 1-minute NIFTY index, assembled into the files config/data.json points at.

    python tools/breeze_history.py --from 2021-10-01 --plan          # sessions, contracts, requests (no login needed)
    python tools/breeze_history.py --from 2021-10-01                  # fetch futures + index (resumable)
    python tools/breeze_history.py --from 2021-10-01 --what index     # only one of them
    python tools/breeze_history.py --build                            # assemble files, point config/data.json at them

Near month: on each session the futures candles are the contract of the first monthly expiry on or after that session
(lab.monthly_expiry: last Thursday up to August 2025, last Tuesday from September 2025, the session before on a holiday), from the day after the previous monthly expiry to its own
expiry day - the upcoming contract is never used early. Each row carries `contract` (e.g. NIFTY26SEPFUT), `expiry` and
`front_month` = 1. The index has no traded volume: its files carry volume 0 (a strategy run on the index uses an
equal-weighted AVWAP).

Fetched pieces go to <data root>/breeze/{futures/<expiry>,index}/<from>__<to>.csv (2 sessions per request, Breeze returns
at most 1,000 candles); an existing piece is not fetched again. --build writes
    <data root>/niftyfut_nearmonth_{minute,5minute}_<first>_to_<last>.csv
    <data root>/nifty50_breeze_{minute,5minute}_<first>_to_<last>.csv
and replaces the four paths in config/data.json (only those values; the file's layout stays). Stored lab results for the
old files are then recomputed by the next `python lab.py`.

Credentials, as for tools/breeze_options.py, come from the environment and are never written anywhere:
BREEZE_API_KEY, BREEZE_API_SECRET, BREEZE_SESSION_TOKEN (the day's apisession from
https://api.icicidirect.com/apiuser/login?api_key=<your key>). Needs `pip install breeze-connect`. Nothing here places orders.
"""
import csv, datetime as D, glob, json, os, re, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import lab  # noqa: E402  (calendar, resampling and data paths shared with the backtests)

ROOT = os.path.dirname(os.path.normpath(lab.DATA["options"]["weekly_dir"]))          # D:/nifty
OUT = os.path.join(ROOT, "breeze")
PER_REQUEST = 2                     # sessions per request (375 one-minute candles a session; Breeze returns at most 1,000)
PAUSE = 0.7                         # ~85 requests / minute (Breeze: 100 / minute, 5,000 / day)
DAY_CAP = 4800
COLS = ["datetime", "open", "high", "low", "close", "volume", "oi"]


def session_days(frm, to):
    """Trading sessions from the long 5-minute index file(s) under the data root (and the current futures file)."""
    days = set()
    for f in glob.glob(os.path.join(ROOT, "nifty50_5minute_*.csv")) + [lab.FUT1]:
        if " - Copy" in f: continue
        for r in csv.DictReader(open(f)):
            d = r["datetime"][:10]
            if frm <= d <= to: days.add(d)
    return sorted(days)


def monthly_expiries():
    """The exchange's monthly expiry of every month from 2019 to the last known option expiry (lab.monthly_expiry: last
    Thursday up to August 2025, last Tuesday from September 2025, the session before on a holiday)."""
    cal = set()
    for sub in ("nifty_options", "nifty_options_1minute"):
        for y in glob.glob(os.path.join(lab.DATA["options"]["weekly_dir"], sub, "[0-9]" * 4)):
            cal |= {os.path.basename(e) for e in glob.glob(os.path.join(y, "????-??-??"))}
    cal.add(lab.DATA["options"]["kite_expiry"])
    months = sorted({e[:7] for e in cal if e >= "2019-01"})
    return sorted({lab.monthly_expiry(m) for m in months})


def near_month(days, monthly):
    """{session: expiry of the near-month contract}; sessions past the known calendar are left out."""
    out = {}
    for d in days:
        e = next((x for x in monthly if x >= d), None)
        if e: out[d] = e
    return out


def contract_name(e):
    return f"NIFTY{e[2:4]}{D.date.fromisoformat(e):%b}FUT".upper()


def chunks(days):
    return [(days[i], days[min(i + PER_REQUEST, len(days)) - 1]) for i in range(0, len(days), PER_REQUEST)]


def plan(frm, to, what):
    days = session_days(frm, to)
    nm = near_month(days, monthly_expiries())
    jobs = []
    if "futures" in what:
        by = {}
        for d, e in nm.items(): by.setdefault(e, []).append(d)
        for e, ds in sorted(by.items()):
            for a, b in chunks(ds):
                f = os.path.join(OUT, "futures", e, f"{a}__{b}.csv")
                if not os.path.exists(f): jobs.append(("futures", e, a, b, f))
    if "index" in what:
        for a, b in chunks(days):
            f = os.path.join(OUT, "index", f"{a}__{b}.csv")
            if not os.path.exists(f): jobs.append(("index", None, a, b, f))
    return days, nm, jobs


def fetch(jobs):
    key, secret, token = (os.environ.get(v) for v in ("BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN"))
    if not (key and secret and token):
        sys.exit("set BREEZE_API_KEY, BREEZE_API_SECRET and BREEZE_SESSION_TOKEN in the environment (see the top of this file)")
    try:
        from breeze_connect import BreezeConnect
    except ImportError:
        sys.exit("the ICICI SDK is missing: pip install breeze-connect")
    br = BreezeConnect(api_key=key)
    br.generate_session(api_secret=secret, session_token=token)
    empty = 0
    for n, (kind, e, a, b, out) in enumerate(jobs[:DAY_CAP], 1):
        args = dict(interval="1minute", from_date=f"{a}T07:00:00.000Z", to_date=f"{b}T16:00:00.000Z", stock_code="NIFTY")
        if kind == "futures":
            args.update(exchange_code="NFO", product_type="futures", expiry_date=f"{e}T07:00:00.000Z", right="others",
                        strike_price="0")
        else:
            args.update(exchange_code="NSE", product_type="cash")
        for attempt in range(4):
            try:
                r = br.get_historical_data_v2(**args); break
            except Exception as ex:                    # network / throttling: back off and retry
                print(f"  retry {attempt + 1} {kind} {e or ''} {a}: {ex}"); time.sleep(5 * (attempt + 1))
        else:
            sys.exit("giving up after repeated errors; run again to resume")
        rows = (r or {}).get("Success") or []
        if (r or {}).get("Error") and not rows: print(f"  {kind} {e or ''} {a}..{b}: {r['Error']}")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", newline="") as fh:         # an empty piece records "asked, nothing returned"
            w = csv.writer(fh); w.writerow(COLS)
            for x in sorted(rows, key=lambda x: x["datetime"]):
                if "09:15" <= x["datetime"][11:16] <= "15:29":
                    w.writerow([x["datetime"][:19], x["open"], x["high"], x["low"], x["close"],
                                x.get("volume", 0) if kind == "futures" else 0, x.get("open_interest", "") or ""])
        empty += not rows
        if n % 50 == 0: print(f"  {n}/{min(len(jobs), DAY_CAP)} requests ({empty} returned no candles)")
        time.sleep(PAUSE)
    print(f"fetched {min(len(jobs), DAY_CAP)} pieces, {empty} with no candles"
          + ("; more remain - run again (tomorrow if the daily cap is reached)" if len(jobs) > DAY_CAP else ""))


def build():
    monthly = monthly_expiries()
    fut, idx = {}, {}
    for f in glob.glob(os.path.join(OUT, "futures", "*", "*.csv")):
        e = os.path.basename(os.path.dirname(f))
        for r in csv.DictReader(open(f)):
            if near_month([r["datetime"][:10]], monthly).get(r["datetime"][:10]) == e:     # near month only
                fut[r["datetime"]] = dict(r, contract=contract_name(e), expiry=e, front_month=1)
    for f in glob.glob(os.path.join(OUT, "index", "*.csv")):
        for r in csv.DictReader(open(f)): idx[r["datetime"]] = dict(r, volume=0)
    if not fut or not idx: sys.exit("nothing fetched yet for futures and index: run the fetch first")
    days = sorted({t[:10] for t in fut} & {t[:10] for t in idx})    # sessions both series have
    fut = [fut[t] for t in sorted(fut) if t[:10] in days]
    idx = [idx[t] for t in sorted(idx) if t[:10] in days]
    a, b = days[0], days[-1]
    paths = {}
    for kind, rows, stem, extra in (("futures", fut, "niftyfut_nearmonth", ["contract", "expiry", "front_month"]),
                                    ("spot", idx, "nifty50_breeze", [])):
        for tf, mins in (("minute", 1), ("5minute", 5)):
            path = os.path.join(ROOT, f"{stem}_{tf}_{a}_to_{b}.csv").replace(os.sep, "/")
            out = rows if mins == 1 else resample_keep(rows, extra)
            with open(path, "w", newline="") as fh:
                w = csv.writer(fh); w.writerow(COLS + extra)
                for r in out: w.writerow([r[c] if c in r else "" for c in COLS + extra])
            paths[(kind, tf)] = path
            print(f"wrote {path} ({len(out)} candles)")
    # point config/data.json at the new files: replace only the four path values, keep the file's layout
    cfg = os.path.join(HERE, "config", "data.json")
    raw = open(cfg, encoding="utf-8", newline="").read()
    for (kind, tf), path in paths.items():
        old = lab.DATA[kind][tf]
        raw = raw.replace(json.dumps(old), json.dumps(path), 1)
    json.loads(raw)
    open(cfg, "w", encoding="utf-8", newline="").write(raw)
    print(f"config/data.json now points at {a} .. {b} ({len(days)} sessions). Next: python lab.py")


def resample_keep(rows, extra):
    """5-minute candles from 1-minute rows; the contract columns come from the candle's first minute."""
    out = lab.resample_rows(rows, 5)
    first = {}
    for r in rows:
        dt = r["datetime"]; m = int(dt[11:13]) * 60 + int(dt[14:16]); b = 555 + (m - 555) // 5 * 5
        first.setdefault(f"{dt[:11]}{b // 60:02d}:{b % 60:02d}:00", r)
    for r in out:
        for c in extra: r[c] = first[r["datetime"]].get(c, "")
    return out


def main():
    opts = sys.argv[1:]
    get = lambda k, d=None: opts[opts.index(k) + 1] if k in opts else d
    if "--build" in opts: return build()
    frm = get("--from")
    if not frm: sys.exit(__doc__)
    to = get("--to", lab.sessions()[-1])
    what = get("--what", "futures,index").split(",")
    days, nm, jobs = plan(frm, to, what)
    print(f"sessions {days[0]} .. {days[-1]}: {len(days)}; near-month contracts {len(set(nm.values()))} "
          f"({contract_name(min(nm.values()))} .. {contract_name(max(nm.values()))}); sessions past the option calendar: "
          f"{len(days) - len(nm)}")
    print(f"requests to make: {len(jobs)} (about {len(jobs) * PAUSE / 60:.0f} minutes; Breeze allows 5,000 a day)")
    if "--plan" in opts or not jobs: return
    fetch(jobs)


if __name__ == "__main__":
    main()
