"""ST55 - Strategy 55: Strategy 3 taken only after a same-side signal of the TradingFinder SMLS indicator.

Strategy 3 unchanged (1-minute near-month futures, CHoCH on close, SETUP, stop at the previous swing, exit at the stop or
the next CHoCH, flat by 15:25). A SETUP is taken only if the "Smart Money Liquidity Structure - OB Signal Setups"
indicator (strategies/smls.py, the port of the Pine script the user supplied) fired a signal on the trade's side - a Long
Signal for a long, a Short Signal for a short - on one of the SPEC["smls"]["lookback"] candles up to the SETUP candle.
The port takes each order block as its origin candle's full range (the script's refiner library was not supplied).
Validated before it was built (STRATEGY_ANALYSIS_TODO S69, split at 2023-03-09): on Strategy 3's futures trades PF
0.32 / 0.16 with such a signal within 30 candles (76 / 63 trades) against 0.36 / 0.37 without. It makes Strategy 3 worse.
Built 2026-10-11 at the user's request ("use this along with Strategy 3"); the user's manual TradingView backtest of the
indicator was profitable, the lab's is not: see S69 for what differs.
"""
import core

_SMLS = core.family("smls")

SPEC = {'code': 'ST55',
 'name': 'Foundation · 1m · CHoCH on close + SMLS order-block signal',
 'description': 'Strategy 3 taken only when the TradingFinder Smart Money Liquidity Structure indicator gave a signal on the '
                "trade's side (Long Signal for a long, Short Signal for a short) within the 30 candles up to the SETUP. "
                'Stop and exit as Strategy 3.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'smls_filter_v1',
           'exit_rule': 'next_choch'},
 'smls': {'lookback': 30, 'notes': "the indicator's inputs are the script's defaults (pivots 3 and 9, Midway mode Defensive, "
                                    "block validity 1,000 candles, mitigation at the proximal line); they are constants in strategies/smls.py"},
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


ENTRY_RULES = ("smls_filter_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
REFUSED_WHY = "the indicator is read on the near-month futures chart; standalone options and index signals are not part of it"


def signals(bars, spec):
    """Strategy 3's trades that follow a same-side SMLS signal within the lookback."""
    eng = core.foundation(bars, spec["rules"])
    S = _SMLS.signals_of(bars); n = spec["smls"]["lookback"]
    keep = [x for x in eng.trades() if _SMLS.recent(S["long" if x["dir"] == "up" else "short"], x["entry"], n)]
    s = eng.with_trades(keep)
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch
    return s
