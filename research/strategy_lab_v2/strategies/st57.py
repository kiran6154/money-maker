"""ST57 - Strategy 57: Strategy 3 read on the day-open ATM straddle's candles.

The chart is the combined premium of the CE and the PE of the strike nearest the index at each day's open (strategies/
atm_straddle.py: how the candles are built, one engine run per session on that session's own pair). Strategy 3's rules on it:
swings / BOS by touch, a CHoCH needs a close beyond the protected level, SETUP, stop at the previous swing, exit at the stop
or the next CHoCH, flat by the square-off.
  bullish SETUP (the straddle's premium turning up)   -> BUY the CE and BUY the PE
  bearish SETUP (the premium turning down)            -> SELL the CE and SELL the PE
Each leg is one position of 1 lot, filled at its own candle close at the straddle trade's entry and exit candles.
Built 2026-10-11 at the user's request ("apply Strategy 3 on the day-open ATM straddle candles"); first numbers:
STRATEGY_ANALYSIS_TODO S70.
"""
import core

SPEC = {'code': 'ST57',
 'name': 'Foundation on the day-open ATM straddle · 1m',
 'description': "Strategy 3's rules read on the candles of the day-open ATM straddle (CE + PE of the strike nearest the index at the open): a bullish SETUP buys the CE and the PE, a bearish SETUP sells both. Stop at the previous swing of the combined premium; exit at the stop or the next CHoCH; flat by the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'both', 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
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


def signals(bars, spec):
    """The futures structure, for the reference chart only; the trades come from the straddle's candles (run)."""
    return _F.signals(bars, spec)
