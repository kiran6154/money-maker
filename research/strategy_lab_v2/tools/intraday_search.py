"""tools/intraday_search.py - how to arrive at a 1-minute intraday strategy like the EMA bands (S148).

Step 1  the edge: does a move continue or reverse? Correlation of the last h minutes' return with the next h minutes'
        (same session only), NIFTY near-month futures 1-minute, by horizon, by period and by time of day; and the
        variance ratio VR(h) = var(h-minute returns) / (h x var(1-minute returns)) - above 1 trends, below 1 reverts.
Step 2  the hurdle: what a 1-lot futures round trip costs in points (0.5 pt slippage a side + charges by date).
Step 3  the family: the EMA distance bands on 1-minute candles, intraday (entries 09:30 - 14:30, flat at the 15:20 open),
        breakout (trend) and fade (reversion) readings, with and without the S146 slope filter, over a small grid;
        chosen on 2018-22 (net PF with at least 300 trades), read on 2023-26.
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd, numba as nb, core
JF = core.family("jilly")
f = JF._store_bars("fut")
t, o, h, l, c = f.t, f.o, f.h, f.l, f.c
MIN = (t % core.DAY) // 60
day = f.day
year = np.array([int(core.dstr(int(d))[:4]) for d in day])
E = f.extra["expiry"]

# ---------------------------------------------------------------- step 1: persistence
print("#### Step 1 - does a move continue? corr(last h-min return, next h-min return), same session; VR = variance ratio\n")
lc = np.log(c)
print("| Horizon | corr 2018-22 | corr 2023-26 | VR 2018-22 | VR 2023-26 |\n|---|---|---|---|---|")
r1 = np.diff(lc); same1 = day[1:] == day[:-1]
for hh in (1, 5, 15, 30, 60):
    i = np.arange(hh, len(c) - hh)
    ok = (day[i - hh] == day[i]) & (day[i + hh] == day[i])
    past, fut = (lc[i] - lc[i - hh])[ok], (lc[i + hh] - lc[i])[ok]; yy = year[i][ok]
    cs = [np.corrcoef(past[m], fut[m])[0, 1] for m in (yy <= 2022, yy >= 2023)]
    vr = []
    j = np.arange(hh, len(c)); okh = day[j - hh] == day[j]; rh = lc[j] - lc[j - hh]
    for lo_, hi_ in ((0, 2022), (2023, 9999)):
        v1 = np.var(r1[same1 & (year[1:] >= lo_) & (year[1:] <= hi_)])
        vr.append(np.var(rh[okh & (year[j] >= lo_) & (year[j] <= hi_)]) / (hh * v1))
    print(f"| {hh} min | {cs[0]:+.4f} | {cs[1]:+.4f} | {vr[0]:.3f} | {vr[1]:.3f} |")

print("\n30-minute persistence by time of day (corr of the last 30 minutes with the next 30, 2018-22 / 2023-26):")
i = np.arange(30, len(c) - 30); ok = (day[i - 30] == day[i]) & (day[i + 30] == day[i])
past, fut, mi, yy = (lc[i] - lc[i - 30])[ok], (lc[i + 30] - lc[i])[ok], MIN[i][ok], year[i][ok]
for a, b in ((585, 630), (630, 720), (720, 810), (810, 900)):
    m = (mi >= a) & (mi < b)
    cs = [np.corrcoef(past[m & q], fut[m & q])[0, 1] for q in (yy <= 2022, yy >= 2023)]
    print(f"   {a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d}  {cs[0]:+.4f} / {cs[1]:+.4f}")

# ---------------------------------------------------------------- step 2: the hurdle
pts = []
for yy_, px in ((2019, 11500), (2022, 17500), (2025, 24000), (2026, 24000)):
    ch = JF._charges(f"{yy_}-06-01", "FUT", px, px, 65)["total"] / 65
    pts.append(f"{yy_}: {ch + 1.0:.1f} pts ({ch:.1f} charges + 1.0 slippage)")
print("\n#### Step 2 - the cost hurdle of a 1-lot futures round trip, in points:", " · ".join(pts))

# ---------------------------------------------------------------- step 3: the family on 1-minute candles, intraday
@nb.njit(cache=True)
def sim(o, c, ema, up, lo, MIN, day, mode, slope_n):
    """mode 1 = breakout (close through a band enters that way), -1 = fade (close back inside a band enters against
    the band: the reversion reading). Exit: a close back through the EMA, or the 15:20 open. Entries 09:30 - 14:30."""
    n = len(c); out = np.zeros((n // 4, 4)); k = 0; pos = 0; e = 0; epx = 0.0
    for i in range(max(slope_n, 1) + 1, n - 1):
        if pos != 0:
            if day[i + 1] != day[i] or MIN[i + 1] >= 920:
                j = i + 1 if day[i + 1] == day[i] else i
                px = o[j] if j == i + 1 else c[i]
                out[k, 0] = pos; out[k, 1] = e; out[k, 2] = j; out[k, 3] = pos * (px - epx); k += 1; pos = 0; continue
            if (pos == 1 and c[i - 1] >= ema[i - 1] and c[i] < ema[i]) or (pos == -1 and c[i - 1] <= ema[i - 1] and c[i] > ema[i]):
                out[k, 0] = pos; out[k, 1] = e; out[k, 2] = i + 1; out[k, 3] = pos * (o[i + 1] - epx); k += 1; pos = 0
            continue
        if MIN[i] < 570 or MIN[i] > 870 or day[i + 1] != day[i]: continue
        s = 0
        if mode == 1:
            if c[i - 1] <= up[i - 1] and c[i] > up[i]: s = 1
            elif c[i - 1] >= lo[i - 1] and c[i] < lo[i]: s = -1
        else:
            if c[i - 1] >= up[i - 1] and c[i] < up[i]: s = -1
            elif c[i - 1] <= lo[i - 1] and c[i] > lo[i]: s = 1
        if s == 0: continue
        if slope_n > 0 and s * (ema[i] - ema[i - slope_n]) <= 0: continue
        pos = s; e = i + 1; epx = o[i + 1]
    return out[:k]

def bands(n, mult, dl):
    k = 2 / (n + 1); ema = np.empty(len(c)); ema[0] = c[0]
    ema = pd.Series(c).ewm(alpha=k, adjust=False).mean().values
    ad = pd.Series(np.abs(c - ema)).rolling(dl).mean().values
    return ema, ema + mult * ad, ema - mult * ad

def evaluate(tr):
    if not len(tr): return None
    e = tr[:, 1].astype(np.int64); yy = year[e]
    gross = tr[:, 3] - 1.0                                     # 0.5 pt slippage a side
    chg = np.array([JF._charges(core.dstr(int(day[i]))[:10], "FUT", o[i], o[i], 65)["total"] / 65 for i in e])
    net = (gross - chg) * 65
    def pf(x):
        w = x[x > 0].sum(); L = -x[x <= 0].sum(); return w / L if L else np.inf
    A, B = yy <= 2022, yy >= 2023
    return dict(n=len(tr), nA=int(A.sum()), nB=int(B.sum()), gpts=float(tr[:, 3].mean()), pfA=pf(net[A]), pfB=pf(net[B]), netA=net[A].sum(), netB=net[B].sum(),
                gpfA=pf(tr[A, 3]), gpfB=pf(tr[B, 3]), hold=float(np.mean(tr[:, 2] - tr[:, 1])))

rows = []
for n_ in (20, 50, 100, 200):
    for mult in (2.0, 3.0, 4.0):
        for dl in (20, 60):
            ema, up, lo = bands(n_, mult, dl)
            for mode in (1, -1):
                for sl in (0, 60):
                    r = evaluate(sim(o, c, ema, up, lo, MIN, day, mode, sl))
                    if r: rows.append(dict(ema=n_, mult=mult, dlen=dl, mode="breakout" if mode == 1 else "fade", slope=sl, **r))
R = pd.DataFrame(rows)
print("\n#### Step 3 - EMA distance bands on 1-minute candles, intraday: the grid (net = after slippage and charges, 1 lot)\n")
print(f"{len(R)} versions. Gross points a trade: median {R.gpts.median():+.2f}, best {R.gpts.max():+.2f}; versions with a positive gross: {(R.gpts > 0).sum()}")
show = R.sort_values("pfA", ascending=False)
print("\n| EMA | mult | dlen | reading | slope filter | trades | gross pts / trade | min held | gross PF 18-22 / 23-26 | net PF 18-22 / 23-26 | net 18-22 / 23-26 ₹ |\n|---|---|---|---|---|---|---|---|---|---|---|")
for x in list(show.head(12).itertuples()) + list(show.tail(3).itertuples()):
    print(f"| {x.ema} | {x.mult:g} | {x.dlen} | {x.mode} | {'60 min' if x.slope else '-'} | {x.n} | {x.gpts:+.2f} | {x.hold:.0f} | {x.gpfA:.2f} / {x.gpfB:.2f} | {x.pfA:.2f} / {x.pfB:.2f} | {x.netA:+,.0f} / {x.netB:+,.0f} |")
pick = R[R.nA >= 300].sort_values("pfA", ascending=False).iloc[0]
print(f"\nchosen on 2018-22 (net PF, >= 300 trades): EMA {pick.ema}, x{pick.mult:g}, dlen {pick.dlen}, {pick['mode']}, slope {pick.slope} - "
      f"2018-22 PF {pick.pfA:.2f} ({pick.nA}) -> 2023-26 PF {pick.pfB:.2f} ({pick.nB}), net {pick.netB:+,.0f}")
print("by reading (median net PF 2018-22 / 2023-26):", R.groupby("mode")[["pfA", "pfB", "gpts"]].median().round(3).to_dict())
R.to_csv(os.path.join(HERE, "results", "intraday_search_grid.csv"), index=False)
