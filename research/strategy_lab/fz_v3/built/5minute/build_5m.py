"""FZ v3 study, data build for the 5-minute timeframe (ST2 Foundation rules + ST8 fz block).

Read-only on the repository: imports engine / fz / fz_exec / lab from research/strategy_lab with bytecode writing off,
reads the 5-minute near-month futures file in full through engine.load (never lab.sessions(), which drops sessions
before config/data.json history_from), and writes every table to this folder (CSV + parquet).

Every feature in features.csv uses bars <= the SETUP bar only; forward returns and trade outcomes are labels.
See README.md (written by this script) for every column and its look-ahead status.
"""
import sys, os, json, csv, time, hashlib, datetime as D, statistics, types
sys.dont_write_bytecode = True                       # never write __pycache__ into the repository
LAB = r"D:\office\stocks\workspace\money-maker\research\strategy_lab"
OUT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import engine, fz, fz_exec, lab                      # lab: trade_charges + atr_series only (import is side-effect free)
import pandas as pd

T0 = time.time()
TIMES = {}
def lap(name):
    TIMES[name] = round(time.time() - T0, 2); print(f"[{TIMES[name]:8.2f}s] {name}", flush=True)

TF = "5minute"; TF_MIN = 5
FIRST, LAST = "2021-10-01", "2026-09-25"
IS_END = "2025-12-31"                                # IS = sessions <= IS_END; OOS = after
LOT = 65
SLIP = 5.0                                           # points per side (ST2 / ST8 types.FUT.slippage_pts)
WARMUP_SESSIONS = 5                                  # ST2 / ST8 warmup_days (flagged, not dropped)
RULES = dict(break_mode="touch", choch_mode="touch", avwap_weight="volume", sl_rule="choch_candle")   # ST2 rules
data_cfg = json.load(open(os.path.join(LAB, "config", "data.json"), encoding="utf-8"))
PATH = data_cfg["futures"][TF]
charges = json.load(open(os.path.join(LAB, "config", "charges.json"), encoding="utf-8"))["ZERODHA_NFO_FUT"]
st8 = json.load(open(os.path.join(LAB, "strategies", "strategy_8.json"), encoding="utf-8"))
st2 = json.load(open(os.path.join(LAB, "strategies", "strategy_2.json"), encoding="utf-8"))
assert st2["rules"]["sl_rule"] == "choch_candle" and st2["rules"]["break_mode"] == "touch"
assert st8["types"]["FUT"]["slippage_pts"] == SLIP and st2["lot_size"] == LOT
cfg = fz.thresholds(st8["fz"][TF])
ATR_N = st8["options"]["atr_period"]

