"""Rainbow ribbon intraday (entry_rule rainbow_v1): the family module behind ST29 and ST30 (v1 rainbow.py).

The ribbon: `widner` = `levels` recursive SMA(period) of the close; `ema` = EMA(p) per period (seeded with the simple
average of its first p closes). band = [lowest line, highest line]; fan bullish when every faster line is above the next
slower one. Oscillator = 100 x (close - mean of the lines) / (highest - lowest close over `lookback` candles).
Entry: a fresh close outside the band (the previous close was not), in the entry_from .. entry_until window, with the
`fan` / `osc_min` / `trigger` ("cross" or "pullback": a re-emergence within pullback_bars while the far edge kept its slope)
rules. Exits: the strategy file's position block (managed in ST29 / ST30); in strategy mode the band's far side at the
signal is the stop and exit "band" also closes on a close back through it.
Futures only, on the futures' own candles; one position per contract (the lab's lock). Every number is in SPEC["rainbow"].
"""
import numpy as np
from numba import njit
import core

ENTRY_RULES = ("rainbow_v1",)
TYPES = ("FUT",)
UNDERLYINGS = ("FUT",)
REFUSED_WHY = "rainbow v1 trades the near-month futures on their own candles; option types and index signals are not part of it yet"


@njit(cache=True)
def _sma(x, p):
    """Average of the last p values; NaN until p defined values (a NaN input restarts the count); the sum is taken
    afresh each candle, left to right (v1 sum(win) / p)."""
    n = len(x); out = np.full(n, np.nan); cnt = 0
    for i in range(n):
        if np.isnan(x[i]):
            cnt = 0; continue
        cnt += 1
        if cnt >= p:
            s = 0.0
            for j in range(i - p + 1, i + 1): s += x[j]
            out[i] = s / p
    return out


@njit(cache=True)
def _ema(x, p):
    n = len(x); out = np.full(n, np.nan); a = 2.0 / (p + 1)
    if n < p: return out
    s = 0.0
    for j in range(p): s += x[j]
    prev = s / p; out[p - 1] = prev
    for i in range(p, n):
        prev = prev + a * (x[i] - prev); out[i] = prev
    return out


@njit(cache=True)
def _ribbon(L, c, lookback):
    """L: lines x candles (fastest first). Returns start, top, bot, fan_up, fan_dn, osc."""
    m, n = L.shape
    start = n
    for i in range(n):
        ok = True
        for k in range(m):
            if np.isnan(L[k, i]):
                ok = False; break
        if ok:
            start = i; break
    top = np.full(n, np.nan); bot = np.full(n, np.nan); osc = np.zeros(n)
    fu = np.zeros(n, np.bool_); fd = np.zeros(n, np.bool_)
    for i in range(start, n):
        tp = L[0, i]; bt = L[0, i]; s = 0.0; up = True; dn = True
        for k in range(m):
            v = L[k, i]
            if v > tp: tp = v
            if v < bt: bt = v
            s += v
            if k < m - 1:
                if not (v > L[k + 1, i]): up = False
                if not (v < L[k + 1, i]): dn = False
        top[i] = tp; bot[i] = bt; fu[i] = up; fd[i] = dn
        j0 = max(0, i - lookback + 1)
        hi = c[j0]; lo = c[j0]
        for j in range(j0, i + 1):
            if c[j] > hi: hi = c[j]
            if c[j] < lo: lo = c[j]
        osc[i] = 100.0 * (c[i] - s / m) / (hi - lo) if hi > lo else 0.0
    return start, top, bot, fu, fd, osc


