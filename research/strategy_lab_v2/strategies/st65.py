"""ST65 - Strategy 65: Strategy 64 trading both the buy and the sell signals of the armed option.

Strategy 64: a bullish SETUP on the day-open ATM straddle's candles arms the leg that is going up; Strategy 3 then runs on
that option's own candles; the stop follows the option's BOS.
The change: the armed option's bearish SETUPs are traded too.
  option's bullish SETUP   BUY it;  stop at its previous swing low,  moved up to the level each bullish BOS broke
  option's bearish SETUP   SELL it; stop at its previous swing high, moved down to the level each bearish BOS broke
Exit at the stop, the option's next CHoCH, or the square-off. One trade a leg at a time. 1 lot.
Built 2026-10-11 from the user's instruction ("in this, do it for both sell and buy signals"). First numbers:
STRATEGY_ANALYSIS_TODO S78.
"""
import core

SPEC = {'code': 'ST65',
 'name': 'Straddle long scenario → Strategy 3 on the rising option, buy and sell · stop follows the BOS · 1m',
 'description': "Strategy 64 with both sides of the armed option traded: its bullish SETUP buys it, its bearish SETUP sells it; the stop follows the option's BOS in the trade's direction (to the level that BOS broke, never back). Exit at the stop, the option's next CHoCH or the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'leg_structure', 'lookback': 5, 'window': 'day', 'sides': 'both', 'trail': 'bos_level', 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
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
