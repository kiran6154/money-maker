"""volatility.red "Basic Technical Trading Strategies" (family module for ST95 - ST102): the eight candle setups of
https://volatility.red/Basic_Technical_Trading_Strategies written as mechanical rules on the candles of what is traded.

The page gives each setup as a description (candle counts, a reversal candle, an entry above its high, a stop under a low,
a target at a prior pivot, trailing "after 75% of the way"); it leaves the moving-average periods as examples, gives no
pivot definition and no size for "wide range", "extended" or "base". Every number the page does not give is a key of
SPEC["vred"] (listed in PARAMS with the page's own words beside it) and is fixed before the first run.

Long side of each setup (the short is the mirror: the same code on negated prices):
  drop_pop        3-5 Candle Drop: 3 to 5 consecutive candles with a lower high AND a lower low (one run, same session);
                  the pullback retraces at most 60% of the prior advance (the last confirmed pivot low to the last confirmed
                  pivot high); support to the left: the pullback low in the 40 - 60% band of that advance, or within
                  `near_atr` x ATR of a confirmed pivot low, or the rising fast SMA inside the reversal candle; trend: fast
                  SMA above slow SMA and the slow SMA rising. Target the prior pivot high.
  drop_pop_ma     the same with the support REQUIRED to be the rising fast SMA in the reversal candle's area (its low within
                  `near_atr` x ATR of the SMA or the SMA inside the candle); the other supports do not count.
  ma_zone         Moving Average Buy Zone: the same run (3 to 5 candles), both SMAs rising, fast above slow, the reversal
                  candle's low between the two SMAs (`zone_tol_atr` x ATR of tolerance either side); retracement <= 60%;
                  target the prior pivot high.
  breakout        a base: the last L candles (6 <= L <= 20, same session) whose whole range is at most `base_atr` x ATR,
                  the base low above the fast SMA, fast SMA above slow; entry above the base high; stop the base low less
                  `buffer_atr` x ATR; target the base high plus the height of the move into the base (the last confirmed
                  pivot low before the base to the base high).
  momentum_stall  a wide-range green candle (range >= `wide_atr` x ATR, body >= `body_pct` of the range) followed by 1 to
                  3 stall candles that stay in its top 30% (low >= high - 0.3 x range) without trading above its high;
                  entry above that high; stop the lowest stall low; target the nearest confirmed pivot high above the
                  entry level (within `lookback` candles), else the wide candle's range projected; trail under every
                  completed candle from the first candle after the entry ("starting after one full candle").
  matched_move    a rally (the last confirmed pivot low to the highest high after it, height H >= `rally_atr` x ATR), then
                  2 to 10 sideways candles not above the rally high with lows no deeper than 10% of H below it, at least
                  one of them red; entry above the rally high; stop the lowest consolidation low; target that low plus H;
                  trail under every completed candle from the first candle after the entry.
  climactic       at least 5 consecutive red candles each with a lower high; the run's low at least `ext_atr` x ATR below
                  the fast SMA ("extended far below the major MA": the page's 2% is a daily-chart number); a green
                  reversal candle; stop the run's low; target the 50% retracement of the decline (the high before the run
                  to its low); if the close `time_stop` candles after the entry is not above the entry, out at that close.
  major_sr        Major Support Buy Zone: at least 3 consecutive red candles with lower highs and lower lows into a major
                  pivot low (`major_k` candles each side) - the reversal candle's low within `near_atr` x ATR of it; stop the
                  lowest low of the approach; target the last major pivot high above. The page's stage 1 / stage 3 (range
                  market) condition has no numeric definition there and is not applied.

Common to every setup:
  reversal candle   green (close above open) and closing in the upper half of its range; the pattern candles are in one session.
  pivots            a confirmed swing: the highest high (lowest low) of `pivot_k` candles either side, known `pivot_k` candles later.
  entry             the first candle within `trigger_within` candles after the signal candle, same session, that trades above
                    the trigger level (the reversal candle's high, the base high, ...) AND closes above it: entry at that
                    candle's CLOSE (the page: a buy-stop above the high; the lab fills at the close of the candle that
                    trades through). A close below the stop level before that voids the setup. One position at a time.
  stop              the setup's level, and for the pullback setups the lower of it and the entry candle's low (the page);
                    touched -> out at the stop, at the open when the candle opens beyond it; checked before the target.
  target            touched -> out at the target (at the open when it opens beyond); the setup is skipped when the target is
                    not above the entry.
  trail             `trail: pct` (the page's "trail once 75% of the way to the target"): once a high has reached entry +
                    `trail_pct` x (target - entry) the stop moves to each completed candle's low, never back;
                    `trail: each` (momentum stall, matched move): the stop moves to each completed candle's low from
                    `trail_after` candles after the entry.
  close             intraday: a position still open at the square-off is closed at that candle's close; no entry at or after it.
Futures: points of the futures. Options via futures: the futures trade's candles, a call for a long and a put for a short.
Options standalone: the same rules on the option's own candles (the chart's SMAs / ATR are of the option).
"""
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
import core

