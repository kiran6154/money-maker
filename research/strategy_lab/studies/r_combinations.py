"""Study: exit combinations for the managed-exit strategies (Strategy 9 = 1-minute, Strategy 10 = 5-minute entries), on
near-month futures. Question from the user (2026-09-29): hold longer (positional), reverse once / keep reversing, other R
combinations - which, if any, work?

Every variant uses the same entries (the engine's SETUPs are computed once per timeframe and reused); only the position
block changes. Costs as in the strategy files (5 pts slippage per side, Zerodha futures charges, lot 65). Windows: the last
three months and the whole history in use (config/data.json history_from: 2026 only, Jan - Sep 2026; the May 2026
contract is missing, see README Data).

    python studies/r_combinations.py            # writes studies/r_combinations.json and prints the table
    python studies/r_combinations.py --tf 15minute --code ST10   # Strategy 10's rules on 15-minute candles
Nothing here writes to the lab's results, database or strategy files.
"""
import copy, json, os, sys, time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.chdir(HERE)
import engine, lab

# the engine's result depends only on the candles and the rules; memoise it so every variant reuses one run per window
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

BASE = {"lots": 3, "lock": "strike", "exit": "position", "stop": {"futures_pts": 50, "option_pct": 5},
        "scale_out": [{"lots": 1, "target_r": 1}, {"lots": 1, "target_r": 2}], "trail": {"start_r": 3, "lag_r": 1},
        "square_off": "15:25", "reverse": None}
def V(name, **kw):
    p = copy.deepcopy(BASE); p.update(kw); return name, p
REV1, REV3, REVN = ({"trigger": "initial_stop", "max": n} for n in (1, 3, 20))
VARIANTS = [
    V("base: 1R/2R/trail 3R-1, intraday"),
    V("reverse once", reverse=REV1),
    V("reverse up to 3", reverse=REV3),
    V("keep reversing", reverse=REVN),
    V("positional", square_off=None),
    V("positional + reverse once", square_off=None, reverse=REV1),
    V("positional + keep reversing", square_off=None, reverse=REVN),
    V("targets 2R/4R", scale_out=[{"lots": 1, "target_r": 2}, {"lots": 1, "target_r": 4}], trail={"start_r": 4, "lag_r": 1}),
    V("targets 1R/3R, trail 4R-1", scale_out=[{"lots": 1, "target_r": 1}, {"lots": 1, "target_r": 3}], trail={"start_r": 4, "lag_r": 1}),
    V("wider trail 3R-2", trail={"start_r": 3, "lag_r": 2}),
    V("early trail 2R-1", trail={"start_r": 2, "lag_r": 1}),
    V("no scale-out, trail 2R-1", scale_out=[], trail={"start_r": 2, "lag_r": 1}),
    V("positional, targets 2R/4R, trail 4R-2", square_off=None, scale_out=[{"lots": 1, "target_r": 2}, {"lots": 1, "target_r": 4}], trail={"start_r": 4, "lag_r": 2}),
    V("positional, no scale-out, trail 3R-2", square_off=None, scale_out=[], trail={"start_r": 3, "lag_r": 2}),
    V("stop 75 pts", stop={"futures_pts": 75, "option_pct": 5}),
    V("stop 35 pts", stop={"futures_pts": 35, "option_pct": 5}),
    V("positional, stop 75, trail 3R-2", square_off=None, stop={"futures_pts": 75, "option_pct": 5}, trail={"start_r": 3, "lag_r": 2}),
]
CHARGES = json.load(open(lab.CHARGECFG, encoding="utf-8"))
SPECS = dict((sp["code"], sp) for _, sp in lab.load_strategies())


def one(code, pos, frm, to, tf):
    row = next(x for x in lab.type_rows(SPECS[code]) if x["variant"] == "FUT")
    st = dict(row, position_json=json.dumps(pos, sort_keys=True), timeframe=tf, data_file=lab.tf_file("fut", tf),
              spot_file=lab.tf_file("spot", tf), signal_file=lab.tf_file("fut", tf), date_from=frm, date_to=to, period="study",
              underlying="FUT", positions="BOTH")
    r = lab.run_variant(st, dict(CHARGES[row["charge_code"]], code=row["charge_code"]))["-"]
    T = r["trades"]; s = lab.stats(T)
    by = {}
    for x in T: by[x["entry_time"][:4]] = by.get(x["entry_time"][:4], 0) + x["net"]
    return dict(net=round(s["net_inr"]), lot_exits=s["trades"], positions=len({(x["entry_time"], x["position"]) for x in T}),
                pf=s["pf"], t=s["t_stat"], max_dd=round(s["max_dd_inr"]), locked=sum("locked" in str(k.get("why", "")) for k in r["skipped"]),
                reversal_lots=sum(1 for x in T if x.get("reversal")), by_year={k: round(v) for k, v in sorted(by.items())})


def main():
    ss = lab.sessions()
    windows = {"2026": (ss[2], ss[-1]), "3M": (lab.resolve_backtest(dict(kind="preset", preset="3M"), 2)[0], ss[-1])}
    out = {"windows": windows, "variants": [n for n, _ in VARIANTS], "results": {}}
    runs = (("ST9", "minute"), ("ST10", "5minute"))
    if "--tf" in sys.argv:                     # e.g. --tf 15minute --code ST10: one strategy's entries on other candles
        runs = ((sys.argv[sys.argv.index("--code") + 1] if "--code" in sys.argv else "ST10", sys.argv[sys.argv.index("--tf") + 1]),)
    tag = "" if "--tf" not in sys.argv else "_" + runs[0][1]
    for code, tf in runs:
        for wname, (frm, to) in windows.items():
            for name, pos in VARIANTS:
                t0 = time.time(); res = one(code, pos, frm, to, tf)
                out["results"].setdefault(code, {}).setdefault(wname, {})[name] = res
                print(f"{code} {wname} {name:<42} net {res['net']:>+12,}  pos {res['positions']:>5}  PF {res['pf']}  t {res['t']}  "
                      f"DD {res['max_dd']:>+11,}  rev {res['reversal_lots']:>4}  ({time.time() - t0:.0f}s)", flush=True)
                json.dump(out, open(os.path.join(HERE, "studies", f"r_combinations{tag}.json"), "w"), indent=1)
            _memo.clear()                      # free the window's candles before the next one


if __name__ == "__main__":
    main()
