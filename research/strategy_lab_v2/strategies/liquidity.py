"""Liquidity filters on Foundation SETUPs (family module for ST39 / ST40): was the CHoCH preceded by a liquidity sweep, did it
break an equal-highs / equal-lows level, does the SETUP candle show displacement. Every number is in SPEC["liquidity"].

For a bullish CHoCH at candle ci with its SETUP at candle k (bearish mirrors, highs for lows):
  sweep     within the `lookback` candles up to and including ci, a candle's low went below a confirmed swing low and the
            candle closed back above it. The swing low must be confirmed before that candle and formed at most `memory`
            candles before it (older levels are not counted as liquidity here) and at least `min_age` candles before it
            (default 0; ST41 / ST42 use 40: a level that has stood, not one of the swings that form every few candles).
            `extreme` (default off): the sweep candle must also make the lowest low of those `lookback` candles.
  equal     the swing high the CHoCH broke (the protected level) has a twin: another swing high confirmed before ci,
            formed at most `memory` candles before it, whose price is within tol_atr x ATR(atr_period) at ci.
  displace  the SETUP candle's body is at least body_atr x ATR(atr_period) at k, or it leaves a fair-value gap in the
            trade's direction (bullish: low[k] > high[k - 2]).
Two structural filters (ST44 / ST45; keys optional in SPEC["liquidity"], off when absent):
  extreme_sweep  within `lookback` candles up to ci, a candle went below the session's low so far (`session`) and / or the
                 previous session's low (`prev_day`) and closed back above it (bullish; highs for bearish)
  pivot_degree   the swing the CHoCH broke is the highest high (swing high) / lowest low (swing low) of the `bars` candles
                 on each side of it, all of them before the CHoCH candle
All read only candles up to the SETUP candle's close.
"""
import numpy as np
import core

FILTERS = ("sweep", "equal", "displace", "extreme_sweep", "pivot_degree")
DEFAULT = {'sweep': {'on': True, 'lookback': 30, 'memory': 240},
           'equal': {'on': False, 'tol_atr': 0.25, 'memory': 240, 'atr_period': 14},
           'displace': {'on': True, 'body_atr': 1.0, 'atr_period': 14, 'fvg': True},
           'notes': 'fixed 2026-10-11 before any run (the brief gave no numbers); switch a filter with on: True / False'}

_SW = {}


def _sweeps(bars, eng, memory, min_age=0):
    """(swept_low, swept_high): per candle, did it take a confirmed swing low / high (formed min_age .. memory candles
    before it) and close back inside."""
    key = (id(bars), id(eng), memory, min_age)           # the entry keeps both objects, so their ids cannot be reused
    if key not in _SW or _SW[key][2] is not bars or _SW[key][3] is not eng:
        n = len(bars); lo = np.zeros(n, bool); hi = np.zeros(n, bool)
        l, h, c = bars.l, bars.h, bars.c
        for kind, sb, p, sc in zip(eng.sk, eng.sb, eng.sp, eng.sc):
            a, z = max(int(sc) + 1, int(sb) + min_age), min(n, int(sb) + memory + 1)   # confirmed, old enough, within the memory
            if a >= z: continue
            if kind == -1: lo[a:z] |= (l[a:z] < p) & (c[a:z] > p)
            else: hi[a:z] |= (h[a:z] > p) & (c[a:z] < p)
        while len(_SW) > 8: del _SW[next(iter(_SW))]
        _SW[key] = (lo, hi, bars, eng)
    return _SW[key][:2]


def sweep_ok(bars, sw, ci, up, lookback, extreme):
    """A sweep candle among the `lookback` candles up to and including ci (with `extreme`: one that is also their extreme)."""
    a = max(0, ci - lookback); w = sw[a:ci + 1]
    if not extreme: return bool(w.any())
    x = bars.l[a:ci + 1] if up else bars.h[a:ci + 1]
    return bool((w & ((x <= x.min()) if up else (x >= x.max()))).any())


_EX = {}


