"""ST110 - Strategy 110: Jilly's ORB + Noise Band, the script defaults (no volatility filter).

Built 2026-10-25 from the user's jilly_paper_spec.md: the rules of section 1 without the sigma filter - the configuration of the
user's summary table (futures 1,065 trades, PF 1.205; ATM and 1-ITM 817 trades, PF 1.141 / 1.158). Futures: 10 x ATR stop and
1R; options: the same stop and target read on the future (BUILD: the spec does not say which option exits gave its 817-trade
table; ST111 carries the spec's ORM + 2R). The rules: strategies/jilly.py. Numbers: STRATEGY_ANALYSIS_TODO S120.
"""
import core

SPEC = {'code': 'ST110',
 'name': 'Jilly ORB + noise band (script defaults, no vol filter) · 1m',
 'description': 'Near-month futures, 1-minute: at the 09:45 ... 14:00 closes, LONG when the close is above ORH + 0.3 ATR(9, 5m), the noise band UB(key) and VWAP (SHORT the mirror); first signal only; next-bar open. Futures: 10 x ATR stop, 1R target, flat 15:20. Options: ATM / 1-ITM weekly bought, the same stop and target read on the future.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'jilly_orb_noise_v1', 'exit_rule': 'next_choch'},
 'jilly': {'filter': False, 'band_k': 1.25, 'sigma_lb': 20, 'rank_lb': 250, 'rank_min': 120, 'rank_cut': 0.2, 'or_keys': 15, 'atr_n': 9, 'atr_buf': 0.3, 'ck_first': 30, 'ck_last': 285, 'ck_step': 15, 'flatten': '15:20', 'opt_from': '2020-02-01', 'stop_atr': 10, 'target_r': 1, 'opt_stop': 'atr', 'target_r_opt': 1},
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
