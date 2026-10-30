"""tools/crt_bench.py - the user's "CRT 5m - Candle Range Theory" Pine indicator (2026-10-27) as a futures backtest
(STRATEGY_ANALYSIS_TODO S152).

The rules, as the Pine script draws them (bar-close mode; showPreview's intrabar signal is not tradeable on history):
  range candle  = the previous 5-minute candle (rH, rL)
  bearish CRT   = high > rH, close < rH, close >= rL, not an outside bar (high > rH and low < rL) -> short
  bullish CRT   = low < rL, close > rL, close <= rH, not an outside bar -> long
  optional      sweep candle range >= minRangeATR x ATR14 of the range candle; reqColor (bear red / bull green)
  entry         the sweep candle's close
  fib on the sweep candle (rng = its high - low, fib0 = its low for a long / high for a short):
    SL = fib0 -/+ slFibExt x rng (default 0.25)        TP = fib0 +/- tpFibLevel x rng (default 2.0)
  one CRT at a time (waitTrade); the next one may fire on the candle the previous one ends.

Fills  entry at the sweep candle's close; exits walked on the 1-minute candles after it (a minute that touches both:
       stop first; a gap through a level fills at the open). Slippage 0.5 pt a side + futures charges by trade date
       (jilly._charges), 1 lot of 65.
Modes  "pine"     the indicator literally: no session boundaries, held until SL / TP (overnight included)
       "intraday" the range and sweep candles in the same session, entries on candles closing by 15:10, flat at 15:20
Split  2018-22 (IS) / 2023-26 (OOS) / 2026 alone. The defaults are the script's own; the grid is sensitivity, not a pick.

    python tools/crt_bench.py
"""
import os
import sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path: sys.path.insert(0, os.path.join(HERE, "tools")); sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import core
import bandlab as BL

JF = BL.JF
LOT = 65


def bars5():
    f, MIN, cut, ses, year = BL.data()
    B, q1 = BL.tf_bars(5)
    tr = np.maximum(B.h[1:], B.c[:-1]) - np.minimum(B.l[1:], B.c[:-1])
    tr = np.concatenate([[B.h[0] - B.l[0]], tr])
    atr = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().values        # ta.atr = RMA of the true range
    return B, q1, atr


def simulate(mode="intraday", tp_fib=2.0, sl_ext=0.25, min_atr=0.0, req_color=False, last_entry=910, flat=920, invert=None):
    f, MIN, cut, ses, year = BL.data()
    B, q1, atr = bars5()
    O, H, L, C = B.o, B.h, B.l, B.c
    n5, n1 = len(C), len(f.c)
    out = []; free_at = 0                      # 1-minute index from which a new CRT may be taken
    for k in range(2, n5):
        i = int(q1[k])                         # the sweep candle's last minute: entry at its close
        if i < free_at - 0 or i + 1 >= n1: continue
        if i < free_at: continue
        rH, rL = H[k - 1], L[k - 1]
        if mode == "intraday":
            if ses[int(q1[k - 1])] != ses[i] or MIN[i] + 1 > last_entry: continue
        if (rH - rL) < min_atr * atr[k - 1]: continue
        outside = H[k] > rH and L[k] < rL
        if outside: continue
        bear = H[k] > rH and C[k] < rH and C[k] >= rL and (not req_color or C[k] < O[k])
        bull = L[k] < rL and C[k] > rL and C[k] <= rH and (not req_color or C[k] > O[k])
        if not (bear or bull): continue
        side = 1 if bull else -1
        rng = max(H[k] - L[k], 0.05)
        fib0 = L[k] if bull else H[k]
        sl = fib0 - side * sl_ext * rng
        tp = fib0 + side * tp_fib * rng
        entry = C[k]
        if side * (tp - entry) <= 0: continue
        if invert == "mirror":                 # the opposite of the same trade: its stop is the target, its target the stop
            side, sl, tp = -side, tp, sl
        elif invert == "fresh":                # the opposite side with the script's own geometry from the other extreme
            side = -side; fib0 = L[k] if side > 0 else H[k]
            sl = fib0 - side * sl_ext * rng; tp = fib0 + side * tp_fib * rng
        j = i + 1; why = None; px = None
        while j < n1:
            if mode == "intraday" and (ses[j] != ses[i] or MIN[j] >= flat):
                if ses[j] != ses[i]: j -= 1; px = f.c[j]
                else: px = f.o[j]
                why = "eod"; break
            o_, h_, l_ = f.o[j], f.h[j], f.l[j]
            if side * (o_ - sl) <= 0: why, px = "sl", o_; break
            if (l_ <= sl) if side > 0 else (h_ >= sl): why, px = "sl", sl; break
            if side * (o_ - tp) >= 0: why, px = "tp", o_; break
            if (h_ >= tp) if side > 0 else (l_ <= tp): why, px = "tp", tp; break
            j += 1
        if why is None: break                  # still open at the end of the data
        out.append((side, i, j, entry, px, why, rng))
        free_at = j                            # the indicator may fire again on the candle the trade ends
    return out


