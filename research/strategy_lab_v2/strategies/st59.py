"""ST59 - Strategy 59: a short straddle managed leg by leg on the straddle chart's signals.

The signal chart is Strategy 57's (the day-open ATM straddle's candles, Strategy 3's structure rules).
  bearish SETUP (the sell side)   be short the straddle: SELL every leg not held - both when flat, or the one leg that was
                                  bought back earlier (the re-entry)
  bullish SETUP (the buy side)    BUY BACK one leg, the one going up: the CE or the PE with the larger change of its close
                                  over the last SPEC["straddle"]["lookback"] candles (a tie goes to the CE), when it is
                                  held; the other leg stays short
  square-off                      whatever is left is closed
No stop and no CHoCH exit: the bullish SETUP is the management. Each leg 1 lot, filled at its own candle close.
Built 2026-10-11 from the user's description ("straddle as is on the sell side; on a buy we exit one side and keep the
other and enter again; we will manage it"). Which leg is "going up" is Strategy 58's definition. First numbers:
STRATEGY_ANALYSIS_TODO S72.
"""
import core

SPEC = {'code': 'ST59',
 'name': 'Managed short straddle on the straddle chart · 1m',
 'description': "Read on the day-open ATM straddle's candles: a bearish SETUP sells the CE and the PE; a bullish SETUP buys back only the leg that is going up and keeps the other short; the next bearish SETUP sells the missing leg again. No stop; flat by the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'managed_short', 'lookback': 5, 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
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
