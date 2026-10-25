"""ST113 - Strategy 113: Jilly's ORB + Noise Band applied directly to the option's own chart, the paper spec's settings.

Strategy 112 with the volatility filter (the leg's sigma(30) rank against the previous 250 sessions) and the OR-midpoint stop
with a 2R target, all read on the option itself. The rules and the choices: strategies/jilly_opt.py. Numbers: STRATEGY_ANALYSIS_TODO S121.
"""
import core

SPEC = {'code': 'ST113',
 'name': "Jilly ORB + noise band on the option's own chart (spec: sigma filter, OR-midpoint stop + 2R) · 1m",
 'description': "Strategy 112 with the paper spec's settings: skip a leg's day when its sigma(09:45) ranks in the bottom 20% of the previous 250 sessions; stop at the leg's own OR midpoint, 2R target, flat 15:20.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'jilly_orb_noise_opt_v1', 'exit_rule': 'next_choch'},
 'jilly': {'filter': True, 'band_k': 1.25, 'sigma_lb': 20, 'rank_lb': 250, 'rank_min': 120, 'rank_cut': 0.2, 'or_keys': 15, 'atr_n': 9, 'atr_buf': 0.3, 'ck_first': 30, 'ck_last': 285, 'ck_step': 15, 'flatten': '15:20', 'opt_from': '2020-02-01', 'stop': 'orm', 'stop_atr': 10, 'target_r': 2},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:20', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 0, 'strike_step': 50, 'strike_choices': ['ATM', 'ITM1'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'named', 'from': '2018-01-02', 'to': '2026-10-23', 'default': True,
                'notes': 'options from the store, 2020-02 on (the sigma profile warms up on the sessions before)'},
               {'label': '2018-22', 'kind': 'named', 'from': '2018-01-02', 'to': '2022-12-31'},
               {'label': '2023-26', 'kind': 'named', 'from': '2023-01-01', 'to': '2026-10-23'}]}

_F = core.family("jilly_opt")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
