"""ST129 - Strategy 129: Strategy 111's options in three lots - lot 1 out at +20 premium points, lot 2 at +30, lot 3 on the spec's exits.

Built 2026-10-26 at the user's word ("enter 3 lots, exit one at 20 points, exit 2nd at 30 points"; points on the option
premium). Signals, stop (the OR midpoint on the future), 2R target and 15:20 flatten are Strategy 111's; the two targets
are resting limits on the option. Options only. The rules: strategies/jilly.py (`scale_pts`). Numbers: STRATEGY_ANALYSIS_TODO S137.
"""
import core

SPEC = {'code': 'ST129',
 'name': "Jilly paper spec, options in 3 lots: +20 / +30 premium points, the last on the spec's exits · 1m",
 'description': "Strategy 111's options bought as 3 lots: lot 1 sold at +20 premium points, lot 2 at +30 (resting limits), lot 3 on the spec's exits (OR-midpoint stop on the future, 2R, 15:20).",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'jilly_orb_noise_v1', 'exit_rule': 'next_choch'},
 'jilly': {'filter': True, 'band_k': 1.25, 'sigma_lb': 20, 'rank_lb': 250, 'rank_min': 120, 'rank_cut': 0.2, 'or_keys': 15, 'atr_n': 9, 'atr_buf': 0.3, 'ck_first': 30, 'ck_last': 285, 'ck_step': 15, 'flatten': '15:20', 'opt_from': '2020-02-01', 'stop_atr': 10, 'target_r': 1, 'opt_stop': 'orm', 'target_r_opt': 2, 'scale_pts': [20, 30]},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:20', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 0, 'strike_step': 50, 'strike_choices': ['ATM', 'ITM1'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'named', 'from': '2018-01-02', 'to': '2026-10-23', 'default': True,
                'notes': 'futures 2018 on; options from the store (2020-07 on)'},
               {'label': '2018-22', 'kind': 'named', 'from': '2018-01-02', 'to': '2022-12-31'},
               {'label': '2023-26', 'kind': 'named', 'from': '2023-01-01', 'to': '2026-10-23'}]}

_F = core.family("jilly")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, ('OPT_FUT_SIGNAL',), _F.UNDERLYINGS, _F.OWN_COVERAGE, "the 3 lots and their +20 / +30 targets are on the option premium; only the Options type runs"
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
