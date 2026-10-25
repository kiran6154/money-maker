"""ST118 - Strategy 118: Jilly's ORB + Noise Band (Strategy 111) as the day's confirmation, then Strategy 3's SETUPs in the confirmation's direction.

Built 2026-10-25 at the user's request ("extend the strategy: apply CHoCH / BOS plain for entry and exits, and after the base
strategy's confirmation apply Strategy 1 or 2 or 3"; "even check reversals in CHoCH / BOS"). The rules: strategies/jilly_ext.py.
Numbers: STRATEGY_ANALYSIS_TODO S122.
"""
import core

SPEC = {'code': 'ST118',
 'name': 'Jilly-confirmed day → Strategy 3 SETUPs in its direction · 1m',
 'description': "After Strategy 111's signal, Strategy 3's SETUPs (1-minute, a CHoCH needs a close, stop at the previous swing, exit at the next CHoCH) in the signal's direction; flat 15:20.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'close', 'avwap_weight': 'volume', 'sl_rule': 'prev_swing', 'entry_rule': 'jilly_ext_v1', 'exit_rule': 'next_choch'},
 'jext': {'mode': 'setup', 'sides': 'jilly', 'minutes': 1, 'warm': 2, 'rules': {'break_mode': 'touch', 'choch_mode': 'close', 'avwap_weight': 'volume', 'sl_rule': 'prev_swing'}},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:20', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 0, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'named', 'from': '2018-01-02', 'to': '2026-10-23', 'default': True,
                'notes': 'futures 2018 on; options from 2020-02 (the store)'},
               {'label': '2018-22', 'kind': 'named', 'from': '2018-01-02', 'to': '2022-12-31'},
               {'label': '2023-26', 'kind': 'named', 'from': '2023-01-01', 'to': '2026-10-23'}]}

_F = core.family("jilly_ext")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
