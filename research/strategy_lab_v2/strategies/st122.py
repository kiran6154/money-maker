"""ST122 - Strategy 122: Strategy 119 on the leg whose 09:15 premium is 100 - 250, not the ATM strike.

Built 2026-10-25 at the user's word ("for the option standalone, stick to an opening range of 100 - 250, not just ATM"): each day,
for the CE and for the PE, the strike nearest the money that opens (09:15) between 100 and 250; the rules then read on that
leg's own chart, both sides. The rules: strategies/jilly_opt.py. Numbers: STRATEGY_ANALYSIS_TODO S128.
"""
import core

SPEC = {'code': 'ST122',
 'name': "Jilly on the option's own chart, both sides, the leg opening at 100 - 250 premium (defaults) · 1m",
 'description': "Strategy 112 on both sides of each leg's own chart: the day-open ATM CE and PE are each bought on their upside breakout (above ORH + 0.3 ATR, UB and VWAP) and sold on their downside breakdown (below ORL - 0.3 ATR, LB and VWAP); stop 10 x the option's ATR, 1R target, flat 15:20.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'jilly_orb_noise_opt_v1', 'exit_rule': 'next_choch'},
 'jilly': {'filter': False, 'band_k': 1.25, 'sigma_lb': 20, 'rank_lb': 250, 'rank_min': 120, 'rank_cut': 0.2, 'or_keys': 15, 'atr_n': 9, 'atr_buf': 0.3, 'ck_first': 30, 'ck_last': 285, 'ck_step': 15, 'flatten': '15:20', 'opt_from': '2020-02-01', 'sides': 'both', 'prem_lo': 100, 'prem_hi': 250, 'prem_steps': 12, 'stop': 'atr', 'stop_atr': 10, 'target_r': 1},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:20', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 0, 'strike_step': 50, 'strike_choices': ['PREM'],
             'strike_default': 'PREM', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'named', 'from': '2018-01-02', 'to': '2026-10-23', 'default': True,
                'notes': 'options from the store, 2020-02 on (the sigma profile warms up on the sessions before)'},
               {'label': '2018-22', 'kind': 'named', 'from': '2018-01-02', 'to': '2022-12-31'},
               {'label': '2023-26', 'kind': 'named', 'from': '2023-01-01', 'to': '2026-10-23'}]}

_F = core.family("jilly_opt")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main, chart_leg = _F.run, _F.chart_main, _F.chart_leg


def signals(bars, spec):
    return _F.signals(bars, spec)
