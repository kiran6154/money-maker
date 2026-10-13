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

ST69 / ST70 (entry_rule "sma_arm_v1"): the cross does not trade, it SWITCHES ON the Foundation rules for the rest of the day.
  the signal  on SPEC["sma_cross"]["candles_min"]-minute candles built from the strategy's own (1-minute) candles: a
              candle closes down through an SMA of the low that is falling (the rule above, `falling` included). From the
              candle after that close until the square-off the day is armed.
  entry       the Foundation engine on the strategy's own candles (SPEC["rules"]: Strategy 1's or Strategy 3's): each
              bearish SETUP while the day is armed -> SHORT at its close. One position at a time.
  stop        the engine's own: the previous swing high (rules.sl_rule).
  target      entry - target_pts.
  close       the square-off. The engine's next-CHoCH exit is NOT used.
The SMAs are drawn as steps: each 5-minute value holds from the candle that completes it.
"""
import numpy as np
import core

ENTRY_RULES = ("sma_cross_v1", "sma_arm_v1")
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


# ---------------------------------------------------------------- the cross as a switch for the Foundation rules (ST69 / ST70)
_HTF = {}


def htf(bars, minutes):
    """The `minutes`-minute candles inside `bars` (09:15-aligned): (low, close, day of each, index of the bar that completes
    each, for every bar the index of the last COMPLETED candle or -1). Cached per series."""
    key = (id(bars), minutes, len(bars))
    if key not in _HTF or _HTF[key][0] is not bars:
        t = bars.t; tod = t % core.DAY
        bucket = t - tod + (555 + ((tod // 60 - 555) // minutes) * minutes) * 60
        cuts = np.concatenate([[0], np.nonzero(np.diff(bucket))[0] + 1, [len(t)]]); q0, q1 = cuts[:-1], cuts[1:] - 1
        low = np.minimum.reduceat(bars.l, q0); close = bars.c[q1]
        of = np.repeat(np.arange(len(q0)), q1 - q0 + 1)               # the candle a bar belongs to
        done = np.where(np.arange(len(t)) == q1[of], of, of - 1)      # complete only at its last bar
        while len(_HTF) > 200: del _HTF[next(iter(_HTF))]
        _HTF[key] = (bars, (low, close, bars.day[q1], q1, done))
    return _HTF[key][1]


def _sma(x, period):
    out = np.full(len(x), np.nan)
    if len(x) >= period:
        cs = np.concatenate([[0.0], np.cumsum(x)]); out[period - 1:] = (cs[period:] - cs[:-period]) / period
    return out


def htf_line(bars, period, minutes):
    """SMA(period) of the higher-timeframe lows, as a value per bar: the last completed candle's (nan before any)."""
    low, _, _, _, done = htf(bars, minutes); v = _sma(low, period)
    return np.where(done >= 0, v[np.maximum(done, 0)], np.nan)


def option_lines_htf(s, spec):
    return [(nm, htf_line(s, n, spec["sma_cross"]["candles_min"])) for nm, n in zip(colors(spec), spec["sma_low"]["periods"])]


def signals_arm(bars, spec):
    """Foundation's bearish SETUPs on days armed by a cross down of a falling SMA, each walked to the engine's stop, the
    target or the square-off."""
    X = spec["sma_cross"]; m = X["candles_min"]; tgt_pts = float(X["target_pts"]); sq = spec["position"]["square_off"]
    o, h, l, c, t_ = bars.o, bars.h, bars.l, bars.c, bars.t; n = len(bars)
    low5, c5, d5, q1, _ = htf(bars, m)
    cross = np.zeros(len(low5), bool)
    for p_ in X["periods"]:
        v = _sma(low5, p_)
        with np.errstate(invalid="ignore"):
            k = (c5[:-1] >= v[:-1]) & (c5[1:] < v[1:]) & (d5[1:] == d5[:-1])
            if X.get("falling"): k &= v[1:] < v[:-1]
        cross[1:] |= k
    armed_from = {}                                               # session -> the bar that completed its first signal candle
    for b_ in np.nonzero(cross)[0]: armed_from.setdefault(int(d5[b_]), int(q1[b_]))
    eng = core.foundation(bars, spec["rules"])
    trades, free = [], -1
    for x in eng.trades():
        i = x["entry"]
        if x["dir"] != "down" or x["sl"] is None: continue
        a = armed_from.get(int(bars.day[i]))
        if a is None or i <= a or i <= free: continue             # not armed (yet), or a position is open
        e = float(c[i]); cut = core.square_off_at(sq, int(t_[i]))
        if cut and t_[i] >= cut: continue
        sl, tg = float(x["sl"]), e - tgt_pts
        if sl <= e or e <= tgt_pts: continue
        last = (int(np.searchsorted(t_, cut, "right")) - 1) if cut else n - 1
        if last <= i: continue
        xi, px, why, still = last, float(c[last]), ("eod" if cut else "open"), not cut
        for k in range(i + 1, last + 1):
            if h[k] >= sl: xi, px, why, still = k, max(float(o[k]), sl), "stop_loss", False; break
            if l[k] <= tg: xi, px, why, still = k, min(float(o[k]), tg), "target 1", False; break
        trades.append(dict(entry=i, exit=xi, exit_px=px, dir="down", choch=x["choch"], sl=sl, pts=e - px, open=still, exit_reason=why))
        free = xi
    sg = eng.with_trades(trades, [htf_line(bars, p_, m) for p_ in spec["sma_low"]["periods"]])
    sg.line_names, sg.line_colors = list(colors(spec)), list(colors(spec).values())
    return sg
