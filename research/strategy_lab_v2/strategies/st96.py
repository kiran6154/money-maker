"""ST96 - Strategy 96: volatility.red's "3-5 Candle Drop and Pop MA play" on 5-minute near-month futures, both sides, intraday.

Built 2026-10-25 from https://volatility.red/Basic_Technical_Trading_Strategies at the user's request ("there are strategies
as well, build it in our project and backtest"). The rules as coded, and every number the page leaves open:
strategies/vred.py. Numbers: STRATEGY_ANALYSIS_TODO S112.
"""
import core

SPEC = {'code': 'ST96',
 'name': 'volatility.red · 3-5 Candle Drop and Pop MA play · 5m',
 'description': "Strategy 95's 3 to 5 candle pullback, with the support required to be the rising SMA 20 in the reversal candle's area (its low within 0.5 ATR of the SMA or the SMA inside the candle); the other supports do not count. Same entry, stop, target and trail. Shorts are the mirror. Intraday.",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 3,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'choch_candle',
           'entry_rule': 'vred_v1', 'exit_rule': 'own'},
 'vred': {'setup': 'drop_pop_ma',
          'sides': 'both',
          'sma_fast': 20, 'sma_slow': 50, 'atr': 14, 'pivot_k': 3, 'major_k': 10,
          'run_min': 3, 'run_max': 5, 'retrace_max': 0.6, 'support_band': [0.4, 0.6], 'near_atr': 0.5, 'zone_tol_atr': 0.25,
          'base_min': 6, 'base_max': 20, 'base_atr': 1.5, 'buffer_atr': 0.1,
          'wide_atr': 1.5, 'body_pct': 0.6, 'stall_pct': 0.3, 'stall_max': 3,
          'rally_atr': 3.0, 'cons_min': 2, 'cons_max': 10, 'cons_pct': 0.1,
          'climax_run': 5, 'ext_atr': 2.0, 'retrace_target': 0.5, 'time_stop': 3,
          'lookback': 300, 'trigger_within': 3, 'trail_pct': 0.75, 'trail_after': 1,
          'notes': 'every number the page leaves open; strategies/vred.py PARAMS says which words each stands for'},
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
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'},
               {'label': 'All data', 'kind': 'all', 'square_off': None, 'notes': 'positional: held overnight, no square-off'}]}

_F = core.family("vred")
ENTRY_RULES = _F.ENTRY_RULES


def signals(bars, spec):
    """volatility.red's 3-5 Candle Drop and Pop MA play, long and short, each walked to its stop, target, trail or the square-off (strategies/vred.py)."""
    return _F.signals(bars, spec)


def option_lines(s):
    """The two SMAs on an option's own chart, from the option's own candles."""
    return _F.option_lines(s, SPEC)
