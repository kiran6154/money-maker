"""Study: which rainbow-ribbon intraday variant to make Strategies 29 (1-minute) and 30 (5-minute). Pre-registered in
STRATEGY_ANALYSIS_TODO S53 before any number was seen: the grid, the selection window, the rule.

Grid (48 variants per timeframe): ribbon kind (widner 10 x SMA(2) | ema 5/8/13/21/34/55) x trigger (cross | pullback,
5 bars) x fan (full | none) x osc_min (0 | 25, lookback 10) x exits (band: strategy exit, band stop + band exit;
s9: managed 1R/2R scale-out + trail 3R-1, stop 50; trail: managed all-lot trail 3R-2, stop 50). Fixed: 3 lots, one
position per contract, entries 09:20-14:30, square-off 15:25, near-month futures, lab costs (5-pt slippage, Zerodha).

Selection: Jan 5 - Jun 30 2026 (in sample) picks, Jul 1 - Sep 25 2026 (out of sample) is reported and never used to
pick. Rule: the variant with the highest in-sample net among those with >= 30 in-sample POSITIONS (distinct entries, not
lot exits: a managed position closes as up to three records) and PF > 1 (a PF of None with a positive net - no losing
lot - counts as > 1); ties on net go to the higher PF, then to grid order; if none qualifies, the highest in-sample net
is reported with that said. One run per variant over the whole window; the two halves are its positions split by entry
date. What the halves share: the ribbon's state and the EMA seed (the widner lines depend on their last few closes
only); no position spans the boundary (square-off 15:25). The in-sample half holds 100 sessions, the out-of-sample 62,
and the in-sample half has a hole: no May 2026 contract in the futures file (Apr 28 -> May 29, see README Data).
Lab stats count lot exits ('trades'); this study adds 'positions' to each half.

    python studies/rainbow_grid.py                 # both timeframes; writes studies/rainbow_grid.json, prints the tables
    python studies/rainbow_grid.py --tf 5minute
Nothing here writes to the lab's results, database or strategy files.
"""
import copy, itertools, json, os, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)
import engine, lab, rainbow  # noqa: E402

_load, _run, _memo = engine.load, engine.run, {}
def load(path, a, b, w):
    key = ("load", path, a, b, w)
    if key not in _memo: _memo[key] = _load(path, a, b, w)
    return _memo[key]
def run(bars, p):
    key = ("run", id(bars), json.dumps(p, sort_keys=True))
    if key not in _memo: _memo[key] = _run(bars, p)
    return _memo[key]
engine.load, engine.run = load, run

FROM, SPLIT, TO = "2026-01-05", "2026-07-01", "2026-09-25"
MIN_TRADES, WARMUP = 30, 2
RB = dict(lookback=10, pullback_bars=5, entry_from="09:20", entry_until="14:30")
KINDS = {"widner": dict(kind="widner", levels=10, period=2), "ema": dict(kind="ema", periods=[5, 8, 13, 21, 34, 55])}
POS = {"band": (dict(lots=3, lock="strike", exit="strategy", stop={"futures_pts": 50, "option_pct": 5}, scale_out=[], trail=None,
                     square_off="15:25", reverse=None), "band"),
       "s9": (dict(lots=3, lock="strike", exit="position", stop={"futures_pts": 50, "option_pct": 5},
                   scale_out=[{"lots": 1, "target_r": 1}, {"lots": 1, "target_r": 2}], trail={"start_r": 3, "lag_r": 1},
                   square_off="15:25", reverse=None), "none"),
       "trail": (dict(lots=3, lock="strike", exit="position", stop={"futures_pts": 50, "option_pct": 5}, scale_out=[],
                      trail={"start_r": 3, "lag_r": 2}, square_off="15:25", reverse=None), "none")}
GRID = [dict(kind=k, trigger=tr, fan=f, osc_min=om, exits=ex) for k, tr, f, om, ex in
        itertools.product(KINDS, ("cross", "pullback"), ("full", "none"), (0, 25), POS)]
CHARGES = json.load(open(lab.CHARGECFG, encoding="utf-8"))
BASE = dict(next(sp for _, sp in lab.load_strategies() if sp["code"] == "ST9"))


def spec_of(v):
    sp = copy.deepcopy(BASE)
    sp["rules"] = dict(sp["rules"], entry_rule="rainbow_v1")
    sp["rainbow"] = dict(KINDS[v["kind"]], trigger=v["trigger"], fan=v["fan"], osc_min=v["osc_min"], exit=POS[v["exits"]][1], **RB)
    sp["position"] = POS[v["exits"]][0]
    return sp


