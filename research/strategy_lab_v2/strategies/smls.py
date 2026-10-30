"""Smart Money Liquidity Structure - OB signal setups (family module): a port of the TradingFinder Pine script the user
supplied on 2026-10-11 ("Smart Money Liquidity Structure [TradingFinder] OB Signal Setups"), on lab candles.

What the script does, and what is ported as written (inputs at the script's defaults):
  swings     3-candle pivots labelled H / L / HH / HL / LH / LL by the script's own state machine
  One / Two  a five-label (or seven-label) pattern ending in a HH below the HH four labels back (bullish; mirror for
             bearish) makes a Demand order block at the pattern's origin low, kept only if one (One) or two (Two) of the
             pattern's lows are still untouched above the block: that untouched low is the "liquidity"
  Midway     9-candle pivots; a strong close through the last swing high (body 0.6 ATR, break 0.25 ATR: "Defensive")
             makes a candidate block at the last swing low; it becomes a block when, within 30 candles, a fresh swing low
             forms above it with a 0.5 ATR reaction and all four quality points
  signal     the first candle after a block is created that trades into it = "Long Signal" (Demand) / "Short Signal"
             (Supply). A block ends when it is entered (mitigation at the proximal line), closed through, or 1,000
             candles old.
NOT ported exactly: the script takes each block's edges from an imported TradingView library
(TFlab/OrderBlockRefiner_TradingFinder/2) whose source was not supplied. Here a block is the full high-low range of its
origin candle (the refiner switched off). Signals therefore match the script's logic but a block can be wider than on the
user's chart, so a signal can come a little earlier here.
Pivot ties: a pivot high is a candle whose high is above every high of the n candles before it and not below any of the n
after it (Pine's own tie rule is not documented).

    signals_of(bars) -> dict(long, short: per candle, the signal fired on it; stop_long / stop_short: the block's far
                             edge at that signal; kind: 1 One, 2 Two, 3 Midway)
Everything is causal: a value at candle i uses candles up to i.
"""
import numpy as np
import core

PP, CPP, OB_VALID = 3, 9, 1000
C_BREAK, C_BODY, C_REACT, C_FORM, C_SCORE = 0.25, 0.60, 0.50, 30, 4          # "Defensive"
SW = np.lib.stride_tricks.sliding_window_view
COUNT = {}                                       # how far candidates got in the last port() run (diagnostics)
def _n(k): COUNT[k] = COUNT.get(k, 0) + 1


def _pivots(h, l, n):
    """(pivot high at centre c known at c + n, pivot low): boolean per candle i = the candle the pivot becomes known on."""
    N = len(h); ph = np.zeros(N, bool); pl = np.zeros(N, bool)
    if N < 2 * n + 1: return ph, pl
    left_h = SW(h, n).max(axis=1); left_l = SW(l, n).min(axis=1)             # window ending at index j + n - 1
    for i in range(2 * n, N):
        c = i - n
        if h[c] > left_h[c - n] and h[c] >= h[c + 1:i + 1].max(): ph[i] = True
        if l[c] < left_l[c - n] and l[c] <= l[c + 1:i + 1].min(): pl[i] = True
    return ph, pl


