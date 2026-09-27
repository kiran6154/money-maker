"""FZ parity and hygiene checks.

    python tests/test_fz_parity.py

1. fz_exec.simulate() on every Foundation SETUP with the engine's own stop gives back engine.run()'s trades field for
   field, and refuses exactly the SETUPs the engine skipped, on the 1m and 5m futures files over the lab's all-data
   windows: REENTER rows are filled, stopped and exited by Foundation's own rules.
2. fz.py never names a trade-outcome field (exit_px, exit_reason, pts, net, mfe, mae), a swing's final-state flag
   (broken) or the engine's CHoCH-window end (["end"]), and imports neither engine nor lab: the gate cannot read how a
   ticket ended.
3. fz.run() with a callback that refuses every position produces the same card as the real run (the card does not
   depend on positions); the ledger's card columns match and gates differ only on rows touched by in_position or a
   REENTER.
4. Every key of every strategy file's fz block has a value and a source, the blocks of one strategy family share one key
   set, and fz.thresholds() accepts them and refuses a missing key, an unknown key and a key without a source.
5. REENTER rows keep their rule: no REENTER fills on a close inside its band (R1-R3, or a LEAVE, put the fill beyond the
   edge), a TAKE is turned into a REENTER only on TAKE branch 1 (a LEAVE of the watched band, evaluation M22), and every
   REENTER position's SETUP row ends with outcome_gate REENTER (so REENTER rows and positions agree).
"""
import copy, csv, glob, json, os, re, sys, types
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import engine, fz, fz_exec, lab

# (timeframe, strategy file, lab warm-up = sessions before the first shown one)
CASES = [("minute", "strategy_5.json", 2), ("5minute", "strategy_6.json", 5)]
CARD_COLS = ("zone_id", "zone_kind", "band_lo", "band_hi", "visit_n", "this_bars", "this_vol", "first_bars", "first_vol",
             "vol_na", "first_vol_na", "read", "left_id", "session_bar", "in_id", "level_in_band", "entered_zone_id",
             "entered_visit_n", "entered_read", "leave_vol_ok", "leave_kind")


def inputs(tf, warm, atr_period):
    """Bars for the all-data window with fm_na (not the front month, or zero volume) and atr14, as lab builds them."""
    ss = lab.sessions()
    bars, s0 = engine.load(lab.DATA["futures"][tf], ss[warm], ss[-1], warm)
    fm = {r["datetime"][:10]: r["front_month"] for r in csv.DictReader(open(lab.FUT1))}
    bars["fm_na"] = [fm[x[:10]] == "0" or vv == 0 for x, vv in zip(bars["t"], bars["v"])]
    bars["atr14"] = lab.atr_series(types.SimpleNamespace(t=bars["t"], h=bars["h"], l=bars["l"], c=bars["c"]), atr_period)
    return bars, s0


def parity(bars, s0, r, sl_rule, touch):
    stop = fz_exec.stops(bars, fz_exec.view(r)["swings"], sl_rule)
    chi = [e["i"] for e in r["chs"]]
    eng = {x["entry"]: x for x in r["trades"]}
    skipped = {x["entry"] for x in r["skipped"]}
    bad = []
    for x in r["setups"]:
        k, d, ch = x["i"], x["dir"], x["ch"]
        y = fz_exec.simulate(bars, k, d, stop(k, d, ch), chi, touch, choch=ch)
        if (y is None and k not in skipped) or (y is not None and y != eng.get(k)): bad.append(k)
    shown = sum(1 for x in r["trades"] if x["entry"] >= s0)
    same = shown - sum(1 for k in bad if k >= s0)
    return bad, f"{same}/{shown} shown trades ({len(r['trades'])} in the run, {len(skipped)} skipped)"


def tokens():
    src = open(os.path.join(HERE, "fz.py"), encoding="utf-8").read()
    bad = [tok for tok in ("exit_px", "exit_reason", "pts", "net", "mfe", "mae", "broken") if re.search(rf"\b{tok}\b", src)]
    bad += [tok for tok in ('["end"]', "['end']") if tok in src]
    bad += [m for m in ("import engine", "import lab", "from engine", "from lab") if m in src]
    return bad


