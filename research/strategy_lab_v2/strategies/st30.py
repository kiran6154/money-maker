"""ST30 - Strategy 30: Rainbow ribbon intraday on 5-minute near-month futures: Widner's Rainbow Charts (10 recursive 2-period simple averages of the close); a fresh close outside the ribbon with every faster line beyond the next, oscillator at least 25 (lookback 10), as a re-emergence (price had closed outside on that side within the last 5 candles, came back, and the ribbon's far edge kept its slope) enters at that close (09:20–14:30), one position per contract; exits: 3 lots, stop 50 pts = 1R; from 3R every lot's stop steps up 2R behind the best R reached (no targets); every position flat by 15:25. The variant is the pre-registered grid's pick on Jan 5 – Jun 30 2026 (STRATEGY_ANALYSIS_TODO S53) — every one of the 48 variants lost in that window; this is the one that lost least, kept as the measured answer, not as a recommendation.

Ported from v1 strategies/strategy_30.json; the ribbon rules live in strategies/rainbow.py (shared with the other
rainbow strategy); v2 reproduces v1's trades (tests/test_parity.py).
"""
import core

rainbow = core.family("rainbow")
ENTRY_RULES, TYPES, UNDERLYINGS, REFUSED_WHY = rainbow.ENTRY_RULES, rainbow.TYPES, rainbow.UNDERLYINGS, rainbow.REFUSED_WHY

SPEC = {'code': 'ST30',
 'name': 'Strategy 30',
 'description': "Rainbow ribbon intraday on 5-minute near-month futures: Widner's Rainbow Charts (10 recursive "
                '2-period simple averages of the close); a fresh close outside the ribbon with every faster line '
                'beyond the next, oscillator at least 25 (lookback 10), as a re-emergence (price had closed outside on '
                "that side within the last 5 candles, came back, and the ribbon's far edge kept its slope) enters at "
                'that close (09:20–14:30), one position per contract; exits: 3 lots, stop 50 pts = 1R; from 3R every '
                "lot's stop steps up 2R behind the best R reached (no targets); every position flat by 15:25. The "
                "variant is the pre-registered grid's pick on Jan 5 – Jun 30 2026 (STRATEGY_ANALYSIS_TODO S53) — every "
                'one of the 48 variants lost in that window; this is the one that lost least, kept as the measured '
                'answer, not as a recommendation.',
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'rainbow_v1',
           'exit_rule': 'next_choch'},
 'lot_size': 65,
 'position': {'lots': 3,
              'square_off': '15:25',
              'lock': 'strike',
              'exit': 'position',
              'stop': {'futures_pts': 50, 'option_pct': 5},
              'scale_out': [],
              'trail': {'start_r': 3, 'lag_r': 2}},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY', 'MONTHLY'],
             'expiry_min_days': 1,
             'strike_step': 50,
             'strike_choices': ['ATR2', 'ATM', 'ITM1', 'OTM1'],
             'strike_default': 'ATR2',
             'atr_period': 14},
 'rainbow': {'notes': 'Picked 2026-09-30 by the pre-registered grid (corrected after review) in '
                      'studies/rainbow_grid.py (S53): 48 variants, in sample Jan 5 - Jun 30 2026, out of sample Jul 1 '
                      '- Sep 25 2026; rule = highest in-sample net among variants with >= 30 positions and PF > 1, '
                      "which none met: the highest in-sample net was taken. Every number here is the grid's; the exit "
                      "block is the lab's position handling.",
             'kind': 'widner',
             'levels': 10,
             'period': 2,
             'trigger': 'pullback',
             'fan': 'full',
             'osc_min': 25,
             'lookback': 10,
             'pullback_bars': 5,
             'entry_from': '09:20',
             'entry_until': '14:30',
             'exit': 'none'},
 'backtests': [{'label': 'Design period',
                'kind': 'named',
                'from': '2026-01-05',
                'to': '2026-06-30',
                'notes': "the grid's selection window (S53): in sample for the variant"},
               {'label': 'Unseen test',
                'kind': 'named',
                'from': '2026-07-01',
                'to': '2026-09-25',
                'notes': "never used to pick the variant; read it against the pick's out-of-sample rank in S53"},
               {'label': 'All data', 'kind': 'all', 'notes': 'every session with data, after the warm-up'},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'},
               {'label': '3M', 'kind': 'preset', 'preset': '3M'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'default': True,
                'notes': 'the current month, intraday (every position closed by 15:25)'}]}


def signals(bars, spec):
    """Rainbow ribbon entries (spec['rainbow']); exits are the position block's."""
    return rainbow.signals(bars, spec)
