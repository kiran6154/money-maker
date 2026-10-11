"""ST65 - Strategy 65: Strategy 64 with the straddle chart's sell signal arming the winning leg too. Long only.

Strategy 64: a bullish SETUP on the day-open ATM straddle's candles arms the leg that is going up; Strategy 3 then runs on
that option's own candles and buys it on its bullish SETUP; the stop follows the option's BOS.
The change: a bearish SETUP on the straddle chart (its sell signal) arms a leg as well - the winning one, the same
definition: the CE or the PE with the larger change of its close over SPEC["straddle"]["lookback"] candles. Nothing is
ever sold: the armed option is bought on its own bullish SETUP, stop at its previous swing low, moved up to the level each
bullish BOS broke; exit at the stop, the option's next CHoCH, or the square-off. One trade a leg at a time. 1 lot.
Built 2026-10-11. The first build (the armed option's own sell signals traded as shorts) was not what the user asked for
and was replaced the same day: "this is also long only; when you get a sell in the combined chart, enter long in the
winning one". Both sets of numbers: STRATEGY_ANALYSIS_TODO S78.
"""
import core

SPEC = {'code': 'ST65',
 'name': 'Straddle buy or sell signal → Strategy 3 long on the winning option · stop follows the BOS · 1m',
 'description': "Strategy 64 with both signals of the day-open ATM straddle's candles arming a leg: a bullish or a bearish SETUP there arms the option (CE or PE) that is going up; Strategy 3 on that option's own candles then buys it on its bullish SETUP. Long only. The stop follows the option's BOS; exit at the stop, its next CHoCH or the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'leg_structure', 'lookback': 5, 'window': 'day', 'sides': 'long', 'arm': 'both', 'trail': 'bos_level', 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
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
