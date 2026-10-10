"""ST56 - Strategy 56: the TradingFinder SMLS indicator's own signals, traded directly.

No Foundation entry: every "Long Signal" / "Short Signal" of the "Smart Money Liquidity Structure - OB Signal Setups"
indicator (strategies/smls.py, the port of the Pine script the user supplied) on the strategy's candles is a trade:
  entry   the close of the signal candle (the first candle that trades into a new order block)
  stop    the far edge of that order block (its low for a long, its high for a short) = 1R; a signal whose candle closes
          beyond that edge is not taken
  exit    the stop, or flat at 15:25. 1 lot. One position at a time on the contract (the lab's lock).
The port takes each order block as its origin candle's full range (the script's refiner library was not supplied), so a
block can be wider than on the user's chart: the entry can come a little earlier and the stop sit a little further.
rules.sl_rule is not used for the stop (the indicator sets it); it is there because the lab's managed stop reads the
signal's own stop (position.stop.from 'signal').
Validated before it was built (STRATEGY_ANALYSIS_TODO S69): before any cost the signals average +0.2 / +1.7 futures
points a trade on the two halves (split 2023-03-09) with 9% / 11% winners; after the lab's costs every variant loses.
Built 2026-10-11 at the user's request, so each trade can be opened on the chart and compared with TradingView.
"""
import numpy as np
import core

_SMLS = core.family("smls")

SPEC = {'code': 'ST56',
 'name': 'SMLS order-block signals · 1m',
 'description': "The TradingFinder Smart Money Liquidity Structure indicator's own signals: enter at the close of the first "
                "candle that trades into a new order block (Long Signal / Short Signal), stop at the block's far edge, "
                'flat by 15:25; 1 lot.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'choch_candle',
           'entry_rule': 'smls_v1',
           'exit_rule': 'next_choch'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'exit': 'position', 'stop': {'from': 'signal'},
              'scale_out': [], 'trail': None},
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


ENTRY_RULES = ("smls_v1",)
TYPES = ("FUT",)
UNDERLYINGS = ("FUT",)
REFUSED_WHY = ("the indicator's signals and stops are prices of the candles it is read on; here that is the near-month futures "
               "(options and index signals are not part of it)")
CUT = 15 * 3600 + 25 * 60


def signals(bars, spec):
    """One trade per indicator signal: the signal candle's close, with the block's far edge as the stop."""
    eng = core.foundation(bars, spec["rules"])                      # the structure on the chart only; no entry comes from it
    S = _SMLS.signals_of(bars); out = []
    for key, sk, d in (("long", "stop_long", "up"), ("short", "stop_short", "down")):
        for i in np.nonzero(S[key])[0]:
            i = int(i); e = float(bars.c[i]); stop = float(S[sk][i])
            if bars.t[i] % core.DAY >= CUT or not ((stop < e) if d == "up" else (stop > e)): continue
            out.append(dict(entry=i, exit=i, exit_px=e, dir=d, choch=i, sl=stop, pts=0.0, open=True, exit_reason="open"))
    return eng.with_trades(sorted(out, key=lambda x: x["entry"]))
