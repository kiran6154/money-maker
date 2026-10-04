"""ST4 - Strategy 4: Strategy 2 with one change: a CHoCH needs a candle to CLOSE beyond the protected level (and beyond the AVWAP for a trend flip) instead of touching it. Everything else as Strategy 2 — 5-minute candles, swings / BOS by touch, stop at the CHoCH candle.

Ported from v1 strategies/strategy_4.json; v2 reproduces its trades (tests/test_parity.py).
"""
import core

SPEC = {'code': 'ST4',
 'name': 'Foundation · 5m · CHoCH on close',
 'description': 'Strategy 2 with one change: a CHoCH needs a candle to CLOSE beyond the protected level (and beyond '
                'the AVWAP for a trend flip) instead of touching it. Everything else as Strategy 2 — 5-minute candles, '
                'swings / BOS by touch, stop at the CHoCH candle.',
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 5,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'choch_candle',
           'entry_rule': 'setup_v1',
           'exit_rule': 'next_choch'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY', 'MONTHLY'],
             'expiry_min_days': 1,
             'strike_step': 50,
             'strike_choices': ['ATR2', 'ATM', 'ITM2', 'ITM1', 'OTM1', 'OTM2', 'OTM3', 'OTM4'],
             'strike_default': 'ATR2',
             'atr_period': 14,
             'native_scan': {'choices': ['ATR2', 'ATM', 'ITM1', 'OTM1'], 'every_minutes': 5, 'one_per_side': True}},
 'backtests': [{'label': 'All data', 'kind': 'all', 'notes': 'every session with data, after the warm-up'},
               {'label': 'Design period',
                'kind': 'named',
                'from': '2026-08-26',
                'to': '2026-09-25',
                'notes': "the window Strategy 2's rules were built on"},
               {'label': 'Unseen test',
                'kind': 'named',
                'from': '2026-07-08',
                'to': '2026-08-25',
                'notes': 'a window the rules never saw while being built'},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'},
               {'label': '3M', 'kind': 'preset', 'preset': '3M'},
               {'label': 'All data',
                'kind': 'all',
                'underlying': 'INDEX',
                'notes': 'signals on the NIFTY index (equal-weight AVWAP); the Futures type trades the near-month '
                         'contract'},
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'default': True,
                'notes': 'the current month, intraday (every position closed by 15:25)'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'square_off': None,
                'notes': 'positional: held overnight, no square-off'}]}


def signals(bars, spec):
    """Foundation SETUPs on these candles; exits at the stop (rules.sl_rule) or the next CHoCH."""
    return core.foundation(bars, spec["rules"])
