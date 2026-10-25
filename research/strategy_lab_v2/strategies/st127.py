"""ST127 - Strategy 127: gap days read with CHoCH / BOS - follow or reverse the gap - 5-minute structure, premium exits.

Built 2026-10-26 at the user's word ("identify if it's gap days and whether price follows or reverses using CHoCH or BOS and
backtest"). The rules: strategies/gapstruct.py. Numbers: STRATEGY_ANALYSIS_TODO S136.
"""
import core

SPEC = {'code': 'ST127',
 'name': 'Gap day → first CHoCH / BOS decides follow or reverse, 150-point ITM option, premium exits · 5m',
 'description': "Gap of 0.2% or more: the day's first 5-minute CHoCH or BOS on the NIFTY spot (Strategy 1's rules) decides - the gap's way is 'follow', the other way 'reverse'; buy the 150-point ITM weekly that way at the next minute; stop 70% of premium, a 20% trail once +5%, flat 15:15.",
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none', 'entry_rule': 'gap_structure_v1', 'exit_rule': 'next_choch'},
 'gapstruct': {'gap_min': 0.2, 'minutes': 5, 'warm': 2, 'last_entry': '14:00', 'take': 'both', 'exit': 'premium', 'itm': 150,
               'stop': 0.7, 'arm': 1.05, 'trail': 0.8, 'slip_pct': 0.1,
               'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'prev_swing'}},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:15', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 0, 'strike_step': 50, 'strike_choices': ['ITM150'],
             'strike_default': 'ITM150', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'named', 'from': '2018-02-01', 'to': '2026-10-23', 'default': True,
                'notes': 'the index and the store options (the main store from 2018)'},
               {'label': '2018-22', 'kind': 'named', 'from': '2018-02-01', 'to': '2022-12-31'},
               {'label': '2023-26', 'kind': 'named', 'from': '2023-01-01', 'to': '2026-10-23'}]}

_F = core.family("gapstruct")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run = _F.run


def signals(bars, spec):
    return _F.signals(bars, spec)
