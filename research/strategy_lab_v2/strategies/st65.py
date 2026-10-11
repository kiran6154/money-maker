"""ST65 - Strategy 65: buy the winning leg at the straddle chart's signal, buy or sell; the option's own structure manages it.

  entry   ANY SETUP on the day-open ATM straddle's candles (its buy signal or its sell signal) -> at that same candle's
          close BUY the winning leg: the CE or the PE with the larger change of its close over SPEC["straddle"]["lookback"]
          candles. No SETUP of the option is waited for. Nothing is ever sold.
  stop    the option's own latest confirmed swing low below the entry; at every bullish BOS of the option it moves up to
          the level that BOS broke, never back
  exit    the stop, the option's next bearish CHoCH (that candle's close), or the square-off
One trade a leg at a time. 1 lot.
Built 2026-10-11 and corrected twice the same day at the user's word: first build sold the option on its own sell
signals ("no, not that ... long only; when you get a sell in the combined chart, enter long in the winning one"); the
second waited for the option's own SETUP ("we are entering late; enter at the same time as the derived chart's signal").
All three sets of numbers: STRATEGY_ANALYSIS_TODO S78.
"""
import core

SPEC = {'code': 'ST65',
 'name': 'Straddle buy or sell signal → buy the winning option at once · stop follows the BOS · 1m',
 'description': "Any SETUP on the day-open ATM straddle's candles (buy or sell) buys the winning leg (the CE or the PE going up) at that same candle's close. Long only. Stop at the option's own last swing low, moved up to the level each bullish BOS of the option broke; exit at the stop, the option's next bearish CHoCH or the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'leg_structure', 'lookback': 5, 'window': 'day', 'sides': 'long', 'arm': 'both', 'entry': 'signal', 'trail': 'bos_level', 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
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
