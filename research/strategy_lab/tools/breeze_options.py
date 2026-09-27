"""Fill the local NIFTY option data with every strike a backtest decision could pick, from ICICI Breeze (which, unlike
Kite, serves expired contracts). Written for STRATEGY_ANALYSIS_TODO S41: the local weekly/monthly files hold only the five
strikes around the ATM of the day before expiry (a window chosen with hindsight), so far strikes were skipped.

    python tools/breeze_options.py 2026-07-28 2026-08-25 --plan     # what would be fetched (no login needed)
    python tools/breeze_options.py 2026-07-28 2026-08-25            # fetch 1-minute and 5-minute candles
    python tools/breeze_options.py 2026-07-28 --interval 1minute

Which strikes: for each expiry E, every session whose nearest expiry (lab.OptionChain.expiry_for, weekly and monthly, the
strategies' expiry_min_days) is E; on every spot candle of those sessions (1- and 5-minute) every strike choice of every
strategy file (ATR2, ATM, ITM1-2, OTM1-4 ...) for CE and PE, via lab.pick_strike: the strikes the backtests can ask for,
decided from spot at the time and nothing later. Each strike is fetched from the first session that can ask for it to E.
Strikes already in the expiry's combined file are skipped.

Output (the layout the existing files use, read by lab.OptionChain):
    <weekly_dir>/nifty_options_1minute/<YYYY>/<E>/.chunks/options/<CE|PE>/<strike>/<from>__<to>.csv
    <weekly_dir>/nifty_options/<YYYY>/<E>/.chunks/options/<CE|PE>/<strike>/<from>__<to>.csv
and a "full_chain" section in each expiry's manifest.json (so stored lab results for that data are recomputed).
Resumable: a chunk file that exists is not fetched again. Nothing here places orders.

Credentials are read at runtime from the environment and never written anywhere:
    BREEZE_API_KEY, BREEZE_API_SECRET  - from the ICICI Breeze API app
    BREEZE_SESSION_TOKEN               - log in at https://api.icicidirect.com/apiuser/login?api_key=<your key> (valid for
                                         the day); the token is the apisession value in the address you are sent to
Needs the ICICI SDK once:  pip install breeze-connect
"""
import csv, datetime as D, json, os, sys, time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import lab  # noqa: E402  (strike rule, calendars and data paths shared with the backtests)

INTERVALS = {"1minute": ("nifty_options_1minute", 2), "5minute": ("nifty_options", 10)}   # folder, trading days per request
COLS = ["datetime", "stock_code", "exchange_code", "expiry_date", "strike_price", "option_right",
        "open", "high", "low", "close", "volume", "open_interest"]
PAUSE = 0.7                 # ~85 requests / minute (Breeze allows 100 / minute, 5,000 / day)
DAY_CAP = 4800


def plan(expiries):
    """{expiry: {(right, strike): first session that can ask for it}} and the sessions per expiry."""
    specs = [s for _, s in lab.load_strategies()]
    choices = sorted({c for s in specs for c in s["options"]["strike_choices"]})
    kinds = sorted({k for s in specs for k in s["options"]["expiry_types"]})
    min_days = sorted({s["options"]["expiry_min_days"] for s in specs})
    step = specs[0]["options"]["strike_step"]
    atr_n = sorted({s["options"]["atr_period"] for s in specs})
    row = dict(lab.type_rows(specs[0])[1], timeframe="minute")
    chain = lab.OptionChain(row)
    sessions = lab.sessions()
    need, days = {e: {} for e in expiries}, {e: [] for e in expiries}
    for d in sessions:
        for e in expiries:
            if any(chain.expiry_for(d, md, k) == e for md in min_days for k in kinds): days[e].append(d)
    for tf in ("minute", "5minute"):
        spot = lab.Series.get(lab.tf_file("spot", tf))
        atrs = {n: lab.atr_series(spot, n) for n in atr_n}
        for i, t in enumerate(spot.t):
            d = t[:10]
            for e in expiries:
                if d not in days[e]: continue
                for n, atr in atrs.items():
                    for c in choices:
                        for right in ("CE", "PE"):
                            k = int(lab.pick_strike(c, right, spot.c[i], atr[i], step))
                            need[e].setdefault((right, k), d)
    return need, days, sessions


def existing(e, interval, right):
    folder = os.path.join(lab.DATA["options"]["weekly_dir"], INTERVALS[interval][0], e[:4], e)
    f = os.path.join(folder, f"NIFTY_{e}_{right}_{interval}.csv")
    if not os.path.exists(f): return folder, set()
    return folder, {int(float(r["strike_price"])) for r in csv.DictReader(open(f))}


