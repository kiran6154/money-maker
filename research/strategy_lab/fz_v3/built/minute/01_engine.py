"""FZ v3 data build, 1-minute, stage 1: Foundation engine over the WHOLE 5-year near-month futures file.

Reads the file through engine.load (never lab.sessions(), which drops sessions before config history_from), asserts the
first bar is 2021-10-01 and the last 2026-09-25, runs engine.run with Strategy 1's rules (break_mode touch, choch_mode
touch, avwap_weight volume, sl_rule prev_swing), prices every Foundation trade at lot 65 with lab.trade_charges
(ZERODHA_NFO_FUT) and 5 pts slippage per side (lab.price_trade's arithmetic restated), MFE / MAE from the bars
(lab.excursion's definition restated), and writes:
  bars.csv       one row per bar: session index, bar-in-session, time of day, OHLCV, fm_na, atr14, protected level
  sessions.csv   one row per session: date, bar range, front_month (last row of the day, as lab.fm_by_day), contract, split
  swings.csv     engine swings (kind, bar, price, confirmation bar) + the FINAL-STATE broken flag (look-ahead, diagnostic)
  events.csv     CHoCH and BOS events with dir, flip, level, avwap, trend, anchor swings; end (CHoCH) = next CHoCH bar (look-ahead)
  setups.csv     every Foundation SETUP (bar, dir, CHoCH bar) and whether the engine traded it
  trades.csv     every Foundation trade priced (pts, slippage, gross, charges, net, win, exit reason, MFE / MAE)
  skipped.csv    SETUPs the engine skipped (stop on the wrong side of the entry)
  r_slim.pkl     the engine output fields fz_exec.view / opener / build_trades read (sw, setups, chs, prot, trades)
  timing_01.json run times and peak RSS
Read-only on the repository. Everything is written under this folder.
"""
import sys, os, csv, json, time, pickle, types, gc
import psutil

LAB = r"D:\office\stocks\workspace\money-maker\research\strategy_lab"
OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import engine, lab   # noqa: E402  (lab: trade_charges, atr_series; its module body only reads config files)

LOT, SLIP, ATR_N = 65, 5.0, 14
DATE_FROM, DATE_TO = "2021-10-01", "2026-09-25"
IS_END = "2025-12-31"            # IS = sessions <= IS_END, OOS = after (pre-registered in FZ_V3_STUDY_BRIEF.md)
RULES = dict(break_mode="touch", choch_mode="touch", avwap_weight="volume", sl_rule="prev_swing",
             entry_rule="setup_v1", exit_rule="next_choch")
CS = json.load(open(os.path.join(LAB, "config", "charges.json"), encoding="utf-8"))["ZERODHA_NFO_FUT"]
FUT1 = json.load(open(os.path.join(LAB, "config", "data.json"), encoding="utf-8"))["futures"]["minute"]

timing = {}
proc = psutil.Process()
def rss(): return round(proc.memory_info().rss / 1e6, 1)
def peak(): return round(proc.memory_info().peak_wset / 1e6, 1)

# ---------------------------------------------------------------- load (whole file, warm-up 0)
t0 = time.time()
bars, s0 = engine.load(FUT1, DATE_FROM, DATE_TO, 0)
gc.collect()
t, o, h, l, c, v = (bars[k] for k in "tohlcv")
n = len(t)
assert s0 == 0, f"s0 = {s0}, expected 0 (whole file)"
assert t[0][:10] == DATE_FROM, f"first bar {t[0]} is not {DATE_FROM}"
assert t[-1][:10] == DATE_TO, f"last bar {t[-1]} is not {DATE_TO}"
assert all(t[i] < t[i + 1] for i in range(n - 1)), "bars are not strictly time-ordered"
timing["load_s"] = round(time.time() - t0, 1); timing["rss_after_load_mb"] = rss(); timing["peak_after_load_mb"] = peak()
print(f"loaded {n} bars {t[0]} .. {t[-1]} in {timing['load_s']}s, rss {rss()} MB, peak {peak()} MB", flush=True)

# ---------------------------------------------------------------- front_month / contract per session (streamed, no dicts)
t0 = time.time()
fm_day, contract_day, mixed = {}, {}, set()
with open(FUT1, newline="") as f:
    rd = csv.reader(f); hdr = next(rd); ix = {k: i for i, k in enumerate(hdr)}
    for row in rd:
        d = row[ix["datetime"]][:10]
        fm = int(float(row[ix["front_month"]] or 0))
        if d in fm_day and fm_day[d] != fm: mixed.add(d)
        fm_day[d] = fm                                   # last row of the day wins, exactly as lab.fm_by_day
        contract_day[d] = (row[ix["contract"]], row[ix["expiry"]])
timing["front_month_s"] = round(time.time() - t0, 1)
print(f"front_month per session: {len(fm_day)} sessions, {sum(fm_day.values())} front-month, mixed days {len(mixed)}", flush=True)

