"""ST41 - Strategy 41: Strategy 3 with one filter: the CHoCH must follow a sweep of liquidity that has stood.

Strategy 3 unchanged underneath (1-minute near-month futures, CHoCH on close; stop at the previous swing; exit at the stop
or the next CHoCH; flat by 15:25). A SETUP is taken only if (strategies/liquidity.py; numbers in SPEC["liquidity"]):
  sweep    ON   within the 30 candles up to the CHoCH candle, a candle took a confirmed swing low (bullish; a swing high
                for bearish) that was formed at least 40 candles before it, and closed back inside
  extreme  OFF  a switch on the sweep: the sweep candle must also be the lowest low / highest high of those 30 candles
  displace OFF  (it failed twice: S62, S63)   equal OFF (kept as a switch)
Strategy 39's sweep counted any swing and passed 99.7% of SETUPs (S63); the 40-candle age is the user's value, fixed
2026-10-11 before any run. Built at the user's request; first numbers: STRATEGY_ANALYSIS_TODO S64.
"""
import core

_LIQ = core.family("liquidity")

SPEC = {'code': 'ST41',
 'name': 'Foundation · 1m · CHoCH on close + sweep of a 40-candle swing',
 'description': 'Strategy 3 taken only when the CHoCH follows a sweep of liquidity that has stood: within 30 candles a '
                'candle took a swing low / high at least 40 candles old and closed back inside. Stop and exit as Strategy 3.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'liq_v1',
           'exit_rule': 'next_choch'},
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


ENTRY_RULES = ("liq_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
REFUSED_WHY = ("the liquidity filters read the near-month futures chart; standalone options and index signals are not "
               "part of it")


def signals(bars, spec):
    """Strategy 3's trades that pass every enabled liquidity filter; the engine's structure stays on the chart."""
    eng = core.foundation(bars, spec["rules"])
    on = [f for f in _LIQ.FILTERS if spec["liquidity"][f]["on"]]
    keep = [x for x, v in zip(eng.trades(), _LIQ.verdicts(bars, eng, spec)) if all(v[f] for f in on)]
    s = eng.with_trades(keep)
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch
    return s
