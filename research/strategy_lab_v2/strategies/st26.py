"""ST26 - Strategy 26: CHoCH to CHoCH put retest on 5-minute candles: after the structure flips bearish (a close through the protected level and the AVWAP), buy the ITM1 put of the nearest monthly expiry at least 15 days out when a fresh swing high confirms within 50 pts of the VWAP anchored at the pre-break peak, the day is not already down 0.6% and this is not the flip candle; enter on the next candle's open, one position at a time, carried overnight. Exits: a bullish flip; premium stop 5% and a 5-pt trail behind the peak premium; at 15:15, profit > 40% or loss > 2%. PCR rules off; stops on the candle close (exit at that close).

Ported from v1 strategies/strategy_26.json; the c2c rules live in strategies/c2c.py (shared by ST25-ST28); v2 reproduces v1's trades (tests/test_parity.py).
"""
import core

c2c = core.family("c2c")
ENTRY_RULES, TYPES, TIMEFRAMES, OWN_COVERAGE, REFUSED_WHY, TF_WHY = c2c.ENTRY_RULES, c2c.TYPES, c2c.TIMEFRAMES, c2c.OWN_COVERAGE, c2c.REFUSED_WHY, c2c.TF_WHY

SPEC = {'code': 'ST26',
 'name': 'Strategy 26',
 'description': 'CHoCH to CHoCH put retest on 5-minute candles: after the structure flips bearish (a close through the '
                'protected level and the AVWAP), buy the ITM1 put of the nearest monthly expiry at least 15 days out '
                'when a fresh swing high confirms within 50 pts of the VWAP anchored at the pre-break peak, the day is '
                "not already down 0.6% and this is not the flip candle; enter on the next candle's open, one position "
                'at a time, carried overnight. Exits: a bullish flip; premium stop 5% and a 5-pt trail behind the peak '
                'premium; at 15:15, profit > 40% or loss > 2%. PCR rules off; stops on the candle close (exit at that '
                'close).',
 'timeframe': '5minute',
 'underlying': 'INDEX',
 'warmup_days': 5,
 'rules': {'break_mode': 'close',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'c2c_v1',
           'exit_rule': 'next_choch'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': None, 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['MONTHLY'],
             'expiry_min_days': 15,
             'strike_step': 50,
             'strike_choices': ['ITM1'],
             'strike_default': 'ITM1',
             'atr_period': 14},
 'c2c': {'notes': "every number is from the user's 'Nifty CHoCH to CHoCH in Plain English' spec (2026-09-29), except "
                  'pcr.window_pts / pcr.min_strikes (the local option files hold a strike window, not the full chain: '
                  'STRATEGY_ANALYSIS_TODO S52)',
         'band_pts': 50,
         'day_drop_pct': 0.6,
         'pcr': None,
         'stop_pct': 5,
         'trail_pts': 5,
         'stop_fill': 'close',
         'ladder': {'time': '15:15', 'profit_pct': 40, 'loss_pct': 2},
         'max_open': 1},
 'backtests': [{'label': 'Option data window',
                'kind': 'named',
                'from': '2026-06-23',
                'to': '2026-09-14',
                'default': True,
                'notes': 'the sessions whose nearest monthly >= 15 days out has full-chain option data (Jul-28, Aug-25 '
                         'Breeze; Sep-29 Kite); 07-14..07-21 still lack Aug-25 data'},
               {'label': 'Option data window',
                'kind': 'named',
                'from': '2026-06-23',
                'to': '2026-09-14',
                'underlying': 'FUT',
                'notes': 'signals on the near-month futures (volume-weighted AVWAP) instead of the index'},
               {'label': 'All data',
                'kind': 'all',
                'notes': 'every session; signals whose expiry lacks full-chain data are skipped with the reason'},
               {'label': 'All data', 'kind': 'all', 'underlying': 'FUT', 'notes': 'futures signals, every session'},
               {'label': 'This month', 'kind': 'preset', 'preset': 'MTD'}]}


signals, run = c2c.signals, c2c.run      # the engine's structure; the put entries and exits are c2c.run's
