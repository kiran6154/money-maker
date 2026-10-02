"""ST15 - Strategy 15: Strategy 1's entries (1-minute), positional, all 3 lots trail: stop 50 pts (futures) / 5% of premium (options) = 1R; no partial exits; from 3R the stop steps up 2R behind the best whole R reached. Best of the 2026 exit study (S50) - chosen in-sample.

Ported from v1 strategies/strategy_15.json; v2 reproduces its trades (tests/test_parity.py).
"""
import core

SPEC = {'code': 'ST15',
 'name': 'Strategy 15',
 'description': "Strategy 1's entries (1-minute), positional, all 3 lots trail: stop 50 pts (futures) / 5% of premium "
                '(options) = 1R; no partial exits; from 3R the stop steps up 2R behind the best whole R reached. Best '
                'of the 2026 exit study (S50) - chosen in-sample.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'setup_v1',
           'exit_rule': 'next_choch'},
 'lot_size': 65,
 'position': {'lots': 3,
              'lock': 'strike',
              'exit': 'position',
              'stop': {'futures_pts': 50, 'option_pct': 5},
              'square_off': None,
              'reverse': None,
              'scale_out': [],
              'trail': {'start_r': 3, 'lag_r': 2}},
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
                'notes': "Strategy 1's design window (the exits were not tuned on it)"},
               {'label': 'Unseen test',
                'kind': 'named',
                'from': '2026-07-08',
                'to': '2026-08-25',
                'notes': 'the rules never saw this window while being built'},
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
                'notes': 'the current month (positional: held overnight)'}]}


def signals(bars, spec):
    """Foundation SETUPs on these candles; exits are the position block's (managed stop, targets in R, trail)."""
    return core.foundation(bars, spec["rules"])
