"""ST39 - Strategy 39: Strategy 3 with liquidity filters on the SETUP (a SETUP that fails an enabled one is not taken).

Strategy 3 unchanged underneath (1-minute near-month futures, CHoCH on close, SETUP = both pair AVWAPs slope with the
CHoCH and a candle closes beyond the CHoCH candle; stop at the previous swing; exit at the stop or the next CHoCH; flat by
15:25). Filters (strategies/liquidity.py; numbers in SPEC["liquidity"]):
  sweep     ON   the CHoCH was preceded, within 30 candles, by a candle that took a confirmed swing low (bullish; a swing
                 high for bearish) and closed back inside
  displace  ON   the SETUP candle's body is at least 1 x ATR(14), or it leaves a fair-value gap in the trade's direction
  equal     OFF  the level the CHoCH broke has a twin swing within 0.25 x ATR(14) (equal highs / lows); built as a switch
Values fixed 2026-10-11 before any run (the brief gave ideas, not numbers). The order-block idea of the brief is not built.
Built at the user's request; first numbers: STRATEGY_ANALYSIS_TODO S63.
"""
import core

_LIQ = core.family("liquidity")

SPEC = {'code': 'ST39',
 'name': 'Foundation · 1m · CHoCH on close + liquidity sweep & displacement',
 'description': 'Strategy 3 taken only when the CHoCH follows a liquidity sweep (a candle within 30 took a swing low '
                '/ high and closed back inside) and the SETUP candle shows displacement (body 1 ATR or a fair-value '
                'gap). Stop and exit as Strategy 3.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'liq_v1',
           'exit_rule': 'next_choch'},
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


ENTRY_RULES = ("liq_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
REFUSED_WHY = ("the liquidity filters read the near-month futures chart; standalone options and index signals are not "
               "part of it")


def signals(bars, spec):
    """Strategy 3's trades that pass every enabled liquidity filter; the engine's structure stays on the chart."""
    eng = core.foundation(bars, spec["rules"])
    on = _LIQ.on_filters(spec)
    keep = [x for x, v in zip(eng.trades(), _LIQ.verdicts(bars, eng, spec)) if all(v[f] for f in on)]
    s = eng.with_trades(keep)
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch
    return s
