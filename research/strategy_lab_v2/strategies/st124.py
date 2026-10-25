"""ST124 - Strategy 124: the NIFTY gap-and-go -> Williams chain (OptionsBuyer.in's description; research only).

Built 2026-10-26 from the user's pasted spec: the 10% opening-range breakout in the gap's direction (09:46 - 12:00) buys the
150-point ITM weekly option; when it stands down on "opposite_first" or "filled" (and the gap is under 0.2% or 0.5% and above),
the Williams levels (open +/- 0.5 x the previous day's close range, to 14:29) take over. Exits on the premium: stop at 70%,
a trail at 80% of the highest close once above 105%, flat 15:15. The rules: strategies/gapgo.py. Numbers: STRATEGY_ANALYSIS_TODO S132.
"""
import core

SPEC = {'code': 'ST124',
 'name': 'Gap-and-go 10% OR breakout -> Williams levels, 150-point ITM option · 1m',
 'description': "NIFTY spot, 1-minute: the 09:15 - 09:45 close range broken by 10% of its width in the gap's direction (09:46 - 12:00) buys the 150-point ITM weekly option; if the opposite side breaks first or the gap has already filled, the Williams levels (open +/- half of yesterday's close range) take over until 14:29 on gaps under 0.2% or 0.5% and above. Stop -30% on the premium, a 20% trail once +5%, flat 15:15.",
 'timeframe': 'minute',
 'underlying': 'INDEX',
 'warmup_days': 1,
 'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none', 'entry_rule': 'gapgo_williams_v1', 'exit_rule': 'next_choch'},
 'gapgo': {'band': 0.1, 'gng_end': '12:00', 'wk': 0.5, 'wk_end': '14:29', 'itm': 150, 'stop': 0.7, 'arm': 1.05, 'trail': 0.8, 'flatten': '15:15', 'slip_pct': 0.1, 'bots': 'both', 'williams': True},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:15', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 0.5},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY'], 'expiry_min_days': 0, 'strike_step': 50, 'strike_choices': ['ITM150'],
             'strike_default': 'ITM150', 'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'named', 'from': '2018-02-01', 'to': '2026-10-23', 'default': True,
                'notes': 'the index and the store options (the main store from 2018)'},
               {'label': '2018-22', 'kind': 'named', 'from': '2018-02-01', 'to': '2022-12-31'},
               {'label': '2023-26', 'kind': 'named', 'from': '2023-01-01', 'to': '2026-10-23'}]}

_F = core.family("gapgo")
ENTRY_RULES, TYPES, UNDERLYINGS, OWN_COVERAGE, REFUSED_WHY = _F.ENTRY_RULES, _F.TYPES, _F.UNDERLYINGS, _F.OWN_COVERAGE, _F.REFUSED_WHY
run = _F.run


def signals(bars, spec):
    return _F.signals(bars, spec)
