"""ST43 - Strategy 43: Strategy 3 with the three entry filters that held on both halves of the history.

Strategy 3 unchanged underneath (1-minute near-month futures, CHoCH on close; stop at the previous swing; exit at the stop
or the next CHoCH; flat by 15:25). A SETUP is taken only if it passes all three:
  slope      (st38.py) both pair AVWAPs moved at least 2.0 pts with the trade over the last 6 candles
  pivot_age  (st38.py) the swing whose break made the CHoCH was formed at least 10 candles before it
  risk       the stop is at least 20 pts from the entry: |SETUP close - previous-swing stop| >= SPEC["risk"]["min_pts"]
Off, kept as switches: trend, displacement, separation (S62).
Reference, fixed before this file existed (STRATEGY_ANALYSIS_TODO S64, split at 2023-03-09): PF 0.52 on each half,
305 / 498 trades, 48% / 52% of them held under 30 minutes, net negative on both. The 20 pts came from that study, which
used the whole history: it is not an out-of-sample result, and it is in points, not scaled to the index level.
Built 2026-10-11 at the user's request.
"""
import numpy as np
import core

_ST38 = core.family("st38")

SPEC = {'code': 'ST43',
 'name': 'Foundation · 1m · CHoCH on close + AVWAP slope, swing age & stop ≥ 20 pts',
 'description': 'Strategy 3 taken only when both pair AVWAPs moved 2 pts with the trade over 6 candles, the broken swing '
                'is at least 10 candles old, and the stop (previous swing) is at least 20 pts from the entry. Stop and '
                'exit as Strategy 3.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'chop_risk_v1',
           'exit_rule': 'next_choch'},
 'chop': {'slope': {'on': True, 'bars': 6, 'min_pts': 2.0},
          'trend': {'on': False},
          'pivot_age': {'on': True, 'min_bars': 10},
          'displace': {'on': False, 'body_atr': 0.8, 'atr_period': 14, 'close_pct': 30},
          'separation': {'on': False, 'min_pts': 10.0},
          'notes': 'the middle of the ranges in the 2026-10-11 brief, fixed before any run; switch a filter off with on: False'},
 'risk': {'on': True, 'min_pts': 20.0,
          'notes': 'entry to stop in futures points; from the holding-time study (S64), which used the whole history'},
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


ENTRY_RULES = ("chop_risk_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
REFUSED_WHY = _ST38.REFUSED_WHY


def signals(bars, spec):
    """Strategy 3's trades that pass every enabled anti-chop filter and the minimum stop distance."""
    eng = core.foundation(bars, spec["rules"])
    on = [f for f in _ST38.FILTERS if spec["chop"][f]["on"]]
    R = spec["risk"]
    far = lambda x: (not R["on"]) or (x["sl"] is not None and abs(float(bars.c[x["entry"]]) - x["sl"]) >= R["min_pts"])
    keep = [x for x, v in zip(eng.trades(), _ST38.verdicts(bars, eng, spec)) if all(v[f] for f in on) and far(x)]
    s = eng.with_trades(keep)
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch
    return s
