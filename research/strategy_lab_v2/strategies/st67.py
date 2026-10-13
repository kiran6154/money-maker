"""ST67 - Strategy 67: short when a candle closes down through an SMA of the low; 30 point stop, 30 point target; intraday.

On 5-minute candles, with the SMA 20, 50, 100, 200 and 500 of the candle LOW (SPEC["sma_low"]: periods, colours; drawn
on the chart):
  entry   a candle CLOSES below an SMA whose value the previous candle closed at or above (a cross down), for any SMA of
          SPEC["sma_cross"]["periods"] -> SHORT at that close. One position at a time.
  stop    entry + SPEC["sma_cross"]["stop_pts"] (30): touched -> out at the stop (at the open if the candle opens above it)
  target  entry - SPEC["sma_cross"]["target_pts"] (30): touched -> out at the target (at the open if it opens below it)
          In one candle the stop is checked before the target.
  close   intraday: no entry at or after the square-off; a position still open then is closed at that candle's close.
Applied directly on what is traded:
  Futures               the futures' own candles and SMAs; 30 points of the futures.
  Options standalone    each option's own candles and SMAs; the option itself is SOLD; 30 points of its premium (an option
                        priced at or under the target distance is not sold: the target cannot be reached).
  Options via futures   the futures signal; a short buys a put, in and out at the futures trade's candles.
Nothing of the Foundation engine trades here: its structure is only still drawn.
Built 2026-10-13 from the user's instructions ("add the 20, 50, 100, 200, 500 SMA of the low on 5-minute candles ...
directly on futures and on options"; then "the strategy is: if the SMA is crossed down do a short; stop and profit 30
points; intraday"). Which SMA was not said: any of the five; each alone is measured in STRATEGY_ANALYSIS_TODO S85.
"""
import numpy as np
import core

SPEC = {'code': 'ST67',
 'name': 'SMA-of-low cross down · short · 30 / 30 pts · 5m',
 'description': "On 5-minute candles: when a candle closes down through the SMA 20, 50, 100, 200 or 500 of the candle LOW, go short at that close; stop 30 points, target 30 points, intraday. On the futures' own chart, and on each option's own chart (the option is sold). The five SMAs are drawn in five colours.",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 8,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'choch_candle',
           'entry_rule': 'sma_cross_v1',
           'exit_rule': 'next_choch'},
 'sma_low': {'periods': [20, 50, 100, 200, 500], 'source': 'low',
             'colors': ['#e5484d', '#f5a524', '#30a46c', '#0090ff', '#8e4ec6'],
             'notes': 'red 20, amber 50, green 100, blue 200, purple 500'},
 'sma_cross': {'periods': [20, 50, 100, 200, 500], 'side': 'short', 'stop_pts': 30, 'target_pts': 30,
               'notes': 'a close below an SMA the previous close was at or above; any of the periods'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY', 'MONTHLY'],
             'expiry_min_days': 1,
             'strike_step': 50,
             'strike_choices': ['ATR2', 'ATM', 'ITM2', 'ITM1', 'OTM1', 'OTM2', 'OTM3', 'OTM4'],
             'strike_default': 'ATR2',
             'atr_period': 14,
             'native_scan': {'choices': ['ATR2', 'ATM', 'ITM1', 'OTM1'], 'every_minutes': 5, 'one_per_side': True}},
 'backtests': [{'label': 'All data', 'kind': 'all', 'notes': 'every session with data, after the warm-up'},
               {'label': 'Design period',
                'kind': 'named',
                'from': '2026-08-26',
                'to': '2026-09-25',
                'notes': 'the rules were built on this window'},
               {'label': 'Unseen test',
                'kind': 'named',
                'from': '2026-07-08',
                'to': '2026-08-25',
                'notes': 'the rules never saw this window while being built'},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'},
               {'label': '3M', 'kind': 'preset', 'preset': '3M'},
               {'label': 'All data',
                'kind': 'all',
                'underlying': 'INDEX',
                'notes': 'signals on the NIFTY index (equal-weight AVWAP); the Futures type trades the near-month '
                         'contract'},
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'default': True,
                'notes': 'the current month, intraday (every position closed by 15:25)'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'square_off': None,
                'notes': 'positional: held overnight, no square-off'}]}


_P = SPEC["sma_low"]
LINE_COLORS = {f"SMA {n} low": c for n, c in zip(_P["periods"], _P["colors"])}      # the option charts' colours, by line name
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


ENTRY_RULES = ("sma_cross_v1",)


def signals(bars, spec):
    """Shorts at a close down through an SMA of the low, each walked to its stop, its target or the square-off."""
    X = spec["sma_cross"]; stop_pts, tgt_pts = float(X["stop_pts"]), float(X["target_pts"]); sq = spec["position"]["square_off"]
    o, h, l, c, t_ = bars.o, bars.h, bars.l, bars.c, bars.t; n = len(bars)
    cross = np.zeros(n, bool)
    for p_ in X["periods"]:
        v = sma_low(bars, p_)
        with np.errstate(invalid="ignore"):
            cross[1:] |= (c[:-1] >= v[:-1]) & (c[1:] < v[1:]) & (bars.day[1:] == bars.day[:-1])
    trades, free = [], -1
    for i in np.nonzero(cross)[0]:
        i = int(i)
        if i <= free: continue                                    # one position at a time
        e = float(c[i]); cut = core.square_off_at(sq, int(t_[i]))
        if cut and t_[i] >= cut: continue
        if e <= tgt_pts: continue                                 # an option under the target distance: it cannot be reached
        sl, tg = e + stop_pts, e - tgt_pts
        last = (int(np.searchsorted(t_, cut, "right")) - 1) if cut else n - 1
        x, px, why, still = last, float(c[last]), ("eod" if cut else "open"), not cut
        for k in range(i + 1, last + 1):
            if h[k] >= sl: x, px, why, still = k, max(float(o[k]), sl), "stop_loss", False; break
            if l[k] <= tg: x, px, why, still = k, min(float(o[k]), tg), "target 1", False; break
        trades.append(dict(entry=i, exit=x, exit_px=px, dir="down", choch=i, sl=sl, pts=e - px, open=still, exit_reason=why))
        free = x
    sg = core.foundation(bars, spec["rules"]).with_trades(trades, [sma_low(bars, p_) for p_ in _P["periods"]])
    sg.line_names, sg.line_colors = list(LINE_COLORS), list(LINE_COLORS.values())
    return sg


def option_lines(s):
    """The same SMAs on an option's own chart, from the option's own candles."""
    return [(nm, sma_low(s, n)) for nm, n in zip(LINE_COLORS, _P["periods"])]
