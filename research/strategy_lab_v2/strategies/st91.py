"""ST91 - Strategy 91: weekly options sold against a 10% CAGR fair-value line, hedged with monthly longs.

Built 2026-10-24 at the user's request: "assume NIFTY to be 2000 on 1 January 2000; with 10% CAGR get the current price.
One day before the current weekly expiry, at 09:30: if the index is above that price, sell 1 lot each of next-weekly puts
with premium close to 150 and 450 (nearest strike rounded to 100) and buy 3 lots of a monthly put close to 200 premium
(monthly expiry at least 18 days out, else the next monthly). Move in 1-hour steps until the P&L is up 3% or down 6%, or
the next next day is the expiry of the sold options, or the bought options expire under 15 days. Vice versa when below."
The rules and the build choices: strategies/cagr_hedge.py. Numbers: STRATEGY_ANALYSIS_TODO S103.
"""
import core

SPEC = {'code': 'ST91',
 'name': 'Fair-value line (10% CAGR from 2000) → weekly 150 / 450 shorts + 3 monthly 200 longs · hourly',
 'description': "The session before each weekly expiry at 09:30: the index against 2000 × 1.10^years. Above: sell one next-weekly put near 150 and one near 450 premium, buy three monthly puts near 200 (monthly at least 18 days out). Below: the same with calls. Marked hourly; out at +3% / -6% of the margin plus debit, two sessions before the sold expiry, or when the monthly has under 15 days.",
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none',
           'entry_rule': 'cagr_hedge_v1', 'exit_rule': 'next_choch'},
 'cagr': {'base_price': 2000, 'cagr': 0.10, 'entry_time': '09:30', 'steps': ['09:30', '10:30', '11:30', '12:30', '13:30', '14:30', '15:25'],
          'short_premiums': [150, 450], 'long_premium': 200, 'long_lots': 3, 'strike_round': 100, 'premium_tolerance': 75,
          'monthly_min_days': 18, 'long_exit_days': 15, 'target_pct': 3.0, 'stop_pct': 6.0, 'margin_per_short_lot': 150000,
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
FIXED_HOLDING = "Strategy 91 holds across sessions by its own rule; the square-off is not used"
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    return _F.signals(bars, spec)