ENTRY_RULES = ("vred_v1",)
SETUPS = ("drop_pop", "drop_pop_ma", "ma_zone", "breakout", "momentum_stall", "matched_move", "climactic", "major_sr")

# every number the page leaves open, with the page's words; a strategy file copies these into SPEC["vred"]
PARAMS = {
    "sma_fast": 20, "sma_slow": 50,          # "the example is a 20 SMA", "the 20 and 50 SMA"
    "atr": 14,                               # the unit for every size the page gives in words
    "pivot_k": 3, "major_k": 10,             # "prior pivot high" / "major support" - no definition on the page
    "run_min": 3, "run_max": 5,              # "3-5 candle", "no more than 5 down candles"
    "retrace_max": 0.60,                     # "no more than 60% of the prior advance"
    "support_band": (0.40, 0.60),            # "40-60% retracement" as support
    "near_atr": 0.5,                         # "in the area of": within this many ATR
    "zone_tol_atr": 0.25,                    # the MA zone's tolerance either side
    "base_min": 6, "base_max": 20, "base_atr": 1.5, "buffer_atr": 0.1,   # "a base or consolidation", "with some buffer"
    "wide_atr": 1.5, "body_pct": 0.6, "stall_pct": 0.30, "stall_max": 3,  # "wide-range candle", "top 30%", "no more than three"
    "rally_atr": 3.0, "cons_min": 2, "cons_max": 10, "cons_pct": 0.10,   # "retrace no more than 10% of the prior rally"
    "climax_run": 5, "ext_atr": 2.0, "retrace_target": 0.5, "time_stop": 3,   # "at least 5", "2% or more", "40-60%", "2-3 candles"
    "lookback": 300,                         # how far back a pivot may be to count
    "trigger_within": 3,                     # candles the entry trigger may take (inside candles allowed on the page)
    "trail_pct": 0.75, "trail_after": 1,     # "trail once 75% of the way", "starting after one full candle"
}
COLORS = {"fast": "#f5a524", "slow": "#0090ff"}


def _sma(x, period):
    out = np.full(len(x), np.nan)
    if len(x) >= period:
        cs = np.concatenate([[0.0], np.cumsum(x)]); out[period - 1:] = (cs[period:] - cs[:-period]) / period
    return out


def _runs(flag, day):
    """Length of the run of consecutive True flags ending at each bar (a session change breaks it)."""
    n = len(flag); out = np.zeros(n, np.int64)
    for i in range(1, n):
        if flag[i]: out[i] = (out[i - 1] + 1) if day[i] == day[i - 1] else 1
    return out


def _pivots(x, k):
    """Confirmed swing highs of x: (bar index, value, bar at which each is known) - the highest of k candles either side."""
    n = len(x)
    if n < 2 * k + 1: return np.empty(0, np.int64), np.empty(0), np.empty(0, np.int64)
    w = sliding_window_view(x, 2 * k + 1); mid = x[k:n - k]
    ok = (mid >= w.max(1)) & (mid > w[:, :k].max(1))
    idx = np.nonzero(ok)[0] + k
    return idx, x[idx], idx + k


