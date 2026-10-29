"""ST153 - Strategy 153: the handoff "NIFTY Supertrend / CHoCH-BOS option strategies" book G3.

Added 2026-10-29 so the book shows on the dashboard (the user: "not able to see in dashboard"). The trades are nifty_bt's
(research/strategy_lab_v2/nifty_bt, the spec in nifty_bt/spec/); this file only points at its trade list
(strategies/handoff.py). Numbers: STRATEGY_ANALYSIS_TODO S162.
"""
import core

SPEC = {'code': 'ST153',
 'name': 'G3 · Rs100+ SELL · 15m Supertrend + 5m confirm · lock / Rs50',
 'description': "Spec G3: Rs100+ SELL - 15m ST(4,3) + 5m confirm - ST exit - lock50 / Rs50 target. Read on the option's own "
                'chart; one trade at a time per leg.',
 'timeframe': '15minute',
 'underlying': 'INDEX',
 'warmup_days': 1,
 'rules': {'break_mode': 'close',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'handoff_v1',
           'exit_rule': 'next_choch'},
 'handoff': {'source': 'golden', 'file': 'G3', 'side': -1},
 'lot_size': 75,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': None, 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.1},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.1}},
 'options': {'expiry_types': ['WEEKLY', 'MONTHLY'],
             'expiry_min_days': 0,
             'strike_step': 50,
             'strike_choices': ['ATM'],
             'strike_default': 'ATM',
             'atr_period': 14},
 'backtests': [{'label': 'All data',
                'kind': 'named',
                'from': '2018-01-02',
                'to': '2026-10-19',
                'default': True,
                'notes': "nifty_bt's trade list (option contracts from the download store)"},
               {'label': '2018-22', 'kind': 'named', 'from': '2018-01-02', 'to': '2022-12-31'},
               {'label': '2023-26', 'kind': 'named', 'from': '2023-01-01', 'to': '2026-10-19'}]}

_F = core.family("handoff")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
