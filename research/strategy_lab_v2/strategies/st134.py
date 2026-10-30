"""ST134 - Strategy 134: Alien Algorithms' Institutional Imbalance Framework, Block Failure, on 5-minute near-month futures, both sides, intraday.

Built 2026-10-26 from https://docs.alienalgorithms.com/ at the user's request ("i need profitable strategy from that"). The
indicator is closed-source; the rules as coded, and every number its docs leave open: strategies/iif.py. Numbers:
STRATEGY_ANALYSIS_TODO S131.
"""
import core

SPEC = {'code': 'ST134',
 'name': 'IIF · Block Failure · 5m',
 'description': "A 15-minute OrderBlock broken by a close beyond its break level is read the other way: a broken bullish block sells, a broken bearish one buys, at that close. Stop the block's far edge, target the nearest open 5-minute gap at least 1R away (else 2R); flat 15:25.",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 5,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'choch_candle',
           'entry_rule': 'iif_v1', 'exit_rule': 'own'},
 'iif': {'signal': 'break'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY', 'MONTHLY'], 'expiry_min_days': 1, 'strike_step': 50,
             'strike_choices': ['ATR2', 'ATM', 'ITM2', 'ITM1', 'OTM1', 'OTM2', 'OTM3', 'OTM4'], 'strike_default': 'ATR2',
             'atr_period': 14,
             'native_scan': {'choices': ['ATR2', 'ATM', 'ITM1', 'OTM1'], 'every_minutes': 5, 'one_per_side': True}},
 'backtests': [{'label': 'All data', 'kind': 'all', 'default': True, 'notes': 'every session with data, after the warm-up'},
               {'label': 'First half', 'kind': 'named', 'from': '2018-01-08', 'to': '2022-06-30'},
               {'label': 'Second half', 'kind': 'named', 'from': '2022-07-01', 'to': '2026-10-09'},
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'}]}

_F = core.family("iif")
ENTRY_RULES = _F.ENTRY_RULES
TYPES = ("FUT", "OPT_FUT_SIGNAL")
REFUSED_WHY = "the signals are read on the future's own candles; the option's own chart is not run"


def signals(bars, spec):
    """IIF Block Failure, the counter-trend read (strategies/iif.py)."""
    return _F.signals(bars, spec)
