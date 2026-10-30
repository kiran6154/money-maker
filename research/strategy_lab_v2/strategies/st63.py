"""ST63 - Strategy 63: the straddle chart's long scenario switches Strategy 3 on, on the option's own chart.

Two charts:
  the WHEN and the WHICH   the day-open ATM straddle's candles (Strategy 57's chart, Strategy 3's rules). A bullish SETUP
                           there is the long scenario; it arms the leg that is going up (the CE or the PE with the larger
                           change of its close over SPEC["straddle"]["lookback"] candles). Nothing is traded on it.
  the TRADES               from the next candle, Strategy 3 on THAT OPTION'S OWN candles: swings, protected level, CHoCH,
                           SETUP; a bullish SETUP of the option buys it; stop at the option's previous swing low; exit at
                           the stop or the option's next CHoCH; flat by the square-off. One trade a leg at a time.
SPEC["straddle"]: window "day" = once armed, the leg stays armed to the close; sides "long" = the option is only bought.
Built 2026-10-11 from the user's instruction ("when this long scenario comes, start applying our Strategy 3 on the
options directly and start to trade"). The window and the side are the build's choice, fixed before the run; the other
three combinations are measured in STRATEGY_ANALYSIS_TODO S76, with the first numbers.
"""
import core

SPEC = {'code': 'ST63',
 'name': 'Straddle long scenario → Strategy 3 on the rising option · 1m',
 'description': "A bullish SETUP on the day-open ATM straddle's candles arms the leg (CE or PE) that is going up; from then Strategy 3 runs on that option's own candles and its bullish SETUPs buy the option: stop at the option's previous swing, exit at the stop or its next CHoCH, flat by the square-off.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'straddle_v1',
           'exit_rule': 'next_choch'},
 'straddle': {'mode': 'leg_structure', 'lookback': 5, 'window': 'day', 'sides': 'long', 'notes': 'the day-open ATM pair and its candles: strategies/atm_straddle.py'},
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
