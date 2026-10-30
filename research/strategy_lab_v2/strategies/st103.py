"""ST103 - Strategy 103: Strategy 1's CHoCH / BOS (Foundation on 1-minute futures) with a 20 EMA filter on the SETUP.

Built 2026-10-25 at the user's request ("create new strategy for our choch bos, add 20ema to avoid sideways and wrong
trades. this will avoid multiple trades as well"). Strategy 1 is untouched; this file keeps only the SETUPs that pass the
filter, exactly as ST31 keeps only the ones that match the 1-hour direction.

The filter (every choice is in SPEC["ema_filter"]):
  period   the EMA of the closes of the strategy's own candles (1-minute near-month futures), seeded with the first close,
           computed over the window including its warm-up sessions.
  price    "with_trend": a bullish SETUP is taken only when its entry candle CLOSES above the EMA, a bearish one only when
           it closes below it (the user's "wrong trades": a long under the average, a short above it).
  slope    True: the EMA must also slope the trade's way on the entry candle - its value above (long) / below (short) its
           value one candle before (the user's "sideways": a flat average takes nothing). The slope is read candle to
           candle (the lab's meaning of slope), not over the day.
  candles_min  1 (default): the EMA of the 1-minute closes. 5 / 15: the EMA of the 5- / 15-minute closes (candles built
           from the strategy's own 1-minute candles, 09:15-aligned); at each 1-minute candle the value and the slope are
           those of the last COMPLETED higher candle, so nothing of an unfinished candle is read. The 1-minute default
           hardly filters (S113: a SETUP has just broken its level, so it is nearly always on a 1-minute EMA's side);
           the higher candles are the variants measured there.
Everything else is Strategy 1's: stop at the previous swing, exit at the stop or the next CHoCH, flat by 15:25, the lab's
fills, lock, costs and option types. Numbers against Strategy 1: STRATEGY_ANALYSIS_TODO S113.
"""
import numpy as np
import core

ENTRY_RULES = ("ema_filter_v1",)

SPEC = {'code': 'ST103',
 'name': 'Foundation + 20 EMA filter · 1m',
 'description': "Strategy 1 (CHoCH / BOS on 1-minute futures) with a 20 EMA filter: a bullish SETUP is taken only when its "
                "entry candle closes above the 20 EMA and the EMA is rising on that candle; a bearish one only below a "
                "falling EMA. Stop at the previous swing; exit on the stop or the next CHoCH; flat by 15:25.",
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'ema_filter_v1',
           'exit_rule': 'next_choch'},
 'ema_filter': {'period': 20, 'price': 'with_trend', 'slope': True, 'candles_min': 1,
                'notes': "price: 'with_trend' (close on the EMA's side) or 'none'; slope: the EMA above / below its value "
                         "one candle before, on the entry candle; candles_min: 1 = the EMA of the 1-minute closes, 5 / 15 = "
                         "of the 5- / 15-minute closes, the last completed candle's value at each 1-minute candle"},
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
 'backtests': [{'label': 'All data', 'kind': 'all', 'default': True, 'notes': 'every session with data, after the warm-up'},
               {'label': 'First half', 'kind': 'named', 'from': '2018-01-08', 'to': '2022-06-30'},
               {'label': 'Second half', 'kind': 'named', 'from': '2022-07-01', 'to': '2026-10-09'},
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'},
               {'label': 'This month', 'kind': 'preset', 'preset': 'MTD'}]}


def ema(x, period):
    """EMA of x seeded with x[0] (alpha = 2 / (period + 1))."""
    a = 2.0 / (period + 1); out = np.empty(len(x)); v = float(x[0])
    for i in range(len(x)):
        v = v + a * (float(x[i]) - v); out[i] = v
    return out


def ema_per_bar(bars, F):
    """(EMA value, EMA value one candle before) known at each 1-minute candle's close: of the 1-minute closes, or of the
    last completed `candles_min`-minute candle built from them."""
    period, m = int(F["period"]), int(F.get("candles_min") or 1)
    if m == 1:
        e = ema(bars.c, period); prev = np.r_[np.nan, e[:-1]]
        return e, prev
    t = bars.t; tod = t % core.DAY
    bucket = t - tod + (555 + ((tod // 60 - 555) // m) * m) * 60
    cuts = np.concatenate([[0], np.nonzero(np.diff(bucket))[0] + 1, [len(t)]]); q1 = cuts[1:] - 1
    of = np.repeat(np.arange(len(q1)), np.diff(cuts))                   # the higher candle each bar belongs to
    # a higher candle is complete when a 1-minute candle's end reaches its end, by the clock (not by the next bar's
    # existence, which would read a candle before it is over); the session's last bucket ends at 15:30 like the others
    complete = t + 60 >= bucket + m * 60
    done = np.where(complete, of, of - 1)
    eh = ema(bars.c[q1], period)
    cur = np.where(done >= 0, eh[np.maximum(done, 0)], np.nan)
    prev = np.where(done >= 1, eh[np.maximum(done - 1, 0)], np.nan)
    return cur, prev


def passes(e, ep, c, i, up, F):
    """True if the SETUP entering at candle i, long (up) or short, passes SPEC["ema_filter"] F (EMA e, its previous value ep)."""
    if np.isnan(e[i]): return False
    if F.get("price", "with_trend") == "with_trend" and not ((c[i] > e[i]) if up else (c[i] < e[i])): return False
    if F.get("slope") and not ((e[i] > ep[i]) if up else (e[i] < ep[i])): return False
    return True


def signals(bars, spec):
    """Strategy 1's trades, kept only where the entry candle is on the 20 EMA's side with the EMA sloping that way."""
    F = spec["ema_filter"]
    eng = core.foundation(bars, spec["rules"])
    e, ep = ema_per_bar(bars, F)
    keep = [x for x in eng.trades() if passes(e, ep, bars.c, x["entry"], x["dir"] == "up", F)]
    s = eng.with_trades(keep, [e])
    s.line_names, s.line_colors = [f"EMA {F['period']}"], ["#f5a524"]
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch            # keep the SETUP markers on the chart
    return s


def option_lines(s):
    """The same EMA on an option's own chart, from the option's own candles."""
    return [(f"EMA {SPEC['ema_filter']['period']}", ema_per_bar(s, SPEC["ema_filter"])[0])]
