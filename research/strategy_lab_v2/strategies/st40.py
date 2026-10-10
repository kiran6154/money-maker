"""ST40 - Strategy 40: Strategy 38 (Strategy 3 + five anti-chop filters) with the liquidity filters of Strategy 39 on top.

A SETUP is taken only if it passes every enabled filter of both sets:
  anti-chop (st38.py, SPEC["chop"], unchanged): pair-AVWAP slope size, close beyond the trend AVWAP, age of the broken
            swing, displacement candle (body 0.8 ATR or a close in the outer 30%), pair-AVWAP separation 10 pts
  liquidity (liquidity.py, SPEC["liquidity"], as Strategy 39): sweep ON, displacement ON (body 1 ATR or a fair-value gap),
            equal highs / lows OFF
Stop and exit as Strategy 3. Built 2026-10-11 at the user's request; first numbers: STRATEGY_ANALYSIS_TODO S63.
"""
import numpy as np
import core

_ST38 = core.family("st38")
_LIQ = core.family("liquidity")

SPEC = {'code': 'ST40',
 'name': 'Foundation · 1m · CHoCH on close + anti-chop + liquidity filters',
 'description': "Strategy 38 (Strategy 3 + five anti-chop filters) taken only when the CHoCH also follows a liquidity "
                "sweep and the SETUP candle shows displacement (Strategy 39's filters). Stop and exit as Strategy 3.",
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
          'trend': {'on': True},
          'pivot_age': {'on': True, 'min_bars': 10},
          'displace': {'on': True, 'body_atr': 0.8, 'atr_period': 14, 'close_pct': 30},
          'separation': {'on': True, 'min_pts': 10.0},
          'notes': 'the middle of the ranges in the 2026-10-11 brief, fixed before any run; switch a filter off with on: False'},
 'liquidity': {k: (dict(v) if isinstance(v, dict) else v) for k, v in _LIQ.DEFAULT.items()},
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
    on_l = _LIQ.on_filters(spec)
    keep = [x for x, c, l in zip(eng.trades(), _ST38.verdicts(bars, eng, spec), _LIQ.verdicts(bars, eng, spec))
            if all(c[f] for f in on_c) and all(l[f] for f in on_l)]
    s = eng.with_trades(keep)
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch
    return s
