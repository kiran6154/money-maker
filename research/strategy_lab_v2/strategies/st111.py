"""ST111 - Strategy 111: Jilly's ORB + Noise Band as the paper-trading spec runs it.

Built 2026-10-25 from the user's jilly_paper_spec.md: Strategy 110 plus the volatility filter (skip a day whose sigma(30)
ranks below 0.20 of the prior 250 sessions); futures 10 x ATR + 1R; options (ATM, 1-ITM) with the stop at the OR midpoint on
the future and a 2R target - the spec's table: futures 787 trades PF 1.276, ATM 575 PF 1.267, 1-ITM 575 PF 1.269. The rules:
strategies/jilly.py. Numbers: STRATEGY_ANALYSIS_TODO S120.
"""
import core

SPEC = {'code': 'ST111',
 'name': 'Jilly ORB + noise band, paper spec (sigma filter; options OR-midpoint stop + 2R) · 1m',
 'description': "The paper-trading configuration: Strategy 110's signals on days whose sigma(09:45) is not in the bottom 20% of the prior 250 sessions. Futures: 10 x ATR stop, 1R, flat 15:20. Options: ATM / 1-ITM weekly bought, the stop at the OR midpoint on the future and a 2R target.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'jilly_orb_noise_v1', 'exit_rule': 'next_choch'},
 'jilly': {'filter': True, 'band_k': 1.25, 'sigma_lb': 20, 'rank_lb': 250, 'rank_min': 120, 'rank_cut': 0.2, 'or_keys': 15, 'atr_n': 9, 'atr_buf': 0.3, 'ck_first': 30, 'ck_last': 285, 'ck_step': 15, 'flatten': '15:20', 'opt_from': '2020-02-01', 'stop_atr': 10, 'target_r': 1, 'opt_stop': 'orm', 'target_r_opt': 2},
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
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
