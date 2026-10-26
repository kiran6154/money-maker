"""ST139 - Strategy 139: 15m RSI-rainbow option sell - RSI 70 then the first close below the rainbow mid.

Built 2026-10-26 at the user's word ("build these and backtest") from variant A_s11 of the hand-off spec "Strategy 11 family" (claude.ai chat "15min RSI rainbow"); 2 slots per side, the fixed premium gate, OTM <= 250 points. The rules: strategies/optsell15.py
(the lab names differ from the specs' own). Numbers: STRATEGY_ANALYSIS_TODO S144; the full variant table:
tools/optsell_report.py.
"""
import core

SPEC = {'code': 'ST139',
 'name': '15m RSI-rainbow option sell - RSI 70 then the first close below the rainbow mid · 15m',
 'description': 'Monthly NIFTY options, 15-minute bars of each contract: RSI-14 at 70+ within 5 bars, then the first close below the rainbow mid sells it (22 - 35 days to expiry, 0.5 - 4% OTM, premium 246.7 - 700). No stop until the premium has decayed 30%; then out on a touch of the entry or a close above the rainbow top; else intrinsic at expiry.',
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none', 'entry_rule': 'optsell15_v1', 'exit_rule': 'next_choch'},
 **{'s11': {'var': 'A_s11', 'K': 0, 'gate': 'fixed', 'universe': 'clean', 'slots': 2}},
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
