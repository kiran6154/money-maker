"""ST93 - Strategy 93: Strategy 92 with the monthly longs rolled to the next month at 15 days.

Strategy 92 (the fair-value line's side; two next-weekly shorts near 150 and 450 premium rolled weekly at the same strikes;
three monthly longs near 200 premium; marked hourly, +3% / -6% of the margin plus debit). The one change, at the user's
word ("one more: after the 15th, roll the buy to the next month"): when the monthly longs have under 15 days to expiry
they are sold and three of the next monthly at least 18 days out are bought at the strike whose premium then is nearest
200 (SPEC["cagr"]["roll_long"]); the position ends only at the target, the stop, or a roll with no contract. The rules:
strategies/cagr_hedge.py. Numbers: STRATEGY_ANALYSIS_TODO S105.
"""
import core

SPEC = {'code': 'ST93',
 'name': 'Fair-value line → weekly shorts rolled at the same strikes, the monthly longs rolled at 15 days · hourly',
 'description': 'Strategy 92 with the longs rolled too: when the three monthly longs have under 15 days to expiry they are sold and three of the next monthly (at least 18 days out, premium nearest 200) are bought; the weekly shorts keep rolling at the same strikes. The position ends only at +3% / -6% of the margin plus debit (realized plus open), or when a roll has no contract.',
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'cagr_hedge_v1', 'exit_rule': 'next_choch'},
 'cagr': {'base_price': 2000, 'cagr': 0.10, 'entry_time': '09:30', 'steps': ['09:30', '10:30', '11:30', '12:30', '13:30', '14:30', '15:25'],
          'short_premiums': [150, 450], 'long_premium': 200, 'long_lots': 3, 'strike_round': 100, 'premium_tolerance': 75,
          'monthly_min_days': 18, 'long_exit_days': 15, 'target_pct': 3.0, 'stop_pct': 6.0, 'margin_per_short_lot': 150000, 'roll': True, 'roll_long': True,
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
FIXED_HOLDING = "Strategy 93 holds across sessions by its own rule; the square-off is not used"
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
