"""ST67 - Strategy 67: short when a candle closes down through an SMA of the low; 30 point stop, 30 point target; intraday.

On 5-minute candles, with the SMA 20, 50, 100, 200 and 500 of the candle LOW drawn in five colours: a candle closing below
an SMA that the previous candle closed at or above is a SHORT at that close (any of the five), stop 30 points, target 30
points, flat by the square-off. On the futures' own chart and on each option's own chart (the option is sold). The rules
in full: strategies/sma_cross.py.
Built 2026-10-13 from the user's instructions ("add the 20, 50, 100, 200, 500 SMA of the low on 5-minute candles ...
directly on futures and on options"; then "if the SMA is crossed down do a short; stop and profit 30 points; intraday").
Which SMA was not said: any of the five; each alone is measured in STRATEGY_ANALYSIS_TODO S85. From the same day no entry
is taken on the last candle before the square-off (S85, the artefact note).
"""
import core

SPEC = {'code': 'ST67',
 'name': 'SMA-of-low cross down · short · 30 / 30 pts · 5m',
 'description': "On 5-minute candles: when a candle closes down through the SMA 20, 50, 100, 200 or 500 of the candle LOW, go short at that close; stop 30 points, target 30 points, intraday. On the futures' own chart, and on each option's own chart (the option is sold). The five SMAs are drawn in five colours.",
 'timeframe': '5minute',
 'underlying': 'FUT',
 'warmup_days': 8,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'choch_candle',
           'entry_rule': 'sma_cross_v1',
           'exit_rule': 'next_choch'},
 'sma_low': {'periods': [20, 50, 100, 200, 500], 'source': 'low',
             'colors': ['#e5484d', '#f5a524', '#30a46c', '#0090ff', '#8e4ec6'],
             'notes': 'red 20, amber 50, green 100, blue 200, purple 500'},
 'sma_cross': {'periods': [20, 50, 100, 200, 500], 'side': 'short', 'stop_pts': 30, 'target_pts': 30,
               'notes': 'a close below an SMA the previous close was at or above; any of the periods'},
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 1, 'square_off': '15:25', 'lock': 'strike', 'scale_out': []},
 'types': {'FUT': {'charge_code': 'ZERODHA_NFO_FUT', 'slippage_pts': 5.0},
           'OPT_FUT_SIGNAL': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5},
           'OPT_NATIVE': {'charge_code': 'ZERODHA_NFO_OPT', 'slippage_pts': 0.5}},
 'options': {'expiry_types': ['WEEKLY', 'MONTHLY'],
             'expiry_min_days': 1,
             'strike_step': 50,
             'strike_choices': ['ATR2', 'ATM', 'ITM2', 'ITM1', 'OTM1', 'OTM2', 'OTM3', 'OTM4'],
             'strike_default': 'ATR2',
             'atr_period': 14,
             'native_scan': {'choices': ['ATR2', 'ATM', 'ITM1', 'OTM1'], 'every_minutes': 5, 'one_per_side': True}},
 'backtests': [{'label': 'All data', 'kind': 'all', 'notes': 'every session with data, after the warm-up'},
               {'label': 'Design period',
                'kind': 'named',
                'from': '2026-08-26',
                'to': '2026-09-25',
                'notes': 'the rules were built on this window'},
               {'label': 'Unseen test',
                'kind': 'named',
                'from': '2026-07-08',
                'to': '2026-08-25',
                'notes': 'the rules never saw this window while being built'},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'},
               {'label': '3M', 'kind': 'preset', 'preset': '3M'},
               {'label': 'All data',
                'kind': 'all',
                'underlying': 'INDEX',
                'notes': 'signals on the NIFTY index (equal-weight AVWAP); the Futures type trades the near-month '
                         'contract'},
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'default': True,
                'notes': 'the current month, intraday (every position closed by 15:25)'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'square_off': None,
                'notes': 'positional: held overnight, no square-off'}]}


_F = core.family("sma_cross")
ENTRY_RULES = _F.ENTRY_RULES
LINE_COLORS = _F.colors(SPEC)                     # the option charts' colours, by line name


def signals(bars, spec):
    """Shorts at a close down through an SMA of the low (strategies/sma_cross.py)."""
    return _F.signals(bars, spec)


def option_lines(s):
    """The same SMAs on an option's own chart, from the option's own candles."""
    return _F.option_lines(s, SPEC)
