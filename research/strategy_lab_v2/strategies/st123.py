"""ST123 - Strategy 123: Strategy 120 (Jilly on both sides of the ATM option's own chart, the sigma filter) with the settings chosen
on 2020 - 2023 only.

Built 2026-10-26 at the user's word ("yes, do a new one") after the settings check (STRATEGY_ANALYSIS_TODO S128): 240 cells
(band width, breakout buffer, opening-range length, stop, target) ranked on 2020-02 → 2023-12 alone; the top cell - band 1.5,
buffer 0.5 ATR, a 30-minute opening range (09:15 - 09:44, so the first checkpoint is the 10:00 close), stop 3 x the option's ATR, 2R -
is this strategy. Its 2024 - 2026 numbers were not used to pick it. Strategy 120 stays the reference. The rules:
strategies/jilly_opt.py. Numbers: STRATEGY_ANALYSIS_TODO S128.
"""
import core

SPEC = {'code': 'ST123',
 'name': "Jilly on the ATM option's own chart, both sides, settings chosen on 2020-23 (band 1.5, buffer 0.5, 30-minute range, 3 x ATR, 2R) · 1m",
 'description': "Strategy 120 with the settings picked on 2020 - 2023 only in a 240-cell sweep: the noise band at 1.5 sigma, the breakout buffer 0.5 ATR, a 30-minute opening range (09:15 - 09:44; the first checkpoint is 10:00), stop 3 x the option's ATR, 2R target; both sides of each ATM leg's own chart, flat 15:20.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'jilly_orb_noise_opt_v1', 'exit_rule': 'next_choch'},
 'jilly': {'filter': True, 'band_k': 1.5, 'sigma_lb': 20, 'rank_lb': 250, 'rank_min': 120, 'rank_cut': 0.2, 'or_keys': 30, 'atr_n': 9, 'atr_buf': 0.5, 'ck_first': 45, 'ck_last': 285, 'ck_step': 15, 'flatten': '15:20', 'opt_from': '2020-02-01', 'sides': 'both', 'stop': 'atr', 'stop_atr': 3, 'target_r': 2},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:20', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 0, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'named', 'from': '2018-01-02', 'to': '2026-10-23', 'default': True,
                'notes': 'options from the store, 2020-02 on (the sigma profile warms up on the sessions before)'},
               {'label': '2018-22', 'kind': 'named', 'from': '2018-01-02', 'to': '2022-12-31'},
               {'label': '2023-26', 'kind': 'named', 'from': '2023-01-01', 'to': '2026-10-23'}]}

_F = core.family("jilly_opt")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main, chart_leg = _F.run, _F.chart_main, _F.chart_leg


def signals(bars, spec):
    return _F.signals(bars, spec)
