"""ST69 - Strategy 69: the SMA cross of Strategy 68 switches Strategy 1 on; shorts only; 30 point target.

  the signal  on 5-minute candles: a candle closes down through the SMA 20, 50, 100, 200 or 500 of the candle LOW while that
              SMA is falling (Strategy 68's entry). It trades nothing: from the next candle to the square-off the day is armed.
  entry       Strategy 1's rules on 1-minute candles (swings, protected level, CHoCH by a touch, the AVWAP pair, SETUP):
              each bearish SETUP while the day is armed -> SHORT at its close. One position at a time.
  stop        Strategy 1's: the previous swing high.
  target      30 points below the entry (SPEC["sma_cross"]["target_pts"]).
  close       intraday: the square-off. Strategy 1's next-CHoCH exit is not used.
On the futures' own chart and on each option's own chart (the option is sold). The rules in full: strategies/sma_cross.py.
Built 2026-10-13 from the user's instruction ("extend this strategy and create a new one: apply Strategy 1 or 3 after you
get the signal in the SMA; the SMA cross-over is the signal to start Strategy 1 or 3; entry and stop are Strategy 1's or
3's; the target is 30 points or intraday"). Both were built: Strategy 69 with Strategy 1's rules, Strategy 70 with
Strategy 3's. First numbers: STRATEGY_ANALYSIS_TODO S87.
"""
import core

SPEC = {'code': 'ST69',
 'name': 'SMA cross down (falling) → Strategy 1 shorts · 30 pt target · 1m',
 'description': "A 5-minute close down through a falling SMA 20 / 50 / 100 / 200 / 500 of the candle LOW arms the day; from then Strategy 1's bearish SETUPs on 1-minute candles are shorted: stop at the previous swing high, target 30 points, flat by the square-off (no CHoCH exit). Futures' own chart and each option's own chart.",
 'timeframe': 'minute',
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