def sha(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()[:16]

# ---------------------------------------------------------------- 1. bars (full file, no lab.sessions())
fut, s0 = engine.load(PATH, FIRST, LAST, 0)
assert s0 == 0, f"s0 = {s0}, expected 0 (no warm-up cut)"
assert fut["t"][0][:10] == FIRST, f"first bar {fut['t'][0]} is not {FIRST}"
assert fut["t"][-1][:10] == LAST, f"last bar {fut['t'][-1]} is not {LAST}"
# --truncate "YYYY-MM-DD HH:MM:SS": causality check, the same build on the bars up to that time only (into a subfolder).
# Every as-of column of a SETUP at bar <= the cut must come out identical; only the labels / post-SETUP columns may differ.
TRUNC = sys.argv[sys.argv.index("--truncate") + 1] if "--truncate" in sys.argv else None
if TRUNC:
    keep = sum(1 for x in fut["t"] if x <= TRUNC)
    fut = {k: fut[k][:keep] for k in "tohlcv"}
    OUT = os.path.join(OUT, "trunc_" + TRUNC.replace("-", "").replace(":", "").replace(" ", "_")); os.makedirs(OUT, exist_ok=True)
    print(f"TRUNCATED at {TRUNC}: {keep} bars -> {OUT}", flush=True)
t, o, h, l, c, v = (fut[k] for k in "tohlcv")
n = len(t)
# the extra CSV columns (oi, contract, expiry, front_month), aligned by datetime
extra = list(csv.DictReader(open(PATH)))[:n]
assert len(extra) == n and all(r["datetime"] == x for r, x in zip(extra, t)), "CSV rows do not align with engine.load"
oi = [float(r.get("oi") or 0) for r in extra]
contract = [r["contract"] for r in extra]
expiry = [r["expiry"] for r in extra]
front_month = [int(float(r.get("front_month") or 0)) for r in extra]
del extra
sess, sbar = [0] * n, [0] * n
for i in range(1, n):
    if t[i][:10] != t[i - 1][:10]: sess[i], sbar[i] = sess[i - 1] + 1, 0
    else: sess[i], sbar[i] = sess[i - 1], sbar[i - 1] + 1
days = sorted({x[:10] for x in t})
day_of_sess = {sess[i]: t[i][:10] for i in range(n)}
fm_na = [front_month[i] == 0 or v[i] == 0 for i in range(n)]
atr14 = lab.atr_series(types.SimpleNamespace(t=t, h=h, l=l, c=c), ATR_N)
print(f"bars {n}, sessions {len(days)}, first {t[0]}, last {t[-1]}, front_month==0 bars {sum(1 for x in front_month if x == 0)}, "
      f"zero-volume bars {sum(1 for x in v if x == 0)}, fm_na bars {sum(fm_na)}", flush=True)
lap("load")

# ---------------------------------------------------------------- 2. engine (ST2 rules)
r = engine.run(fut, RULES)
lap("engine.run")
sw, events, chs, prot, setups, trades, skipped = (r[k] for k in ("sw", "events", "chs", "prot", "setups", "trades", "skipped"))
print(f"swings {len(sw)}, events {len(events)} (CHoCH {len(chs)}, BOS {len(events) - len(chs)}), setups {len(setups)}, "
      f"trades {len(trades)}, engine-skipped {len(skipped)}", flush=True)

# ---------------------------------------------------------------- 3. Foundation trade pricing (lab.price_trade mirrored)
def price(entry, exit_, exit_px, up):
    """Slippage 5 pts per side, charges lab.trade_charges(ZERODHA_NFO_FUT) on the slipped prices, lot 65.
    Returns dict(gross_inr, charges_inr, slip_inr, cost_inr, net_inr) with net_inr == pts x 65 - cost_inr."""
    e = c[entry]
    if up: buy, sell = e + SLIP, exit_px - SLIP
    else: sell, buy = e - SLIP, exit_px + SLIP
    chg = lab.trade_charges(charges, buy, sell, LOT)
    gross = (sell - buy) * LOT                       # after slippage, as lab's gross
    slip = 2 * SLIP * LOT
    return dict(gross_inr=round(gross, 2), charges_inr=round(chg["total"], 2), slip_inr=slip,
                cost_inr=round(chg["total"] + slip, 2), net_inr=round(gross - chg["total"], 2))

def excursion(entry, exit_, up):
    """Max favourable / adverse move between the entry close and the exit bar (bars entry+1..exit, wicks), in points."""
    e = c[entry]
    if exit_ <= entry: return 0.0, 0.0
    hi_, lo_ = max(h[entry + 1:exit_ + 1]), min(l[entry + 1:exit_ + 1])
    return (round(hi_ - e, 2), round(e - lo_, 2)) if up else (round(e - lo_, 2), round(hi_ - e, 2))

def trade_row(x):
    up = x["dir"] == "up"
    pr = price(x["entry"], x["exit"], x["exit_px"], up)
    mfe, mae = excursion(x["entry"], x["exit"], up)
    pts = round(x["pts"], 2)
    assert abs(pts * LOT - pr["cost_inr"] - pr["net_inr"]) < 0.05, "net != pts x lot - cost"
    return dict(entry_i=x["entry"], entry_time=t[x["entry"]], date=t[x["entry"]][:10], session_idx=sess[x["entry"]],
                dir=x["dir"], choch_i=x["choch"], choch_time=t[x["choch"]], entry_px=c[x["entry"]], sl=x["sl"],
                exit_i=x["exit"], exit_time=t[x["exit"]], exit_px=x["exit_px"], exit_reason=x["exit_reason"],
                open=bool(x["open"]), pts=pts, pts_x_lot=round(pts * LOT, 2), **pr, win=pr["net_inr"] > 0,
                bars_held=x["exit"] - x["entry"], sessions_held=sess[x["exit"]] - sess[x["entry"]],
                crosses_roll=contract[x["entry"]] != contract[x["exit"]], contract=contract[x["entry"]],
                mfe_pts=mfe, mae_pts=mae, split="IS" if t[x["entry"]][:10] <= IS_END else "OOS",
                in_warmup=sess[x["entry"]] < WARMUP_SESSIONS)
trade_rows = [trade_row(x) for x in trades]
lap("price trades")

# ---------------------------------------------------------------- 4. FZ (ST8 fz block), memory from bar 0, ledger from s0 = 0
bars = dict(fut, fm_na=fm_na, atr14=atr14)
view = fz_exec.view(r)
touch = RULES["break_mode"] == "touch"
out = fz.run(bars, view, cfg, TF_MIN, s0, fz_exec.opener(bars, r, RULES["sl_rule"], touch))
lap("fz.run")
fz_trades = fz_exec.build_trades(bars, r, out, RULES["sl_rule"], touch)
lap("fz build_trades")
card, ledger, zones, watches, stats = out["card"], out["ledger"], out["zones"], out["watches"], out["stats"]
assert len(card) == n and len(ledger) == len(setups), "card / ledger sizes"
print(f"fz: zones {len(zones)}, ledger {len(ledger)}, watches {len(watches)}, positions {len(fz_trades)} "
      f"(TAKE {sum(1 for x in fz_trades if x['gate'] == 'TAKE')}, REENTER {sum(1 for x in fz_trades if x['gate'] == 'REENTER')})", flush=True)

def fz_trade_row(x):
    up = x["dir"] == "up"
    pr = price(x["entry"], x["exit"], x["exit_px"], up)
    mfe, mae = excursion(x["entry"], x["exit"], up)
    pts = round(x["pts"], 2)
    return dict(gate=x["gate"], setup_i=x.get("setup_i", x["entry"]), entry_i=x["entry"], entry_time=t[x["entry"]],
                date=t[x["entry"]][:10], session_idx=sess[x["entry"]], dir=x["dir"], choch_i=x["choch"],
                entry_px=c[x["entry"]], sl=x["sl"], exit_i=x["exit"], exit_time=t[x["exit"]], exit_px=x["exit_px"],
                exit_reason=x["exit_reason"], open=bool(x["open"]), pts=pts, pts_x_lot=round(pts * LOT, 2), **pr,
                win=pr["net_inr"] > 0, bars_held=x["exit"] - x["entry"], zone_id=x.get("zone_id"),
                fill_used=x.get("fill_used"), reenter_reason=x.get("reenter_reason"), sl_bar=x.get("sl_bar"),
                sl_in_band=x.get("sl_in_band"), mfe_pts=mfe, mae_pts=mae,
                split="IS" if t[x["entry"]][:10] <= IS_END else "OOS", in_warmup=sess[x["entry"]] < WARMUP_SESSIONS)
fz_trade_rows = [fz_trade_row(x) for x in fz_trades]

# ---------------------------------------------------------------- 5. per-SETUP feature table (bars <= k only)
import bisect
ev_i = [e["i"] for e in events]                      # events in bar order (BOS before CHoCH on the same bar)
ch_by_i = {e["i"]: e for e in chs}
sw_conf = [s["conf"] for s in sw]                    # confirmation order == list order
swH = [(s["conf"], s["p"], s["bar"]) for s in sw if s["k"] == "H"]
swL = [(s["conf"], s["p"], s["bar"]) for s in sw if s["k"] == "L"]
swH_conf, swL_conf = [x[0] for x in swH], [x[0] for x in swL]
trade_by_entry = {x["entry"]: x for x in trades}
trow_by_entry = {x["entry_i"]: x for x in trade_rows}
skipped_by_entry = {x["entry"]: x for x in skipped}
fz_by_setup = {}
for x in fz_trade_rows: fz_by_setup.setdefault(x["setup_i"], x)
ledger_by_i = {row["i"]: row for row in ledger}
setups_by_sess = {}
for x in setups: setups_by_sess.setdefault(sess[x["i"]], []).append(x["i"])
trades_sorted_exit = sorted(trade_rows, key=lambda x: x["exit_i"])
sess_open_i = {}
for i in range(n):
    if sbar[i] == 0: sess_open_i[sess[i]] = i

def med(xs): return statistics.median(xs) if xs else None

def regime(k):
    """Event-structure regime as of bar k (events with i <= k, the SETUP's own CHoCH included)."""
    j = bisect.bisect_right(ev_i, k)
    E = events[:j]
    out_ = dict(n_events_asof=j)
    last_bos = next((e for e in reversed(E) if e["kind"] == "BOS"), None)
    last_ch = next((e for e in reversed(E) if e["kind"] == "CHoCH"), None)
    # CHoCHs since the last BOS (all CHoCHs when there is no BOS yet); BOS since the last CHoCH
    ib = max((q for q, e in enumerate(E) if e["kind"] == "BOS"), default=-1)
    ic = max((q for q, e in enumerate(E) if e["kind"] == "CHoCH"), default=-1)
    out_["n_choch_since_bos"] = sum(1 for e in E[ib + 1:] if e["kind"] == "CHoCH")
    out_["n_bos_since_choch"] = sum(1 for e in E[ic + 1:] if e["kind"] == "BOS")
    out_["n_flip_choch_since_bos"] = sum(1 for e in E[ib + 1:] if e["kind"] == "CHoCH" and e.get("flip"))
    out_["bars_since_bos"] = (k - last_bos["i"]) if last_bos else None
    out_["last_bos_dir"] = last_bos["dir"] if last_bos else None
    out_["last_bos_same_session"] = (sess[last_bos["i"]] == sess[k]) if last_bos else None
    prev_ch = [e for e in E if e["kind"] == "CHoCH"]
    out_["bars_since_prev_choch"] = (k - prev_ch[-2]["i"]) if len(prev_ch) >= 2 else None
    out_["last_choch_dir"] = last_ch["dir"] if last_ch else None
    K = 6
    last_k = E[-K:]
    out_["alternations_last6"] = sum(1 for a, b in zip(last_k, last_k[1:]) if a["kind"] != b["kind"])
    out_["last6_kinds"] = "".join("C" if e["kind"] == "CHoCH" else "B" for e in last_k)
    run_ = 0
    for e in reversed(E):
        if e["kind"] == "CHoCH": run_ += 1
        else: break
    out_["choch_run"] = run_
    out_["n_events_last_36"] = sum(1 for e in E if k - e["i"] < 36)
    out_["n_choch_last_36"] = sum(1 for e in E if k - e["i"] < 36 and e["kind"] == "CHoCH")
    out_["n_events_today"] = sum(1 for e in E if sess[e["i"]] == sess[k])
    out_["n_choch_today"] = sum(1 for e in E if sess[e["i"]] == sess[k] and e["kind"] == "CHoCH")
    out_["n_bos_today"] = out_["n_events_today"] - out_["n_choch_today"]
    return out_

def volume_feats(k, up):
    v_prev20 = v[max(0, k - 20):k]; v_prev60 = v[max(0, k - 60):k]
    m20, m60 = med(v_prev20), med(v_prev60)
    f = dict(vol=v[k], vol_med20=m20, vol_med60=m60,
             vol_ratio20=(v[k] / m20) if m20 else None, vol_ratio60=(v[k] / m60) if m60 else None,
             vol_na=fm_na[k])
    # last visibly-high-volume bar this session before or at k: v[j] >= 3 x median of the previous 20 bars (>= 5 bars)
    hv = None
    j0 = sess_open_i[sess[k]]
    for j in range(k, j0 - 1, -1):
        base = v[max(0, j - 20):j]
        if len(base) >= 5 and not fm_na[j]:
            mb = med(base)
            if mb and v[j] >= 3 * mb: hv = j; break
    if hv is None:
        f.update(hv3_bars_since=None, hv3_dir=None, hv3_dir_agree=None, hv3_ratio=None, hv3_high_held=None, hv3_low_held=None)
    else:
        d = "up" if c[hv] > o[hv] else "down" if c[hv] < o[hv] else "flat"
        mb = med(v[max(0, hv - 20):hv])
        f.update(hv3_bars_since=k - hv, hv3_dir=d, hv3_dir_agree=(d == ("up" if up else "down")),
                 hv3_ratio=round(v[hv] / mb, 3),
                 hv3_high_held=all(h[j] <= h[hv] for j in range(hv + 1, k + 1)),      # bars after it up to k
                 hv3_low_held=all(l[j] >= l[hv] for j in range(hv + 1, k + 1)))
    # session volume so far vs the same bar count of the previous session (both known at k)
    j_prev = sess_open_i.get(sess[k] - 1)
    if j_prev is not None:
        cum = sum(v[j0:k + 1]); prev = sum(v[j_prev:min(j_prev + sbar[k] + 1, j0)])
        f["sess_vol_vs_prev_sess"] = round(cum / prev, 3) if prev else None
    else: f["sess_vol_vs_prev_sess"] = None
    return f

def level_feats(k, up, ch, lvl):
    sg = 1 if up else -1
    jH, jL = bisect.bisect_right(swH_conf, k) - 1, bisect.bisect_right(swL_conf, k) - 1
    shp, slp = (swH[jH][1] if jH >= 0 else None), (swL[jL][1] if jL >= 0 else None)
    p = prot[k]
    a = atr14[k] or None
    f = dict(prot_lvl=p, dist_prot_pts=round(sg * (c[k] - p), 2) if p is not None else None,
             dist_prot_atr=round(sg * (c[k] - p) / a, 3) if (p is not None and a) else None,
             last_sh_px=shp, last_sl_px=slp,
             dist_sh_pts=round(shp - c[k], 2) if shp is not None else None,      # + = swing high above the close
             dist_sl_pts=round(c[k] - slp, 2) if slp is not None else None,      # + = swing low below the close
             last_sh_bars_ago=(k - swH[jH][2]) if jH >= 0 else None, last_sl_bars_ago=(k - swL[jL][2]) if jL >= 0 else None,
             choch_lvl=lvl, dist_choch_lvl_pts=round(sg * (c[k] - lvl), 2) if lvl is not None else None,
             dist_choch_lvl_atr=round(sg * (c[k] - lvl) / a, 3) if (lvl is not None and a) else None,
             n_swings_last_36=sum(1 for s in sw if s["conf"] <= k and k - s["conf"] < 36),
             choch_bar_range=round(h[ch] - l[ch], 2), choch_bar_range_atr=round((h[ch] - l[ch]) / a, 3) if a else None,
             move_since_choch_pts=round(sg * (c[k] - c[ch]), 2))
    return f

def window_feats(k):
    a = atr14[k] or None
    j0 = sess_open_i[sess[k]]
    def rng(N):
        lo_i = max(0, k - N + 1)
        return round(max(h[lo_i:k + 1]) - min(l[lo_i:k + 1]), 2)
    r12, r36 = rng(12), rng(36)
    so = o[j0]; sh_, sl_ = max(h[j0:k + 1]), min(l[j0:k + 1])
    prev_close = c[j0 - 1] if j0 > 0 else None
    return dict(atr14=round(atr14[k], 3), range12_pts=r12, range12_atr=round(r12 / a, 3) if a else None,
                range36_pts=r36, range36_atr=round(r36 / a, 3) if a else None,
                bar_range_pts=round(h[k] - l[k], 2), bar_body_pts=round(c[k] - o[k], 2),
                bar_range_atr=round((h[k] - l[k]) / a, 3) if a else None,
                close_pos_in_bar=round((c[k] - l[k]) / (h[k] - l[k]), 3) if h[k] > l[k] else None,
                sess_open=so, close_vs_sess_open_pts=round(c[k] - so, 2),
                sess_range_sofar_pts=round(sh_ - sl_, 2), sess_range_sofar_atr=round((sh_ - sl_) / a, 3) if a else None,
                close_pos_in_sess_range=round((c[k] - sl_) / (sh_ - sl_), 3) if sh_ > sl_ else None,
                gap_pts=round(so - prev_close, 2) if prev_close is not None else None,
                prev_close=prev_close, ret_6_pts=round(c[k] - c[k - 6], 2) if k >= 6 else None,
                ret_12_pts=round(c[k] - c[k - 12], 2) if k >= 12 else None,
                ret_36_pts=round(c[k] - c[k - 36], 2) if k >= 36 else None)

def asof_today(k):
    """Foundation trades of this session already closed by bar k (exit <= k): known at k's close."""
    closed = [x for x in trade_rows if x["session_idx"] == sess[k] and x["exit_i"] <= k and x["entry_i"] < k]
    return dict(today_n_closed_asof=len(closed), today_net_asof=round(sum(x["net_inr"] for x in closed), 2),
                today_n_stops_asof=sum(1 for x in closed if x["exit_reason"] == "stop_loss"),
                today_n_setups_before=sum(1 for i in setups_by_sess[sess[k]] if i < k),
                last_closed_net_asof=closed[-1]["net_inr"] if closed else None,
                last_closed_reason_asof=closed[-1]["exit_reason"] if closed else None)

CARD_KEYS = ("out_run", "out_side", "wick_depth", "cluster_sit", "prev_bars", "prev_vol", "last_leave_failed", "touches",
             "last_hunt_at", "last_hunt_dir", "last_reject_at", "last_reject_dir", "leave_side", "first_clock_lived")
LEDGER_ASOF = ("zone_id", "zone_kind", "band_lo", "band_hi", "visit_n", "this_bars", "this_vol", "first_bars", "first_vol",
               "vol_na", "first_vol_na", "read", "left_id", "in_id", "level_in_band", "gate", "block_reason", "branch",
               "take_why", "entered_zone_id", "entered_visit_n", "entered_read", "leave_vol_ok", "leave_kind",
               "watch_kind", "watch_band_id")
LEDGER_POST = ("outcome_gate", "refused", "watch_outcome", "reenter_reason", "fill_used", "fill_bar", "fill_delay_bars",
               "edge_dist_pts", "armed_bars", "rearmed_bars", "sl_bar")

feat_rows = []
for x in setups:
    k, up, ch = x["i"], x["dir"] == "up", x["ch"]
    e = ch_by_i[ch]
    lvl = e["lvl"]
    sg = 1 if up else -1
    row = dict(setup_i=k, time=t[k], date=t[k][:10], session_idx=sess[k], session_bar=sbar[k], hhmm=t[k][11:16],
               hour=int(t[k][11:13]), minute_of_session=sbar[k] * TF_MIN, dow=D.date.fromisoformat(t[k][:10]).weekday(),
               dir=x["dir"], choch_i=ch, choch_time=t[ch], bars_since_choch=k - ch, choch_flip=bool(e.get("flip")),
               choch_trend_before=e["tr"], choch_same_session=sess[ch] == sess[k],
               open=o[k], high=h[k], low=l[k], close=c[k], contract=contract[k],
               days_to_expiry=(D.date.fromisoformat(expiry[k]) - D.date.fromisoformat(t[k][:10])).days,
               split="IS" if t[k][:10] <= IS_END else "OOS", in_warmup=sess[k] < WARMUP_SESSIONS)
    # Foundation stop (known at the SETUP close)
    sl = l[ch] if up else h[ch]
    row.update(sl=sl, sl_dist_pts=round(sg * (c[k] - sl), 2),
               sl_dist_atr=round(sg * (c[k] - sl) / atr14[k], 3) if atr14[k] else None,
               engine_skipped=k in skipped_by_entry)
    row.update(window_feats(k)); row.update(regime(k)); row.update(volume_feats(k, up)); row.update(level_feats(k, up, ch, lvl))
    row.update(asof_today(k))
    # FZ card (as of bar k) and ledger
    cd = card[k]
    row.update({"card_" + kk: cd[kk] for kk in CARD_KEYS})
    L = ledger_by_i[k]
    row.update({"fz_" + kk: L[kk] for kk in LEDGER_ASOF})
    row.update({"fzpost_" + kk: L[kk] for kk in LEDGER_POST})
    lo_, hi_ = L["band_lo"], L["band_hi"]
    if lo_ is not None and hi_ is not None and hi_ > lo_:
        row.update(fz_band_width=round(hi_ - lo_, 2), fz_pos_in_band=round((c[k] - lo_) / (hi_ - lo_), 3),
                   fz_dist_band_edge_ahead=round((hi_ - c[k]) if up else (c[k] - lo_), 2),
                   fz_dist_band_edge_behind=round((c[k] - lo_) if up else (hi_ - c[k]), 2))
    else:
        row.update(fz_band_width=None, fz_pos_in_band=None, fz_dist_band_edge_ahead=None, fz_dist_band_edge_behind=None)
    # ---- labels (forward-looking) ----
    for N in (5, 15, 30):
        row[f"fwd_ret_{N}_pts"] = round(c[k + N] - c[k], 2) if k + N < n else None
        row[f"fwd_ret_{N}_dir_pts"] = round(sg * (c[k + N] - c[k]), 2) if k + N < n else None
    tr = trow_by_entry.get(k)
    if tr is not None:
        row.update(fnd_traded=True, fnd_exit_i=tr["exit_i"], fnd_exit_time=tr["exit_time"], fnd_exit_px=tr["exit_px"],
                   fnd_exit_reason=tr["exit_reason"], fnd_open=tr["open"], fnd_pts=tr["pts"], fnd_gross_inr=tr["gross_inr"],
                   fnd_charges_inr=tr["charges_inr"], fnd_slip_inr=tr["slip_inr"], fnd_cost_inr=tr["cost_inr"],
                   fnd_net_inr=tr["net_inr"], fnd_win=tr["win"], fnd_bars_held=tr["bars_held"],
                   fnd_sessions_held=tr["sessions_held"], fnd_crosses_roll=tr["crosses_roll"],
                   fnd_mfe_pts=tr["mfe_pts"], fnd_mae_pts=tr["mae_pts"])
    else:
        row.update(fnd_traded=False, fnd_exit_i=None, fnd_exit_time=None, fnd_exit_px=None, fnd_exit_reason=None,
                   fnd_open=None, fnd_pts=None, fnd_gross_inr=None, fnd_charges_inr=None, fnd_slip_inr=None,
                   fnd_cost_inr=None, fnd_net_inr=None, fnd_win=None, fnd_bars_held=None, fnd_sessions_held=None,
                   fnd_crosses_roll=None, fnd_mfe_pts=None, fnd_mae_pts=None)
    fzx = fz_by_setup.get(k)
    if fzx is not None:
        row.update(fzpos_kind=fzx["gate"], fzpos_entry_i=fzx["entry_i"], fzpos_entry_time=fzx["entry_time"],
                   fzpos_exit_i=fzx["exit_i"], fzpos_exit_time=fzx["exit_time"], fzpos_exit_reason=fzx["exit_reason"],
                   fzpos_pts=fzx["pts"], fzpos_net_inr=fzx["net_inr"])
    else:
        row.update(fzpos_kind=None, fzpos_entry_i=None, fzpos_entry_time=None, fzpos_exit_i=None, fzpos_exit_time=None,
                   fzpos_exit_reason=None, fzpos_pts=None, fzpos_net_inr=None)
    feat_rows.append(row)
lap("features")

# ---------------------------------------------------------------- 6. write everything
def write(name, rows, cols=None):
    df = pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT, name + ".csv"), index=False)
    try: df.to_parquet(os.path.join(OUT, name + ".parquet"), index=False)
    except Exception as ex: print(f"parquet {name}: {ex}")
    print(f"  wrote {name}: {len(df)} rows x {len(df.columns)} cols", flush=True)
    return df

