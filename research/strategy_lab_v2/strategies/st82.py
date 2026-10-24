"""ST82 - Strategy 82: structure + Order Block retest + the option's previous-day range (the user's document of 2026-10-24).

The rules: strategies/ob_retest.py; every number: SPEC["ob"]. The document's results (55 signals, 32 after its filter,
+58.6 points, profit factor 1.35, no costs) and this build's are compared in STRATEGY_ANALYSIS_TODO S94, with the choices
the document leaves open (how recent the CHoCH must be, which impulse, whether a short buys or sells the PE).
"""
import core

SPEC = {'code': 'ST82',
 'name': 'CHoCH + Order Block retest + option previous-day range · ATM options · 5m',
 'description': "On the NIFTY index 5-minute candles: after a CHoCH, a retest of a fresh Order Block that closes the trade's way is an entry in the ATM option of the nearest weekly expiry - the CE for a long if the CE is at or above its previous-day low, the PE for a short if the PE is below its previous-day low. Stop 40% of the premium, target 1.5R, out after 30 minutes or at 15:00.",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 3,
 'rules': {'break_mode': 'close',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'none',
           'entry_rule': 'ob_retest_v1',
           'exit_rule': 'next_choch'},
 'ob': {'pivot': 5, 'lookback': 10, 'impulse_atr': 0.7, 'rr': 1.5, 'stop_pct': 0.4, 'sell_target': 0.5,
        'start': '09:30', 'last_entry': '15:00', 'flatten': '15:00', 'time_exit_min': 30, 'short_as': 'buy_pe', 'prev_day_filter': True,
        'notes': "the document's parameters; short_as: buy_pe (its section 1: a short buys the PE, with the long exits) or sell_pe (its exit table: the PE is sold, stop x 1.4, target x 0.5)"},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 0, 'strike_step': 50, 'strike_choices': ['ATM'],
             'strike_default': 'ATM', 'atr_period': 14},
 'backtests': [{'label': 'Document period', 'kind': 'named', 'from': '2025-12-01', 'to': '2026-09-30', 'default': True,
                'notes': "the document's test period, Dec 2025 - Sep 2026"},
               {'label': 'First half', 'kind': 'named', 'from': '2025-12-01', 'to': '2026-04-30'},
               {'label': 'Second half', 'kind': 'named', 'from': '2026-05-01', 'to': '2026-09-30'},
               {'label': 'All option data', 'kind': 'named', 'from': '2025-08-01', 'to': '2026-10-09'}]}

_F = core.family("ob_retest")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run, chart_main = _F.run, _F.chart_main


def signals(bars, spec):
    """The futures structure, for the reference chart only; the trades come from run()."""
    return _F.signals(bars, spec)
