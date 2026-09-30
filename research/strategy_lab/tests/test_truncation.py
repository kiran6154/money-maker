"""Look-ahead check: cutting the data at a random bar must not change any decision made before the cut.

    python tests/test_truncation.py

Engine cases: swings, events, SETUPs, closed trades and the protected level before each cut.
FZ cases (strategies 5 and 6, the band model, and 7 and 8, the room model; both futures files, CHoCH by touch, memory
from the file's first session and the lab's warm-ups 2 / 5 as the shown start): the zone card before the cut, the ledger's zone_id / read / gate / block_reason for
SETUPs before the cut, the watch log (opening, arming and outcome before the last bar) and the closed FZ positions.
Uniform cuts land mostly where nothing is live (Foundation 1m is dormant after 4 Sep), so FZ adds targeted cuts one to
five bars after SETUPs and inside WATCH / ARMED windows, and prints how many cuts had FZ state live across the cut.
The last bar of cut data cannot know that a position open there stays open: a gate the full run blocked there for
in_position is the one comparison skipped (the engine's own 'open at the data end' convention).
"""
import json, os, random, sys, types
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import engine, fz, fz_exec, lab

CASES = [("D:/nifty/niftyfut_5minute_2026-07-01_to_2026-09-25.csv", "choch_candle"),
         ("D:/nifty/niftyfut_minute_2026-07-01_to_2026-09-25.csv", "prev_swing"),
         ("D:/nifty/options/NIFTY_2026-09-29/5minute/NIFTY26SEP24000PE.csv", "choch_candle")]
P = dict(break_mode="touch", avwap_weight="volume")
FZ_CASES = [("minute", "strategy_5.json", 2), ("5minute", "strategy_6.json", 5),    # (timeframe, strategy file, warm-up)
            ("minute", "strategy_7.json", 2), ("5minute", "strategy_8.json", 5)]   # 7, 8: the room model (FZ v2)
FZ_UNIFORM, FZ_TARGETED = 12, 24                                                    # cuts per FZ case


def decisions(r, cut):
    sw = [(s["k"], s["bar"], s["p"], s["conf"]) for s in r["sw"] if s["conf"] < cut]
    ev = [(e["i"], e["kind"], e["dir"]) for e in r["events"] if e["i"] < cut]
    su = [(x["i"], x["dir"], x["ch"]) for x in r["setups"] if x["i"] < cut]
    tr = [(x["entry"], x["dir"], x["exit"], x["exit_px"], x["exit_reason"], x["sl"]) for x in r["trades"]
          if x["exit"] < cut - 1 and not x["open"]]
    prot = r["prot"][:cut]
    return sw, ev, su, tr, prot


