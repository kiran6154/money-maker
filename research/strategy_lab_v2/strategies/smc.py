"""Smart-money structures on lab candles (family module for ST47 / ST48): a port of the user's LuxAlgo-derived 'Smart Money
Concepts Pro' Pine script (swing / internal structure, order blocks, fair value gaps, equal highs / lows, premium /
discount range) and of the 'living zones' rule of the user's liquidity_variants Pine files (25-pt price bands holding a
share of the session's volume, dropped after 15 candles away unless a return held).

Everything is causal: a value at candle i uses candles up to i. A pivot of size n is known n candles after it forms; a
5-minute fair value gap is known when its third 5-minute candle has closed. Differences from the Pine script, by
construction: no drawing; an order block list is capped at the script's 20 visible blocks for the tap test.
Validation of each rule as an entry filter, by half: STRATEGY_ANALYSIS_TODO S68.

    arrays(bars) -> {sw_bias, int_bias (+1 / -1 / 0), ob_int_bull / bear, ob_sw_bull / bear, fvg_bull / bear (the candle
                     trades into a live block / gap), eql_swept / eqh_swept, zone_in (the close is inside a heavy band that
                     is still open), trail_top / trail_bot}
"""
import core
import numpy as np

SW = np.lib.stride_tricks.sliding_window_view


def _legs(h, l, size):
    """Pine leg(size): state 0 after a new high pivot (bearish leg), 1 after a new low pivot; pivot = candle i - size."""
    n = len(h); st = np.zeros(n, np.int8)
    hh = np.full(n, np.inf); ll = np.full(n, -np.inf)
    hh[size - 1:] = SW(h, size).max(axis=1); ll[size - 1:] = SW(l, size).min(axis=1)       # highest / lowest of the last `size`
    cur = 0
    for i in range(n):
        if i >= size:
            if h[i - size] > hh[i]: cur = 0
            elif l[i - size] < ll[i]: cur = 1
        st[i] = cur
    return st


