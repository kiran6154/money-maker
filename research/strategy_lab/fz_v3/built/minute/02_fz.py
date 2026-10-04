"""FZ v3 data build, 1-minute, stage 2: the ST7 room card and gate (fz.run) over the whole 5-year file.

Reloads the bars exactly as stage 1 did (engine.load, whole file, warm-up 0, same assertions), rebuilds fm_na from
sessions.csv (front_month == 0 or volume == 0, as lab.run_fz) and atr14 with lab.atr_series, takes the frozen engine
view from r_slim.pkl (fz_exec.view), the thresholds from strategies/strategy_7.json (fz.thresholds on the 'minute'
block), the position callback from fz_exec.opener (Strategy 1 stop rule prev_swing, touch mode) and runs fz.run with
s0 = 0 (memory from the first bar, ledger over every SETUP). Then writes:
  card.csv        one row per bar: every card field as of that bar (fz.py never rewrites a card row)
  ledger.csv      one row per Foundation SETUP: the card columns fz.py copies, the gate as of the SETUP bar and the
                  post-SETUP outcome columns (outcome_gate, fill_*, watch_outcome ... : look-ahead, diagnostic only)
  zones.csv       every room ever born (edges, birth / retirement bars, merges, touches)
  visits.csv      every stay of every room (start, end, ended_by, bars, vol, vol_na, entry_dir, touch, defend_dir)
  watches.csv     the watch log
  decisions.csv   every position fz.run opened (TAKE / REENTER) with the pinned band snapshot
  fz_trades.csv   fz_exec.build_trades: the ST7 positions in engine shape, priced like trades.csv
  fz_stats.json   fz.run's counters, run times, peak RSS, the thresholds used
The card is streamed to disk and freed before anything else is built, to keep the process under 1 GB.
"""
import sys, os, csv, json, time, pickle, types, gc
import psutil

LAB = r"D:\office\stocks\workspace\money-maker\research\strategy_lab"
OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import engine, lab, fz, fz_exec   # noqa: E402

LOT, SLIP, ATR_N, TF_MIN = 65, 5.0, 14, 1
DATE_FROM, DATE_TO = "2021-10-01", "2026-09-25"
SL_RULE, TOUCH = "prev_swing", True
CS = json.load(open(os.path.join(LAB, "config", "charges.json"), encoding="utf-8"))["ZERODHA_NFO_FUT"]
FUT1 = json.load(open(os.path.join(LAB, "config", "data.json"), encoding="utf-8"))["futures"]["minute"]
ST7 = json.load(open(os.path.join(LAB, "strategies", "strategy_7.json"), encoding="utf-8"))

timing = {}
proc = psutil.Process()
def rss(): return round(proc.memory_info().rss / 1e6, 1)
def peak(): return round(proc.memory_info().peak_wset / 1e6, 1)
def say(*a): print(time.strftime("%H:%M:%S"), *a, f"[rss {rss()} MB, peak {peak()} MB]", flush=True)

# ---------------------------------------------------------------- bars
# LEAN = True reads stage 1's bars.csv (engine.load's output written with repr, so the same floats bit for bit, plus the
# fm_na and atr14 stage 1 computed) with csv.reader: no per-row dicts, so the process peaks well under 1 GB. LEAN = False
# is the first run's path (engine.load again + lab.atr_series), which peaked at 1,021 MB working set because the load's
# transient row dicts leave pymalloc arenas the > 512-byte card dicts cannot reuse. Both produce identical outputs (md5
# checked, see fz_stats.json['lean_rerun']).
LEAN = "--engine-load" not in sys.argv
t0 = time.time()
if LEAN:
    t, o, h, l, c, v, fm_na, atr14 = [], [], [], [], [], [], [], []
    with open(os.path.join(OUT, "bars.csv"), newline="") as f:
        rd = csv.reader(f); hdr = next(rd); ix = {k: i for i, k in enumerate(hdr)}
        it, io, ih, il, ic, iv, ifm, ia = (ix[k] for k in ("datetime", "open", "high", "low", "close", "volume", "fm_na", "atr14"))
        for row in rd:
            t.append(row[it]); o.append(float(row[io])); h.append(float(row[ih])); l.append(float(row[il]))
            c.append(float(row[ic])); v.append(float(row[iv])); fm_na.append(row[ifm] == "1"); atr14.append(float(row[ia]))
    bars = dict(t=t, o=o, h=h, l=l, c=c, v=v, fm_na=fm_na, atr14=atr14); s0 = 0
else:
    bars, s0 = engine.load(FUT1, DATE_FROM, DATE_TO, 0)
    gc.collect()
    t, o, h, l, c, v = (bars[k] for k in "tohlcv")
    fm = {}
    with open(os.path.join(OUT, "sessions.csv"), newline="") as f:
        for row in csv.DictReader(f): fm[row["date"]] = int(row["front_month"])
    bars["fm_na"] = [fm.get(x[:10], 0) == 0 or vv == 0 for x, vv in zip(t, v)]
    bars["atr14"] = lab.atr_series(types.SimpleNamespace(t=t, h=h, l=l, c=c), ATR_N)
