"""Writes timing_01.json from the stage-1 files (01_engine.py's in-script summary crashed after every data file was
written; the run times below are copied from its console log, see log in the build notes)."""
import os, csv, json
OUT = os.path.dirname(os.path.abspath(__file__))
IS_END, LOT, SLIP = "2025-12-31", 65, 5.0
P = lambda n: os.path.join(OUT, n)
by_split = {}
n_tr = 0
for r in csv.DictReader(open(P("trades.csv"), newline="")):
    n_tr += 1
    sp = "IS" if r["entry_time"][:10] <= IS_END else "OOS"
    d = by_split.setdefault(sp, dict(n=0, net=0.0, wins=0, pts=0.0, charges=0.0, stop_loss=0, next_choch=0, open=0))
    d["n"] += 1; d["net"] += float(r["net"]); d["wins"] += int(r["win"]); d["pts"] += float(r["pts"]); d["charges"] += float(r["charges"])
    d[r["exit_reason"]] += 1
for d in by_split.values():
    d.update(net=round(d["net"], 2), pts=round(d["pts"], 2), charges=round(d["charges"], 2),
             mean_net=round(d["net"] / d["n"], 2), win_rate=round(d["wins"] / d["n"], 4),
             mean_cost_inr=round(d["charges"] / d["n"] + 2 * SLIP * LOT, 2))
fm_na = 0; n_bars = 0
for r in csv.DictReader(open(P("bars.csv"), newline="")):
    n_bars += 1; fm_na += int(r["fm_na"])
sess = list(csv.DictReader(open(P("sessions.csv"), newline="")))
sw = sum(1 for _ in open(P("swings.csv"))) - 1
ev = list(csv.DictReader(open(P("events.csv"), newline="")))
setups = sum(1 for _ in open(P("setups.csv"))) - 1
skipped = sum(1 for _ in open(P("skipped.csv"))) - 1
timing = dict(load_s=17.0, rss_after_load_mb=532.3, peak_after_load_mb=571.4, engine_run_s=958.0, rss_after_engine_mb=143.2,
              bars=n_bars, sessions=len(sess), swings=sw, events=len(ev), choch=sum(1 for e in ev if e["kind"] == "CHoCH"),
              bos=sum(1 for e in ev if e["kind"] == "BOS"), setups=setups, trades=n_tr, skipped=skipped,
              front_month_mixed_days=[s["date"] for s in sess if s["front_month_mixed"] == "1"],
              sessions_not_front_month=[s["date"] for s in sess if s["front_month"] != "1"], fm_na_bars=fm_na,
              by_split=by_split, is_sessions=sum(1 for s in sess if s["split"] == "IS"),
              oos_sessions=sum(1 for s in sess if s["split"] == "OOS"), lot=LOT, slippage_pts_per_side=SLIP,
              rules=dict(break_mode="touch", choch_mode="touch", avwap_weight="volume", sl_rule="prev_swing",
                         entry_rule="setup_v1", exit_rule="next_choch"),
              date_from="2021-10-01", date_to="2026-09-25", is_end=IS_END,
              note="run times and RSS copied from 01_engine.py's console log; its in-script summary crashed (string cells) "
                   "after all data files were written, fixed in the script afterwards; counts here are re-read from the files")
json.dump(timing, open(P("timing_01.json"), "w"), indent=1)
print(json.dumps(timing, indent=1))