def _extremes(bars):
    """Per candle, cumulative counts of: took the session's low so far / the session's high so far / the previous
    session's low / high, and closed back inside."""
    key = id(bars)
    if key not in _EX or _EX[key][0] is not bars:
        n = len(bars); h, l, c, day = bars.h, bars.l, bars.c, bars.day
        slo = np.full(n, np.nan); shi = np.full(n, np.nan); pdl = np.full(n, np.nan); pdh = np.full(n, np.nan)
        start = 0; prev = (np.nan, np.nan)
        for i in range(n):
            if i and day[i] != day[i - 1]:
                prev = (float(l[start:i].min()), float(h[start:i].max())); start = i
            if i > start: slo[i] = l[start:i].min(); shi[i] = h[start:i].max()
            pdl[i], pdh[i] = prev
        with np.errstate(invalid="ignore"):
            t = dict(sess_lo=(l < slo) & (c > slo), sess_hi=(h > shi) & (c < shi), pd_lo=(l < pdl) & (c > pdl), pd_hi=(h > pdh) & (c < pdh))
        while len(_EX) > 4: del _EX[next(iter(_EX))]
        _EX[key] = (bars, {k: np.concatenate([[0], np.cumsum(v)]) for k, v in t.items()})
    return _EX[key][1]


def on_filters(spec):
    """The enabled filters of a SPEC (a filter missing from SPEC["liquidity"] is off)."""
    return [f for f in FILTERS if spec["liquidity"].get(f, {}).get("on")]


def verdicts(bars, eng, spec):
    """Per engine trade: {filter: passed?} for every liquidity filter (enabled or not)."""
    L = spec["liquidity"]
    S = L["sweep"]; cl, chh = _sweeps(bars, eng, S["memory"], S.get("min_age", 0))
    atr_e = core.atr(bars, L["equal"]["atr_period"]); atr_d = core.atr(bars, L["displace"]["atr_period"])
    cj = {int(c): j for j, c in enumerate(eng.qi)}
    out = []
    for x in eng.trades():
        k, ci = x["entry"], x["choch"]; up = x["dir"] == "up"; j = cj[ci]
        v = dict(sweep=sweep_ok(bars, cl if up else chh, ci, up, S["lookback"], S.get("extreme", False)))
        s0 = int(eng.qsw[j]); kind, p0 = eng.sk[s0], float(eng.sp[s0]); tol = L["equal"]["tol_atr"] * float(atr_e[ci])
        q = int(np.searchsorted(eng.sc, ci)) - 1; twin = False               # swings confirmed before the CHoCH candle
        while q >= 0 and eng.sc[q] >= eng.sb[s0] - L["equal"]["memory"]:     # confirmed earlier than that = formed earlier too
            if q != s0 and eng.sk[q] == kind and eng.sb[q] >= eng.sb[s0] - L["equal"]["memory"] and abs(float(eng.sp[q]) - p0) <= tol:
                twin = True; break
            q -= 1
        v["equal"] = twin
        o_, c_ = float(bars.o[k]), float(bars.c[k])
        fvg = L["displace"].get("fvg") and k >= 2 and (bars.l[k] > bars.h[k - 2] if up else bars.h[k] < bars.l[k - 2])
        v["displace"] = bool(abs(c_ - o_) >= L["displace"]["body_atr"] * float(atr_d[k]) or fvg)
        E = L.get("extreme_sweep")
        if E:
            cum = _extremes(bars); a0 = max(0, ci - E["lookback"]); took = lambda nm: bool(cum[nm][ci + 1] - cum[nm][a0] > 0)
            v["extreme_sweep"] = bool((E.get("session") and took("sess_lo" if up else "sess_hi")) or
                                      (E.get("prev_day") and took("pd_lo" if up else "pd_hi")))
        else: v["extreme_sweep"] = True
        D = L.get("pivot_degree")
        if D:
            K, sb = D["bars"], int(eng.sb[s0])
            if sb + K > ci or sb - K < 0: v["pivot_degree"] = False
            else:
                w = (bars.h if kind == 1 else bars.l)[sb - K:sb + K + 1]
                v["pivot_degree"] = bool(p0 >= w.max() - 1e-9) if kind == 1 else bool(p0 <= w.min() + 1e-9)
        else: v["pivot_degree"] = True
        out.append(v)
    return out
