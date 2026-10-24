"""ST94 - Strategy 94: Strategy 1's Foundation rules on the day-open ATM options' own 1-minute candles, buys only, each
trade tagged by where its entry premium sits against the same option's previous-session range.

Built 2026-10-25 at the user's request ("extend Foundation 1, apply it on options directly; see how many of the buys are
losses when taken inside the previous day's range"). The rules and the build choices: strategies/foundation_opt.py.
Numbers: STRATEGY_ANALYSIS_TODO S107.
"""
import core

SPEC = {'code': 'ST94',
 'name': 'Foundation on the ATM option itself · buys · previous-day range tagged · 1m',
 'description': "Strategy 1's rules read on each session's day-open ATM CE and PE candles: a bullish SETUP buys the option at that candle's close, out at the previous swing's stop or the next CHoCH, flat 15:25; one trade a leg at a time. Each trade is tagged inside / above / below the same option's previous-session range (recorded, not acted on).",
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'prev_swing',
           'entry_rule': 'foundation_opt_v1', 'exit_rule': 'next_choch'},
 'fopt': {'expiry_min_days': 1, 'sides': 'long',
          'notes': "the nearest weekly expiry at least this many days out; sides: long (the bullish SETUPs buy the option) or both"},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 1, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'Store options', 'kind': 'named', 'from': '2024-09-20', 'to': '2026-10-23', 'default': True,
                'notes': 'the span of the 1-minute options in the download store'},
               {'label': 'First half', 'kind': 'named', 'from': '2024-09-20', 'to': '2025-09-30'},
               {'label': 'Second half', 'kind': 'named', 'from': '2025-10-01', 'to': '2026-10-23'}]}

_F = core.family("foundation_opt")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