def keys():
    """Problems with the fz blocks of the strategy files (empty list = fine)."""
    bad, sets = [], {}
    for path in sorted(glob.glob(os.path.join(HERE, "strategies", "*.json"))):
        spec = json.load(open(path, encoding="utf-8"))
        if "fz" not in spec: continue
        name = os.path.basename(path)
        for tf, block in spec["fz"].items():
            for k, e in block.items():
                if not isinstance(e, dict) or "value" not in e or not str(e.get("source") or "").strip():
                    bad.append(f"{name} {tf}.{k}: no value or source")
            try: fz.thresholds(block)
            except ValueError as ex: bad.append(f"{name} {tf}: {ex}")
            sets[name] = set(block)
            for label, mutate in (("missing key", lambda b: b.pop(next(iter(b)))),
                                  ("unknown key", lambda b: b.update(extra_key=dict(value=1, source="x"))),
                                  ("no source", lambda b: b[next(iter(b))].pop("source"))):
                b = copy.deepcopy(block); mutate(b)
                try: fz.thresholds(b); bad.append(f"{name} {tf}: a {label} was accepted")
                except ValueError: pass
    if len({frozenset(s) for s in sets.values()}) > 1: bad.append(f"fz key sets differ between files: {sorted(sets)}")
    if not sets: bad.append("no strategy file has an fz block")
    return bad


def reenter_rules(bars, z, trades):
    """Problems with the REENTER rows of one fz.run (empty list = fine), see 5 above."""
    c, t = bars["c"], bars["t"]
    snap = {d[1]: d[4] for d in z["decisions"] if d[0] == "REENTER"}
    rows = {x["i"]: x for x in z["ledger"]}
    bad = [f"fill inside the band at {t[e]}" for e, b in snap.items() if b["lo"] <= c[e] <= b["hi"]]
    bad += [f"TAKE turned REENTER on branch {x['branch']} at {x['time']}" for x in z["ledger"]
            if x["gate"] == "REENTER" and x["branch"] not in ("watch", "leave")]
    bad += [f"REENTER at {t[x['entry']]}: SETUP row outcome_gate {rows[x['setup_i']]['outcome_gate']}" for x in trades
            if x["gate"] == "REENTER" and x["setup_i"] in rows and rows[x["setup_i"]]["outcome_gate"] != "REENTER"]
    return bad


def main():
    fails = 0
    bad = keys()
    print("fz keys:", "OK" if not bad else bad); fails += bool(bad)
    bad = tokens()
    print("fz.py tokens:", "OK" if not bad else bad); fails += bool(bad)
    for tf, fname, warm in CASES:
        spec = json.load(open(os.path.join(HERE, "strategies", fname), encoding="utf-8"))
        rules, touch = spec["rules"], spec["rules"]["break_mode"] == "touch"
        bars, s0 = inputs(tf, warm, spec["options"]["atr_period"])
        r = engine.run(bars, dict(break_mode=rules["break_mode"], choch_mode=rules.get("choch_mode", rules["break_mode"]),
                                  avwap_weight=rules["avwap_weight"], sl_rule=rules["sl_rule"]))
        bad, note = parity(bars, s0, r, rules["sl_rule"], touch)
        print(f"{tf}: simulate() vs engine trades: {note}", "OK" if not bad else f"FAIL at bars {bad[:10]}")
        fails += bool(bad)

        cfg = fz.thresholds(spec["fz"][tf])
        V = fz_exec.view(r)
        real = fz.run(bars, V, cfg, lab.TF_MIN[tf], s0, fz_exec.opener(bars, r, rules["sl_rule"], touch))
        none = fz.run(bars, V, cfg, lab.TF_MIN[tf], s0, lambda *a: None)
        same_card = real["card"] == none["card"]
        ra, rb = {x["i"]: x for x in real["ledger"]}, {x["i"]: x for x in none["ledger"]}
        col_diff = [i for i in ra if i not in rb or any(ra[i][k] != rb[i][k] for k in CARD_COLS)]
        gate_diff = [i for i in ra if i in rb and ra[i]["gate"] != rb[i]["gate"]]
        odd = [i for i in gate_diff if not ("in_position" in (ra[i]["block_reason"], rb[i]["block_reason"])
                                            or "REENTER" in (ra[i]["gate"], rb[i]["gate"]))]
        ok = same_card and not col_diff and not odd and set(ra) == set(rb)
        print(f"{tf}: card with vs without positions: card {'identical' if same_card else 'DIFFERS'}, "
              f"ledger card columns {'identical' if not col_diff else f'differ at {col_diff[:5]}'}, "
              f"{len(gate_diff)} gate differences ({len(odd)} not explained by in_position / REENTER)",
              "OK" if ok else "FAIL")
        fails += not ok
        trades = fz_exec.build_trades(bars, r, real, rules["sl_rule"], touch)
        bad = reenter_rules(bars, real, trades)
        n_re = sum(1 for x in trades if x["gate"] == "REENTER")
        print(f"{tf}: REENTER rows ({n_re} positions): fills beyond the band, conversions only on a LEAVE, outcome_gate "
              f"on every REENTER SETUP", "OK" if not bad else f"FAIL {bad[:5]}")
        fails += bool(bad)
    print("OK - FZ parity" if not fails else f"{fails} failing checks")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
