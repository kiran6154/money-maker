"""ST38 - Strategy 38: Strategy 3 with five anti-chop filters on the SETUP (a SETUP that fails any enabled one is not taken).

Strategy 3 unchanged underneath: 1-minute near-month futures, swings / BOS by touch, a CHoCH needs a close beyond the
protected level, SETUP = both pair AVWAPs slope with the CHoCH and a candle closes beyond the CHoCH candle; stop at the
previous swing; exit at the stop or the next CHoCH (any CHoCH, filtered or not); flat by 15:25.

Filters, all read at the SETUP candle's close k (dir = +1 bullish / -1 bearish); every number is in SPEC["chop"]:
  1 slope      both pair AVWAPs (anchored at the swing high and the swing low the CHoCH carries) moved at least
               min_pts in the trade's direction over the last `bars` candles: dir * (AVWAP[k] - AVWAP[k - bars]) >= min_pts
               (from the anchor candle when the anchor is younger than `bars`)
  2 trend      the close is beyond the trend AVWAP in the new direction: the AVWAP of the trend that was in force when the
               CHoCH printed (the one the engine tests a flip against), valued at k
  3 pivot_age  the swing whose break made the CHoCH was formed at least min_bars candles before the CHoCH candle
  4 displace   the SETUP candle is a displacement candle: |close - open| >= body_atr * ATR(atr_period), or its close is in
               the outer close_pct % of its range on the trade's side
  5 separation the two pair AVWAPs are at least min_pts apart at k
The values are the middle of the ranges in the brief (2026-10-11), fixed before any run; none was tuned on a result.
Thresholds in points are not scaled to the index level (NIFTY 10,000 in 2018, 25,000 in 2026).
Built 2026-10-11 at the user's request; first numbers: STRATEGY_ANALYSIS_TODO S62.
"""
import numpy as np
import core

SPEC = {'code': 'ST38',
 'name': 'Foundation · 1m · CHoCH on close + anti-chop filters',
 'description': 'Strategy 3 with five anti-chop filters on the SETUP: both pair AVWAPs must have moved 2 pts with the '
                'trade over 6 candles, the close must be beyond the trend AVWAP, the broken swing must be at least 10 '
                'candles old, the SETUP candle must show displacement (body 0.8 ATR or a close in the outer 30% of its '
                'range), and the two AVWAPs must be 10 pts apart. Stop and exit as Strategy 3.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'close',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'chop_v1',
           'exit_rule': 'next_choch'},
 'chop': {'slope': {'on': True, 'bars': 6, 'min_pts': 2.0},
          'trend': {'on': True},
          'pivot_age': {'on': True, 'min_bars': 10},
          'displace': {'on': True, 'body_atr': 0.8, 'atr_period': 14, 'close_pct': 30},
          'separation': {'on': True, 'min_pts': 10.0},
          'notes': 'the middle of the ranges in the 2026-10-11 brief, fixed before any run; switch a filter off with on: False'},
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
               {'label': 'Design period',
                'kind': 'named',
                'from': '2026-08-26',
                'to': '2026-09-25',
                'notes': "the window Strategy 1's rules were built on"},
               {'label': 'Unseen test',
                'kind': 'named',
                'from': '2026-07-08',
                'to': '2026-08-25',
                'notes': 'a window the rules never saw while being built'},
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
                'notes': 'the current month, intraday (every position closed by 15:25)'},
               {'label': 'This month',
                'kind': 'preset',
                'preset': 'MTD',
                'square_off': None,
                'notes': 'positional: held overnight, no square-off'},
               {'label': 'All data', 'kind': 'all', 'underlying': 'INDEX', 'square_off': None}]}


ENTRY_RULES = ("chop_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
REFUSED_WHY = ("the anti-chop thresholds are in futures points on the near-month futures chart; standalone options and "
               "index signals are not part of it")
FILTERS = ("slope", "trend", "pivot_age", "displace", "separation")


def verdicts(bars, eng, spec):
    """Per engine trade: {filter: passed?} for every filter (enabled or not), read at the SETUP candle's close."""
    C = spec["chop"]; seg = core.trend_segments(eng); starts = np.array([a for a, _ in seg], dtype=np.int64)
    atr_ = core.atr(bars, C["displace"]["atr_period"])
    cj = {int(c): j for j, c in enumerate(eng.qi)}
    out = []
    for x in eng.trades():
        k, ci = x["entry"], x["choch"]; d = 1 if x["dir"] == "up" else -1; j = cj[ci]
        aH, aL = int(eng.sb[eng.qhi[j]]), int(eng.sb[eng.qlo[j]])
        n = C["slope"]["bars"]
        mv = [d * (eng.av(a, k) - eng.av(a, max(k - n, a))) for a in (aH, aL)]
        v = dict(slope=min(mv) >= C["slope"]["min_pts"])
        q = int(np.searchsorted(starts, ci, "right")) - 1          # the trend AVWAP in force at the CHoCH candle
        v["trend"] = q >= 0 and d * (float(bars.c[k]) - eng.av(seg[q][1], k)) > 0
        v["pivot_age"] = ci - int(eng.sb[eng.qsw[j]]) >= C["pivot_age"]["min_bars"]
        o_, h_, l_, c_ = (float(z[k]) for z in (bars.o, bars.h, bars.l, bars.c)); rng = h_ - l_
        outer = rng > 0 and (((h_ - c_) if d == 1 else (c_ - l_)) / rng * 100 <= C["displace"]["close_pct"])
        v["displace"] = abs(c_ - o_) >= C["displace"]["body_atr"] * float(atr_[k]) or outer
        v["separation"] = abs(eng.av(aH, k) - eng.av(aL, k)) >= C["separation"]["min_pts"]
        out.append(v)
    return out


def signals(bars, spec):
    """Strategy 3's trades that pass every enabled filter; the engine's structure and SETUP markers stay on the chart."""
    eng = core.foundation(bars, spec["rules"])
    on = [f for f in FILTERS if spec["chop"][f]["on"]]
    keep = [x for x, v in zip(eng.trades(), verdicts(bars, eng, spec)) if all(v[f] for f in on)]
    s = eng.with_trades(keep)
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch
    return s
