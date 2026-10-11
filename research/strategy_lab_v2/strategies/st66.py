"""ST66 - Strategy 66: Strategy 1 with the market structure started again on a gap day.

Strategy 1's rules unchanged (swings, protected level, CHoCH / BOS by touch, the AVWAP pair, SETUP; stop at the previous
swing; exit at the stop or the next CHoCH). The one change:
  gap day   a session whose first candle opens SPEC["gap_reset"]["pts"] points or more above or below the previous
            session's last close. On that day the CHoCH / BOS structure is reset: swings, protected level, trend and
            AVWAP anchors are forgotten and built again from the day's first candle (strategies/gap_reset.py).
On other days the structure carries over from the day before, as in Strategy 1.
Built 2026-10-11 from the user's instruction ("extend Strategy 1: if the day's open is more or less by 20 - 30 points,
reset the CHoCH / BOS and start from the day's first candle"). 20 is the build's choice inside the range given; 25 and 30
are measured beside it in STRATEGY_ANALYSIS_TODO S84.
"""
import core

SPEC = {'code': 'ST66',
 'name': 'Foundation · gap-day reset · 1m',
 'description': "Strategy 1 (Foundation rules on 1-minute candles) with one change: on a day that opens 20 points or more away from the previous close, the CHoCH / BOS structure is reset and built again from the day's first candle. Stop at the previous swing; exit on the stop or the next CHoCH.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'setup_v1',
           'exit_rule': 'next_choch'},
 'gap_reset': {'pts': 20, 'notes': 'the day opens this many points or more from the previous close: strategies/gap_reset.py'},
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
 'backtests': [{'label': 'All data', 'kind': 'all', 'notes': 'every session with data, after the warm-up'},
               {'label': 'Design period',
                'kind': 'named',
                'from': '2026-08-26',
                'to': '2026-09-25',
                'notes': 'the rules were built on this window'},
               {'label': 'Unseen test',
                'kind': 'named',
                'from': '2026-07-08',
                'to': '2026-08-25',
                'notes': 'the rules never saw this window while being built'},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'},
               {'label': '3M', 'kind': 'preset', 'preset': '3M'},
               {'label': 'All data',
                'kind': 'all',
                'timeframe': '5minute',
                'notes': 'Strategy 1 rules on 5-minute candles'},
               {'label': 'All data',
                'kind': 'all',
                'underlying': 'INDEX',
                'notes': 'signals on the NIFTY index (equal-weight AVWAP); the Futures type trades the near-month '
                         'contract'},
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'default': True,
                'notes': 'the current month, intraday (every position closed by 15:25)'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'square_off': None,
                'notes': 'positional: held overnight, no square-off'}]}


_G = core.family("gap_reset")


def signals(bars, spec):
    """Foundation SETUPs with the structure started again at every gap day; exits at the stop or the next CHoCH."""
    return _G.foundation(bars, spec["rules"], spec["gap_reset"]["pts"])
