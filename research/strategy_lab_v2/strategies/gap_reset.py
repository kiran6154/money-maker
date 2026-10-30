"""Foundation engine with a restart on gap days (family module for ST66).

A session is a gap day when its first candle's OPEN is at least SPEC["gap_reset"]["pts"] points above or below the previous
session's last CLOSE (the same candles the signals are read on). On a gap day the market structure starts again: the engine
runs from that session's first candle with no memory of what came before - no swings, no protected level, no trend, no
CHoCH / BOS, no AVWAP anchor from an earlier session. The structure then carries on across the following sessions until
the next gap day.

How: the candles are cut at every gap day's first candle and the engine (core._engine, unchanged) runs once on each piece;
the pieces are joined into one core.Signals, so the runner, the charts and the signal list see one continuous result.
A position open at the last candle of a piece is closed there by the engine (an intraday run has squared it off before).
"""
import numpy as np
import core


def gap_starts(bars, pts):
    """Candle indices where the structure starts again: 0, and the first candle of every gap day."""
    first = np.nonzero(np.diff(bars.day))[0] + 1                       # the first candle of each session after the first
    gap = np.abs(bars.o[first] - bars.c[first - 1]) >= pts
    return np.concatenate([[0], first[gap]]).astype(np.int64), len(first) + 1


def foundation(bars, rules, pts):
    """core.foundation(bars, rules) with the structure started again at every gap day."""
    starts, _ = gap_starts(bars, pts)
    if len(starts) == 1: return core.foundation(bars, rules)
    touch = rules["break_mode"] == "touch"
    ch_touch = (rules.get("choch_mode") or rules["break_mode"]) == "touch"
    w = np.ascontiguousarray(bars.v if rules["avwap_weight"] == "volume" else np.ones(len(bars)), dtype=np.float64)
    sl_rule = core.SL_RULES[rules.get("sl_rule", "none")]
    ends = np.concatenate([starts[1:], [len(bars)]])
    # positions in the engine's output tuple, by what an entry is
    BAR = {1, 3, 10, 13, 22, 23, 25, 26, 27, 30, 34}                   # candle indices: + the piece's first candle
    SWING = {17, 20, 21}                                               # swing indices (-1 = none): + the swings before
    CUM = {7, 8}                                                       # cumulative sums, one longer than the candles
    parts = [[] for _ in range(37)]; n_sw = 0; off = [0.0, 0.0]; pieces = []
    for a, e in zip(starts, ends):
        a, e = int(a), int(e); pieces.append((a, n_sw))
        out = core._engine(bars.o[a:e], bars.h[a:e], bars.l[a:e], bars.c[a:e], w[a:e], bars.day[a:e], touch, ch_touch, sl_rule)
        for k, x in enumerate(out):
            if k in BAR: x = x + a
            elif k in SWING: x = np.where(x >= 0, x + n_sw, x)
            elif k in CUM:
                x = x + off[k - 7]; off[k - 7] = float(x[-1]); x = x[:-1] if e < len(bars) else x
            parts[k].append(x)
        n_sw += len(out[0])
    sg = core.Signals(bars, tuple(np.concatenate(p) for p in parts))
    sg.pieces = pieces                                 # (first candle, first swing) of each piece: the chart's trend AVWAP restarts there
    return sg