def evaluate(tr, label=""):
    f, MIN, cut, ses, year = BL.data()
    if not tr: return dict(label=label, n=0)
    a = np.array([x[1] for x in tr])
    gross = np.array([x[0] * (x[4] - x[3]) for x in tr])
    pts = gross - 1.0                                                   # 0.5 pt slippage a side
    chg = np.array([JF._charges(core.dstr(int(f.day[i])), "FUT", f.c[i], f.c[i], LOT)["total"] / LOT for i in a])
    net = (pts - chg) * LOT
    yy = year[a]
    wk = pd.Series(net, index=pd.to_datetime([core.dstr(int(f.day[i])) for i in a])).resample("W").sum()
    wk = wk[wk != 0]
    def pf(x):
        w = x[x > 0].sum(); l = -x[x <= 0].sum(); return round(float(w / l), 2) if l else float("inf")
    def dd(x):
        eq = np.cumsum(x); return round(float((eq - np.maximum.accumulate(eq)).min())) if len(x) else 0
    A, Bm, Z = yy <= 2022, yy >= 2023, yy == 2026
    why = pd.Series([x[5] for x in tr]).value_counts().to_dict()
    t = float(net.mean() / (net.std(ddof=1) / np.sqrt(len(net)))) if len(net) > 1 else 0.0
    return dict(label=label, n=len(tr), per_day=round(len(tr) / len(np.unique(f.day[a])), 2),
                win=round(float((net > 0).mean() * 100), 1), gross_pts=round(float(gross.mean()), 2),
                cost_pts=round(float(1.0 + chg.mean()), 2), rng=round(float(np.mean([x[6] for x in tr])), 1),
                net=round(float(net.sum())), netA=round(float(net[A].sum())), netB=round(float(net[Bm].sum())), net26=round(float(net[Z].sum())),
                pf=pf(net), pfA=pf(net[A]), pfB=pf(net[Bm]), pf26=pf(net[Z]), t=round(t, 2), dd=dd(net),
                worst_wk=round(float(wk.min())), pos_wk=round(float((wk > 0).mean() * 100), 1),
                long_net=round(float(net[np.array([x[0] > 0 for x in tr])].sum())), exits=why,
                gross_pf=pf(gross), by_year={int(y): round(float(net[yy == y].sum())) for y in np.unique(yy)})


if __name__ == "__main__":
    import json, time
    t0 = time.time()
    rows = []
    if "invert" in sys.argv:                   # S152: sell on every bullish CRT, buy on every bearish one
        for mode in ("pine", "intraday"):
            for inv in ("mirror", "fresh"):
                rows.append(evaluate(simulate(mode, invert=inv), f"{mode} | inverted ({inv})"))
        for se in (0.0, 1.0):
            rows.append(evaluate(simulate("intraday", sl_ext=se, invert="fresh"), f"intraday | inverted (fresh), SL -{se}"))
        for ma in (1.0, 1.5):
            rows.append(evaluate(simulate("intraday", min_atr=ma, invert="fresh"), f"intraday | inverted (fresh), range >= {ma} ATR"))
        for r in rows: print(json.dumps(r))
        sys.exit()
    for mode in ("pine", "intraday"):
        rows.append(evaluate(simulate(mode), f"{mode} | defaults (TP fib 2, SL -0.25, no filters)"))
    for tpf in (1.0, 1.5, 3.0):
        rows.append(evaluate(simulate("intraday", tp_fib=tpf), f"intraday | TP fib {tpf}"))
    for se in (0.0, 0.5, 1.0):
        rows.append(evaluate(simulate("intraday", sl_ext=se), f"intraday | SL -{se}"))
    rows.append(evaluate(simulate("intraday", req_color=True), "intraday | sweep candle coloured"))
    for ma in (0.5, 1.0, 1.5):
        rows.append(evaluate(simulate("intraday", min_atr=ma), f"intraday | range >= {ma} ATR"))
    for r in rows: print(json.dumps(r))
    print(f"{time.time() - t0:.0f}s")
