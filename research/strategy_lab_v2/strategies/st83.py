"""ST83 - Strategy 83: opening-range sweep / reclaim continuation, ORR_V1 as written.

The ruleset as written: the reclaim close enters at the next minute's open (a blind entry).
The rules: strategies/orr.py; every number: SPEC["orr"]. Built 2026-10-24 from the user's IMPLEMENTATION_RULESET.md
(ORR_V1, proposed there as "Strategy 27" of the Spring application; Strategy 27 is taken in the lab, so it is ST83).
Numbers against the ruleset's own: STRATEGY_ANALYSIS_TODO S95.
"""
import core

SPEC = {'code': 'ST83',
 'name': 'ORR_V1 opening-range sweep / reclaim · 50 / 50 pts · 1m',
 'description': "The 09:15 candle with a body of 60-90% of its range sets the side (bullish: longs only, bearish: shorts only). Price sweeps the opposite opening boundary and a 1-minute close reclaims it: enter at the next minute's open. 50 point stop and target from the slipped fill, 0.5 point slippage, unlimited re-entries after a fresh sweep and reclaim, flat at 15:15.",
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'orr_v1',
           'exit_rule': 'next_choch'},
 'orr': {'body_min': 0.6, 'body_max': 0.9, 'stop_pts': 50, 'target_pts': 50, 'slippage': 0.5, 'cutoff': '15:15',
         'notes': 'the ruleset ORR_V1 values: opening body 60% (inclusive) to 90% (exclusive) of its range, 50 / 50 point bracket from the slipped fill, 0.5 point adverse slippage per execution, entries before and force close at 15:15'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 1, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'Ruleset 2025', 'kind': 'named', 'from': '2025-01-01', 'to': '2025-10-28', 'notes': "the ruleset's first sample"},
               {'label': 'Ruleset 2026', 'kind': 'named', 'from': '2026-01-01', 'to': '2026-09-22', 'notes': "the ruleset's second sample"},
               {'label': 'All data', 'kind': 'all', 'default': True, 'notes': 'every complete session from 2018'},
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'}]}

_F = core.family("orr")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
