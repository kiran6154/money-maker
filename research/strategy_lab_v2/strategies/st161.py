"""ST161 - Strategy 161: G2's construction on the option's 1-minute chart, BOS buys, taken only with the dOI regime.

Added 2026-10-30 (the user: "create previous as strategy", after STRATEGY_ANALYSIS_TODO S178). The trades are
tools/oi_regime_book.py's (nifty_bt candidates, the regime from tools/oi_regime.py); this file only points at the trade
list (strategies/handoff.py). Numbers: STRATEGY_ANALYSIS_TODO S178 / S179.
"""
import core

SPEC = {'code': 'ST161',
 'name': 'Rs100+ BUY · 1m Supertrend(10,3) BOS · with the ATM dOI regime',
 'description': "The p100 option of the next expiry (G2's 09:19 pick), Supertrend(10,3) on its 1-minute candles; a BOS of the Supertrend-segment swings buys at the next 1-minute open, stop at the swing, positional, trail + lock50, one open trade per leg. Taken only when the session's cumulative ATM dOI regime agrees at the signal minute (CE: put writing leads; PE: call writing leads).",
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 1,
 'rules': {'break_mode': 'close',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'handoff_v1',
           'exit_rule': 'next_choch'},
 'handoff': {'source': 'books', 'file': '1m_ST10-3_BOS_with_regime', 'side': 1, 'chart': {'chart': 'stswing', 'tf': 1, 'p': 10, 'm': 3.0}},
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
run, chart_main, chart_leg = _F.run, _F.chart_main, _F.chart_leg


def signals(bars, spec):
    return _F.signals(bars, spec)
