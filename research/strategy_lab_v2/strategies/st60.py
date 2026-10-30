"""ST60 - Strategy 60: both sides of the straddle chart, nothing bought back, a 20 point target on every leg.

The signal chart is Strategy 57's (the day-open ATM straddle's candles, Strategy 3's rules).
  bearish SETUP   SELL the CE and SELL the PE
  bullish SETUP   BUY the one leg that is going up (Strategy 58's definition: the larger change of its close over the last
                  SPEC["straddle"]["lookback"] candles); a short still open is NOT bought back
  target          every leg: SPEC["straddle"]["target_pts"] points on its own premium (short: entry - 20, long: entry + 20),
                  touched on the leg's own 1-minute candles
  stop / exit     as Strategy 3, on the straddle chart: the entry's legs still open leave when that straddle trade's stop
                  (the previous swing of the combined premium) is touched or at the next CHoCH; flat by the square-off
One entry a side at a time; a short entry and a long entry can be open together. 1 lot a leg.
Built 2026-10-11 from the user's instruction ("don't exit any, manage it with buy; keep a 20 points target for all
entries; the stop-loss exit remains the same"; answers: buy the rising leg, target on each leg's own premium, Strategy
3's stop + CHoCH). First numbers: STRATEGY_ANALYSIS_TODO S73.
"""
import core

SPEC = {'code': 'ST60',
 'name': 'Straddle chart · sell both / buy the rising leg · 20 pt target · 1m',
 'description': "Read on the day-open ATM straddle's candles: a bearish SETUP sells the CE and the PE; a bullish SETUP buys the leg that is going up, without buying any short back. Every leg has a 20 point target on its own premium; the legs left leave at Strategy 3's stop or the next CHoCH on the straddle chart, or at the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'both_sides', 'lookback': 5, 'target_pts': 20, 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
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