class _Piv:
    def __init__(self, x, k):
        self.i, self.v, self.known = _pivots(x, k)

    def last(self, at, before=None):
        """Index into the pivot arrays of the last pivot known by bar `at` (and at a bar <= `before`), else -1."""
        j = int(np.searchsorted(self.known, at, "right")) - 1
        if before is not None:
            while j >= 0 and self.i[j] > before: j -= 1
        return j

    def near(self, at, level, tol, lookback):
        """True if a pivot known by `at`, within `lookback` bars, lies within `tol` of `level`."""
        j = self.last(at)
        while j >= 0 and self.i[j] >= at - lookback:
            if abs(self.v[j] - level) <= tol: return True
            j -= 1
        return False

    def nearest_above(self, at, level, lookback):
        """The lowest pivot value above `level` among the pivots known by `at` within `lookback` bars, else nan."""
        j = self.last(at); best = np.nan
        while j >= 0 and self.i[j] >= at - lookback:
            if self.v[j] > level and not best < self.v[j]: best = self.v[j]
            j -= 1
        return best


def _frame(o, h, l, c, v, day, X):
    """Everything the detectors read, for one orientation of the prices."""
    atr = core._atr(h, l, c, int(X["atr"]))
    return dict(o=o, h=h, l=l, c=c, day=day, n=len(c), atr=atr,
                fast=_sma(c, int(X["sma_fast"])), slow=_sma(c, int(X["sma_slow"])),
                ph=_Piv(h, int(X["pivot_k"])), pl=_Piv(-l, int(X["pivot_k"])),      # pl values are NEGATED lows
                mph=_Piv(h, int(X["major_k"])), mpl=_Piv(-l, int(X["major_k"])),
                rev=(c > o) & ((c - l) >= 0.5 * (h - l)))


def _lower_runs(F, both):
    h, l, c, o, day = F["h"], F["l"], F["c"], F["o"], F["day"]
    f = np.zeros(F["n"], bool)
    k = (h[1:] < h[:-1]) & (day[1:] == day[:-1])
    if both: k &= l[1:] < l[:-1]
    f[1:] = k
    return _runs(f, day)


def _trend(F, i):
    return F["fast"][i] > F["slow"][i] and F["slow"][i] > F["slow"][i - 1]


def _advance(F, i, run_end, n_run, X):
    """(pivot high value, pivot high bar, pivot low value, pullback low, retracement) of the pullback ending at i, or None."""
    ph, pl = F["ph"], F["pl"]
    j = ph.last(i, before=run_end - n_run + 1)
    if j < 0 or ph.i[j] < i - int(X["lookback"]): return None
    q = pl.last(i, before=ph.i[j] - 1)
    if q < 0 or pl.i[q] < i - int(X["lookback"]): return None
    top, bottom = float(ph.v[j]), float(-pl.v[q]); A = top - bottom
    if A <= 0: return None
    low = float(F["l"][run_end - n_run + 1:i + 1].min())
    r = (top - low) / A
    if not (0 < r <= float(X["retrace_max"])) or F["h"][i] >= top: return None
    return top, int(ph.i[j]), bottom, low, r