def engine_cases():
    bad = 0
    for (path, sl), mode in [(c, m) for c in CASES for m in ("touch", "close")]:   # CHoCH by touch and by close
        bars, _ = engine.load(path, "2026-08-26", "2026-09-25", 5)
        p = dict(P, sl_rule=sl, choch_mode=mode)
        full = engine.run(bars, p)
        n = len(bars["t"])
        for cut in sorted(random.sample(range(n // 4, n - 5), 12)):
            part = {k: v[:cut] for k, v in bars.items()}
            r = engine.run(part, p)
            a, b = decisions(full, cut), decisions(r, cut)
            names = ("swings", "events", "setups", "closed trades", "protected level")
            diffs = [nm for nm, x, y in zip(names, a, b) if x != y]
            if diffs:
                bad += 1; print(f"FAIL {os.path.basename(path)} cut={cut} ({bars['t'][cut]}): {diffs}")
        print(f"{os.path.basename(path)} (CHoCH by {mode}): 12 cuts checked")
    return bad


# ---------------------------------------------------------------- FZ
def fz_run(bars, spec, tf, s0):
    """engine.run + fz.run + the FZ positions on `bars`, with fm_na and atr14 built from these bars as lab does."""
    rules = spec["rules"]; touch = rules["break_mode"] == "touch"
    r = engine.run(bars, dict(break_mode=rules["break_mode"], choch_mode=rules.get("choch_mode", rules["break_mode"]),
                              avwap_weight=rules["avwap_weight"], sl_rule=rules["sl_rule"]))
    fm = lab.fm_by_day()
    b = dict(bars, fm_na=[fm.get(x[:10], 0) == 0 or vv == 0 for x, vv in zip(bars["t"], bars["v"])],
             atr14=lab.atr_series(types.SimpleNamespace(t=bars["t"], h=bars["h"], l=bars["l"], c=bars["c"]),
                                  spec["options"]["atr_period"]))
    z = fz.run(b, fz_exec.view(r), fz.thresholds(spec["fz"][tf]), lab.TF_MIN[tf], s0,
               fz_exec.opener(b, r, rules["sl_rule"], touch))
    z["trades"] = fz_exec.build_trades(b, r, z, rules["sl_rule"], touch)
    return z


def fz_decisions(z, cut, full=None):
    """What FZ decided before `cut` (the cut data's last bar is cut - 1). `full` = the uncut run's ledger by bar, used
    only to skip the last bar's gate when the uncut run blocked it for in_position."""
    end = cut - 1
    skip = lambda x: x["i"] == end and full is not None and full[x["i"]]["block_reason"] == "in_position"
    card = z["card"][:cut]
    led = [(x["i"], x["zone_id"], x["read"]) + ((None, None) if skip(x) else (x["gate"], x["block_reason"]))
           for x in z["ledger"] if x["i"] < cut]
    wat = [(w["opened_at"], w["band_id"], w["dir"], w["kind"], w["opened_by_read"], w["setup_i"],
            w["armed_at"] if w["armed_at"] is not None and w["armed_at"] < end else None,
            (w["outcome"], w["outcome_bar"]) if w["outcome"] != "active" and w["outcome_bar"] < end else None)
           for w in z["watches"] if w["opened_at"] < end]
    tr = [(x["entry"], x["dir"], x["exit"], x["exit_px"], x["exit_reason"], x["sl"], x["gate"], x["fill_used"],
           x["reenter_reason"]) for x in z["trades"] if x["exit"] < end and not x["open"]]
    return card, led, wat, tr


def fz_cuts(z, s0, n, rng):
    """12 uniform cuts after s0, plus up to 24 targeted ones: 1-5 bars after a SETUP, and inside WATCH / ARMED windows."""
    uni = sorted(rng.sample(range(max(s0 + 1, n // 4), n - 5), FZ_UNIFORM))
    near = sorted({x["i"] + d for x in z["ledger"] for d in range(1, 6) if x["i"] + d < n})
    inw = sorted({j for w in z["watches"] if w["opened_at"] >= s0
                  for j in range(w["opened_at"] + 1, min(w["outcome_bar"], n - 1) + 1)})
    pick = lambda xs, k: rng.sample(xs, min(k, len(xs)))
    tgt = set(pick(near, FZ_TARGETED // 2)); tgt |= set(pick([j for j in inw if j not in tgt], FZ_TARGETED - len(tgt)))
    return sorted(set(uni) | tgt)


def live_at(z, cut):
    """FZ state spans the cut: a watch live on its last bar, a position open across it, or a SETUP in its last 5 bars."""
    end = cut - 1
    return (any(w["opened_at"] <= end <= w["outcome_bar"] for w in z["watches"])
            or any(x["entry"] <= end < x["exit"] for x in z["trades"])
            or any(end - 5 < x["i"] <= end for x in z["ledger"]))


def fz_cases():
    bad = 0
    ss = lab.sessions()
    for tf, fname, warm in FZ_CASES:
        spec = json.load(open(os.path.join(HERE, "strategies", fname), encoding="utf-8"))
        bars, s0 = engine.load(lab.DATA["futures"][tf], ss[warm], ss[-1], warm)
        full = fz_run(bars, spec, tf, s0)
        by = {x["i"]: x for x in full["ledger"]}
        n = len(bars["t"])
        cuts = fz_cuts(full, s0, n, random.Random(f"fz-truncation|{tf}"))
        informative = 0
        for cut in cuts:
            part = {k: v[:cut] for k, v in bars.items()}
            z = fz_run(part, spec, tf, s0)
            a, b = fz_decisions(full, cut, by), fz_decisions(z, cut, by)
            names = ("card", "ledger", "watches", "closed FZ positions")
            diffs = [nm for nm, x, y in zip(names, a, b) if x != y]
            informative += live_at(full, cut)
            if diffs:
                bad += 1; print(f"FAIL FZ {spec['code']} {tf} cut={cut} ({bars['t'][cut]}): {diffs}")
        print(f"FZ {spec['code']} ({tf}, CHoCH by touch): {len(cuts)} cuts checked, {informative} with FZ state live "
              f"across the cut")
    return bad


def main():
    random.seed(7)
    bad = engine_cases() + fz_cases()
    print("OK - no look-ahead" if not bad else f"{bad} failing cuts")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
