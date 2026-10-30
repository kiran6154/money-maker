"""ST46 - Strategy 46: Strategy 43 taken only while the Choppiness Index says the market is trending.

Strategy 43 unchanged (Strategy 3 + AVWAP slope size + swing age + stop at least 20 pts). One more condition at the SETUP
candle k, on the same 1-minute candles (SPEC["chop_index"]):
  CHOP(14)[k] < 38.2,  CHOP(n) = 100 * log10( sum of the true range over n candles / (highest high - lowest low of
  those n candles) ) / log10(n).   Above 61.8 = sideways, below 38.2 = trending (the indicator's standard levels).
Validated before it was built (STRATEGY_ANALYSIS_TODO S66, split at 2023-03-09): on Strategy 3 PF 0.53 / 0.49 with it
against 0.31 / 0.33 without; on Strategy 43's trades 0.74 / 0.59 (155 / 175 trades) against 0.29 / 0.47; the share of
trades held under 30 minutes falls from about 50% to 35% / 37%. Still net negative on futures on both halves. The
validation used the whole history, so the futures figures are in-sample.
Built 2026-10-11 at the user's request (an SMC note on telling chop from trend).
"""
import numpy as np
import core

_ST38 = core.family("st38")

SPEC = {'code': 'ST46',
 'name': 'Foundation · 1m · ST43 + Choppiness Index below 38.2 (trending)',
 'description': 'Strategy 43 (Strategy 3 + AVWAP slope size + swing age + stop at least 20 pts) taken only while the '
                '14-candle Choppiness Index is below 38.2 at the SETUP candle: its trending reading. Stop and exit as Strategy 3.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'chop_risk_ci_v1',
           'exit_rule': 'next_choch'},
 'chop': {'slope': {'on': True, 'bars': 6, 'min_pts': 2.0},
          'trend': {'on': False},
          'pivot_age': {'on': True, 'min_bars': 10},
          'displace': {'on': False, 'body_atr': 0.8, 'atr_period': 14, 'close_pct': 30},
          'separation': {'on': False, 'min_pts': 10.0},
          'notes': 'the middle of the ranges in the 2026-10-11 brief, fixed before any run; switch a filter off with on: False'},
 'risk': {'on': True, 'min_pts': 20.0,
          'notes': 'entry to stop in futures points; from the holding-time study (S64), which used the whole history'},
 'chop_index': {'on': True, 'period': 14, 'max': 38.2,
                'notes': "the indicator's standard trend level, on the strategy's own candles at the SETUP candle"},
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


ENTRY_RULES = ("chop_risk_ci_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
REFUSED_WHY = _ST38.REFUSED_WHY


_CI = {}


def chop_index(bars, n):
    """Choppiness Index(n) per candle (nan for the first n - 1), cached per bars object (the entry keeps the object)."""
    key = (id(bars), n)
    if key not in _CI or _CI[key][0] is not bars:
        h, l, c = bars.h, bars.l, bars.c
        pc = np.roll(c, 1); pc[0] = c[0]
        tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
        out = np.full(len(bars), np.nan)
        if len(bars) >= n:
            win = np.lib.stride_tricks.sliding_window_view
            rng = np.maximum(win(h, n).max(axis=1) - win(l, n).min(axis=1), 1e-9)
            out[n - 1:] = 100 * np.log10(win(tr, n).sum(axis=1) / rng) / np.log10(n)
        while len(_CI) > 8: del _CI[next(iter(_CI))]
        _CI[key] = (bars, out)
    return _CI[key][1]


def signals(bars, spec):
    """Strategy 43's trades taken only while the Choppiness Index at the SETUP candle is below its trend level."""
    eng = core.foundation(bars, spec["rules"])
    on = [f for f in _ST38.FILTERS if spec["chop"][f]["on"]]
    R, CI = spec["risk"], spec["chop_index"]
    far = lambda x: (not R["on"]) or (x["sl"] is not None and abs(float(bars.c[x["entry"]]) - x["sl"]) >= R["min_pts"])
    ci = chop_index(bars, CI["period"])
    trending = lambda x: (not CI["on"]) or bool(ci[x["entry"]] < CI["max"])        # nan (too few candles) is not trending
    keep = [x for x, v in zip(eng.trades(), _ST38.verdicts(bars, eng, spec)) if all(v[f] for f in on) and far(x) and trending(x)]
    s = eng.with_trades(keep)
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch
    return s