def _pullback_setups(F, X, kind):
    """drop_pop / drop_pop_ma / ma_zone: candidates at each reversal candle ending a 3 - 5 candle run."""
    run = _lower_runs(F, both=True); out = []
    rmin, rmax = int(X["run_min"]), int(X["run_max"]); near = float(X["near_atr"]); tol = float(X["zone_tol_atr"])
    lo_b, hi_b = X["support_band"]
    fast, slow, l, h, atr = F["fast"], F["slow"], F["l"], F["h"], F["atr"]
    for i in np.nonzero(F["rev"])[0]:
        i = int(i)
        if i < 2 or np.isnan(slow[i]) or not _trend(F, i): continue
        end = i if run[i] else i - 1
        n_run = int(run[end])
        if not (rmin <= n_run <= rmax) or F["day"][end] != F["day"][i]: continue
        adv = _advance(F, i, end, n_run, X)
        if adv is None: continue
        top, _, _, low, r = adv
        ma_touch = fast[i] > fast[i - 1] and (abs(l[i] - fast[i]) <= near * atr[i] or l[i] <= fast[i] <= h[i])
        if kind == "drop_pop":
            if not (lo_b <= r <= hi_b or F["pl"].near(i, -low, near * atr[i], int(X["lookback"])) or ma_touch): continue
        elif kind == "drop_pop_ma":
            if not ma_touch: continue
        else:                                                            # ma_zone: the low between the two rising SMAs
            if not (fast[i] > fast[i - 1] and slow[i] - tol * atr[i] <= l[i] <= fast[i] + tol * atr[i]): continue
        out.append(dict(sig=i, trigger=float(h[i]), stop=float(l[i]), target=top, entry_low=True, trail="pct"))
    return out


def _breakout_setups(F, X):
    h, l, c, day, fast, slow, atr = F["h"], F["l"], F["c"], F["day"], F["fast"], F["slow"], F["atr"]
    n = F["n"]; out = []
    bmin, bmax = int(X["base_min"]), int(X["base_max"]); batr, buf = float(X["base_atr"]), float(X["buffer_atr"])
    hi = {L: np.full(n, np.nan) for L in range(bmin, bmax + 1)}; lo = {L: np.full(n, np.nan) for L in range(bmin, bmax + 1)}
    for L in hi:
        if n >= L:
            hi[L][L - 1:] = sliding_window_view(h, L).max(1); lo[L][L - 1:] = sliding_window_view(l, L).min(1)
    first = np.nonzero(np.r_[True, day[1:] != day[:-1]])[0]           # first bar of each session
    sess0 = np.repeat(first, np.diff(np.r_[first, n]))
    for i in range(bmax, n):
        if np.isnan(slow[i]) or not fast[i] > slow[i]: continue
        best = 0
        for L in range(bmax, bmin - 1, -1):                               # the longest base ending here
            if i - L + 1 < sess0[i]: continue
            if hi[L][i] - lo[L][i] <= batr * atr[i]: best = L; break
        if not best: continue
        bh, bl = float(hi[best][i]), float(lo[best][i])
        if not bl > fast[i]: continue
        q = F["pl"].last(i, before=i - best)
        if q < 0 or F["pl"].i[q] < i - int(X["lookback"]): continue
        height = bh - float(-F["pl"].v[q])
        if height <= 0: continue
        out.append(dict(sig=i, trigger=bh, stop=bl - buf * atr[i], target=bh + height, entry_low=False, trail="pct"))
    return out


def _stall_setups(F, X):
    o, h, l, c, day, atr = F["o"], F["h"], F["l"], F["c"], F["day"], F["atr"]; n = F["n"]; out = []
    wide, body, sp, smax, lb = float(X["wide_atr"]), float(X["body_pct"]), float(X["stall_pct"]), int(X["stall_max"]), int(X["lookback"])
    rng = h - l
    wide_i = np.nonzero((c > o) & (rng >= wide * atr) & ((c - o) >= body * rng))[0]
    for w in wide_i:
        w = int(w); top = float(h[w]); floor = top - sp * float(rng[w]); lows = []
        for i in range(w + 1, min(w + 1 + smax, n)):
            if day[i] != day[w] or h[i] > top or l[i] < floor: break
            lows.append(float(l[i]))
            tgt = F["ph"].nearest_above(i, top, lb)
            if np.isnan(tgt): tgt = top + float(rng[w])
            out.append(dict(sig=i, trigger=top, stop=min(lows), target=tgt, entry_low=False, trail="each"))
    return out


