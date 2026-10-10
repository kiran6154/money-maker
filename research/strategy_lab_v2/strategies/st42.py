"""ST42 - Strategy 42: Strategy 3 with the two anti-chop filters that helped and the tightened sweep.

A SETUP is taken only if it passes all three (everything else of Strategy 3 unchanged):
  slope      (st38.py) both pair AVWAPs moved at least 2.0 pts with the trade over the last 6 candles
  pivot_age  (st38.py) the swing whose break made the CHoCH was formed at least 10 candles before it
  sweep      (liquidity.py, as Strategy 41) within 30 candles a candle took a swing low / high at least 40 candles old
             and closed back inside
Off, kept as switches: trend, displacement and separation of Strategy 38 (no effect / wrong sign / a 95% cut: S62),
liquidity displacement and equal level (S63), the sweep's `extreme`.
Values fixed 2026-10-11 before any run. Built at the user's request; first numbers: STRATEGY_ANALYSIS_TODO S64.
"""
import numpy as np
import core

_ST38 = core.family("st38")
_LIQ = core.family("liquidity")

SPEC = {'code': 'ST42',
 'name': 'Foundation · 1m · CHoCH on close + AVWAP slope, swing age & aged sweep',
 'description': 'Strategy 3 taken only when both pair AVWAPs moved 2 pts with the trade over 6 candles, the broken swing '
                'is at least 10 candles old, and the CHoCH follows a sweep of a swing at least 40 candles old (within 30 '
                'candles, closed back inside). Stop and exit as Strategy 3.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'chop_liq_v1',
           'exit_rule': 'next_choch'},
 'chop': {'slope': {'on': True, 'bars': 6, 'min_pts': 2.0},
          'trend': {'on': False},
          'pivot_age': {'on': True, 'min_bars': 10},
          'displace': {'on': False, 'body_atr': 0.8, 'atr_period': 14, 'close_pct': 30},
          'separation': {'on': False, 'min_pts': 10.0},
          'notes': 'the middle of the ranges in the 2026-10-11 brief, fixed before any run; switch a filter off with on: False'},
 'liquidity': {'sweep': {'on': True, 'lookback': 30, 'memory': 240, 'min_age': 40, 'extreme': False},
               'equal': dict(_LIQ.DEFAULT['equal'], on=False),
               'displace': dict(_LIQ.DEFAULT['displace'], on=False),
               'notes': "lookback 30 and min_age 40 are the user's values of 2026-10-11, fixed before any run"},
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
 'backtests': [{'label': 'All data', 'kind': 'all', 'default': True, 'notes': 'every session with data, after the warm-up'},
               {'label': 'Design period',
                'kind': 'named',
                'from': '2026-08-26',
                'to': '2026-09-25',
                'notes': "the window Strategy 1's rules were built on"},
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
                'notes': 'the current month, intraday (every position closed by 15:25)'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'square_off': None,
                'notes': 'positional: held overnight, no square-off'},
               {'label': 'All data', 'kind': 'all', 'underlying': 'INDEX', 'square_off': None}]}


ENTRY_RULES = ("chop_liq_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
REFUSED_WHY = _ST38.REFUSED_WHY


def signals(bars, spec):
    """Strategy 3's trades that pass every enabled anti-chop filter and every enabled liquidity filter."""
    eng = core.foundation(bars, spec["rules"])
    on_c = [f for f in _ST38.FILTERS if spec["chop"][f]["on"]]
    on_l = [f for f in _LIQ.FILTERS if spec["liquidity"][f]["on"]]
    keep = [x for x, c, l in zip(eng.trades(), _ST38.verdicts(bars, eng, spec), _LIQ.verdicts(bars, eng, spec))
            if all(c[f] for f in on_c) and all(l[f] for f in on_l)]
    s = eng.with_trades(keep)
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch
    return s
