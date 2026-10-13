"""ST71 - Strategy 71: Strategy 69 with everything on 5-minute candles.

  the signal  a 5-minute candle closes down through the SMA 20, 50, 100, 200 or 500 of the candle LOW while that SMA is
              falling. It trades nothing: from the next candle to the square-off the day is armed.
  entry       Strategy 1's rules on the SAME 5-minute candles (that is Strategy 2: swings, protected level, CHoCH by a touch,
              the AVWAP pair, SETUP): each bearish SETUP while the day is armed -> SHORT at its close. One position at a time.
  stop        the structure's own, on 5-minute candles: the previous swing high.
  target      30 points below the entry.
  close       intraday: the square-off. The next-CHoCH exit is not used.
On the futures' own chart and on each option's own chart (the option is sold). The rules in full: strategies/sma_cross.py.
Built 2026-10-13 from the user's instruction ("try everything on 5 minutes"), after Strategies 69 / 70, whose structure is
on 1-minute candles. First numbers: STRATEGY_ANALYSIS_TODO S88.
"""
import core

SPEC = {'code': 'ST71',
 'name': 'SMA cross down (falling) → Strategy 2 shorts · 30 pt target · 5m',
 'description': "Everything on 5-minute candles: a close down through a falling SMA 20 / 50 / 100 / 200 / 500 of the candle LOW arms the day; from then Strategy 2's bearish SETUPs (the Foundation rules on the same 5-minute candles) are shorted: stop at the previous swing high, target 30 points, flat by the square-off (no CHoCH exit).",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 8,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'choch_candle',
           'entry_rule': 'sma_arm_v1',
           'exit_rule': 'next_choch'},
 'sma_low': {'periods': [20, 50, 100, 200, 500], 'source': 'low',
             'colors': ['#e5484d', '#f5a524', '#30a46c', '#0090ff', '#8e4ec6'],
             'notes': 'red 20, amber 50, green 100, blue 200, purple 500'},
 'sma_cross': {'periods': [20, 50, 100, 200, 500], 'side': 'short', 'falling': True, 'candles_min': 5, 'stop': 'structure', 'target_pts': 30,
               'notes': 'the cross arms the day; the Foundation rules then give the entry and the stop'},
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
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'},
               {'label': '3M', 'kind': 'preset', 'preset': '3M'},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'},
               {'label': 'This month', 'kind': 'preset', 'preset': 'MTD', 'default': True}]}

_F = core.family("sma_cross")
ENTRY_RULES = _F.ENTRY_RULES
LINE_COLORS = _F.colors(SPEC)                     # the option charts' colours, by line name


def signals(bars, spec):
    """Foundation's bearish SETUPs on days armed by the SMA cross (strategies/sma_cross.py)."""
    return _F.signals_arm(bars, spec)


def option_lines(s):
    """The same 5-minute SMAs on an option's own chart, from the option's own candles."""
    return _F.option_lines_htf(s, SPEC)


def chart_views(s1, t_from, t_to, main_min):
    """The same instrument on the other timeframes (signal candles, 1-minute), for the charts under the main one."""
    return _F.chart_views(SPEC, s1, t_from, t_to, main_min)
