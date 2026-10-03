"""ST32 - Strategy 32: Strategy 1's Foundation entries on options, each leg taken only with its own 200-SMA trend.

Signals: Strategy 1 unchanged (1-minute futures structure for Options via futures; each option's own chart for Options
standalone): every SETUP, stop at the previous swing, exit at the stop or the next CHoCH, flat by 15:25.
Filter, per option leg, on that option's own candles (same timeframe), at the entry candle's close:
  LONG  (buying the option)  only if its SMA(period) is rising:  SMA[entry] > SMA[entry - 1]
  SHORT (selling the option) only if its SMA(period) is falling: SMA[entry] < SMA[entry - 1]
A leg the filter refuses is listed under "not taken" with the reason; it locks nothing. The SMA runs over the contract's
whole series (from its first candle), so it is formed from the 200th candle of the contract; before that the leg is
refused. Every number is in SPEC["sma_filter"]. Futures are not part of it (the rule is about the options' own trend).
"""
import numpy as np
import core

TYPES = ("OPT_FUT_SIGNAL", "OPT_NATIVE")
REFUSED_WHY = "Strategy 32 filters option legs by the option's own 200-SMA; the futures type is not part of it"

SPEC = {'code': 'ST32',
 'name': 'Strategy 32',
 'description': "Strategy 1's Foundation entries on options, each leg taken only with the option's own 200-SMA: "
                'buy the option only while its SMA 200 is rising, sell it only while it is falling (slope at the entry '
                'candle vs the candle before, on the option\'s own 1-minute candles). Stop at the previous swing; exit on '
                'the stop or the next CHoCH; flat by 15:25.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'setup_v1',
           'exit_rule': 'next_choch'},
 'sma_filter': {'period': 200,
                'trend': 'slope',
                'notes': "uptrend = SMA at the entry candle above the SMA one candle before (the instantaneous slope); "
                         "on the option's own candles of the backtest's timeframe; long legs need it rising, short legs falling"},
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
 'backtests': [{'label': 'All data', 'kind': 'all', 'default': True,
                'notes': 'every session with full-chain option data (from 2026-06-30)'},
               {'label': 'Design period', 'kind': 'named', 'from': '2026-08-26', 'to': '2026-09-25',
                'notes': "Strategy 1's design window, for reading against Strategy 1"},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'},
               {'label': 'This month', 'kind': 'preset', 'preset': 'MTD'}]}


def signals(bars, spec):
    """Strategy 1's engine; the SMA filter acts per option leg in leg_filter()."""
    return core.foundation(bars, spec["rules"])


_SMA = {}
def sma_of(s, period):
    """SMA(period) of a series' closes (nan until `period` candles), cached per series."""
    key = (id(s), period, len(s))
    if key not in _SMA:
        c = np.asarray(s.c, float)
        out = np.full(len(c), np.nan)
        if len(c) >= period:
            cs = np.concatenate([[0.0], np.cumsum(c)])
            out[period - 1:] = (cs[period:] - cs[:-period]) / period
        while len(_SMA) > 400: del _SMA[next(iter(_SMA))]
        _SMA[key] = out
    return _SMA[key]


def leg_filter(ctx, rec, s):
    """None to take this option leg, else why not: the option's own SMA must rise for a long, fall for a short, at the
    entry candle's close (the candle at the entry time, or the last one before it that session)."""
    f = ctx["spec"]["sma_filter"]
    n = f["period"]
    if s is None: return f"no candles for {rec['instrument']}"
    t = rec["entry_time"]
    i = s.find(t)
    if i < 0:
        i = int(np.searchsorted(s.t, t, "right")) - 1
        if i < 0 or s.day[i] != t // core.DAY: return f"{rec['instrument']} has no candle at entry"
    sma = sma_of(s, n)
    if i < 1 or np.isnan(sma[i]) or np.isnan(sma[i - 1]):
        return f"SMA {n} not formed yet on {rec['instrument']} ({i + 1} candles)"
    up, down = sma[i] > sma[i - 1], sma[i] < sma[i - 1]
    if rec["position"] == "LONG" and not up: return f"SMA {n} of {rec['instrument']} not rising at entry (long needs it rising)"
    if rec["position"] == "SHORT" and not down: return f"SMA {n} of {rec['instrument']} not falling at entry (short needs it falling)"
    return None


def option_lines(s):
    """The SMA drawn on an option's own chart."""
    return [("SMA %d" % SPEC["sma_filter"]["period"], sma_of(s, SPEC["sma_filter"]["period"]))]