# ---------------------------------------------------------------- sessions, session bar, atr14, fm_na
sess, sbar = [0] * n, [0] * n
for i in range(1, n):
    if t[i][:10] != t[i - 1][:10]: sess[i], sbar[i] = sess[i - 1] + 1, 0
    else: sess[i], sbar[i] = sess[i - 1], sbar[i - 1] + 1
atr14 = lab.atr_series(types.SimpleNamespace(t=t, h=h, l=l, c=c), ATR_N)
fm_na = [fm_day.get(x[:10], 0) == 0 or vv == 0 for x, vv in zip(t, v)]

# ---------------------------------------------------------------- engine
t0 = time.time()
r = engine.run(bars, RULES)
timing["engine_run_s"] = round(time.time() - t0, 1); timing["rss_after_engine_mb"] = rss(); timing["peak_after_engine_mb"] = peak()
print(f"engine.run: {len(r['sw'])} swings, {len(r['events'])} events ({len(r['chs'])} CHoCH), {len(r['setups'])} setups, "
      f"{len(r['trades'])} trades, {len(r['skipped'])} skipped, in {timing['engine_run_s']}s, rss {rss()} MB", flush=True)

# ---------------------------------------------------------------- writers
def W(name, cols, rows):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for row in rows: w.writerow(row)

def fmt(x):
    """CSV cell: floats in repr (exact round trip), bools as 0/1, None empty."""
    if x is None: return ""
    if isinstance(x, bool): return int(x)
    return repr(x) if isinstance(x, float) else x

# bars.csv
t0 = time.time()
prot = r["prot"]
W("bars.csv", ["bar_i", "datetime", "date", "tod", "session_i", "session_bar", "open", "high", "low", "close", "volume",
               "fm_na", "atr14", "prot"],
  ([i, t[i], t[i][:10], t[i][11:16], sess[i], sbar[i], fmt(o[i]), fmt(h[i]), fmt(l[i]), fmt(c[i]), fmt(v[i]),
    int(fm_na[i]), fmt(atr14[i]), fmt(prot[i])] for i in range(n)))

# sessions.csv
first = {}; last = {}
for i in range(n):
    first.setdefault(sess[i], i); last[sess[i]] = i
srows = []
for k in sorted(first):
    d = t[first[k]][:10]
    srows.append([k, d, first[k], last[k], last[k] - first[k] + 1, fm_day.get(d, 0), contract_day[d][0], contract_day[d][1],
                  "IS" if d <= IS_END else "OOS", int(d in mixed)])
W("sessions.csv", ["session_i", "date", "first_bar", "last_bar", "n_bars", "front_month", "contract", "expiry", "split",
                   "front_month_mixed"], srows)

# swings.csv
W("swings.csv", ["swing_i", "kind", "bar", "bar_time", "price", "conf", "conf_time", "broken_final"],
  ([j, s["k"], s["bar"], t[s["bar"]], fmt(s["p"]), s["conf"], t[s["conf"]], int(s["broken"])] for j, s in enumerate(r["sw"])))

# events.csv (engine order preserved: within a bar, BOS is appended before CHoCH)
erows = []
for j, e in enumerate(r["events"]):
    if e["kind"] == "CHoCH":
        erows.append([j, e["i"], t[e["i"]], "CHoCH", e["dir"], int(e["flip"]), fmt(e["lvl"]), fmt(e["av"]), e["tr"],
                      e["hi"] and e["hi"]["bar"], e["hi"] and fmt(e["hi"]["p"]), e["lo"] and e["lo"]["bar"],
                      e["lo"] and fmt(e["lo"]["p"]), e.get("end"), e["sw"]["bar"], e["sw"]["k"]])
    else:
        erows.append([j, e["i"], t[e["i"]], "BOS", e["dir"], "", "", "", "", "", "", "", "", "", "", ""])
W("events.csv", ["event_i", "i", "time", "kind", "dir", "flip", "lvl", "av", "tr", "hi_bar", "hi_p", "lo_bar", "lo_p",
                 "end", "prot_swing_bar", "prot_swing_kind"], erows)

# trades priced: lab.price_trade restated (LONG: buy = entry + slip, sell = exit - slip; SHORT: sell = entry - slip,
# buy = exit + slip; pts after slippage = sell - buy; gross = pts x lot; charges on buy / sell x lot; net = gross - charges)
def price(x):
    e, px, up = c[x["entry"]], x["exit_px"], x["dir"] == "up"
    if up: buy, sell = e + SLIP, px - SLIP
    else: sell, buy = e - SLIP, px + SLIP
    pts_s = sell - buy
    chg = lab.trade_charges(CS, buy, sell, LOT)
    gross = pts_s * LOT
    return pts_s, gross, chg["total"], gross - chg["total"]

