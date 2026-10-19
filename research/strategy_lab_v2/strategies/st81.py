"""ST81 - Strategy 81: NIFTY regime from CE / PE open interest and price structure.

Built 2026-10-20 from the user's build spec ("NIFTY regime strategy (CE/PE OI + structure)"); the rules, in four separate
pieces (open interest, structure, regime, entries / exits), are in strategies/oi_regime.py and every number is in
SPEC["oi_regime"]. The spec's numbers that were not given (bars for the regime, how tight is tight, the swing pivot, what
upper / lower portion means, the points, the bar cap, the last entry time) are this build's defaults, fixed before any run;
first numbers: STRATEGY_ANALYSIS_TODO S93.
"""
import core

SPEC = {'code': 'ST81',
 'name': 'OI regime (CE / PE OI + structure) · 5m',
 'description': "Regime from the CE and PE open interest of the 3 ATM strikes plus the price structure: both sides written in a tight range = Sideways (sell the top, buy the bottom), CE short buildup in a down structure = BOS down (sell bounces), PE short buildup in an up structure = BOS up (buy dips), CHoCH = flat. Stop and target in points, a bar cap, flat by the square-off.",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'close',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'oi_regime_v1',
           'exit_rule': 'next_choch'},
 'oi_regime': {'strikes': 3, 'expiry_min_days': 0, 'window_min': 30, 'confirm': 2, 'tight_pts': 40, 'pivot_min': 10, 'edge': 0.25,
               'stop_pts': 30, 'target_pts': 30, 'max_min': 60, 'last_entry': '15:10',
               'notes': 'OI: CE / PE dOI of ATM-1 / ATM / ATM+1 of the nearest weekly expiry (the expiry day included), from the 5-minute option files; window_min = minutes of the regime window (6 bars on 5-minute candles, 30 on 1-minute, 2 on 15-minute); confirm = bars in a row before the regime changes; tight_pts = the most the high - low of the window may span for Sideways; pivot_min = minutes each side of a swing (2 bars on 5-minute); edge = the top / bottom share of the range of the window for the Sideways entries; stop / target in points of what is traded; max_min = minutes held at most (12 bars on 5-minute)'},
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
             'strike_default': 'ATM',
             'atr_period': 14},
 'backtests': [{'label': 'OI data', 'kind': 'named', 'from': '2025-08-01', 'to': '2026-10-09', 'default': True,
                'notes': 'the sessions whose option files carry open interest (from August 2025; thinner in September / October 2026)'},
               {'label': 'OI data', 'kind': 'named', 'from': '2025-08-01', 'to': '2026-10-09', 'timeframe': '15minute', 'notes': 'the same rules on 15-minute candles'},
               {'label': 'OI data', 'kind': 'named', 'from': '2025-08-01', 'to': '2026-10-09', 'timeframe': 'minute', 'notes': 'the same rules on 1-minute candles, with the 1-minute option files'},
               {'label': 'OI data', 'kind': 'named', 'from': '2025-08-01', 'to': '2026-10-09', 'underlying': 'INDEX',
                'notes': 'the regime and the structure on the NIFTY index (the spec reads spot); the Futures type trades the near-month contract'},
               {'label': 'First half', 'kind': 'named', 'from': '2025-08-01', 'to': '2026-02-28'},
               {'label': 'Second half', 'kind': 'named', 'from': '2026-03-01', 'to': '2026-10-09'},
               {'label': '3M', 'kind': 'preset', 'preset': '3M'}]}

_F = core.family("oi_regime")
ENTRY_RULES, TYPES, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.REFUSED_WHY
chart_main = _F.chart_main


def signals(bars, spec):
    """The regime trades (strategies/oi_regime.py)."""
    return _F.signals(bars, spec)
