"""ST92 - Strategy 92: Strategy 91 with the weekly shorts rolled to the next week at the same strikes.

Strategy 91 (the session before each weekly expiry at 09:30, the index against 2000 x 1.10^years: above, sell one
next-weekly put near 150 and one near 450 premium and buy three monthly puts near 200; below, calls; marked hourly). The
one change, at the user's word ("roll to next week with the same strike for the sells"): at the "next next day" step the
two shorts are bought back and the same strikes are sold again on the next weekly expiry; the monthly longs stay; the
position's P&L (realized plus open) decides the +3% / -6%; the position ends there or at the monthly's 15 days
(SPEC["cagr"]["roll"]). The rules: strategies/cagr_hedge.py. Numbers: STRATEGY_ANALYSIS_TODO S104.
"""
import core

SPEC = {'code': 'ST92',
 'name': 'Fair-value line → weekly 150 / 450 shorts rolled weekly at the same strikes + 3 monthly 200 longs · hourly',
 'description': "Strategy 91 with the shorts rolled: two sessions before the sold weekly expiry the two shorts are bought back and the same strikes sold again on the next weekly; the three monthly longs stay. The position's P&L (realized plus open) is marked hourly; out at +3% / -6% of the margin plus debit, or when the monthly has under 15 days.",
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'cagr_hedge_v1', 'exit_rule': 'next_choch'},
 'cagr': {'base_price': 2000, 'cagr': 0.10, 'entry_time': '09:30', 'steps': ['09:30', '10:30', '11:30', '12:30', '13:30', '14:30', '15:25'],
          'short_premiums': [150, 450], 'long_premium': 200, 'long_lots': 3, 'strike_round': 100, 'premium_tolerance': 75,
          'monthly_min_days': 18, 'long_exit_days': 15, 'target_pct': 3.0, 'stop_pct': 6.0, 'margin_per_short_lot': 150000, 'roll': True,
          'notes': 'the P&L base is margin_per_short_lot per short lot plus the long legs premium paid; premium_tolerance: a target premium with no strike within it is a skipped entry'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': None, 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 1, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'Store options', 'kind': 'named', 'from': '2024-09-20', 'to': '2026-10-23', 'default': True,
                'notes': 'the span of the 1-minute options in the download store'},
               {'label': 'First half', 'kind': 'named', 'from': '2024-09-20', 'to': '2025-09-30'},
               {'label': 'Second half', 'kind': 'named', 'from': '2025-10-01', 'to': '2026-10-23'}]}

_F = core.family("cagr_hedge")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
FIXED_HOLDING = "Strategy 92 holds across sessions by its own rule; the square-off is not used"
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
