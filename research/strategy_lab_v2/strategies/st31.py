"""ST31 - Strategy 31: Foundation on 1-minute candles, traded only in the direction of the 1-hour structure.

The Foundation engine runs twice on the near-month futures:
  1-hour   the same engine on 1-hour candles (09:15-aligned, built from the 1-minute file); its CHoCHs give the direction
  1-minute Strategy 1's engine (every SETUP, stop at the previous swing, exit at the stop or the next 1-minute CHoCH)
A 1-minute position is taken only when its direction (bullish = long, bearish = short) matches the 1-hour direction as
known at the close of its entry candle - i.e. from the 1-hour candles that had closed by then (a 1-hour candle closes at
its start + 60 min, the last one of a session at 15:30). Before the first 1-hour CHoCH there is no direction and nothing
is taken. Everything else (fills, stop, exit, square-off, lock, costs, option types) is the lab's, as for Strategy 1.

htf.mode (every number and choice is in SPEC["htf"]):
  last_choch  the direction of the latest 1-hour CHoCH (a break of the 1-hour protected level), flipped or not
  trend       the 1-hour engine's trend: changes only on a CHoCH that flips it (a close through the level and the AVWAP)
"""
import numpy as np
import core

ENTRY_RULES = ("htf_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
REFUSED_WHY = ("the 1-hour filter reads the near-month futures; standalone options (signals on each option's own chart) "
               "and index signals are not part of it")
MODES = ("last_choch", "trend")

SPEC = {'code': 'ST31',
 'name': 'Strategy 31',
 'description': 'Strategy 1 (Foundation on 1-minute candles) taken only in the direction of the 1-hour structure: the '
                'direction of the latest 1-hour CHoCH, from the 1-hour candles closed by the entry. Stop at the previous '
                'swing; exit on the stop or the next 1-minute CHoCH; flat by 15:25.',
 'timeframe': 'minute',
 'underlying': 'FUT',
 'warmup_days': 2,
 'rules': {'break_mode': 'touch',
           'choch_mode': 'touch',
           'avwap_weight': 'volume',
           'sl_rule': 'prev_swing',
           'entry_rule': 'htf_v1',
           'exit_rule': 'next_choch'},
 'htf': {'timeframe': '60minute',
         'mode': 'last_choch',
         'warmup_sessions': 20,
         'rules': {'break_mode': 'touch', 'choch_mode': 'touch', 'avwap_weight': 'volume', 'sl_rule': 'none'},
         'notes': 'the 1-hour engine warms up on 20 sessions before the window (about 140 candles) so its first CHoCH '
                  'is not the first swing of the window'},
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
             'atr_period': 14},
 'backtests': [{'label': 'All data', 'kind': 'all', 'notes': 'every session with data, after the warm-up'},
               {'label': '1Y', 'kind': 'preset', 'preset': '1Y'},
               {'label': 'Design period', 'kind': 'named', 'from': '2026-08-26', 'to': '2026-09-25',
                'notes': "Strategy 1's design window, for reading against Strategy 1"},
               {'label': 'Unseen test', 'kind': 'named', 'from': '2026-07-08', 'to': '2026-08-25'},
               {'label': 'This month', 'kind': 'preset', 'preset': 'MTD', 'default': True}]}


def htf_direction(bars, spec):
    """Per 1-minute candle of `bars`: +1 / -1 / 0, the 1-hour direction known at that candle's close."""
    h = spec["htf"]
    if h["mode"] not in MODES: raise ValueError(f"htf.mode must be one of {MODES}")
    hb_all = core.series("fut", h["timeframe"])
    days = np.unique(hb_all.day)
    k = int(np.searchsorted(days, bars.day[0]))
    d0 = days[max(0, k - h["warmup_sessions"])]
    i0, i1 = int(np.searchsorted(hb_all.day, d0)), int(np.searchsorted(hb_all.day, bars.day[-1], "right"))
    hb = hb_all.slice(i0, i1)
    sg = core.foundation(hb, h["rules"])
    # the direction after each 1-hour candle closes
    n = len(hb)
    dirs = np.zeros(n, np.int8)
    ev = {int(i): (int(d), bool(f)) for i, d, f in zip(sg.qi, sg.qd, sg.qflip)}
    cur = 0
    for i in range(n):
        if i in ev and (h["mode"] == "last_choch" or ev[i][1]): cur = ev[i][0]
        dirs[i] = cur
    # when each 1-hour candle closes: its start + the timeframe, the session's last one at 15:30
    step = core.TF_MIN[h["timeframe"]] * 60
    ends = np.minimum(hb.t + step, hb.day * core.DAY + 15 * 3600 + 30 * 60)
    # a 1-minute candle starting at t closes at t + 60: the 1-hour candles with end <= that are known
    j = np.searchsorted(ends, bars.t + 60, "right") - 1
    out = np.where(j >= 0, dirs[np.maximum(j, 0)], 0)
    return out.astype(np.int8)


def signals(bars, spec):
    """Strategy 1's 1-minute trades, kept only where they point the 1-hour direction at their entry candle's close."""
    eng = core.foundation(bars, spec["rules"])
    hd = htf_direction(bars, spec)
    keep = [x for x in eng.trades() if hd[x["entry"]] == (1 if x["dir"] == "up" else -1)]
    s = eng.with_trades(keep)
    s.ui, s.ud, s.uch = eng.ui, eng.ud, eng.uch            # keep the 1-minute SETUP markers on the chart
    return s