def _matched_setups(F, X):
    h, l, c, o, day, atr = F["h"], F["l"], F["c"], F["o"], F["day"], F["atr"]; n = F["n"]; out = []
    cmin, cmax, cpct, ratr, lb = int(X["cons_min"]), int(X["cons_max"]), float(X["cons_pct"]), float(X["rally_atr"]), int(X["lookback"])
    pl = F["pl"]
    for i in range(cmin, n):
        q = pl.last(i)
        if q < 0 or pl.i[q] < i - lb: continue
        a = int(pl.i[q]); bottom = float(-pl.v[q])
        for m in range(cmin, cmax + 1):                                 # the consolidation: the last m candles
            s = i - m + 1
            if s <= a + 1 or day[s] != day[i]: break
            R = float(h[a:s].max()); H = R - bottom
            if H < ratr * atr[i]: break
            seg_h, seg_l = h[s:i + 1], l[s:i + 1]
            if seg_h.max() > R or seg_l.min() < R - cpct * H: continue
            if not np.any(c[s:i + 1] < o[s:i + 1]): continue
            low = float(seg_l.min())
            out.append(dict(sig=i, trigger=R, stop=low, target=low + H, entry_low=False, trail="each"))
            break
    return out


def _climactic_setups(F, X):
    h, l, c, o, day, fast, atr = F["h"], F["l"], F["c"], F["o"], F["day"], F["fast"], F["atr"]; out = []
    red = np.zeros(F["n"], bool); red[1:] = (c[1:] < o[1:]) & (h[1:] < h[:-1]) & (day[1:] == day[:-1])
    run = _runs(red, day); need, ext, rt, ts = int(X["climax_run"]), float(X["ext_atr"]), float(X["retrace_target"]), int(X["time_stop"])
    for i in np.nonzero(F["rev"])[0]:
        i = int(i)
        if i < need + 2 or run[i - 1] < need or day[i - 1] != day[i] or np.isnan(fast[i]): continue
        n_run = int(run[i - 1]); s = i - n_run
        low = float(l[s:i + 1].min())
        if not low <= fast[i] - ext * atr[i]: continue
        top = float(max(h[s - 1], h[s]))
        out.append(dict(sig=i, trigger=float(h[i]), stop=low, target=low + rt * (top - low), entry_low=False, trail="pct", time_stop=ts))
    return out


def _major_setups(F, X):
    h, l, c, o, day, atr = F["h"], F["l"], F["c"], F["o"], F["day"], F["atr"]; out = []
    f = np.zeros(F["n"], bool); f[1:] = (c[1:] < o[1:]) & (h[1:] < h[:-1]) & (l[1:] < l[:-1]) & (day[1:] == day[:-1])
    run = _runs(f, day); rmin, near, lb = int(X["run_min"]), float(X["near_atr"]), int(X["lookback"])
    mpl, mph = F["mpl"], F["mph"]
    for i in np.nonzero(F["rev"])[0]:
        i = int(i)
        if i < rmin + 1 or run[i - 1] < rmin or day[i - 1] != day[i]: continue
        if not mpl.near(i, -float(l[i]), near * atr[i], lb): continue
        j = mph.last(i)
        if j < 0 or mph.i[j] < i - lb or not mph.v[j] > h[i]: continue
        s = i - int(run[i - 1])
        out.append(dict(sig=i, trigger=float(h[i]), stop=float(l[s:i + 1].min()), target=float(mph.v[j]), entry_low=False, trail="pct"))
    return out


_DETECT = {"drop_pop": lambda F, X: _pullback_setups(F, X, "drop_pop"),
           "drop_pop_ma": lambda F, X: _pullback_setups(F, X, "drop_pop_ma"),
           "ma_zone": lambda F, X: _pullback_setups(F, X, "ma_zone"),
           "breakout": _breakout_setups, "momentum_stall": _stall_setups, "matched_move": _matched_setups,
           "climactic": _climactic_setups, "major_sr": _major_setups}