@njit(cache=True)
def _signals(t, c, start, top, bot, fu, fd, osc, fan_full, osc_min, pullback, N, m_from, m_until):
    """Entry signals in time order: (bar, dir +1 / -1)."""
    n = len(c); si = np.empty(2 * n, np.int64); sd = np.empty(2 * n, np.int8); k = 0
    for i in range(start + 1, n):
        hm = (t[i] % 86400) // 60
        if not (m_from <= hm < m_until): continue
        for sg in (1, -1):
            now = c[i] > top[i] if sg == 1 else c[i] < bot[i]
            prev = c[i - 1] > top[i - 1] if sg == 1 else c[i - 1] < bot[i - 1]
            if not now or prev: continue
            if fan_full and not (fu[i] if sg == 1 else fd[i]): continue
            if sg * osc[i] < osc_min: continue
            if pullback:
                j0 = i - N
                if j0 < start: continue
                if not (bot[i] > bot[j0] if sg == 1 else top[i] < top[j0]): continue
                re = False
                for j in range(j0, i - 1):
                    if (c[j] > top[j]) if sg == 1 else (c[j] < bot[j]):
                        re = True; break
                if not re: continue
            si[k] = i; sd[k] = sg; k += 1
    return si[:k], sd[:k]


@njit(cache=True)
def _exits(o, h, l, c, day, top, bot, si, sd, band_exit):
    """Strategy-mode exits: stop at the band's far side at the signal (touch; open beyond it; a session's first candle at
    its close); band exit on a close back through the far side. reason 0 open, 1 stop_loss, 2 band_exit."""
    n = len(c); m = len(si)
    xi = np.empty(m, np.int64); px = np.empty(m); rs = np.empty(m, np.int8); sl = np.empty(m)
    for q in range(m):
        i = si[q]; up = sd[q] == 1
        s = bot[i] if up else top[i]
        sl[q] = s; xi[q] = n - 1; px[q] = c[n - 1]; rs[q] = 0
        for k in range(i + 1, n):
            gap = o[k] <= s if up else o[k] >= s
            hit = l[k] <= s if up else h[k] >= s
            if gap or hit:
                xi[q] = k; rs[q] = 1
                px[q] = c[k] if day[k] != day[k - 1] else (o[k] if gap else s)
                break
            if band_exit and ((c[k] < bot[k]) if up else (c[k] > top[k])):
                xi[q] = k; rs[q] = 2; px[q] = c[k]
                break
    return xi, px, rs, sl


def lines_of(c, cfg):
    if cfg["kind"] == "widner":
        out, src = [], c
        for _ in range(cfg["levels"]):
            src = _sma(src, cfg["period"]); out.append(src)
        return np.array(out)
    return np.array([_ema(c, p) for p in cfg["periods"]])


def signals(bars, spec):
    """The Foundation engine (chart overlays and the CHoCH list) with the ribbon's trades in place of its own."""
    cfg = spec["rainbow"]
    eng = core.foundation(bars, spec["rules"])
    L = lines_of(bars.c, cfg)
    start, top, bot, fu, fd, osc = _ribbon(L, bars.c, cfg["lookback"])
    hm = lambda s: int(s[:2]) * 60 + int(s[3:])
    si, sd = _signals(bars.t, bars.c, start, top, bot, fu, fd, osc, cfg["fan"] == "full", float(cfg["osc_min"]),
                      cfg["trigger"] == "pullback", cfg["pullback_bars"], hm(cfg["entry_from"]), hm(cfg["entry_until"]))
    xi, px, rs, sl = _exits(bars.o, bars.h, bars.l, bars.c, bars.day, top, bot, si, sd, cfg["exit"] == "band")
    why = ("open", "stop_loss", "band_exit")
    trades = [dict(entry=int(i), exit=int(x), exit_px=float(p), dir="up" if d == 1 else "down", choch=int(i),
                   sl=round(float(s), 2), pts=(1 if d == 1 else -1) * (float(p) - float(bars.c[i])), open=r == 0,
                   exit_reason=why[r], osc=round(float(osc[i]), 1))
              for i, d, x, p, r, s in zip(si, sd, xi, px, rs, sl)]
    return eng.with_trades(trades, lines=L)