bar_rows = [dict(i=i, datetime=t[i], date=t[i][:10], session_idx=sess[i], session_bar=sbar[i], open=o[i], high=h[i], low=l[i],
                 close=c[i], volume=v[i], oi=oi[i], contract=contract[i], expiry=expiry[i], front_month=front_month[i],
                 fm_na=fm_na[i], atr14=round(atr14[i], 4), prot=prot[i], split="IS" if t[i][:10] <= IS_END else "OOS",
                 in_warmup=sess[i] < WARMUP_SESSIONS) for i in range(n)]
write("bars", bar_rows); del bar_rows
nb = {}
for i in range(n): nb[sess[i]] = nb.get(sess[i], 0) + 1
write("sessions", [dict(session_idx=q, date=d, split="IS" if d <= IS_END else "OOS", in_warmup=q < WARMUP_SESSIONS,
                        n_bars=nb[q], front_month=front_month[sess_open_i[q]], contract=contract[sess_open_i[q]])
                   for q, d in enumerate(days)])
write("swings", [dict(seq=q, kind=s["k"], bar=s["bar"], time=t[s["bar"]], price=s["p"], conf_bar=s["conf"], conf_time=t[s["conf"]],
                      broken_final=s["broken"]) for q, s in enumerate(sw)])
write("events", [dict(seq=q, i=e["i"], time=t[e["i"]], kind=e["kind"], dir=e["dir"], flip=e.get("flip"), lvl=e.get("lvl"),
                      av=e.get("av"), trend_before=e.get("tr"), sh_bar=e["hi"]["bar"] if e.get("hi") else None,
                      sh_px=e["hi"]["p"] if e.get("hi") else None, sl_bar=e["lo"]["bar"] if e.get("lo") else None,
                      sl_px=e["lo"]["p"] if e.get("lo") else None, window_end=e.get("end"))
                 for q, e in enumerate(events)])