def _walk(F, cands, X, t, sq, mirror):
    """Candidates -> trades (long side of F; `mirror` maps the prices back for the short side)."""
    o, h, l, c, day, n = F["o"], F["h"], F["l"], F["c"], F["day"], F["n"]
    W, tp, ta = int(X["trigger_within"]), float(X["trail_pct"]), int(X["trail_after"])
    trades, free = [], -1
    for cd in sorted(cands, key=lambda d: d["sig"]):
        i = cd["sig"]
        if i <= free: continue
        ent = -1
        for k in range(i + 1, min(i + 1 + W, n)):
            if day[k] != day[i] or c[k] < cd["stop"]: break
            if h[k] > cd["trigger"] and c[k] > cd["trigger"]: ent = k; break
        if ent < 0: continue
        e = float(c[ent]); cut = core.square_off_at(sq, int(t[ent]))
        if cut and t[ent] >= cut: continue
        sl = min(cd["stop"], float(l[ent])) if cd["entry_low"] else cd["stop"]
        tg = cd["target"]
        if not (sl < e < tg): continue
        last = (int(np.searchsorted(t, cut, "right")) - 1) if cut else n - 1
        if last <= ent: continue
        sl0 = sl; armed = cd["trail"] == "each"; hi = e
        x, px, why, still = last, float(c[last]), ("eod" if cut else "open"), not cut
        for k in range(ent + 1, last + 1):
            if l[k] <= sl: x, px, why, still = k, min(float(o[k]), sl), ("trail" if sl > sl0 else "stop_loss"), False; break
            if h[k] >= tg: x, px, why, still = k, max(float(o[k]), tg), "target 1", False; break
            if cd.get("time_stop") and k == ent + cd["time_stop"] and c[k] <= e:
                x, px, why, still = k, float(c[k]), "time", False; break
            hi = max(hi, float(h[k]))
            if cd["trail"] == "pct" and hi >= e + tp * (tg - e): armed = True
            if armed and k >= ent + ta: sl = max(sl, float(l[k]))
        s = -1.0 if mirror else 1.0
        trades.append(dict(entry=ent, exit=x, exit_px=s * px, dir="down" if mirror else "up", choch=i, sl=s * sl0,
                           pts=px - e, open=still, exit_reason=why))
        free = x
    return trades


def signals(bars, spec):
    X = dict(PARAMS, **(spec.get("vred") or {})); setup = X.get("setup"); sq = spec["position"]["square_off"]
    if setup not in SETUPS: raise ValueError(f"{spec['code']}: vred.setup must be one of {SETUPS}")
    sides = X.get("sides", "both")
    o, h, l, c, v, day, t = bars.o, bars.h, bars.l, bars.c, bars.v, bars.day, bars.t
    trades = []
    if sides in ("both", "long"):
        F = _frame(o, h, l, c, v, day, X); trades += _walk(F, _DETECT[setup](F, X), X, t, sq, False)
    if sides in ("both", "short"):
        G = _frame(-o, -l, -h, -c, v, day, X); trades += _walk(G, _DETECT[setup](G, X), X, t, sq, True)
    trades.sort(key=lambda d: d["entry"])
    kept, free = [], -1                                                  # one position at a time across both sides
    for d in trades:
        if d["entry"] > free: kept.append(d); free = d["exit"]
    sg = core.foundation(bars, spec["rules"]).with_trades(kept, [_sma(c, int(X["sma_fast"])), _sma(c, int(X["sma_slow"]))])
    sg.line_names = [f"SMA {X['sma_fast']}", f"SMA {X['sma_slow']}"]; sg.line_colors = [COLORS["fast"], COLORS["slow"]]
    return sg


def option_lines(s, spec):
    X = dict(PARAMS, **(spec.get("vred") or {}))
    return [(f"SMA {X['sma_fast']}", _sma(s.c, int(X["sma_fast"]))), (f"SMA {X['sma_slow']}", _sma(s.c, int(X["sma_slow"])))]
