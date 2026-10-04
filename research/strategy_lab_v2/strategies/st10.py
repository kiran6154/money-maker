"""ST10 - Strategy 10: Strategy 2's entries (5-minute candles: swings, CHoCH by touch, AVWAP pair, SETUP) with managed exits: 3 lots, stop 50 pts (futures) / 5% of the entry premium (options) = 1R; lot 1 out at 1R, lot 2 at 2R; from 3R the last lot's stop steps up 1R behind the best R reached. No CHoCH exit: lots stay open until stop, target, trail or the 15:25 square-off (a positional backtest holds them overnight, to the option's expiry at most). Long and short mirror each other.

Ported from v1 strategies/strategy_10.json; v2 reproduces its trades (tests/test_parity.py).
"""
import core

SPEC = {'code': 'ST10',
 'name': 'Managed exits · 5m',
 'description': "Strategy 2's entries (5-minute candles: swings, CHoCH by touch, AVWAP pair, SETUP) with managed "
                'exits: 3 lots, stop 50 pts (futures) / 5% of the entry premium (options) = 1R; lot 1 out at 1R, lot 2 '
                "at 2R; from 3R the last lot's stop steps up 1R behind the best R reached. No CHoCH exit: lots stay "
                'open until stop, target, trail or the 15:25 square-off (a positional backtest holds them overnight, '
                "to the option's expiry at most). Long and short mirror each other.",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 5,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'setup_v1',
           'exit_rule': 'next_choch'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 3,
              'square_off': '15:25',
              'lock': 'strike',
              'exit': 'position',
              'stop': {'futures_pts': 50, 'option_pct': 5},
              'scale_out': [{'lots': 1, 'target_r': 1}, {'lots': 1, 'target_r': 2}],
              'trail': {'start_r': 3, 'lag_r': 1}},
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
                'notes': "Strategy 2's design window (the exits were not tuned on it)"},
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
                'notes': 'the current month, intraday (every position closed by 15:25)'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'square_off': None,
                'notes': 'positional: held overnight, no square-off'}]}


def signals(bars, spec):
    """Foundation SETUPs on these candles; exits are the position block's (managed stop, targets in R, trail)."""
    return core.foundation(bars, spec["rules"])
