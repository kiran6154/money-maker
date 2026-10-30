"""ST44 - Strategy 44: Strategy 43 with a sweep of a real extreme before the CHoCH (kept for the record: it does not help).

Strategy 43 unchanged (Strategy 3 + AVWAP slope size + swing age + stop at least 20 pts). One more condition
(strategies/liquidity.py, SPEC["liquidity"]["extreme_sweep"]): within the 30 candles up to the CHoCH candle, a candle went
below the session's low so far or the previous session's low and closed back above it (bullish; highs for bearish).
Validated before it was built (STRATEGY_ANALYSIS_TODO S65, split at 2023-03-09): on Strategy 43's trades the ones with such
a sweep have PF 0.38 / 0.49 on the two halves against 0.56 / 0.53 for the ones without: the sweep marks the worse
trades. Built 2026-10-11 at the user's request so the test is on the page and can be re-run on the option history.
"""
import numpy as np
import core

_ST38 = core.family("st38")
_LIQ = core.family("liquidity")

SPEC = {'code': 'ST44',
 'name': 'Foundation · 1m · ST43 + sweep of the session / previous-day extreme',
 'description': 'Strategy 43 taken only when the CHoCH follows a sweep of a real extreme: within 30 candles a candle took the session low so far or the previous day low (highs for a short) and closed back inside. Stop and exit as Strategy 3.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'chop_risk_xsweep_v1',
           'exit_rule': 'next_choch'},
 'chop': {'slope': {'on': True, 'bars': 6, 'min_pts': 2.0},
          'trend': {'on': False},
          'pivot_age': {'on': True, 'min_bars': 10},
          'displace': {'on': False, 'body_atr': 0.8, 'atr_period': 14, 'close_pct': 30},
          'separation': {'on': False, 'min_pts': 10.0},
          'notes': 'the middle of the ranges in the 2026-10-11 brief, fixed before any run; switch a filter off with on: False'},
 'risk': {'on': True, 'min_pts': 20.0,
          'notes': 'entry to stop in futures points; from the holding-time study (S64), which used the whole history'},
 'liquidity': {'sweep': dict(_LIQ.DEFAULT['sweep'], on=False), 'equal': dict(_LIQ.DEFAULT['equal'], on=False),
               'displace': dict(_LIQ.DEFAULT['displace'], on=False),
               'extreme_sweep': {'on': True, 'lookback': 30, 'session': True, 'prev_day': True},
               'notes': 'fixed 2026-10-11 before the validation run (S65)'},
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


ENTRY_RULES = ("chop_risk_xsweep_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
REFUSED_WHY = _ST38.REFUSED_WHY


def signals(bars, spec):
    """Strategy 43's trades (anti-chop filters + minimum stop distance) that also pass the enabled structural filter."""
    eng = core.foundation(bars, spec["rules"])
    on = [f for f in _ST38.FILTERS if spec["chop"][f]["on"]]; on_l = _LIQ.on_filters(spec)
    R = spec["risk"]
    far = lambda x: (not R["on"]) or (x["sl"] is not None and abs(float(bars.c[x["entry"]]) - x["sl"]) >= R["min_pts"])
    keep = [x for x, v, q in zip(eng.trades(), _ST38.verdicts(bars, eng, spec), _LIQ.verdicts(bars, eng, spec))
            if all(v[f] for f in on) and far(x) and all(q[f] for f in on_l)]
    s = eng.with_trades(keep)
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch
    return s
