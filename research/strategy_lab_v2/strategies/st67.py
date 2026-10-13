"""ST67 - Strategy 67: Foundation on 5-minute candles with five SMAs of the candle LOW drawn on the chart.

The trades are Strategy 2's (Foundation rules on 5-minute candles: every SETUP, stop at the previous swing, exit at the
stop or the next CHoCH). Added, on the same 5-minute candles the signals are read on:
  SMA 20, 50, 100, 200, 500 of the candle LOW (SPEC["sma_low"]["periods"]), each in its own colour (SPEC["sma_low"]["colors"])
  - on the futures chart (Futures and Options via futures), from the futures candles
  - on each option's own chart (Options standalone: the engine runs on the option's candles), from that option's candles,
    over the contract's whole series
The SMAs are DRAWN ONLY: no entry, stop or exit reads them yet. The warm-up is 8 sessions (not Strategy 2's 2) so that
the SMA 500 (500 five-minute candles = 6.7 sessions) is formed at the first shown candle.
Built 2026-10-13 from the user's instruction ("create a new strategy, add the 20, 50, 100, 200, 500 SMA of the low on
5-minute candles, different colours, directly on futures and on options as well"). First numbers:
STRATEGY_ANALYSIS_TODO S85.
"""
import numpy as np
import core

SPEC = {'code': 'ST67',
 'name': 'Foundation · 5m · SMA-of-low ribbon (20 / 50 / 100 / 200 / 500)',
 'description': "Foundation rules on 5-minute candles (Strategy 2's trades) with the SMA 20, 50, 100, 200 and 500 of the candle LOW drawn in five colours: on the futures chart, and on each option's own chart. The SMAs are drawn only; no rule reads them yet.",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 8,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'choch_candle',
           'entry_rule': 'setup_v1',
           'exit_rule': 'next_choch'},
 'sma_low': {'periods': [20, 50, 100, 200, 500], 'source': 'low',
             'colors': ['#e5484d', '#f5a524', '#30a46c', '#0090ff', '#8e4ec6'],
             'notes': 'drawn only (red 20, amber 50, green 100, blue 200, purple 500); no rule reads them'},
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


def signals(bars, spec):
    """Foundation SETUPs on these candles (Strategy 2's), with the SMAs of the low as the chart's own lines."""
    sg = core.foundation(bars, spec["rules"])
    sg.lines = [sma_low(bars, n) for n in _P["periods"]]
    sg.line_names, sg.line_colors = list(LINE_COLORS), list(LINE_COLORS.values())
    return sg


def option_lines(s):
    """The same SMAs on an option's own chart, from the option's own candles."""
    return [(nm, sma_low(s, n)) for nm, n in zip(LINE_COLORS, _P["periods"])]