def port(bars):
    h, l, c, o = bars.h, bars.l, bars.c, bars.o
    n = len(bars); atr = core.atr(bars, 50)
    ph, pl = _pivots(h, l, PP); cph, cpl = _pivots(h, l, CPP)
    hh9 = np.full(n, np.nan); ll9 = np.full(n, np.nan)
    hh9[CPP - 1:] = SW(h, CPP).max(axis=1); ll9[CPP - 1:] = SW(l, CPP).min(axis=1)
    out = dict(long=np.zeros(n, bool), short=np.zeros(n, bool), stop_long=np.full(n, np.nan), stop_short=np.full(n, np.nan),
               kind=np.zeros(n, np.int8))
    T, V, X = [], [], []                                                   # labels, prices, candle indices
    HV = LV = np.nan; HI = LI = -1                                         # latest pivot high / low (valuewhen)
    cLH = cLL = np.nan; cLHb = cLLb = -1
    blocks = []                                                            # [dir, origin, created, top, bottom, entered, kind]
    cands = []                                                             # midway candidates: dict

    def untouched(d, price, pb, i):
        if np.isnan(price) or pb < 0 or pb >= i or i - pb > 4998: return False
        return bool(l[pb + 1:i + 1].min() > price) if d == 1 else bool(h[pb + 1:i + 1].max() < price)

    COUNT.clear()
    for i in range(n):
        hp, lp = ph[i], pl[i]
        if hp: HV, HI = float(h[i - PP]), i - PP
        if lp: LV, LI = float(l[i - PP]), i - PP
        labH = lambda: ("HH" if V[len(T) - 2] < HV else "LH") if len(T) > 2 else "H"
        labL = lambda: ("HL" if V[len(T) - 2] < LV else "LL") if len(T) > 2 else "L"
        def pushH(): T.append(labH()); V.append(HV); X.append(HI)
        def pushL(): T.append(labL()); V.append(LV); X.append(LI)
        def pop(): T.pop(); V.pop(); X.pop()
        if hp and lp:
            if T:
                last = T[-1]
                if last in ("L", "LL"):
                    if LV < V[-1]: pop(); pushL()
                    else: pushH()
                elif last in ("H", "HH"):
                    if HV > V[-1]: pop(); pushH()
                    else: pushL()
                elif last == "LH":
                    if HV < V[-1]: pushL()
                    elif HV > V[-1]:
                        if c[i] < V[-1]: pop(); pushH()
                        elif c[i] > V[-1]: pushL()
                elif last == "HL":
                    if LV > V[-1]: pushH()
                    elif LV < V[-1]:
                        if c[i] > V[-1]: pop(); pushL()
                        elif c[i] < V[-1]: pushH()
        elif hp:
            if not T: T.append("H"); V.append(HV); X.append(HI)
            else:
                last = T[-1]
                if last in ("L", "HL", "LL"):
                    if HV > V[-1]: pushH()
                    elif HV < V[-1]: pop(); pushL()
                elif V[-1] < HV: pop(); pushH()
        elif lp:
            if not T: T.append("L"); V.append(LV); X.append(LI)
            else:
                last = T[-1]
                if last in ("H", "HH", "LH"):
                    if LV < V[-1]: pushL()
                    elif LV > V[-1]: pop(); pushH()
                elif V[-1] > LV: pop(); pushL()
        if len(T) > 60: del T[:20], V[:20], X[:20]                         # only the last seven labels are ever read
        cnt = len(T); e5, e9 = cnt >= 5, cnt > 8
        bull_raw = bear_raw = False; a_i = -1; b_orig = False
        if e5 and X[-1] == i - PP:
            t = T[-7:] if e9 else T[-5:]
            p0, p1, p3, p4 = V[-1], V[-2], V[-4], V[-5]; x1, x3 = X[-2], X[-4]; x5 = X[-6] if e9 else -1
            bS = T[-5:] == ["HH", "HL", "LH", "HL", "HH"] and p0 < p4
            sS = T[-5:] == ["LL", "LH", "HL", "LH", "LL"] and p0 > p4
            bO = e9 and bS and T[-7:-5] == ["HH", "HL"]; sO = e9 and sS and T[-7:-5] == ["LL", "LH"]
            bOe = bO and i - x5 <= OB_VALID; sOe = sO and i - x5 <= OB_VALID
            bSe = bS and i - x3 <= OB_VALID; sSe = sS and i - x3 <= OB_VALID
            min_gap = max(0.1, atr[i] * 0.2)
            for d, raw, orig in ((1, bOe or bSe, bOe), (-1, sOe or sSe, sOe)):
                if not raw: continue
                _n('pattern')
                origin = x5 if orig else x3
                top, bottom = float(h[origin]), float(l[origin])           # the refiner switched off: the origin candle's range
                if not (top > bottom and i - origin <= OB_VALID): continue
                a = orig and untouched(d, p3, x3, i) and (p3 > top if d == 1 else p3 < bottom)
                b = untouched(d, p1, x1, i) and (p1 > top if d == 1 else p1 < bottom)
                two = a and b and abs(p3 - p1) >= min_gap
                if two or a or b:
                    _n('block_one_two')
                    blocks.append([d, origin, i, top, bottom, False, 2 if two else 1])
        # ---- midway setup: break of the last 9-candle swing (uses the swings known before this candle)
        buf = max(0.05, atr[i] * C_BREAK); body = c[i] - o[i]
        if i > 0 and not np.isnan(cLH) and not np.isnan(cLL):
            for d in (1, -1):
                if d == 1:
                    brk = cLLb > cLHb and i > cLLb and body >= atr[i] * C_BODY and body > 0 and c[i] > cLH + buf and c[i - 1] <= cLH + buf
                    strong = brk and c[i] - cLH >= atr[i] * max(0.30, C_BREAK * 1.5) and body >= atr[i] * max(0.65, C_BODY * 1.3); anchor = cLLb
                else:
                    brk = cLHb > cLLb and i > cLHb and -body >= atr[i] * C_BODY and body < 0 and c[i] < cLL - buf and c[i - 1] >= cLL - buf
                    strong = brk and cLL - c[i] >= atr[i] * max(0.30, C_BREAK * 1.5) and -body >= atr[i] * max(0.65, C_BODY * 1.3); anchor = cLHb
                if not brk: continue
                _n('midway_break')
                hi_, lo_ = float(h[anchor]), float(l[anchor])
                if not (hi_ > lo_ and i - anchor < OB_VALID): continue
                if any(q["d"] == d and q["origin"] == anchor for q in cands) or any(b_[6] == 3 and b_[0] == d and b_[1] == anchor for b_ in blocks): continue
                good = (hi_ - lo_ <= atr[i] * 1.5) and ((c[i] - hi_) if d == 1 else (lo_ - c[i])) >= atr[i] * 0.9
                _n('midway_candidate')
                cands.append(dict(d=d, origin=anchor, brk=i, top=hi_, bottom=lo_, strong=bool(strong), good=bool(good), clean=True, streak=0))
        if cph[i]: cLH, cLHb = float(h[i - CPP]), i - CPP
        if cpl[i]: cLL, cLLb = float(l[i - CPP]), i - CPP
        for q in cands[::-1]:
            d = q["d"]
            expired = i - q["origin"] >= OB_VALID or i - q["brk"] > C_FORM
            tested = i > q["brk"] and (l[i] <= q["top"] if d == 1 else h[i] >= q["bottom"])
            if expired or tested: _n('midway_expired' if expired else 'midway_tested'); cands.remove(q); continue
            opp = (c[i] < o[i] and o[i] - c[i] >= atr[i] * 0.8) if d == 1 else (c[i] > o[i] and c[i] - o[i] >= atr[i] * 0.8)
            q["streak"] = q["streak"] + 1 if opp else 0
            if q["streak"] >= 2: q["clean"] = False
            has = cpl[i] if d == 1 else cph[i]
            if not has: continue
            _n('midway_pivot_seen')
            px = i - CPP; py = float(l[px] if d == 1 else h[px])
            react = float(hh9[i] - l[px]) if d == 1 else float(h[px] - ll9[i])
            sep = py > q["top"] if d == 1 else py < q["bottom"]
            if px > q["brk"] and sep and untouched(d, py, px, i) and react >= atr[i] * C_REACT:
                _n('midway_fresh_pivot')
                for nm_, ok_ in (("q_strong", q["strong"]), ("q_react", react >= atr[i] * max(0.55, C_REACT * 1.5)), ("q_good", q["good"]), ("q_clean", q["clean"])):
                    if ok_: _n(nm_)
                score = int(q["strong"]) + int(react >= atr[i] * max(0.55, C_REACT * 1.5)) + int(q["good"]) + int(q["clean"])   # a count, not an OR
                if score >= C_SCORE:
                    _n('midway_block')
                    if not any(b_[0] == d and b_[1] == q["origin"] for b_ in blocks):
                        blocks.append([d, q["origin"], i, q["top"], q["bottom"], False, 3])
                    cands.remove(q)
        del cands[:-24]
        # ---- entries and the end of a block
        keep = []
        for b_ in blocks:
            d, origin, created, top, bottom, entered, kind = b_
            expired = i - origin >= OB_VALID
            if not expired and not entered and i > created and l[i] <= top and h[i] >= bottom:
                b_[5] = True
                if d == 1: out["long"][i] = True; out["stop_long"][i] = bottom
                else: out["short"][i] = True; out["stop_short"][i] = top
                out["kind"][i] = kind
            invalid = c[i] < bottom if d == 1 else c[i] > top
            mitig = i > created and (l[i] <= top if d == 1 else h[i] >= bottom)       # proximal line
            if not (expired or invalid or mitig): keep.append(b_)
        blocks = keep[-100:]
    return out


_C = {}


def signals_of(bars):
    """port() cached per bars object (the entry keeps the object). One Python pass over the candles."""
    key = id(bars)
    if key not in _C or _C[key][0] is not bars:
        while len(_C) > 3: del _C[next(iter(_C))]
        _C[key] = (bars, port(bars))
    return _C[key][1]


def recent(arr, k, n):
    """True on any of the n candles up to and including k."""
    return bool(arr[max(0, k - n):k + 1].any())
