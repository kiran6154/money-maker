"""ST31's 1-hour direction must not look ahead: at every 1-minute candle it is the same whether the data ends right after
that candle or months later (truncation test at random candles, both modes), and it only changes when a 1-hour candle
has closed.

    python tests/test_st31_causal.py
"""
import os, sys, random
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import numpy as np
import core


def main():
    mod = core.load_strategies()["ST31"]
    b = core.series("fut", "minute")
    w, s0 = core.window(b, "2026-03-02", "2026-06-30", mod.SPEC["warmup_days"])
    rnd = random.Random(31)
    bad = 0
    for mode in ("last_choch", "trend"):
        spec = dict(mod.SPEC, htf=dict(mod.SPEC["htf"], mode=mode))
        full = mod.htf_direction(w, spec)
        for _ in range(25):
            k = rnd.randrange(s0 + 400, len(w) - 1)
            cut = w.slice(0, k + 1)                       # the data ends at candle k
            got = mod.htf_direction(cut, spec)
            if not np.array_equal(got, full[:k + 1]):
                bad += 1; print(f"{mode}: differs when the data ends at {core.tstr(w.t[k])}")
        # the direction changes only on a 1-minute candle whose close is a 1-hour candle's close
        ch = np.nonzero(np.diff(full) != 0)[0] + 1
        mins = ((w.t[ch] + 60) % core.DAY) // 60 - (9 * 60 + 15)
        off = [int(x) for x in mins if x % 60 != 0 and x != 375]   # 1-hour closes at 10:15 ... 15:15, and 15:30
        if off: bad += 1; print(f"{mode}: {len(off)} changes not at a 1-hour close, e.g. minute {off[:3]}")
        print(f"{mode}: {len(ch)} direction changes, longs allowed on {np.mean(full == 1):.0%} of candles, shorts on {np.mean(full == -1):.0%}")
    print("CAUSAL OK" if not bad else f"{bad} PROBLEM(S)")
    return bad == 0


def test_st31_causal():
    assert main()


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