write("setups", [dict(setup_i=x["i"], time=t[x["i"]], dir=x["dir"], choch_i=x["ch"], choch_time=t[x["ch"]],
                      engine_skipped=x["i"] in skipped_by_entry) for x in setups])
write("skipped", [dict(entry_i=x["entry"], time=t[x["entry"]], dir=x["dir"], sl=x["sl"], close=c[x["entry"]]) for x in skipped])
write("trades", trade_rows)
write("fz_trades", fz_trade_rows)
write("fz_card", [dict(i=i, time=t[i], **{kk: cd[kk] for kk in cd}) for i, cd in enumerate(card)])
write("fz_ledger", [dict(**{kk: row[kk] for kk in row}) for row in ledger])
write("fz_zones", [dict(id=z["id"], kind=z["kind"], lo=z["lo"], hi=z["hi"], mid=z["mid"], origin_bar=z["origin_bar"],
                        birth_bar=z["birth_bar"], born_ts=z["born_ts"], merges=z["merges"], n_visits=len(z["visits"]),
                        touches=z["touches"], retired_bar=z["retired_bar"], retired_by=z["retired_by"],
                        retired_ts=t[z["retired_bar"]] if z["retired_bar"] is not None else None) for z in zones])
write("fz_visits", [dict(zone_id=z["id"], visit_n=V["n"], start=V["start"], start_time=t[V["start"]], end=V["end"],
                         end_time=t[V["end"]] if V["end"] is not None else None, ended_by=V["ended_by"], bars=V["bars"],
                         vol=V["vol"], vol_na=V["vol_na"], entry_dir=V["entry_dir"], touch=bool(V.get("touch")),
                         defend_dir=V.get("defend_dir")) for z in zones for V in z["visits"]])
