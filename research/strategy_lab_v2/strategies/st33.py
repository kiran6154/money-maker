"""ST33 - Strategy 33: Strategy 32's entries with Strategy 9's managed exits.

Entries (Strategy 32, unchanged): Strategy 1's Foundation engine on each option's own 1-minute chart (Options
standalone), a trade taken only with that option's own SMA 200 (long: rising, short: falling, at the entry candle vs the
candle before; rule and numbers in st32.py / SPEC["sma_filter"]).
Exits (Strategy 9, unchanged): 3 lots; stop 5% of the entry premium = 1R; lot 1 out at 1R, lot 2 at 2R; from 3R the last
lot's stop steps up 1R behind the best R reached; no CHoCH exit; flat by 15:25.
Built 2026-10-03 at the user's request ("check st32 with managed exits"); first numbers: STRATEGY_ANALYSIS_TODO S60.
"""
import core

_ST32 = core.family("st32")              # the SMA filter and its chart line, from Strategy 32's own file

TYPES = _ST32.TYPES
REFUSED_WHY = _ST32.REFUSED_WHY

SPEC = {'code': 'ST33',
 'name': 'Foundation on options + SMA-200 · managed exits · 1m',
 'description': "Strategy 32's entries (Foundation on each option's own 1-minute chart, taken only with the option's own "
                "SMA 200: buy while it rises, sell while it falls) with Strategy 9's managed exits: 3 lots, stop 5% of "
                "the entry premium = 1R; lot 1 out at 1R, lot 2 at 2R; from 3R the last lot trails 1R behind the best R. "
                "No CHoCH exit; flat by 15:25.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'setup_v1',
           'exit_rule': 'next_choch'},
 'sma_filter': dict(_ST32.SPEC['sma_filter']),
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
 'backtests': [{'label': 'All data', 'kind': 'all', 'default': True,
                'notes': "every session with full-chain option data (from 2026-06-30); signals on each option's own chart"},
               {'label': 'Design period', 'kind': 'named', 'from': '2026-08-26', 'to': '2026-09-25',
                'notes': "Strategy 1's design window, for reading against Strategies 1, 9 and 32"},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'},
               {'label': 'This month', 'kind': 'preset', 'preset': 'MTD'}]}


def signals(bars, spec):
    """Strategy 1's engine; the SMA filter acts per trade in leg_filter(), the exits are core's managed position."""
    return core.foundation(bars, spec["rules"])


leg_filter = _ST32.leg_filter
option_lines = _ST32.option_lines
