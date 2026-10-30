"""ST130 - Strategy 130: Strategy 111, one lot, with the reverse trade when the trade fails.

Built 2026-10-26 at the user's word ("only one lot per side ... if the sell fails, i.e. it goes above green or below red
and sustains, take the reverse trade"; green = LB, red = UB on the Jilly chart). A short (taken below LB) fails when the
future closes back above LB(key) for 3 consecutive 1-minute closes; a long (above UB) when it closes back below UB(key)
3 times - BUILD: "sustains" = 3 closes, the n = 3 the user chose before. The trade is closed at the next open and the
other side taken there with the same stop / target rules, once a day (a reverse does not reverse again). Futures and
options. The rules: strategies/jilly.py (`fail_rev`). Numbers: STRATEGY_ANALYSIS_TODO S137.
"""
import core

SPEC = {'code': 'ST130',
 'name': 'Jilly paper spec + reverse when the trade fails (3 closes back inside UB / LB) · 1m',
 'description': 'Strategy 111, one lot; a long that closes back below UB (red) or a short that closes back above LB (green) for 3 straight 1-minute closes is closed at the next open and the reverse trade taken there, with the same exit rules; once a day.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'jilly_orb_noise_v1', 'exit_rule': 'next_choch'},
 'jilly': {'filter': True, 'band_k': 1.25, 'sigma_lb': 20, 'rank_lb': 250, 'rank_min': 120, 'rank_cut': 0.2, 'or_keys': 15, 'atr_n': 9, 'atr_buf': 0.3, 'ck_first': 30, 'ck_last': 285, 'ck_step': 15, 'flatten': '15:20', 'opt_from': '2020-02-01', 'stop_atr': 10, 'target_r': 1, 'opt_stop': 'orm', 'target_r_opt': 2, 'fail_rev': 3},
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
