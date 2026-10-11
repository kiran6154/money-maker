"""ST65 - Strategy 65: buy the winning leg at the straddle chart's signal, two lots - one out at 20 points, one trailed.

  entry   ANY SETUP on the day-open ATM straddle's candles (its buy signal or its sell signal) -> at that same candle's
          close BUY the winning leg: the CE or the PE with the larger change of its close over SPEC["straddle"]["lookback"]
          candles. TWO lots. No SETUP of the option is waited for. Nothing is ever sold.
  filter  none. "Only above the option's previous-session low" (SPEC["straddle"]["above_prev_low"]) was tried on
          2026-10-11 and switched off again the same day at the user's word (result version 7 shown again): S83
  stop    both lots: 50 points below the entry premium, flat (SPEC["straddle"]["stop"]). Earlier the same day it was
          the option's latest swing low (S78), then its previous CHoCH candle's low less 10% (S79); changed: S81
  lot T1     out at entry + SPEC["straddle"]["two_lots"]["target_pts"] (20) points
  lot TRAIL  its stop does not move until the option has traded at entry + trail_after_pts (20); from then it sits at
             the level of the latest bullish BOS of the option since the entry and follows every later one, never back
  exit    both: the stop, the option's next bearish CHoCH (that candle's close), or the square-off
  gap     a session whose first candle opens above the previous session's high or below its low starts again: that
          chart's structure is built from the session's first candle only (the straddle chart and the option's own
          chart, each on its own gap; SPEC["straddle"]["gap_restart"]; added 2026-10-11: S80)
One entry a leg at a time (free when both lots are out).
Built 2026-10-11 and changed three times the same day at the user's word (long only, not the option's sells; enter at
the straddle signal's candle, not at the option's SETUP; two lots with the stop moved only after 20 points). The numbers
of every build: STRATEGY_ANALYSIS_TODO S78.
"""
import core

SPEC = {'code': 'ST65',
 'name': 'Straddle signal → buy the winning option, 2 lots · one out at 20 pts, one trailed after 20 pts · 1m',
 'description': "Strategy 65's entry (any SETUP on the day-open ATM straddle's candles buys the winning leg at that candle) with two lots: one leaves at +20 points; the other keeps the first stop until the option has traded 20 points up, then its stop follows the option's bullish BOS. First stop: 50 points below the entry premium. Both leave at the stop, the option's next bearish CHoCH or the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'leg_structure', 'lookback': 5, 'window': 'day', 'sides': 'long', 'arm': 'both', 'entry': 'signal', 'above_prev_low': False, 'gap_restart': True, 'stop': {'rule': 'fixed', 'pts': 50}, 'two_lots': {'target_pts': 20, 'trail_after_pts': 20}, 'trail': 'bos_level', 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 1, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'all', 'default': True,
                'notes': 'every session whose day-open ATM pair has full-chain option data (from 2026-06-30)'},
               {'label': 'First half', 'kind': 'named', 'from': '2026-06-30', 'to': '2026-08-12'},
               {'label': 'Second half', 'kind': 'named', 'from': '2026-08-13', 'to': '2026-10-06'},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'}]}

_F = core.family("atm_straddle")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run = _F.run
chart_main = _F.chart_main        # the lab's main chart is the derived straddle candles, with the structure on them


def signals(bars, spec):
    """The futures structure, for the reference chart only; the trades come from the straddle's candles (run)."""
    return _F.signals(bars, spec)
