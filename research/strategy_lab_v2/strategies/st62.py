"""ST62 - Strategy 62: Strategy 61 with the short straddle imaginary - only the long scalp is traded.

The signal chart is Strategy 57's (the day-open ATM straddle's candles, Strategy 3's rules).
  bearish SETUP   nothing is sold: the short straddle is imaginary (a mark on the chart, never an order)
  bullish SETUP   BUY the one leg that is going up (the larger change of its close over SPEC["straddle"]["lookback"] candles)
  exit            ONLY the target: SPEC["straddle"]["target_pts"] points above the entry premium. No stop, no CHoCH exit;
                  a leg that has not reached it is closed at the square-off
One long at a time. 1 lot.
Built 2026-10-11 from the user's instruction ("this will not short any, short is imaginary; this will scalp only the
long positions"). Every bullish SETUP is bought: which of them will reach 20 points is not known at the entry. First
numbers: STRATEGY_ANALYSIS_TODO S75.
"""
import core

SPEC = {'code': 'ST62',
 'name': 'Straddle chart · long scalp only (short imaginary) · 20 pt target · 1m',
 'description': "Read on the day-open ATM straddle's candles: nothing is sold (the short straddle is imaginary); a bullish SETUP buys the leg that is going up, with one exit: a 20 point target on its own premium. No stop and no CHoCH exit; what has not reached the target is closed at the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'both_sides', 'lookback': 5, 'target_pts': 20, 'exit': 'target_only', 'real': 'long', 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
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
