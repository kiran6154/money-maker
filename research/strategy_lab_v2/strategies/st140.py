"""ST140 - Strategy 140: 15m RSI-rainbow option sell - after the 30% decay, a BOS-ratcheted swing-high trail (K3).

Built 2026-10-26 at the user's word ("build these and backtest") from variant E_s11_armedbos K3 of the hand-off spec "Strategy 11 family" (claude.ai chat "15min RSI rainbow"); 2 slots per side, the fixed premium gate, OTM <= 250 points. The rules: strategies/optsell15.py
(the lab names differ from the specs' own). Numbers: STRATEGY_ANALYSIS_TODO S144; the full variant table:
tools/optsell_report.py.
"""
import core

SPEC = {'code': 'ST140',
 'name': '15m RSI-rainbow option sell - after the 30% decay, a BOS-ratcheted swing-high trail (K3) · 15m',
 'description': "The RSI-rainbow sell (Strategy 139's entry); no stop until the premium has decayed 30%; a swing-high stop ratchets down on each bearish BOS (3-bar pivots); after arming out on a touch of the entry or a close above that stop; else intrinsic at expiry.",
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none', 'entry_rule': 'optsell15_v1', 'exit_rule': 'next_choch'},
 **{'s11': {'var': 'E_s11_armedbos', 'K': 3, 'gate': 'fixed', 'universe': 'clean', 'slots': 2}},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': 'none', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 1.0},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 1.0}},
 'options': {'expiry_types': ['MONTHLY'], 'expiry_min_days': 0, 'strike_step': 50, 'strike_choices': ['OTM'],
             'strike_default': 'OTM', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'named', 'from': '2018-01-02', 'to': '2026-10-23', 'default': True,
                'notes': 'option contracts from the download store'},
               {'label': '2018-23', 'kind': 'named', 'from': '2018-01-02', 'to': '2023-12-31'},
               {'label': '2024-26', 'kind': 'named', 'from': '2024-01-01', 'to': '2026-10-23'}]}

_F = core.family("optsell15")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
