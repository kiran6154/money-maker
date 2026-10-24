"""ST89 - Strategy 89: continuation only - Strategy 88 without the sweep / reclaim entries.

Strategy 88's breakout trigger on its own: three consecutive 1-minute closes ABOVE the opening high sell the PE at the
day's low, three below the opening low sell the CE at the day's high; no waiting for a reversal
(SPEC["orr_opt"]["breakout"] = {"closes": 3}, SPEC["orr_opt"]["reclaim"]: false). Out when the index closes back through
the strike, else 15:15; both sides, one position per side; every session (no body rule). The rules: strategies/orr_opt.py.
Built 2026-10-24 at the user's request ("one more strategy: by default don't wait for the reversal; check for continuation
trades and enter"). Numbers: STRATEGY_ANALYSIS_TODO S100.
"""
import core

SPEC = {'code': 'ST89',
 'name': '3-close breakout only → sell the option at the day high / low · 1m',
 'description': "Continuation only: three consecutive 1-minute closes above the opening high sell the PE at the day's low; three below the opening low sell the CE at the day's high. No sweep / reclaim entries. Out when the index closes back through the strike, else 15:15; both sides, one position per side.",
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'orr_opt_v1', 'exit_rule': 'next_choch'},
 'orr': {'body_min': 0.6, 'body_max': 0.9, 'stop_pts': 50, 'target_pts': 50, 'slippage': 0.5, 'cutoff': '15:15', 'sweep': 'close',
         'notes': "ORR_V1's signal parameters (only the eligibility, the sweep / reclaim and the cutoff are used here)"},
 'orr_opt': {'align': False, 'body_rule': False, 'breakout': {'closes': 3}, 'reclaim': False, 'expiry_min_days': 1, 'target_pct': None,
             'notes': 'align: only the 09:15 body side (ORR_V1) or both sides; the nearest weekly expiry at least this many days out; target_pct: buy back at this % of the premium earned (None: hold to the stop or 15:15)'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 1, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'Store options', 'kind': 'named', 'from': '2024-09-20', 'to': '2026-10-23', 'default': True,
                'notes': 'the span of the 1-minute options in the download store'},
               {'label': 'First half', 'kind': 'named', 'from': '2024-09-20', 'to': '2025-09-30'},
               {'label': 'Second half', 'kind': 'named', 'from': '2025-10-01', 'to': '2026-10-23'}]}

_F = core.family("orr_opt")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
