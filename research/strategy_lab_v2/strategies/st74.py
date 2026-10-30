"""ST74 - Strategy 74: 15-minute SMA cross -> Strategy 2's shorts on 5-minute candles; stop = swing high; target 1:2.

  the signal  on 15-minute candles: a candle closes down through the SMA 20, 50, 100, 200 or 500 of the candle LOW while that
              SMA is falling. It trades nothing: from the next candle to the square-off the day is armed.
  entry       Strategy 2's rules on 5-minute candles (swings, protected level, CHoCH / BOS by touch, the AVWAP pair, SETUP):
              each bearish SETUP while the day is armed -> SHORT at its close. One position at a time.
              At every entry the moving average must still be valid: the SMA that was crossed still falling and the
              entry price below it, and the last completed 15-minute candle itself closed below it - a candle closing back
              above the average ends the signal until the next cross down (SPEC["sma_cross"]["valid_at_entry"]; added
              2026-10-14: S90, S92). Otherwise not traded.
  stop        the previous swing high of the structure.
  target      2 x the stop's distance below the entry (risk to reward 1:2).
  close       intraday: the square-off. The next-CHoCH exit is not used.
On the futures' own chart and on each option's own chart (the option is sold). The 15-minute candles are built from the
5-minute ones. Warm-up 21 sessions: the SMA 500 of 15-minute candles needs 20. The rules in full: strategies/sma_cross.py.
One of eight (Strategies 73 - 80: structure on 5-minute or 1-minute candles x stop at the swing high or at the SMA of the
highs x target 1:1 or 1:2), built 2026-10-13 from the user's instruction ("try the stop as the SMA high or the previous
swing high; try 15-minute SMA and 5-minute CHoCH / BOS; try 15-minute SMA and 1-minute CHoCH / BOS; try 1:2 risk reward as
well, not just 1:1; create new strategies for all these variations"). Numbers: STRATEGY_ANALYSIS_TODO S89.
"""
import core

SPEC = {'code': 'ST74',
 'name': '15m SMA cross → Strategy 2 shorts on 5m · stop swing high · 1:2',
 'description': "A 15-minute close down through a falling SMA 20 / 50 / 100 / 200 / 500 of the candle LOW arms the day; from then Strategy 2's bearish SETUPs on 5-minute candles are shorted. Stop: the previous swing high of the structure. Target: 2 x the stop's distance (1:2). Flat by the square-off; no CHoCH exit.",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 21,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'choch_candle',
           'entry_rule': 'sma_arm_v1',
           'exit_rule': 'next_choch'},
 'sma_low': {'periods': [20, 50, 100, 200, 500], 'source': 'low',
             'colors': ['#e5484d', '#f5a524', '#30a46c', '#0090ff', '#8e4ec6'],
             'notes': 'red 20, amber 50, green 100, blue 200, purple 500'},
 'sma_cross': {'periods': [20, 50, 100, 200, 500], 'side': 'short', 'falling': True, 'candles_min': 15, 'valid_at_entry': 'closed_below', 'stop': 'structure', 'target_r': 2,
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