n = len(t)
assert s0 == 0 and t[0] == DATE_FROM + " 09:15:00" and t[-1] == DATE_TO + " 15:29:00", (s0, t[0], t[-1])
assert n == 443826, n
timing["load_s"] = round(time.time() - t0, 1); timing["lean_loader"] = LEAN
say(f"loaded {n} bars (lean={LEAN}), fm_na bars {sum(bars['fm_na'])}")

# ---------------------------------------------------------------- engine view + callback
with open(os.path.join(OUT, "r_slim.pkl"), "rb") as f: r = pickle.load(f)
assert len(r["prot"]) == n
view = fz_exec.view(r)
cfg = fz.thresholds(ST7["fz"]["minute"])
opener = fz_exec.opener(bars, r, SL_RULE, TOUCH)
say(f"view: {len(view['swings'])} swings, {len(view['setups'])} setups, {len(view['chs'])} CHoCH; cfg keys {len(cfg)}")

# ---------------------------------------------------------------- fz.run
t0 = time.time()
out = fz.run(bars, view, cfg, TF_MIN, 0, opener)
timing["fz_run_s"] = round(time.time() - t0, 1); timing["peak_after_fz_run_mb"] = peak()
say(f"fz.run done in {timing['fz_run_s']}s: {len(out['ledger'])} ledger rows, {len(out['zones'])} rooms, "
    f"{len(out['watches'])} watches, {len(out['decisions'])} positions")

def fmt(x):
    if x is None: return ""
    if isinstance(x, bool): return int(x)
    return repr(x) if isinstance(x, float) else x

def W(name, cols, rows):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for row in rows: w.writerow(row)

# ---------------------------------------------------------------- card (streamed, then freed)
t0 = time.time()
CARD_COLS = ["zone_id", "visit_n", "this_bars", "this_vol", "vol_na", "first_bars", "first_vol", "first_vol_na", "read",
             "left_id", "out_run", "out_side", "session_bar", "gap_pts", "wick_depth", "last_hunt_at", "last_hunt_dir",
             "last_reject_at", "last_reject_dir", "cluster_sit", "prev_bars", "prev_vol", "last_leave_failed", "in_id",
             "leave_side", "leave_vol_ok", "leave_kind", "first_clock_lived", "touches"]
