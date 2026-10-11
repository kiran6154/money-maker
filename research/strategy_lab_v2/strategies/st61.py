"""ST61 - Strategy 61: Strategy 60 with the 20 point target as the only exit.

The signal chart and the entries are Strategy 60's (the day-open ATM straddle's candles; a bearish SETUP sells the CE and
the PE, a bullish SETUP buys the one leg that is going up, no short is bought back).
  exit    a leg leaves ONLY at its target: SPEC["straddle"]["target_pts"] points on its own premium. No stop, no CHoCH
          exit. A leg that has not reached it is closed at the square-off (the book is intraday).
One entry a side at a time: a side is free again when every leg of its last entry is closed. 1 lot a leg.
Built 2026-10-11 from the user's instruction ("same conditions, but we will do only those 20 points target trades,
nothing else"), read as "the target is the only exit": which entries will reach 20 points is not known at the entry, so
"take only the ones that reach it" cannot be traded. First numbers: STRATEGY_ANALYSIS_TODO S74.
"""
import core

SPEC = {'code': 'ST61',
 'name': 'Straddle chart · sell both / buy the rising leg · target only · 1m',
 'description': "Strategy 60's entries on the day-open ATM straddle's candles (a bearish SETUP sells the CE and the PE; a bullish SETUP buys the leg that is going up), with one exit only: a 20 point target on each leg's own premium. No stop and no CHoCH exit; what has not reached the target is closed at the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'both_sides', 'lookback': 5, 'target_pts': 20, 'exit': 'target_only', 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
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
