"""ST68 - Strategy 68: Strategy 67, and the SMA that is crossed must be falling.

Strategy 67's rules (5-minute candles; a close down through the SMA 20, 50, 100, 200 or 500 of the candle LOW is a SHORT;
stop 30 points, target 30 points; intraday; futures' own chart and each option's own chart). The one change:
  the SMA being crossed must itself be falling at the cross candle: its value at that candle is below its value one candle
  before (SPEC["sma_cross"]["falling"]). A cross down through a flat or rising SMA is not traded.
The rules in full: strategies/sma_cross.py.
Built 2026-10-13 from the user's instruction ("extend this strategy and create a new one; the rules are the same except
that the SMA should be falling when the candle is crossing"). First numbers: STRATEGY_ANALYSIS_TODO S86.
"""
import core

SPEC = {'code': 'ST68',
 'name': 'SMA-of-low cross down, SMA falling · short · 30 / 30 pts · 5m',
 'description': "Strategy 67 with one more condition: on 5-minute candles, a close down through the SMA 20, 50, 100, 200 or 500 of the candle LOW is a short only when that SMA is itself falling at that candle (below its value one candle before). Stop 30 points, target 30 points, intraday; futures' own chart and each option's own chart.",
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
 'sma_cross': {'periods': [20, 50, 100, 200, 500], 'side': 'short', 'falling': True, 'stop_pts': 30, 'target_pts': 30,
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


_F = core.family("sma_cross")
ENTRY_RULES = _F.ENTRY_RULES
LINE_COLORS = _F.colors(SPEC)                     # the option charts' colours, by line name


def signals(bars, spec):
    """Shorts at a close down through an SMA of the low (strategies/sma_cross.py)."""
    return _F.signals(bars, spec)


def option_lines(s):
    """The same SMAs on an option's own chart, from the option's own candles."""
    return _F.option_lines(s, SPEC)


def chart_views(s1, t_from, t_to, main_min):
    """The same instrument on the other timeframes (signal candles, 1-minute), for the charts under the main one."""
    return _F.chart_views(SPEC, s1, t_from, t_to, main_min)
