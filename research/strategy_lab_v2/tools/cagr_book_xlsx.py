"""results/cagr_book/*.csv (written by tools/cagr_book.py) -> one Excel workbook: every trade with its entry and exit, sorted by
entry time, then the weekly shorts, the monthly longs, the weeks and the rules on their own sheets.

    python tools/cagr_book_xlsx.py        -> results/cagr_book/cagr_book_trades.xlsx
"""
import os, sys, csv
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.join(HERE, "tools"))
import xlsx_lite

D = os.path.join(HERE, "results", "cagr_book")
rd = lambda f: list(csv.DictReader(open(os.path.join(D, f), encoding="utf-8-sig")))
num = lambda v: float(v) if v not in ("", None) else None
W, M, WK = rd("weekly_short_trades.csv"), rd("monthly_long_trades.csv"), rd("weeks_summary.csv")

trades = []
for r in W:
    trades.append(dict(entry=r["sell_time"], exit=r["buy_back_time"], leg="Weekly short", week=r["week"], action="SELL then BUY back", inst=r["instrument"],
                       exp=r["expiry"], k=int(r["strike"]), typ=r["type"], lots=int(r["lots"]), qty=int(r["qty"]), ep=num(r["sell_price"]), xp=num(r["buy_back_price"]),
                       why=r["exit_reason"], resold=r["re_sold_after_stop"], pts=num(r["points_per_unit_after_slippage"]), gross=num(r["gross_rs"]),
                       chg=num(r["charges_rs"]), net=num(r["net_rs"])))
for r in M:
    trades.append(dict(entry=r["buy_time"], exit=r["sell_time"], leg="Monthly long (hedge)", week="", action="BUY then SELL", inst=r["instrument"],
                       exp=r["expiry"], k=int(r["strike"]), typ=r["type"], lots=int(r["lots"]), qty=int(r["qty"]), ep=num(r["buy_price"]), xp=num(r["sell_price"]),
                       why=r["exit_reason"], resold="", pts=num(r["points_per_unit_after_slippage"]), gross=num(r["gross_rs"]),
                       chg=num(r["charges_rs"]), net=num(r["net_rs"])))
trades.sort(key=lambda t: (t["entry"], t["leg"] != "Monthly long (hedge)", t["k"]))
cum = 0.0; rows = []
for i, t in enumerate(trades, 1):
    cum += t["net"]
    rows.append([i, t["entry"], t["exit"], t["leg"], t["week"], t["action"], t["inst"], t["exp"], t["k"], t["typ"], t["lots"], t["qty"], t["ep"], t["xp"],
                 t["why"], t["resold"], t["pts"], t["gross"], t["chg"], t["net"], round(cum, 2)])
H = ["#", "Entry time", "Exit time", "Leg", "Week", "Action", "Instrument", "Expiry", "Strike", "Type", "Lots", "Qty", "Entry price", "Exit price",
     "Exit reason", "Re-sold after stop", "Points (after slippage)", "Gross ₹", "Charges ₹", "Net ₹", "Cumulative net ₹"]
WID = [5, 17, 17, 20, 7, 18, 24, 11, 8, 6, 5, 6, 11, 11, 18, 10, 12, 12, 10, 12, 14]
FMT = [None] * 12 + ["0.00", "0.00", None, None, "0.00", "#,##0.00", "#,##0.00", "#,##0.00", "#,##0.00"]
sn = sum(t["net"] for t in trades if t["leg"] == "Weekly short"); ln = sum(t["net"] for t in trades if t["leg"] != "Weekly short")
rows += [[], ["", "", "", "Weekly shorts", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", round(sn, 2)],
         ["", "", "", "Monthly longs", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", round(ln, 2)],
         ["", "", "", "Total", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", round(sn + ln, 2)]]

def sheet_of(recs, cols):
    h = list(recs[0].keys()) if recs else cols
    return h, [[num(v) if (v and k not in ("week", "instrument", "expiry", "type", "exit_reason", "sell_time", "buy_back_time", "buy_time", "sell_time", "week_entry",
                                               "entry", "exit", "side", "re_sold_after_stop", "first_sold_expiry", "shorts_sold", "long_held_at_entry",
                                               "last_sold_expiry", "shorts_bought_back", "skipped") and v.replace(".", "", 1).replace("-", "", 1).isdigit()) else v
                for k, v in r.items()] for r in recs]

wh, wr_ = sheet_of(sorted(W, key=lambda r: r["sell_time"]), [])
mh, mr = sheet_of(sorted(M, key=lambda r: r["buy_time"]), [])
kh, kr = sheet_of(WK, [])
rules = [[l] for l in open(os.path.join(D, "README.txt"), encoding="utf-8").read().splitlines()]
out = os.path.join(D, "cagr_book_trades.xlsx")
xlsx_lite.write(out, [("Trades by entry", H, rows, WID, FMT),
                      ("Weekly shorts", wh, wr_, [14] * len(wh), None),
                      ("Monthly longs", mh, mr, [14] * len(mh), None),
                      ("Weeks", kh, kr, [14] * len(kh), None),
                      ("Rules", ["Rules and notes"], rules, [140], None)])
print(out, len(trades), "trades", f"shorts {sn:+,.0f} longs {ln:+,.0f} total {sn + ln:+,.0f}")
