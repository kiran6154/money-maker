"""ST146 - Strategy 146: Strategy 138's EMA distance bands corrected for its failure pattern - only with the EMA's own slope, breakeven after 3 x the mean distance.

Built 2026-10-26 at the user's word ("understand the pattern of failure for the EMA strategy, correct it for today's market and test"). NIFTY near-month
futures from the download store (to 2026-10-23), 1 lot. The rules: strategies/pinerules.py. Numbers: STRATEGY_ANALYSIS_TODO
S146.
"""
import core

SPEC = {'code': 'ST146',
 'name': 'EMA 50 distance bands breakout, only with the EMA slope, breakeven after 3x · 5m',
 'description': "Strategy 138 (5-minute EMA 50 +/- 3 x mean distance, a close through a band enters, a close back through the EMA exits) entered only when the EMA itself moved the trade's way over the last hour; once a close is 3 x the mean distance in profit the stop moves to the entry. Chosen on 2018-23 (S146).",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none', 'entry_rule': 'pine_rules_v1', 'exit_rule': 'next_choch'},
 'pine': {'rule': 'emab', 'ema': 50, 'mult': 3.0, 'dlen': 20, 'slope': 'with', 'be': 3.0},
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
