"""tools/st_straddle.py - 1-minute Supertrend option selling that turns into a straddle (S155).

The user, 2026-10-28: "take a position on the 1-minute Supertrend; if the other side comes, make it a straddle; on a range
breakout exit the loss-making one; do only for sell".

Read as (fixed before the run):
  Supertrend(10, 3) (hl2, Wilder ATR) on 1-minute near-month futures from the download store.
  Flat  : a Supertrend flip 09:20 - 14:30 -> SELL one ATM weekly option at the next minute's open: a flip down sells the CE,
          a flip up sells the PE (ATM = the index at the signal minute rounded to 50; the nearest weekly expiry on or after
          the day). The range starts at this minute.
  One leg: the opposite flip (the "other side") -> SELL the other option too = a straddle. V1: at the SAME strike as the
          held leg (a true straddle); V2: at the ATM strike of that minute. The range is frozen = the futures high / low
          from the held leg's entry to this flip.
  Straddle: a 1-minute futures close above the range -> buy back the CE (the losing leg), keep the PE; a close below ->
          buy back the PE, keep the CE. The kept leg is a one-leg position again: its range restarts at the exit minute,
          and the next opposite flip adds the other leg again (V1 at the kept leg's strike).
  New straddle conversions until 15:10; everything is bought back at 15:20. No stop on a single leg (the straddle is the
  hedge, as asked). Fills at the option minute's open (the first candle at or after the minute, within 5 minutes; an
  entry with no candle is skipped). Costs: the lab's option slippage (max(0.5, 0.5%)) and charges by date, lot 65.
  Reference B0: sell on every flip and buy back on the next flip, reversing into the other side (no straddle).
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
from collections import defaultdict
import numpy as np, pandas as pd
from numba import njit
import core, store_reader
import bandlab as BL
JF = BL.JF
f, MIN, cut, ses, year = BL.data()
o, h, l, c = f.o, f.h, f.l, f.c
LOT = 65


@njit(cache=True)
def _st(h, l, c, n, m):
    out = np.zeros(len(h), np.int8)
    a = 0.0; s = 0.0; fu = 0.0; fl = 0.0; d = 1
    for i in range(len(h)):
        tr = h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        s += tr
        a = s / (i + 1) if i < n else (a * (n - 1) + tr) / n
        mid = (h[i] + l[i]) / 2; bu = mid + m * a; bl = mid - m * a
        if i == 0:
            fu, fl = bu, bl
        else:
            fu = bu if (bu < fu or c[i - 1] > fu) else fu
            fl = bl if (bl > fl or c[i - 1] < fl) else fl
            if d == 1 and c[i] < fl: d = -1
            elif d == -1 and c[i] > fu: d = 1
        out[i] = d
    return out


D1 = _st(h.astype(float), l.astype(float), c.astype(float), 10, 3.0)
FLIP = np.r_[0, np.where(D1[1:] != D1[:-1], D1[1:], 0)].astype(np.int8)

sp = JF._store_bars("index"); exps = sorted(e["expiry"] for e in store_reader.expiries())
_oc = {}
def ocand(ex, k, right, day):
    key = (ex, k, right, day)
    if key not in _oc:
        if len(_oc) > 4000: _oc.clear()
        oc = store_reader.option_candles(ex, k, right, day, day, "minute")
        _oc[key] = (np.array([x[0] for x in oc], dtype=np.int64), np.array([x[1] for x in oc], float)) if oc else None
    return _oc[key]


def opx(ex, k, right, day, tm, strict=True):
    """(fill time, open price) of the option at the first candle at or after tm (within 5 minutes if strict)."""
    g = ocand(ex, k, right, day)
    if g is None: return None
    ot, oo = g; j = int(np.searchsorted(ot, tm))
    if j >= len(ot): return (int(ot[-1]), float(oo[-1])) if not strict else None
    if strict and ot[j] - tm > 300: return None
    return int(ot[j]), float(oo[j])


def atm(i):
    si = int(np.searchsorted(sp.t, int(f.t[i])))
    if si >= len(sp.t) or abs(int(sp.t[si]) - int(f.t[i])) > 120: return None
    return int(round(float(sp.c[si]) / 50) * 50)


def run(mode):
    trades = []
    for a, z in zip(cut[:-1], cut[1:]):
        day = core.dstr(int(f.day[a])); ex = next((q for q in exps if q >= day), None)
        if ex is None: continue
        legs = {}                                  # right -> dict(k, t, px)
        rlo = rhi = None; rng = None               # running range of the one-leg phase / frozen straddle range
        def sell(right, k, i):
            p = opx(ex, k, right, day, int(f.t[i + 1]))
            if p is None: return False
            legs[right] = dict(k=k, t=p[0], px=p[1]); return True
        def buy(right, i, why):
            L = legs.pop(right); p = opx(ex, L["k"], right, day, int(f.t[min(i + 1, z - 1)]), strict=False)
            rec = dict(position="SHORT", entry_time=L["t"], exit_time=p[0], entry_px=L["px"], exit_px=p[1])
            JF._price({"lot_size": LOT}, rec, "OPT"); rec.update(day=day, right=right, why=why, yy=int(day[:4])); trades.append(rec)
        for i in range(a, z - 1):
            m = MIN[i + 1]
            if m >= 920:
                for r in list(legs): buy(r, i, "eod")
                break
            if legs:
                rhi = max(rhi, h[i]) if rhi is not None else h[i]; rlo = min(rlo, l[i]) if rlo is not None else l[i]
            fl = FLIP[i]
            if mode == "B0":
                if fl and legs:
                    for r in list(legs): buy(r, i, "flip")
                if fl and 560 <= MIN[i] <= 870:
                    k = atm(i)
                    if k: sell("CE" if fl < 0 else "PE", k, i)
                continue
            if len(legs) == 2:
                if c[i] > rng[1]: buy("CE", i, "break"); rhi = rlo = None
                elif c[i] < rng[0]: buy("PE", i, "break"); rhi = rlo = None
                continue
            if len(legs) == 1:
                held = next(iter(legs)); other = "PE" if held == "CE" else "CE"
                if fl == (1 if held == "CE" else -1) and MIN[i] <= 910:      # the other side's flip
                    k = legs[held]["k"] if mode == "V1" else atm(i)
                    if k and sell(other, k, i): rng = (rlo, rhi)
                continue
            if fl and 560 <= MIN[i] <= 870:
                k = atm(i)
                if k and sell("CE" if fl < 0 else "PE", k, i): rhi, rlo = h[i], l[i]
    return pd.DataFrame(trades)


def pf(x):
    w = x[x > 0].sum(); L_ = -x[x <= 0].sum(); return w / L_ if L_ else float("inf")


if __name__ == "__main__":
    print("| Version | Legs | Days | Avg points / leg | Charges ₹ / leg | Win % (leg) | Win % (day) | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ | Worst day ₹ | Max drawdown ₹ |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    R = {}
    for mode, nm in (("V1", "V1 straddle at the held leg's strike"), ("V2", "V2 second leg at the ATM of that minute"), ("B0", "B0 sell on each flip, no straddle")):
        T = run(mode); R[mode] = T
        Dd = T.groupby("day").net.sum(); A, Bq, Z = T.yy <= 2022, T.yy >= 2023, T.yy == 2026
        eq = Dd.cumsum(); dd = (eq - eq.cummax()).min()
        print(f"| {nm} | {len(T)} | {len(Dd)} | {T.pts.mean():+.2f} | {T.chg.map(lambda q: q['total']).mean():.0f} | {(T.net > 0).mean() * 100:.0f} | "
              f"{(Dd > 0).mean() * 100:.0f} | {pf(T.net[A]):.2f} | {pf(T.net[Bq]):.2f} | {pf(T.net[Z]):.2f} | {T.net[A].sum():+,.0f} | "
              f"{T.net[Bq].sum():+,.0f} | {T.net[Z].sum():+,.0f} | {Dd.min():+,.0f} | {dd:+,.0f} |", flush=True)
    T = R["V1"]
    print("\nV1 by year (net ₹, legs, days):", {y: (round(g.net.sum()), len(g), g.day.nunique()) for y, g in T.groupby("yy")})
    print("V1 by exit:", {k: (len(g), round(g.net.sum()), round(g.pts.mean(), 1)) for k, g in T.groupby("why")})
    print("V1 legs per day:", T.groupby("day").size().describe()[["mean", "50%", "max"]].round(1).to_dict())
