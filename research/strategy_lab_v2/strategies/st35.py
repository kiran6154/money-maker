"""ST35 - Strategy 35: Strategy 34 with the entry on the trend's side of the SMA 200 (the only change).

Entries: Strategy 1's Foundation engine on each option's own 1-minute chart (Options standalone). At the entry candle's
close, on the option's own candles:
  LONG  (buy the option)  only if the close is ABOVE its SMA 200 and the SMA is rising  (SMA[entry] > SMA[entry - 1])
  SHORT (sell the option) only if the close is BELOW its SMA 200 and the SMA is falling (SMA[entry] < SMA[entry - 1])
(Strategy 32 / 33 / 34 checked the slope only.) Every number is in SPEC["sma_filter"].
Stop and exits as Strategy 34: the CHoCH candle's low (long) / high (short) on the option's chart = 1R; 3 lots, lot 1 out
at 1R, lot 2 at 2R, from 3R the last lot trails 1R behind the best R; no CHoCH exit; flat by 15:25.
Built 2026-10-03 at the user's request ("long is above SMA and SMA rising, short is below SMA and SMA falling"); first
numbers: STRATEGY_ANALYSIS_TODO S60.
"""
import numpy as np
import core

_ST32 = core.family("st32")              # the SMA filter and its chart line, from Strategy 32's own file

TYPES = _ST32.TYPES
REFUSED_WHY = _ST32.REFUSED_WHY

SPEC = {'code': 'ST35',
 'name': 'Foundation on options + price & slope of SMA-200 · managed, CHoCH-candle stop · 1m',
 'description': "Strategy 34 with the entry on the trend's side of the option's SMA 200: buy only when the option closes "
                "above its SMA 200 and the SMA is rising; sell only when it closes below and the SMA is falling (Foundation "
                "on each option's own 1-minute chart). Stop at the CHoCH candle's low / high = 1R; 3 lots, lot 1 out at 1R, "
                "lot 2 at 2R, from 3R the last lot trails 1R behind the best R. No CHoCH exit; flat by 15:25.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'choch_candle',
           'entry_rule': 'setup_v1',
           'exit_rule': 'next_choch'},
 'sma_filter': dict(_ST32.SPEC['sma_filter'], price='with_trend',
                    notes="long: close above the SMA and the SMA rising; short: close below it and the SMA falling; "
                          "on the option's own candles at the entry candle"),
 'lot_size': 65,
 'capital': {'futures_margin': 120000, 'short_option_margin': 150000},
 'position': {'lots': 3,
              'square_off': '15:25',
              'lock': 'strike',
              'exit': 'position',
              'stop': {'from': 'signal'},
              'scale_out': [{'lots': 1, 'target_r': 1}, {'lots': 1, 'target_r': 2}],
              'trail': {'start_r': 3, 'lag_r': 1}},
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
                'notes': "every session with full-chain option data (from 2026-06-30); signals on each option's own chart"},
               {'label': 'Design period', 'kind': 'named', 'from': '2026-08-26', 'to': '2026-09-25',
                'notes': "Strategy 1's design window, for reading against Strategies 32 to 34"},
               {'label': '1M', 'kind': 'preset', 'preset': '1M'},
               {'label': 'This month', 'kind': 'preset', 'preset': 'MTD'}]}


def signals(bars, spec):
    """Strategy 1's engine; the SMA filter acts per trade in leg_filter(), the exits are core's managed position."""
    return core.foundation(bars, spec["rules"])


def leg_filter(ctx, rec, s):
    """Strategy 32's slope rule, then the price side: a long needs the entry candle's close above the SMA, a short below."""
    why = _ST32.leg_filter(ctx, rec, s)
    if why or ctx["spec"]["sma_filter"].get("price") != "with_trend": return why
    n = ctx["spec"]["sma_filter"]["period"]
    t = rec["entry_time"]
    i = s.find(t)
    if i < 0: i = int(np.searchsorted(s.t, t, "right")) - 1          # as in Strategy 32: the last candle at or before entry
    v, c = float(_ST32.sma_of(s, n)[i]), float(s.c[i])
    if rec["position"] == "LONG" and not c > v: return f"close {c:g} not above SMA {n} ({v:.2f}) of {rec['instrument']} (long needs it above)"
    if rec["position"] == "SHORT" and not c < v: return f"close {c:g} not below SMA {n} ({v:.2f}) of {rec['instrument']} (short needs it below)"
    return None


option_lines = _ST32.option_lines