def excursion(x):
    """lab.excursion restated on bar indices: candles after the entry candle up to and including the exit candle,
    before slippage; MFE >= 0, MAE <= 0, in points; plus the bar offsets at which they occur."""
    i0, i1, e, up = x["entry"] + 1, x["exit"], c[x["entry"]], x["dir"] == "up"
    if i1 < i0: return 0.0, 0.0, 0, 0
    hs, ls = h[i0:i1 + 1], l[i0:i1 + 1]
    if up:
        jh = max(range(len(hs)), key=hs.__getitem__); jl = min(range(len(ls)), key=ls.__getitem__)
        fav, adv, jf, ja = hs[jh] - e, ls[jl] - e, jh + 1, jl + 1
    else:
        jl = min(range(len(ls)), key=ls.__getitem__); jh = max(range(len(hs)), key=hs.__getitem__)
        fav, adv, jf, ja = e - ls[jl], e - hs[jh], jl + 1, jh + 1
    return round(max(fav, 0.0), 2), round(min(adv, 0.0), 2), jf, ja

trows, nums = [], []
by_entry = {}
for j, x in enumerate(r["trades"]):
    pts_s, gross, chg, net = price(x)
    nums.append((t[x["entry"]][:10], net, x["pts"], chg))
    mfe, mae, jf, ja = excursion(x)
    up = x["dir"] == "up"
    sl_dist = (c[x["entry"]] - x["sl"]) if up else (x["sl"] - c[x["entry"]])
    trows.append([j, x["entry"], t[x["entry"]], x["exit"], t[x["exit"]], x["dir"], x["choch"], t[x["choch"]],
                  fmt(x["sl"]), fmt(round(sl_dist, 2)), fmt(c[x["entry"]]), fmt(x["exit_px"]), fmt(round(x["pts"], 2)),
                  x["exit_reason"], int(x["open"]), x["exit"] - x["entry"], mfe, mae, jf, ja, fmt(round(pts_s, 2)),
                  fmt(round(gross, 2)), fmt(round(chg, 2)), fmt(round(net, 2)), int(net > 0), int(x["pts"] > 0)])
    by_entry[x["entry"]] = j
W("trades.csv", ["trade_i", "entry", "entry_time", "exit", "exit_time", "dir", "choch", "choch_time", "sl", "sl_dist_pts",
                 "entry_px", "exit_px", "pts", "exit_reason", "open", "bars_held", "mfe", "mae", "mfe_bar", "mae_bar",
                 "slip_pts", "gross", "charges", "net", "win", "win_pts"], trows)

skipped = {x["entry"]: x for x in r["skipped"]}
W("skipped.csv", ["entry", "time", "dir", "sl"], ([x["entry"], t[x["entry"]], x["dir"], fmt(x["sl"])] for x in r["skipped"]))

W("setups.csv", ["setup_i", "time", "dir", "ch", "ch_time", "traded", "trade_i", "skipped_wrong_side_stop"],
  ([x["i"], t[x["i"]], x["dir"], x["ch"], t[x["ch"]], int(x["i"] in by_entry), by_entry.get(x["i"], ""),
    int(x["i"] in skipped)] for x in r["setups"]))

# r_slim.pkl: exactly the fields fz_exec.view / opener / build_trades read
slim = dict(sw=[dict(k=s["k"], bar=s["bar"], p=s["p"], conf=s["conf"]) for s in r["sw"]],
            setups=[dict(i=x["i"], dir=x["dir"], ch=x["ch"]) for x in r["setups"]],
            chs=[dict(i=e["i"], dir=e["dir"], lvl=e["lvl"]) for e in r["chs"]],
            prot=list(r["prot"]), trades=[dict(x) for x in r["trades"]])
with open(os.path.join(OUT, "r_slim.pkl"), "wb") as f: pickle.dump(slim, f, protocol=4)
timing["write_s"] = round(time.time() - t0, 1)

# ---------------------------------------------------------------- summary
by_split = {}
for day, net, pts, chg in nums:          # numeric copies (trows holds the CSV cells, floats as repr strings)
    sp = "IS" if day <= IS_END else "OOS"
    d = by_split.setdefault(sp, dict(n=0, net=0.0, wins=0, pts=0.0, charges=0.0))
    d["n"] += 1; d["net"] += net; d["wins"] += int(net > 0); d["pts"] += pts; d["charges"] += chg
timing.update(bars=n, sessions=len(first), swings=len(r["sw"]), events=len(r["events"]), choch=len(r["chs"]),
              bos=len(r["events"]) - len(r["chs"]), setups=len(r["setups"]), trades=len(r["trades"]),
              skipped=len(r["skipped"]), front_month_mixed_days=sorted(mixed), fm_na_bars=sum(fm_na),
              by_split={k: dict(v, net=round(v["net"], 2), pts=round(v["pts"], 2), charges=round(v["charges"], 2),
                                mean_cost_inr=round(v["charges"] / v["n"] + 2 * SLIP * LOT, 2) if v["n"] else None)
                        for k, v in by_split.items()},
              peak_rss_mb=peak(), rss_end_mb=rss(), rules=RULES, lot=LOT, slippage_pts_per_side=SLIP, charges=CS,
              date_from=DATE_FROM, date_to=DATE_TO, is_end=IS_END, file=FUT1)
json.dump(timing, open(os.path.join(OUT, "timing_01.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in timing.items() if k not in ("charges", "rules")}, indent=1), flush=True)