def one(v, tf):
    sp = spec_of(v)
    row = next(x for x in lab.type_rows(sp) if x["variant"] == "FUT")
    st = dict(row, timeframe=tf, data_file=lab.tf_file("fut", tf), spot_file=lab.tf_file("spot", tf), positions="BOTH", underlying="FUT",
              date_from=FROM, date_to=TO, period="study", warmup_days=WARMUP)
    cs = dict(CHARGES[st["charge_code"]], code=st["charge_code"])
    res = rainbow.run_variant(st, cs)["-"]
    trs = res["trades"]
    def part(a, b):
        xs = [x for x in trs if a <= x["entry_time"][:10] < b]
        return dict(lab.stats(xs), positions=len({(x["entry_time"], x["position"]) for x in xs}))
    return dict(v, tf=tf, IS=part(FROM, SPLIT), OOS=part(SPLIT, "2099-01-01"), ALL=lab.stats(trs), signals=res["rainbow"]["signals"],
                locked=res["rainbow"]["locked"], exit_reasons=res["rainbow"]["exits"])


def label(v):
    return f"{v['kind']:<6} {v['trigger']:<8} fan={v['fan']:<4} osc>={v['osc_min']:<2} {v['exits']:<5}"


def fmt(s):
    return f"{s['positions']:>4} pos {s['trades']:>4} lots  {s['net_inr']:>+11,.0f}  PF {s['pf'] if s['pf'] is None else round(s['pf'], 2)!s:>5}  t {s['t_stat'] if s['t_stat'] is None else round(s['t_stat'], 2)!s:>6}"


def pick(rows):
    good_pf = lambda s: (s["pf"] is None and s["net_inr"] > 0) or (s["pf"] or 0) > 1
    ok = [r for r in rows if r["IS"]["positions"] >= MIN_TRADES and good_pf(r["IS"])]
    pool, qualified = (ok, True) if ok else (rows, False)
    best = max(enumerate(pool), key=lambda kv: (kv[1]["IS"]["net_inr"], kv[1]["IS"]["pf"] if kv[1]["IS"]["pf"] is not None else float("inf"), -kv[0]))[1]
    rank_oos = 1 + sum(1 for r in rows if r["OOS"]["net_inr"] > best["OOS"]["net_inr"])
    return best, qualified, rank_oos


def main():
    tfs = ["minute", "5minute"]
    if "--tf" in sys.argv: tfs = [sys.argv[sys.argv.index("--tf") + 1]]
    out = {}
    for tf in tfs:
        t0 = time.time(); rows = []
        for k, v in enumerate(GRID):
            rows.append(one(v, tf))
            print(f"\r{tf}: {k + 1}/{len(GRID)} {label(v)} IS {fmt(rows[-1]['IS'])}   OOS {fmt(rows[-1]['OOS'])}", flush=True)
        best, qualified, rank = pick(rows)
        print(f"\n== {tf}: {len(rows)} variants in {time.time() - t0:.0f}s; in-sample {FROM}..{SPLIT} picks, out-of-sample {SPLIT}..{TO} reports ==")
        for r in sorted(rows, key=lambda r: -r["IS"]["net_inr"]):
            mark = " <== pick" if r is best else ""
            print(f"{label(r)}  IS {fmt(r['IS'])}   OOS {fmt(r['OOS'])}   locked {r['locked']:>4}{mark}")
        print(f"pick ({'qualified: >= ' + str(MIN_TRADES) + ' IS positions and PF > 1' if qualified else 'NO variant qualified (>= ' + str(MIN_TRADES) + ' IS positions and PF > 1); the highest IS net is shown'}): "
              f"{label(best)} -> OOS {fmt(best['OOS'])}; its OOS rank among the {len(rows)} variants: {rank}")
        out[tf] = dict(window=dict(from_=FROM, split=SPLIT, to=TO), rule=f">= {MIN_TRADES} IS positions (distinct entries), PF > 1 (None with net > 0 counts), highest IS net; ties: higher PF, then grid order",
                       sessions=dict(IS=sum(1 for s in lab.sessions() if FROM <= s < SPLIT), OOS=sum(1 for s in lab.sessions() if SPLIT <= s <= TO)),
                       pick=dict(best, qualified=qualified, oos_rank=rank), rows=rows)
    json.dump(out, open(os.path.join(HERE, "studies", "rainbow_grid.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
    print("wrote studies/rainbow_grid.json")


if __name__ == "__main__":
    main()