def port(bars, atr200, b5=None, swing_len=50, internal_len=5, eq_len=3, eq_thresh=0.1, zone_pts=25.0, zone_share=8.0,
         away_bars=15, hold_bars=8, hold_pts=40.0, eq_memory=240):
    h, l, c, o, v, t, day = bars.h, bars.l, bars.c, bars.o, bars.v, bars.t, bars.day
    n = len(bars)
    hv = (h - l) >= 2 * atr200
    pH = np.where(hv, l, h); pL = np.where(hv, h, l)                       # parsedHigh / parsedLow
    legS, legI, legE = _legs(h, l, swing_len), _legs(h, l, internal_len), _legs(h, l, eq_len)
    out = {k: np.zeros(n, np.int8) for k in ("sw_bias", "int_bias")}
    for k in ("ob_int_bull", "ob_int_bear", "ob_sw_bull", "ob_sw_bear", "fvg_bull", "fvg_bear", "eql_swept", "eqh_swept", "zone_in"):
        out[k] = np.zeros(n, bool)
    out["trail_top"] = np.full(n, np.nan); out["trail_bot"] = np.full(n, np.nan)

    class P:                                                              # a pivot: level, candle, crossed
        __slots__ = ("lvl", "idx", "crossed")
        def __init__(s): s.lvl = np.nan; s.idx = 0; s.crossed = False
    sH, sL, iH, iL, eH, eL = P(), P(), P(), P(), P(), P()
    sw_b = int_b = 0; top = bot = np.nan
    obs = {"int": [], "sw": []}                                           # [hi, lo, bias]
    eqs = []                                                              # [level, kind(+1 high / -1 low), formed]
    # 5-minute FVGs become known at the close of their third candle
    fv = []; f_ptr = 0; fvgs = []
    if b5 is not None and len(b5) > 3:
        d5 = (b5.c - b5.o) / (b5.o * 100); cum = np.cumsum(np.abs(d5)); th = cum / np.maximum(np.arange(len(b5)), 1) * 2
        for j in range(2, len(b5)):
            known = int(b5.t[j]) + 300                                    # the 1-minute candle starting then is the first that sees it
            if b5.l[j] > b5.h[j - 2] and b5.c[j - 1] > b5.h[j - 2] and d5[j - 1] > th[j]: fv.append((known, float(b5.l[j]), float(b5.h[j - 2]), 1))
            elif b5.h[j] < b5.l[j - 2] and b5.c[j - 1] < b5.l[j - 2] and -d5[j - 1] > th[j]: fv.append((known, float(b5.l[j - 2]), float(b5.h[j]), -1))
    # living zones: per session {bin low: [vol, away, inside-run, ref close, held, stopped]}
    bins = {}; tot = 0.0

    for i in range(n):
        if i and day[i] != day[i - 1]: bins = {}; tot = 0.0
        # ---- pivots (Pine getCurrentStructure) for swing, internal, equal
        for leg, size, hi_p, lo_p, kind in ((legS, swing_len, sH, sL, "sw"), (legI, internal_len, iH, iL, "int"), (legE, eq_len, eH, eL, "eq")):
            if i > 0 and leg[i] != leg[i - 1] and i >= size:
                j = i - size
                if leg[i] == 1:                                           # a new low pivot
                    if kind == "eq" and abs(lo_p.lvl - l[j]) < eq_thresh * atr200[i]: eqs.append([min(lo_p.lvl, float(l[j])), -1, i])
                    lo_p.lvl, lo_p.idx, lo_p.crossed = float(l[j]), j, False
                    if kind == "sw": bot = lo_p.lvl
                else:
                    if kind == "eq" and abs(hi_p.lvl - h[j]) < eq_thresh * atr200[i]: eqs.append([max(hi_p.lvl, float(h[j])), 1, i])
                    hi_p.lvl, hi_p.idx, hi_p.crossed = float(h[j]), j, False
                    if kind == "sw": top = hi_p.lvl
        if not np.isnan(top): top = max(top, float(h[i]))                 # updateTrailingExtremes
        if not np.isnan(bot): bot = min(bot, float(l[i]))
        # ---- structure breaks (Pine displayStructure): close crossing the pivot level
        for kind, hi_p, lo_p in (("int", iH, iL), ("sw", sH, sL)):
            if i > 0 and not hi_p.crossed and c[i] > hi_p.lvl and c[i - 1] <= hi_p.lvl and (kind == "sw" or iH.lvl != sH.lvl):
                hi_p.crossed = True
                if kind == "sw": sw_b = 1
                else: int_b = 1
                a, z = hi_p.idx, i
                if z > a:
                    k = a + int(np.argmin(pL[a:z])); obs[kind].insert(0, [float(pH[k]), float(pL[k]), 1]); del obs[kind][100:]
            if i > 0 and not lo_p.crossed and c[i] < lo_p.lvl and c[i - 1] >= lo_p.lvl and (kind == "sw" or iL.lvl != sL.lvl):
                lo_p.crossed = True
                if kind == "sw": sw_b = -1
                else: int_b = -1
                a, z = lo_p.idx, i
                if z > a:
                    k = a + int(np.argmax(pH[a:z])); obs[kind].insert(0, [float(pH[k]), float(pL[k]), -1]); del obs[kind][100:]
        out["sw_bias"][i] = sw_b; out["int_bias"][i] = int_b; out["trail_top"][i] = top; out["trail_bot"][i] = bot
        # ---- order blocks: tap (the candle trades into a live block), then mitigation (High / Low source)
        for kind in ("int", "sw"):
            lst = obs[kind]; keep = []
            for ob in lst[:20]:                                           # the script shows at most 20; older ones are not tradable zones here
                if ob[2] == 1:
                    if l[i] <= ob[0] and h[i] >= ob[1]: out[f"ob_{kind}_bull"][i] = True
                    if l[i] < ob[1]: continue                              # mitigated
                else:
                    if h[i] >= ob[1] and l[i] <= ob[0]: out[f"ob_{kind}_bear"][i] = True
                    if h[i] > ob[0]: continue
                keep.append(ob)
            obs[kind] = keep + lst[20:]
        # ---- 5-minute fair value gaps
        while f_ptr < len(fv) and fv[f_ptr][0] <= t[i]: fvgs.insert(0, list(fv[f_ptr][1:])); f_ptr += 1; del fvgs[40:]
        keep = []
        for g in fvgs:                                                    # [top, bottom, bias]
            if g[2] == 1:
                if l[i] <= g[0] and h[i] >= g[1]: out["fvg_bull"][i] = True
                if l[i] < g[1]: continue
            else:
                if h[i] >= g[1] and l[i] <= g[0]: out["fvg_bear"][i] = True
                if h[i] > g[0]: continue
            keep.append(g)
        fvgs = keep
        # ---- equal highs / lows swept: through the level and closed back
        keep = []
        for e in eqs:
            if i - e[2] > eq_memory: continue
            if e[1] == -1 and l[i] < e[0] and c[i] > e[0]: out["eql_swept"][i] = True; continue
            if e[1] == 1 and h[i] > e[0] and c[i] < e[0]: out["eqh_swept"][i] = True; continue
            if (e[1] == -1 and c[i] < e[0]) or (e[1] == 1 and c[i] > e[0]): continue      # closed through: gone
            keep.append(e)
        eqs = keep
        # ---- living zones (the zip): volume by 25-pt bin, prorated by overlap; heavy and still open
        if v[i] > 0 and h[i] > l[i]:
            span = h[i] - l[i]
            for b in range(int(np.floor(l[i] / zone_pts)), int(np.floor(h[i] / zone_pts)) + 1):
                lo = b * zone_pts; ov = max(0.0, min(h[i], lo + zone_pts) - max(l[i], lo))
                if ov > 0:
                    z = bins.setdefault(lo, [0.0, 0, 0, float(c[i]), False, False]); z[0] += v[i] * ov / span; tot += v[i] * ov / span
        for lo, z in bins.items():
            if z[5]: continue
            inside = lo <= c[i] < lo + zone_pts
            if inside:
                z[1] = 0; z[2] += 1
                if z[2] == 1: z[3] = float(c[i])
                if z[2] >= hold_bars and abs(c[i] - z[3]) >= hold_pts: z[4] = True
            else:
                z[1] += 1
                if not z[4]: z[2] = 0
            heavy = tot > 0 and 100.0 * z[0] / tot >= zone_share
            broken = z[1] >= away_bars and not z[4]
            if heavy and broken: z[5] = True
            if inside and heavy and not broken: out["zone_in"][i] = True
    return out


_C = {}


def arrays(bars):
    """port() on these candles, cached per bars object (the entry keeps the object). About a minute for 8 years of 1-minute
    candles: one pass in Python."""
    key = id(bars)
    if key not in _C or _C[key][0] is not bars:
        b5 = None
        if len(bars) > 1 and int(bars.t[1] - bars.t[0]) == 60:               # 1-minute candles: the FVGs come from the 5-minute series
            f = core.series("fut", "5minute"); a = int(np.searchsorted(f.t, bars.t[0])); z = int(np.searchsorted(f.t, bars.t[-1], "right"))
            if z - a > 3 and abs(float(f.c[z - 1]) - float(bars.c[-1])) < 0.02 * float(bars.c[-1]): b5 = f.slice(a, z)   # the same instrument
        while len(_C) > 3: del _C[next(iter(_C))]
        _C[key] = (bars, port(bars, core.atr(bars, 200), b5))
    return _C[key][1]


def recent(arr, k, n):
    """True on any of the n candles up to and including k."""
    return bool(arr[max(0, k - n):k + 1].any())
