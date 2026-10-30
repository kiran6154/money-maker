"""Reporting (spec §2.9, §9.7-9.8) and lot scaling / compounding (§12.7)."""
import numpy as np, pandas as pd
from .costs import LOT

FIXED = 40 * 1.18                  # brokerage + GST per round trip: per order, does not grow with lots (§12.7)


def stats(T, name="", lot=LOT):
    """net, trades, win %, max DD, worst trade, 2018-22 / 2023-26, yearly, and the result at ₹1 / ₹2 slippage per side."""
    if not len(T): return dict(book=name, trades=0)
    T = T.sort_values("exit_time"); x = T.net; eq = x.cumsum(); yr = x.groupby(pd.to_datetime(T.entry_time).dt.year).sum()
    y = pd.to_datetime(T.entry_time).dt.year
    out = dict(book=name, trades=len(T), win=round((x > 0).mean() * 100, 1), net=round(x.sum()), maxDD=round((eq - eq.cummax()).min()),
               worst=round(x.min()), net_18_22=round(x[y <= 2022].sum()), net_23_26=round(x[y >= 2023].sum()),
               slip1=round(x.sum() - len(T) * lot * 2 * 0.9), slip2=round(x.sum() - len(T) * lot * 2 * 1.9),
               yrs_pos=f"{(yr > 0).sum()}/{len(yr)}", by_year=" ".join(f"{k % 100}:{v / 1000:+.0f}k" for k, v in yr.items()))
    if "worst_open" in T: out["worst_open"] = round(T.worst_open.min())
    return out


def flat_share(X):
    """share of 1-min candles with o = h = l = c (no trade) - print a warning above 10 % (§1, §9.8)."""
    return float(((X.open == X.high) & (X.high == X.low) & (X.low == X.close)).mean())


# ------------------------------------------------------------------ §12.7 lot scaling
def scale(T, lots, slip=0.10, lot=LOT):
    """per-trade net at `lots` lots per leg: brokerage + GST stays per order, the rest scales; slip = ₹ per side per unit."""
    return lots * (T.net + FIXED) - FIXED - lots * lot * 2 * (slip - 0.10)


def capital_per_lot(T, short_margin=200000.0, slip=1.0, lot=LOT):
    """peak concurrent short lots x margin + peak long-premium outlay + 1.5 x max drawdown, 1 lot per leg (side: -1 short, +1 long)."""
    ev = sorted([(r.entry_time, 1, r.side, r.entry) for r in T.itertuples()] + [(r.exit_time, -1, r.side, r.entry) for r in T.itertuples()],
                key=lambda z: (z[0], z[1]))
    ns = 0; prem = 0.0; pk_s = 0; pk_p = 0.0
    for t, k, s, e in ev:
        if s < 0: ns += k
        else: prem += k * e * lot
        pk_s = max(pk_s, ns); pk_p = max(pk_p, prem)
    x = scale(T.sort_values("exit_time"), 1, slip, lot); eq = x.cumsum(); dd = (eq - eq.cummax()).min()
    return pk_s * short_margin + pk_p + 1.5 * abs(dd)


class SizingPolicy:
    """lots for the next entry from realised equity; cap at max_lots (§12.7)."""
    def __init__(self, cap_per_lot, max_lots=10): self.cap, self.max = cap_per_lot, max_lots
    def lots(self, equity, current): raise NotImplementedError


class Fixed(SizingPolicy):
    def lots(self, equity, current): return 1


class DoubleUp(SizingPolicy):
    def lots(self, equity, current):
        while current * 2 <= self.max and equity >= self.cap * current * 2: current *= 2
        return current


class DoubleUpDown(SizingPolicy):
    """the recommended rule: double when capital allows 2x, halve if equity falls below what the current lots need."""
    def lots(self, equity, current):
        while current * 2 <= self.max and equity >= self.cap * current * 2: current *= 2
        while current > 1 and equity < self.cap * current: current //= 2
        return current


class AddOne(SizingPolicy):
    def lots(self, equity, current): return int(min(self.max, max(1, equity // self.cap)))


def compound(T, policy, start=None, slip=1.0, lot=LOT):
    """walk entries and exits in time order; lots decided at entry on realised equity. Returns the equity path."""
    T = T.reset_index(drop=True); net1 = T.net - lot * 2 * (slip - 0.10)
    ev = sorted([(r.entry_time, 1, i) for i, r in T.iterrows()] + [(r.exit_time, 0, i) for i, r in T.iterrows()], key=lambda z: (z[0], z[1]))
    eq = start if start is not None else policy.cap; lots = 1; size = {}; hist = []
    for t, k, i in ev:
        if k == 1: lots = policy.lots(eq, lots); size[i] = lots
        else:
            n = size[i]; pnl = n * (net1[i] + FIXED) - FIXED; eq += pnl; hist.append((t, eq, n, pnl))
    H = pd.DataFrame(hist, columns=["t", "equity", "lots", "pnl"])
    yrs = (pd.to_datetime(H.t.iloc[-1]) - pd.to_datetime(T.entry_time.min())).days / 365.25 if len(H) else 1
    s0 = start if start is not None else policy.cap
    return H, dict(final=round(H.equity.iloc[-1]), CAGR=round(((H.equity.iloc[-1] / s0) ** (1 / yrs) - 1) * 100, 1),
                   maxDD=round((H.equity - H.equity.cummax()).min()), final_lots=int(H.lots.iloc[-1]))
