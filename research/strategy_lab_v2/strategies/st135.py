"""ST135 - Strategy 135: the IBS rule: the 15:19 close's place in the day's range, held overnight (one of the user's four Pine rules).

Built 2026-10-26 at the user's word ("create those 4 as strategies here with our backtesting project"). NIFTY near-month
futures from the download store (to 2026-10-23), 1 lot. The rules: strategies/pinerules.py. Numbers: STRATEGY_ANALYSIS_TODO
S142 (standalone and in the combined book) and S143.
"""
import core

SPEC = {'code': 'ST135',
 'name': 'IBS at the close - overnight, out next day 09:16 · 1m',
 'description': "At the 15:19 bar, IBS = (close - session low) / (session high - session low): above 0.7 long, below 0.3 short; in at 15:20, out at the next session's 09:16 open. Not on expiry day or before a weekday holiday.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none', 'entry_rule': 'pine_rules_v1', 'exit_rule': 'next_choch'},
 'pine': {'rule': 'ibs', 'long_above': 0.7, 'short_below': 0.3},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': 'none', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 0, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'named', 'from': '2018-01-02', 'to': '2026-10-23', 'default': True,
                'notes': 'near-month futures from the download store'},
               {'label': '2018-22', 'kind': 'named', 'from': '2018-01-02', 'to': '2022-12-31'},
               {'label': '2023-26', 'kind': 'named', 'from': '2023-01-01', 'to': '2026-10-23'}]}

_F = core.family("pinerules")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
