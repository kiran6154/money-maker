"""ST90 - Strategy 90: sell the day-open ATM option when it closes below its own previous-session low; out at a bullish
CHoCH of the option if in loss, else trail the stop at the bounce's top.

Built 2026-10-24 at the user's request ("one more strategy: if an option crosses below the previous day's low, sell; if
CHoCH upside, exit if in loss, else trail"). The rules and the build choices: strategies/pdl_short.py. Numbers:
STRATEGY_ANALYSIS_TODO S102.
"""
import core

SPEC = {'code': 'ST90',
 'name': 'Option below its previous-day low → sell; bullish CHoCH: out if in loss, else trail · 1m',
 'description': "Each session's day-open ATM CE and PE on their own 1-minute candles: a close below the option's previous-session low sells it at the next minute's open. At each bullish CHoCH of the option: in loss, buy back at that close; in profit, trail the stop at the top of the bounce (lowered to each new swing high). Flat at 15:15; one position per leg.",
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'pdl_short_v1', 'exit_rule': 'next_choch'},
 'pdl': {'expiry_min_days': 1,
         'notes': "the nearest weekly expiry at least this many days out; the level is the leg's own previous-session low; the exit rule is fixed (see pdl_short.py)"},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:15', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 1, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'Store options', 'kind': 'named', 'from': '2024-09-20', 'to': '2026-10-23', 'default': True,
                'notes': 'the span of the 1-minute options in the download store'},
               {'label': 'First half', 'kind': 'named', 'from': '2024-09-20', 'to': '2025-09-30'},
               {'label': 'Second half', 'kind': 'named', 'from': '2025-10-01', 'to': '2026-10-23'}]}

_F = core.family("pdl_short")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