write("fz_watches", [dict(**w, opened_time=t[w["opened_at"]], outcome_time=t[w["outcome_bar"]] if w["outcome_bar"] is not None else None)
                     for w in watches])
feat_df = write("features", feat_rows)
json.dump(stats, open(os.path.join(OUT, "fz_stats.json"), "w"), indent=1)
lap("write")

# ---------------------------------------------------------------- 7. counts + meta
def book(rows):
    nets = [x["net_inr"] for x in rows]
    return dict(n=len(rows), net_inr=round(sum(nets), 2), mean_net_inr=round(sum(nets) / len(nets), 2) if nets else None,
                wins=sum(1 for x in rows if x["win"]), pts=round(sum(x["pts"] for x in rows), 2),
                open_at_end=sum(1 for x in rows if x["open"]),
                exit_reasons={k_: sum(1 for x in rows if x["exit_reason"] == k_) for k_ in ("next_choch", "stop_loss", "open")},
                median_cost_inr=med([x["cost_inr"] for x in rows]))
counts = {}
for sp in ("IS", "OOS", "ALL"):
    F = [x for x in feat_rows if sp == "ALL" or x["split"] == sp]
    TR = [x for x in trade_rows if sp == "ALL" or x["split"] == sp]
    FT = [x for x in fz_trade_rows if sp == "ALL" or x["split"] == sp]
    counts[sp] = dict(sessions=sum(1 for d in days if sp == "ALL" or (d <= IS_END) == (sp == "IS")),
                      bars=sum(1 for i in range(n) if sp == "ALL" or (t[i][:10] <= IS_END) == (sp == "IS")),
                      setups=len(F), engine_skipped=sum(1 for x in F if x["engine_skipped"]),
                      foundation=book(TR),
                      gate_at_setup={g: sum(1 for x in F if x["fz_gate"] == g) for g in ("TAKE", "WATCH", "BLOCK", "REENTER")},
                      outcome_gate={g: sum(1 for x in F if x["fzpost_outcome_gate"] == g) for g in ("TAKE", "WATCH", "BLOCK", "REENTER")},
                      fz_positions=dict(TAKE=sum(1 for x in FT if x["gate"] == "TAKE"), REENTER=sum(1 for x in FT if x["gate"] == "REENTER"),
                                        book=book(FT)),
                      block_reasons={}, reads={})
    for x in F:
        if x["fz_gate"] == "BLOCK": counts[sp]["block_reasons"][x["fz_block_reason"]] = counts[sp]["block_reasons"].get(x["fz_block_reason"], 0) + 1
        counts[sp]["reads"][x["fz_read"]] = counts[sp]["reads"].get(x["fz_read"], 0) + 1
