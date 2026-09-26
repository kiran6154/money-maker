"""Look-ahead check: cutting the data at a random bar must not change any decision made before the cut.

    python tests/test_truncation.py
"""
import os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine

CASES = [("D:/nifty/niftyfut_5minute_2026-07-01_to_2026-09-25.csv", "choch_candle"),
         ("D:/nifty/niftyfut_minute_2026-07-01_to_2026-09-25.csv", "prev_swing"),
         ("D:/nifty/options/NIFTY_2026-09-29/5minute/NIFTY26SEP24000PE.csv", "choch_candle")]
P = dict(break_mode="touch", avwap_weight="volume")


def decisions(r, cut):
    sw = [(s["k"], s["bar"], s["p"], s["conf"]) for s in r["sw"] if s["conf"] < cut]
    ev = [(e["i"], e["kind"], e["dir"]) for e in r["events"] if e["i"] < cut]
    su = [(x["i"], x["dir"], x["ch"]) for x in r["setups"] if x["i"] < cut]
    tr = [(x["entry"], x["dir"], x["exit"], x["exit_px"], x["exit_reason"], x["sl"]) for x in r["trades"]
          if x["exit"] < cut - 1 and not x["open"]]
    prot = r["prot"][:cut]
    return sw, ev, su, tr, prot


def main():
    random.seed(7); bad = 0
    for path, sl in CASES:
        bars, _ = engine.load(path, "2026-08-26", "2026-09-25", 5)
        p = dict(P, sl_rule=sl)
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
        print(f"{os.path.basename(path)}: 12 cuts checked")
    print("OK - no look-ahead" if not bad else f"{bad} failing cuts")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
