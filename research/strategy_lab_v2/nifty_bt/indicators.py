"""Bars and indicators (spec §3.3, §4.1-4.3), written to give the reference code's numbers exactly.

Every function works on completed bars; a bar's values are known at its close time `ct` (last minute + 1 min)."""
import numpy as np, pandas as pd
from numba import njit


def agg(g, tf):
    """1-min frame (datetime, date, tod, open, high, low, close) -> tf-minute bars anchored at 09:15, continuous across days."""
    if tf == 1:
        B = g[["datetime", "open", "high", "low", "close"]].rename(columns={"datetime": "bk"}).copy()
        B["last_dt"] = g.datetime.values
    else:
        k = ((g.tod.astype(int) - 555) // tf).clip(lower=0); bk = g.date + pd.to_timedelta(555 + k * tf, unit="m")
        B = g.assign(bk=bk).groupby("bk").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"),
                                              last_dt=("datetime", "last")).reset_index()
    B[["open", "high", "low", "close"]] = B[["open", "high", "low", "close"]].astype(float)
    B["ct"] = B.last_dt + pd.Timedelta(minutes=1)
    return B


def true_range(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    return np.maximum.reduce([h - l, np.abs(h - pc), np.abs(l - pc)])


@njit(cache=True)
def _st_loop(h, l, c, atr, m):
    n = len(c); hl2 = (h + l) / 2; ub = hl2 + m * atr; lb = hl2 - m * atr; fu = ub.copy(); fl = lb.copy()
    d = np.ones(n, np.int8)
    for i in range(1, n):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = 1 if c[i] > fu[i - 1] else (-1 if c[i] < fl[i - 1] else d[i - 1])
    return d


def st_dir(B, period=10, mult=3.0):
    """§4.1 Supertrend direction (+1 / -1) per bar; Wilder ATR = ewm(alpha=1/p, adjust=False) of TR (TR[0] uses C[0])."""
    h, l, c = B.high.values.astype(float), B.low.values.astype(float), B.close.values.astype(float)
    atr = pd.Series(true_range(h, l, c)).ewm(alpha=1 / period, adjust=False).mean().values
    return _st_loop(h, l, c, atr, float(mult))


def pivots(h, l, N):
    """§4.2 swing high at p: H[p] > max(H[p-N..p-1]) and H[p] >= max(H[p+1..p+N]); lows mirror (confirmed at p+N)."""
    H = pd.Series(h); L = pd.Series(l)
    lh = H.shift(1).rolling(N).max().values; rh = H[::-1].shift(1).rolling(N).max()[::-1].values
    ll = L.shift(1).rolling(N).min().values; rl = L[::-1].shift(1).rolling(N).min()[::-1].values
    with np.errstate(invalid="ignore"):
        return (h > lh) & (h >= rh), (l < ll) & (l <= rl)


@njit(cache=True)
def _struct_loop(h, l, c, ph, pl, N):
    n = len(c)
    ev = np.zeros(n, np.int8); last_sl = np.full(n, np.nan); last_sh = np.full(n, np.nan)
    new_sl = np.full(n, np.nan); new_sh = np.full(n, np.nan)
    top = np.nan; bot = np.nan; tx = True; bx = True; trend = 0; s_l = np.nan; s_h = np.nan
    for i in range(n):
        p = i - N
        if p >= 0:
            if ph[p]: top = h[p]; tx = False; s_h = h[p]; new_sh[i] = h[p]
            if pl[p]: bot = l[p]; bx = False; s_l = l[p]; new_sl[i] = l[p]
        if not tx and c[i] > top:
            ev[i] = 1 if trend == 1 else 2; tx = True; trend = 1
        if not bx and c[i] < bot:
            ev[i] = -1 if trend == -1 else -2; bx = True; trend = -1
        last_sl[i] = s_l; last_sh[i] = s_h
    return ev, last_sl, last_sh, new_sl, new_sh


def pivot_structure(B, N):
    """§4.2 CHoCH / BOS on pivots: ev = +-1 BOS, +-2 CHoCH at the bar close; last / newly confirmed swings."""
    h, l, c = B.high.values.astype(float), B.low.values.astype(float), B.close.values.astype(float)
    ph, pl = pivots(h, l, N)
    ev, a, b, x, y = _struct_loop(h, l, c, ph, pl, N)
    return dict(ev=ev, last_sl=a, last_sh=b, new_sl=x, new_sh=y)


def st_segment_structure(B, d):
    """§12.2 swings from Supertrend segments: swing high = highest high of a completed UP segment (confirmed at the
    flip-down bar close), swing low mirror. Returns events [(ct, side, 'BOS'|'CHoCH', stop)], swing-high (t, v), swing-low (t, v)."""
    h, l, c, ct = B.high.values, B.low.values, B.close.values, B.ct.values; n = len(c)
    seg_hi = seg_lo = np.nan; H = L = np.nan; Hx = Lx = True; trend = 0; ev = []; sh = []; sl = []
    for i in range(n):
        if i > 0 and d[i] != d[i - 1]:
            if d[i - 1] == 1: H = seg_hi; Hx = False; sh.append((ct[i], H))
            else: L = seg_lo; Lx = False; sl.append((ct[i], L))
            seg_hi, seg_lo = h[i], l[i]
        else:
            seg_hi = h[i] if np.isnan(seg_hi) else max(seg_hi, h[i]); seg_lo = l[i] if np.isnan(seg_lo) else min(seg_lo, l[i])
        if not Hx and c[i] > H: ev.append((ct[i], 1, "BOS" if trend == 1 else "CHoCH", L)); Hx = True; trend = 1
        if not Lx and c[i] < L: ev.append((ct[i], -1, "BOS" if trend == -1 else "CHoCH", H)); Lx = True; trend = -1
    arr = lambda xs, k: np.array([x[k] for x in xs])
    return ev, arr(sh, 0), arr(sh, 1), arr(sl, 0), arr(sl, 1)


def ema(c, span):
    return pd.Series(c).ewm(span=span, adjust=False).mean().values


def atr_wilder(B, n):
    tr = np.maximum.reduce([B.high - B.low, (B.high - B.close.shift()).abs(), (B.low - B.close.shift()).abs()])
    return pd.Series(np.nan_to_num(np.asarray(tr, float))).ewm(alpha=1 / n, adjust=False).mean().values


def psar_bull(h, l, af0=0.02, afmax=0.2):
    n = len(h); bull = np.zeros(n, bool); up = True; ep = h[0]; sar = l[0]; af = af0
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < sar: up = False; sar = ep; ep = l[i]; af = af0
            elif h[i] > ep: ep = h[i]; af = min(af + af0, afmax)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar: up = True; sar = ep; ep = h[i]; af = af0
            elif l[i] < ep: ep = l[i]; af = min(af + af0, afmax)
        bull[i] = up
    return bull


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).values
