"""The learner (entry_rule rl_v1): the family module behind ST19-ST24 (v1 rl.py).

A contextual bandit over the Foundation SETUPs (linear Thompson sampling): at each SETUP it skips or picks an exit profile x
stop x lots from SPEC["rl"], and learns from every action's outcome once its exit candle has closed. It learns once over
the whole futures file; each backtest is a window cut from that run, scored beside a base book, random books, matched
permutations, a seed spread and the oracle (see rl_lib/lib_rl.py's docstring - the learner is v1's rl.py, copied, with its
lab / engine calls going to rl_lib/rl_lab.py (v1 lab functions, copied) and rl_lib/rl_engine.py (v2's engine)).
Futures only, on the futures' own candles; each exit profile carries its own square-off (a backtest cannot override it).
"""
import json, os, sys
import core

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "rl_lib"))
import lib_rl as rl          # v1's rl.py, copied (a unique name: v1's `rl` may be loaded in the same process)

ENTRY_RULES = rl.RULES
TYPES, UNDERLYINGS, TIMEFRAMES = ("FUT",), ("FUT",), ("minute", "5minute")
REFUSED_WHY = rl.FUT_WHY
TF_WHY = "the learner reads the 1-minute or 5-minute futures file whole"
FIXED_HOLDING = rl.SQUARE_OFF_WHY            # a backtest's square-off override is refused with this reason


def signals(bars, spec):
    """Foundation on these candles (the chart); the learner's trades come from run()."""
    return core.foundation(bars, spec["rules"])


def _row(ctx):
    """The v1 strategy row rl.py reads."""
    spec, r = ctx["spec"], ctx["spec"]["rules"]
    return dict(code=spec["code"], variant="FUT", underlying="FUT", timeframe=ctx["tf"],
                data_file=core.FUT1 if ctx["tf"] == "minute" else core.FUT5,
                rl_json=json.dumps(spec["rl"], ensure_ascii=False), position_json=json.dumps(core.position_of(spec), sort_keys=True),
                lot_size=spec["lot_size"], slippage_pts=ctx["slippage_pts"], atr_period=spec["options"]["atr_period"],
                break_mode=r["break_mode"], choch_mode=r.get("choch_mode") or r["break_mode"], avwap_weight=r["avwap_weight"],
                sl_rule=r["sl_rule"], date_from=ctx["date_from"], date_to=ctx["date_to"])


def run(ctx):
    """{'-': dict(trades, skipped, signals, rl)} for the window, cut from the strategy's one learning run."""
    res = rl.run_variant(_row(ctx), ctx["charges"])["-"]
    T = lambda s: core.ts(s) if isinstance(s, str) and len(s) == 19 else s
    trades = [dict(x, entry_time=T(x["entry_time"]), exit_time=T(x["exit_time"]), choch_time=T(x["choch_time"]),
                   label=x["position"] + (f" · {x['tranche']}" if x.get("tranche") else ""), scan=x.get("arm", ""))
              for x in res["trades"]]
    signals = [dict(g, time=T(g["time"]), setup=T(g.get("setup")), hi=g["hi"] and (T(g["hi"][0]), g["hi"][1]),
                    lo=g["lo"] and (T(g["lo"][0]), g["lo"][1])) for g in res["signals"]]
    out = dict(trades=trades, skipped=res["skipped"], signals=signals)
    if res.get("rl"): out["rl"] = res["rl"]
    return {"-": out}
