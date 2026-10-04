"""Download a full NIFTY option chain (every listed strike, CE+PE) for one expiry from Kite.

    python kite_options.py 2026-09-29            # 1-minute candles + OI, then 5-minute built locally

Output: D:/nifty/options/NIFTY_<expiry>/{minute,5minute}/<tradingsymbol>.csv and manifest.csv.
Resumable: contracts whose minute file already exists are skipped (delete the file to re-fetch).
Kite only serves contracts that are still listed; expired weeklies cannot be downloaded.
"""
import csv, os, sys, time, datetime as D
import requests
from kitecreds import creds

EXPIRY = sys.argv[1] if len(sys.argv) > 1 else "2026-09-29"
TO = D.date.today()
OUT = f"D:/nifty/options/NIFTY_{EXPIRY}"
CHUNK_DAYS = 55            # Kite: max 60 days per minute-candle request
PAUSE = 0.35               # ~3 requests/second (Kite historical limit)

k, t, _, _ = creds()
H = {"X-Kite-Version": "3", "Authorization": f"token {k}:{t}"}


def get(url, params, tries=5):
    for n in range(tries):
        r = requests.get(url, headers=H, params=params, timeout=60)
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(1.5 * (n + 1)); continue
        r.raise_for_status(); return r.json()["data"]["candles"]
    raise RuntimeError(f"gave up after {tries} tries: {url} {params}")


def resample5(rows):
    """1-minute rows -> 5-minute candles aligned to 09:15 (volume summed, OI = last)."""
    out, cur, key = [], None, None
    for dt, o, h, l, c, v, oi in rows:
        m = int(dt[11:13]) * 60 + int(dt[14:16]); b = 555 + (m - 555) // 5 * 5
        k5 = f"{dt[:11]}{b // 60:02d}:{b % 60:02d}:00"
        if k5 != key:
            if cur: out.append(cur)
            key, cur = k5, [k5, o, h, l, c, v, oi]
        else:
            cur[2] = max(cur[2], h); cur[3] = min(cur[3], l); cur[4] = c; cur[5] += v; cur[6] = oi
    if cur: out.append(cur)
    return out


def main():
    ins = requests.get("https://api.kite.trade/instruments/NFO", headers=H, timeout=60)
    ins.raise_for_status()
    chain = sorted((x for x in csv.DictReader(ins.text.splitlines())
                    if x["name"] == "NIFTY" and x["segment"] == "NFO-OPT" and x["expiry"] == EXPIRY),
                   key=lambda x: (float(x["strike"]), x["instrument_type"]))
    if not chain:
        sys.exit(f"no listed NIFTY options for expiry {EXPIRY}")
    for sub in ("minute", "5minute"): os.makedirs(f"{OUT}/{sub}", exist_ok=True)
    manifest = []
    t0 = time.time()
    for j, x in enumerate(chain, 1):
        sym, fn = x["tradingsymbol"], f"{OUT}/minute/{x['tradingsymbol']}.csv"
        if not os.path.exists(fn):
            rows, d = [], D.date(2026, 7, 1)
            while d <= TO:
                e = min(d + D.timedelta(days=CHUNK_DAYS), TO)
                for cnd in get(f"https://api.kite.trade/instruments/historical/{x['instrument_token']}/minute",
                               {"from": f"{d} 09:15:00", "to": f"{e} 15:30:00", "oi": 1}):
                    dt = cnd[0][:19].replace("T", " ")
                    if dt[11:16] <= "15:29": rows.append([dt, *cnd[1:6], cnd[6] if len(cnd) > 6 else 0])
                d = e + D.timedelta(days=1); time.sleep(PAUSE)
            hdr = ["datetime", "open", "high", "low", "close", "volume", "oi"]
            for sub, data in (("minute", rows), ("5minute", resample5(rows))):
                with open(f"{OUT}/{sub}/{sym}.csv", "w", newline="") as f:
                    w = csv.writer(f); w.writerow(hdr); w.writerows(data)
        with open(fn) as f:
            n = sum(1 for _ in f) - 1
            f.seek(0); lines = f.read().splitlines()
        first, last = (lines[1][:10], lines[-1][:10]) if n > 0 else ("", "")
        manifest.append([sym, x["instrument_token"], x["strike"], x["instrument_type"], EXPIRY, x["lot_size"], n, first, last])
        if j % 20 == 0 or j == len(chain):
            print(f"{j}/{len(chain)} {sym} rows={n}  elapsed {time.time() - t0:.0f}s", flush=True)
    with open(f"{OUT}/manifest.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["tradingsymbol", "instrument_token", "strike", "type", "expiry", "lot_size", "minute_rows", "first_day", "last_day"])
        w.writerows(manifest)
    print("done:", OUT, len(manifest), "contracts")


if __name__ == "__main__":
    main()