def chunks(sessions, first, last, per):
    ds = [d for d in sessions if first <= d <= last]
    return [(ds[i], ds[min(i + per, len(ds)) - 1]) for i in range(0, len(ds), per)]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = sys.argv[1:]
    expiries = [a for a in args if len(a) == 10]
    intervals = [opts[opts.index("--interval") + 1]] if "--interval" in opts else list(INTERVALS)
    if not expiries: sys.exit(__doc__)
    need, days, sessions = plan(expiries)
    jobs = []
    for e in expiries:
        if not days[e]: print(f"{e}: no session in the data uses this expiry"); continue
        for iv in intervals:
            for right in ("CE", "PE"):
                folder, have = existing(e, iv, right)
                ks = sorted(k for (r, k) in need[e] if r == right and k not in have)
                for k in ks:
                    for a, b in chunks(sessions, need[e][(right, k)], e, INTERVALS[iv][1]):
                        out = os.path.join(folder, ".chunks", "options", right, str(k), f"{a}__{b}.csv")
                        if not os.path.exists(out): jobs.append((e, iv, right, k, a, b, out))
        n_str = len({k for (r, k) in need[e]})
        print(f"{e}: sessions {days[e][0]} .. {days[e][-1]} ({len(days[e])}), strikes asked for {n_str} "
              f"({min(k for _, k in need[e])} .. {max(k for _, k in need[e])})")
    print(f"requests to make: {len(jobs)} (about {len(jobs) * PAUSE / 60:.0f} minutes; Breeze allows 5,000 a day)")
    if "--plan" in opts or not jobs: return
    if len(jobs) > DAY_CAP: print(f"more than {DAY_CAP} requests: this run stops at the cap; run it again tomorrow to resume")

    key, secret, token = (os.environ.get(v) for v in ("BREEZE_API_KEY", "BREEZE_API_SECRET", "BREEZE_SESSION_TOKEN"))
    if not (key and secret and token):
        sys.exit("set BREEZE_API_KEY, BREEZE_API_SECRET and BREEZE_SESSION_TOKEN in the environment (see the top of this file)")
    try:
        from breeze_connect import BreezeConnect
    except ImportError:
        sys.exit("the ICICI SDK is missing: pip install breeze-connect")
    br = BreezeConnect(api_key=key)
    br.generate_session(api_secret=secret, session_token=token)

    done = empty = 0
    for n, (e, iv, right, k, a, b, out) in enumerate(jobs[:DAY_CAP], 1):
        for attempt in range(4):
            try:
                r = br.get_historical_data_v2(interval=iv, from_date=f"{a}T07:00:00.000Z", to_date=f"{b}T16:00:00.000Z",
                                              stock_code="NIFTY", exchange_code="NFO", product_type="options",
                                              expiry_date=f"{e}T07:00:00.000Z", right="call" if right == "CE" else "put",
                                              strike_price=str(k))
                break
            except Exception as ex:                      # network / throttling: back off and retry
                print(f"  retry {attempt + 1} {e} {k}{right} {a}: {ex}"); time.sleep(5 * (attempt + 1))
        else:
            sys.exit("giving up after repeated errors; run again to resume")
        rows = (r or {}).get("Success") or []
        if (r or {}).get("Error") and not rows:
            print(f"  {e} {k}{right} {a}..{b}: {r['Error']}")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", newline="") as fh:              # an empty file records "asked, nothing traded"
            w = csv.writer(fh); w.writerow(COLS)
            for x in sorted(rows, key=lambda x: x["datetime"]):
                if not ("09:15" <= x["datetime"][11:16] <= "15:29"): continue
                w.writerow([x["datetime"][:19], "NIFTY", "NFO", e, k, right, x["open"], x["high"], x["low"], x["close"],
                            x.get("volume", 0), x.get("open_interest", 0)])
        done += 1; empty += not rows
        if n % 50 == 0: print(f"  {n}/{min(len(jobs), DAY_CAP)} requests ({empty} returned no candles)")
        time.sleep(PAUSE)

    stamp = D.datetime.now().isoformat(timespec="seconds")
    for e in expiries:
        for iv in intervals:
            folder, _ = existing(e, iv, "CE")
            mf = os.path.join(folder, "manifest.json")
            m = json.load(open(mf, encoding="utf-8")) if os.path.exists(mf) else {}
            m["full_chain"] = dict(source="ICICI Breeze get_historical_data_v2", tool="research/strategy_lab/tools/breeze_options.py",
                                   updated_at=stamp, strikes={r: sorted(k for (rr, k) in need[e] if rr == r) for r in ("CE", "PE")},
                                   rule="every strike any strategy's strike choice picks from spot on the sessions using this expiry")
            os.makedirs(folder, exist_ok=True)
            json.dump(m, open(mf, "w", encoding="utf-8"), indent=2)
    print(f"done: {done} requests, {empty} with no candles; manifests updated. Next: python lab.py (only affected results re-run)")


if __name__ == "__main__":
    main()
