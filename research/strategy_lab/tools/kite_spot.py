"""NIFTY 50 index (spot) candles from Kite, 1-minute and 5-minute, for strike selection and ATR.

    python kite_spot.py 2026-07-01 2026-09-25
"""
import csv, sys, time, datetime as D
import requests
from kitecreds import creds

FROM = D.date.fromisoformat(sys.argv[1] if len(sys.argv) > 1 else "2026-07-01")
TO = D.date.fromisoformat(sys.argv[2] if len(sys.argv) > 2 else "2026-09-25")
TOKEN = 256265          # NSE:NIFTY 50
k, t, _, _ = creds()
H = {"X-Kite-Version": "3", "Authorization": f"token {k}:{t}"}

for interval, chunk in (("minute", 55), ("5minute", 90)):
    rows, d = [], FROM
    while d <= TO:
        e = min(d + D.timedelta(days=chunk), TO)
        r = requests.get(f"https://api.kite.trade/instruments/historical/{TOKEN}/{interval}", headers=H,
                         params={"from": f"{d} 09:15:00", "to": f"{e} 15:30:00"}, timeout=60)
        r.raise_for_status()
        rows += [[c[0][:19].replace("T", " "), *c[1:5]] for c in r.json()["data"]["candles"]
                 if c[0][11:16] <= ("15:29" if interval == "minute" else "15:25")]
        d = e + D.timedelta(days=1); time.sleep(0.4)
    fn = f"D:/nifty/nifty50_{interval}_kite_{FROM}_to_{TO}.csv"
    with open(fn, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["datetime", "open", "high", "low", "close"]); w.writerows(rows)
    print(fn, len(rows), "rows", len({x[0][:10] for x in rows}), "days")
