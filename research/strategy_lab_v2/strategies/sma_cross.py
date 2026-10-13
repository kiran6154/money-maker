"""SMA-of-low cross strategies (family module for ST67 / ST68): short when a candle closes down through an SMA of the low.

On the candles of what is traded (the futures; or an option's own candles for Options standalone), with the SMAs of the
candle LOW of SPEC["sma_low"]["periods"] (drawn on the chart in SPEC["sma_low"]["colors"]):
  entry   a candle CLOSES below an SMA whose value the previous candle closed at or above (a cross down, same session), for
          any SMA of SPEC["sma_cross"]["periods"] -> SHORT at that close. One position at a time.
          SPEC["sma_cross"]["falling"]: the SMA that is crossed must itself be falling at that candle - its value below
          its value one candle before.
          No entry on the last candle before the square-off (it would be opened and closed on the same candle).
  stop    entry + stop_pts: touched -> out at the stop (at the open if the candle opens above it)
  target  entry - target_pts: touched -> out at the target (at the open if it opens below it)
          In one candle the stop is checked before the target.
  close   intraday: no entry at or after the square-off; a position still open then is closed at that candle's close.
Futures: 30 points of the futures. Options standalone: the option itself is SOLD, the points are of its premium (an option
priced at or under the target distance is not sold). Options via futures: the futures short buys a put, in and out at the
futures trade's candles. Nothing of the Foundation engine trades here; its structure is only still drawn.
"""
import numpy as np
import core

ENTRY_RULES = ("sma_cross_v1",)
_SMA = {}


def sma_low(s, period):
    """SMA(period) of a series' candle LOWS (nan until `period` candles), cached per series."""
    key = (id(s), period, len(s))                 # the entry keeps the series, so its id cannot pass to another one
    if key not in _SMA or _SMA[key][0] is not s:
        x = np.asarray(s.l, float); out = np.full(len(x), np.nan)
        if len(x) >= period:
            cs = np.concatenate([[0.0], np.cumsum(x)])
            out[period - 1:] = (cs[period:] - cs[:-period]) / period
        while len(_SMA) > 400: del _SMA[next(iter(_SMA))]
        _SMA[key] = (s, out)
    return _SMA[key][1]


def colors(spec):
    """{line name: colour} of the strategy's SMAs."""
    return {f"SMA {n} low": c for n, c in zip(spec["sma_low"]["periods"], spec["sma_low"]["colors"])}


def option_lines(s, spec):
    """The SMAs on an option's own chart, from the option's own candles."""
    return [(nm, sma_low(s, n)) for nm, n in zip(colors(spec), spec["sma_low"]["periods"])]


def signals(bars, spec):
    """Shorts at a close down through an SMA of the low, each walked to its stop, its target or the square-off."""
    X = spec["sma_cross"]; stop_pts, tgt_pts = float(X["stop_pts"]), float(X["target_pts"]); sq = spec["position"]["square_off"]
    o, h, l, c, t_ = bars.o, bars.h, bars.l, bars.c, bars.t; n = len(bars)
    cross = np.zeros(n, bool)
    for p_ in X["periods"]:
        v = sma_low(bars, p_)
        with np.errstate(invalid="ignore"):
            k = (c[:-1] >= v[:-1]) & (c[1:] < v[1:]) & (bars.day[1:] == bars.day[:-1])
            if X.get("falling"): k &= v[1:] < v[:-1]
        cross[1:] |= k
    trades, free = [], -1
    for i in np.nonzero(cross)[0]:
        i = int(i)
        if i <= free: continue                                    # one position at a time
        e = float(c[i]); cut = core.square_off_at(sq, int(t_[i]))
        if cut and t_[i] >= cut: continue
        if e <= tgt_pts: continue                                 # an option under the target distance: it cannot be reached
        sl, tg = e + stop_pts, e - tgt_pts
        last = (int(np.searchsorted(t_, cut, "right")) - 1) if cut else n - 1
        if last <= i: continue                                    # the last candle before the square-off: nothing to hold
        x, px, why, still = last, float(c[last]), ("eod" if cut else "open"), not cut
        for k in range(i + 1, last + 1):
            if h[k] >= sl: x, px, why, still = k, max(float(o[k]), sl), "stop_loss", False; break
            if l[k] <= tg: x, px, why, still = k, min(float(o[k]), tg), "target 1", False; break
        trades.append(dict(entry=i, exit=x, exit_px=px, dir="down", choch=i, sl=sl, pts=e - px, open=still, exit_reason=why))
        free = x
    sg = core.foundation(bars, spec["rules"]).with_trades(trades, [sma_low(bars, p_) for p_ in spec["sma_low"]["periods"]])
    sg.line_names, sg.line_colors = list(colors(spec)), list(colors(spec).values())
    return sg
