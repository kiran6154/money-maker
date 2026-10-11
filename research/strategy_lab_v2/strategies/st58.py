"""ST58 - Strategy 58: Strategy 57's buy signals, buying only the leg that is going up.

The signal chart is Strategy 57's (the day-open ATM straddle's candles, Strategy 3's rules). Only bullish SETUPs trade:
  entry   buy ONE leg, the one going up: the CE or the PE with the larger change of its close over the last
          SPEC["straddle"]["lookback"] candles up to the entry candle (a tie goes to the CE)
  exit    when the straddle chart turns to the sell side: the straddle trade's own exit (its stop at the previous swing of
          the combined premium, or the next CHoCH), or the square-off
Bearish SETUPs are not traded (they are the exit). 1 lot.
Built 2026-10-11 at the user's request ("when we see a buy trade in this, buy only the one that is going up, and exit that
on the sell side"). The definition of "going up" and its 5 candles are the build's choice, fixed before any run; first
numbers: STRATEGY_ANALYSIS_TODO S70.
"""
import core

SPEC = {'code': 'ST58',
 'name': 'Straddle long signal · buy the rising leg · 1m',
 'description': "Strategy 3's rules read on the day-open ATM straddle's candles; long signals only: on a bullish SETUP buy just the leg (CE or PE) that is going up - the larger gain over the last 5 candles - and leave it when the straddle chart turns to the sell side (its stop or the next CHoCH), or at the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'rising_leg', 'lookback': 5, 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 1, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'all', 'default': True,
                'notes': 'every session whose day-open ATM pair has full-chain option data (from 2026-06-30)'},
               {'label': 'First half', 'kind': 'named', 'from': '2026-06-30', 'to': '2026-08-12'},
               {'label': 'Second half', 'kind': 'named', 'from': '2026-08-13', 'to': '2026-10-06'},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'}]}

_F = core.family("atm_straddle")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run = _F.run
chart_main = _F.chart_main        # the lab's main chart is the derived straddle candles, with the structure on them


def signals(bars, spec):
    """The futures structure, for the reference chart only; the trades come from the straddle's candles (run)."""
    return _F.signals(bars, spec)
