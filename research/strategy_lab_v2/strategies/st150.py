"""ST150 - Strategy 150: Strategy 28 (the user's "Nifty CHoCH to CHoCH in Plain English") on the download store's option data, 2018 on.

Built 2026-10-26: the user sent the spec again ("build this, check if this exists"). It exists as Strategy 28, but its option
prices and OI cover 2026-06-23 - 09-14 only; this runs the same c2c rules with the option side from D:/nifty_data
(strategies/c2c_store.py). Numbers: STRATEGY_ANALYSIS_TODO S147.
"""
import core

c2c = core.family("c2c_store")
ENTRY_RULES, TYPES, TIMEFRAMES, OWN_COVERAGE, REFUSED_WHY, TF_WHY = c2c.ENTRY_RULES, c2c.TYPES, c2c.TIMEFRAMES, c2c.OWN_COVERAGE, c2c.REFUSED_WHY, c2c.TF_WHY

SPEC = {'code': 'ST150',
 'name': 'Put retest · PCR off · touch stops · store options 2018-',
 'description': 'CHoCH to CHoCH put retest on 5-minute candles: after the structure flips bearish (a close through the '
                'protected level and the AVWAP), buy the ITM1 put of the nearest monthly expiry at least 15 days out '
                'when a fresh swing high confirms within 50 pts of the VWAP anchored at the pre-break peak, the day is '
                "not already down 0.6% and this is not the flip candle; enter on the next candle's open, one position "
                'at a time, carried overnight. Exits: a bullish flip; premium stop 5% and a 5-pt trail behind the peak '
                'premium; at 15:15, profit > 40% or loss > 2%. PCR rules off; stops by touch (exit at the stop, at the '
                'open on a gap).',
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
         'stop_fill': 'touch',
         'ladder': {'time': '15:15', 'profit_pct': 40, 'loss_pct': 2},
         'max_open': 1},
 'backtests': [{'label': 'All data', 'kind': 'named', 'from': '2018-01-08', 'to': '2026-10-09', 'default': True,
                'notes': 'the index 5-minute candles; option prices and OI from the download store'},
               {'label': '2018-22', 'kind': 'named', 'from': '2018-01-08', 'to': '2022-12-31'},
               {'label': '2023-26', 'kind': 'named', 'from': '2023-01-01', 'to': '2026-10-09'},
               {'label': 'Option data window', 'kind': 'named', 'from': '2026-06-23', 'to': '2026-09-14',
                'notes': 'the window Strategy 28 has full-chain data for (a cross-check)'}]}


signals, run = c2c.signals, c2c.run      # the engine's structure; the put entries and exits are c2c.run's