card = out["card"]
assert len(card) == n
assert set(card[0]) == set(CARD_COLS), sorted(set(card[0]) ^ set(CARD_COLS))
with open(os.path.join(OUT, "card.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["bar_i", "datetime"] + CARD_COLS)
    for i in range(n):
        cd = card[i]
        w.writerow([i, t[i]] + [fmt(cd[k]) for k in CARD_COLS])
read_counts = {}
for cd in card: read_counts[cd["read"]] = read_counts.get(cd["read"], 0) + 1
out["card"] = None; del card; gc.collect()
timing["card_write_s"] = round(time.time() - t0, 1)
say(f"card.csv written; reads {read_counts}")

# ---------------------------------------------------------------- ledger
L = out["ledger"]
LEDGER_KEYS = ["i", "time", "dir", "choch_i", "zone_id", "zone_kind", "band_lo", "band_hi", "visit_n", "this_bars",
               "this_vol", "first_bars", "first_vol", "vol_na", "first_vol_na", "read", "left_id", "session_bar", "in_id",
               "level_in_band", "gate", "outcome_gate", "block_reason", "branch", "take_why", "refused",
               "entered_zone_id", "entered_visit_n", "entered_read", "leave_vol_ok", "leave_kind", "watch_kind",
               "watch_band_id", "watch_outcome", "reenter_reason", "fill_used", "fill_bar", "fill_delay_bars",
               "edge_dist_pts", "armed_bars", "rearmed_bars", "sl_bar"]
extra = sorted(set().union(*(set(x) for x in L)) - set(LEDGER_KEYS)) if L else []
cols = LEDGER_KEYS + extra
W("ledger.csv", cols + ["choch_time", "fill_time"],
  ([fmt(x.get(k)) for k in cols] + [t[x["choch_i"]], t[x["fill_bar"]] if x.get("fill_bar") is not None else ""] for x in L))
say(f"ledger.csv: {len(L)} rows, extra keys {extra}")

# ---------------------------------------------------------------- zones + visits
zrows, vrows = [], []
for z in out["zones"]:
    zrows.append([z["id"], z["kind"], fmt(z["lo"]), fmt(z["hi"]), fmt(z["mid"]), z["origin_bar"], z["birth_bar"], z["born_ts"],
                  z["merges"], len(z["visits"]), sum(1 for V in z["visits"] if not V.get("touch")), z["touches"],
                  fmt(z["retired_bar"]), z["retired_by"] or "",
                  t[z["retired_bar"]] if z["retired_bar"] is not None else ""])
    for V in z["visits"]:
        vrows.append([z["id"], V["n"], V["start"], t[V["start"]], fmt(V["end"]), t[V["end"]] if V["end"] is not None else "",
                      V["ended_by"] or "", V["bars"], fmt(V["vol"]), int(V["vol_na"]), V["entry_dir"] or "",
                      int(bool(V.get("touch"))), V.get("defend_dir") or ""])
W("zones.csv", ["zone_id", "kind", "lo", "hi", "mid", "origin_bar", "birth_bar", "born_ts", "merges", "n_stays", "n_visits",
                "touches", "retired_bar", "retired_by", "retired_time"], zrows)
W("visits.csv", ["zone_id", "visit_n", "start", "start_time", "end", "end_time", "ended_by", "bars", "vol", "vol_na",
                 "entry_dir", "touch", "defend_dir"], vrows)

# ---------------------------------------------------------------- watches + decisions
T = lambda i: "" if i is None else t[i]
W("watches.csv", ["opened_at", "opened_time", "band_id", "dir", "kind", "opened_by_read", "setup_i", "outcome",
                  "outcome_bar", "outcome_time", "armed_at", "last_armed_at"],
  ([w["opened_at"], t[w["opened_at"]], w["band_id"], w["dir"], w["kind"], w["opened_by_read"], w["setup_i"], w["outcome"],
    fmt(w["outcome_bar"]), T(w["outcome_bar"]), fmt(w["armed_at"]), fmt(w["last_armed_at"])] for w in out["watches"]))
W("decisions.csv", ["kind", "entry", "entry_time", "dir", "setup_i", "band_id", "band_lo", "band_hi", "band_mid",
                    "band_sit_mean", "band_vol_na"],
  ([k, e, t[e], d, si, b["id"], fmt(b["lo"]), fmt(b["hi"]), fmt(b["mid"]), fmt(b["sit_mean"]), int(b["vol_na"])]
   for k, e, d, si, b in out["decisions"]))

# ---------------------------------------------------------------- FZ trades (build_trades), priced like trades.csv
t0 = time.time()
fzt = fz_exec.build_trades(bars, r, out, SL_RULE, TOUCH)
def price(x):
    e, px, up = c[x["entry"]], x["exit_px"], x["dir"] == "up"
    if up: buy, sell = e + SLIP, px - SLIP
    else: sell, buy = e - SLIP, px + SLIP
    pts_s = sell - buy
    chg = lab.trade_charges(CS, buy, sell, LOT)
    return pts_s, pts_s * LOT, chg["total"], pts_s * LOT - chg["total"]
frows = []
for j, x in enumerate(fzt):
    pts_s, gross, chg, net = price(x)
    frows.append([j, x["gate"], x["entry"], t[x["entry"]], x["exit"], t[x["exit"]], x["dir"], x.get("choch"),
                  x.get("setup_i", x["entry"]), fmt(x["sl"]), fmt(c[x["entry"]]), fmt(x["exit_px"]), fmt(round(x["pts"], 2)),
                  x["exit_reason"], int(x["open"]), x["exit"] - x["entry"], x["zone_id"], x["fill_used"],
                  x.get("reenter_reason") or "", x.get("sl_bar") or "", fmt(x.get("sl_in_band")),
                  fmt(round(pts_s, 2)), fmt(round(gross, 2)), fmt(round(chg, 2)), fmt(round(net, 2)), int(net > 0)])
W("fz_trades.csv", ["fz_trade_i", "gate", "entry", "entry_time", "exit", "exit_time", "dir", "choch", "setup_i", "sl",
                    "entry_px", "exit_px", "pts", "exit_reason", "open", "bars_held", "zone_id", "fill_used",
                    "reenter_reason", "sl_bar", "sl_in_band", "slip_pts", "gross", "charges", "net", "win"], frows)
timing["build_trades_s"] = round(time.time() - t0, 1)
say(f"fz_trades.csv: {len(fzt)} positions ({sum(1 for x in fzt if x['gate'] == 'TAKE')} TAKE, "
    f"{sum(1 for x in fzt if x['gate'] == 'REENTER')} REENTER)")

# ---------------------------------------------------------------- stats
gates = {}
for x in L: gates[x["outcome_gate"]] = gates.get(x["outcome_gate"], 0) + 1
gates_at = {}
for x in L: gates_at[x["gate"]] = gates_at.get(x["gate"], 0) + 1
timing.update(bars=n, ledger_rows=len(L), rooms=len(out["zones"]), watches=len(out["watches"]),
              positions=len(out["decisions"]), gates_by_outcome=gates, gates_at_setup=gates_at, reads_per_bar=read_counts,
              peak_rss_mb=peak(), rss_end_mb=rss(), sl_rule=SL_RULE, touch=TOUCH, tf_min=TF_MIN, s0=0,
              strategy_file="strategies/strategy_7.json", thresholds=cfg, counters=out["stats"])
json.dump(timing, open(os.path.join(OUT, "fz_stats.json"), "w"), indent=1)
say("done")
print(json.dumps({k: v for k, v in timing.items() if k not in ("thresholds", "counters")}, indent=1), flush=True)