TIMES["total"] = round(time.time() - T0, 2)
meta = dict(timeframe=TF, tf_min=TF_MIN, data_file=PATH, data_sha1_16=sha(PATH), first_bar=t[0], last_bar=t[-1], bars=n,
            sessions=len(days), is_window=[FIRST, IS_END], oos_window=["2026-01-01", LAST], warmup_sessions_flagged=WARMUP_SESSIONS,
            engine_rules=RULES, engine_source="strategies/strategy_2.json rules (ST2)", fz_block_source="strategies/strategy_8.json fz.5minute (ST8)",
            fz_cfg=cfg, lot=LOT, slippage_pts_per_side=SLIP, charge_code="ZERODHA_NFO_FUT", charges=charges, atr_period=ATR_N,
            code_sha1_16={f: sha(os.path.join(LAB, f)) for f in ("engine.py", "fz.py", "fz_exec.py", "fz_report.py", "lab.py")},
            script_sha1_16=sha(os.path.abspath(__file__)), built_at=D.datetime.now().isoformat(timespec="seconds"),
            python=sys.version.split()[0], pandas=pd.__version__, run_times_s=TIMES, counts=counts)
json.dump(meta, open(os.path.join(OUT, "meta.json"), "w"), indent=1, default=str)
json.dump(TIMES, open(os.path.join(OUT, "run_times.json"), "w"), indent=1)
print(json.dumps(counts, indent=1, default=str))
print("columns:", list(feat_df.columns))
print("done", TIMES)
