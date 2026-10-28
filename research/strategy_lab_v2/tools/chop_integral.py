"""tools/chop_integral.py - the Choppiness Index integrated over a sideways stretch, as a grade of the stretch, and whether
the grade says anything about the breakout that ends it (S154).

The user, 2026-10-28: "apply integration in this and grade its quality" (after the CHOP sideways charts).

Fixed before the run (N and the cutoff are the ones drawn for the user on 2026-10-28, picked by eye on 21-23 Oct 2026 -
not tuned on this test):
  5-minute near-month futures candles (09:15-aligned). Over the PREVIOUS N = 12 candles (n-1 lag): path = sum of (high -
  low), span = highest high - lowest low, CHOP = 100 log10(path / span) / log10(N). Sideways when CHOP >= 50.
  A sideways stretch = consecutive sideways candles; its integral = sum over the stretch of (CHOP - 50) (area above the
  cutoff, in CHOP-points x candles), plus its length and its box width (the span at the break).
  Breakout = a candle whose close is outside the previous-12 high / low box while the candle before was sideways, 09:30 -
  14:30. Trade: in at the next candle's open the break's way; stop = the opposite side of the box; out at the stop (on a
  close), after 12 candles (1 hour), or 15:20. Costs = tools/bandlab.evaluate (futures, dated charges + 1 pt slippage).
  Grade = the integral's terciles, cut on 2018-22 breaks: C (lowest third), B, A (highest third); the 2023-26 breaks use
  the same cut points. Reference rows: breaks of the box when the candle before was NOT sideways; every sideways break.
  Also reported per grade (added after the first run, to separate box width from the grade): reached 30 points
  the break's way before the stop; share of breaks that go 1x the box width the break's way before closing back past the box's
  other side (follow-through), within the hour.
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
import core, bandlab as BL

N, CUT, HOLD = 12, 50.0, 12
f, MIN1, cut1, ses1, year1 = BL.data()
B, last = BL.tf_bars(5)
t = np.asarray(B.t); o, h, l, c = (np.asarray(x, float) for x in (B.o, B.h, B.l, B.c))
day = t // core.DAY; MIN = (t % core.DAY) // 60
yr = np.array([int(core.dstr(int(d))[:4]) for d in day])
path = pd.Series(h - l).rolling(N).sum().shift(1).values
hh = pd.Series(h).rolling(N).max().shift(1).values; ll = pd.Series(l).rolling(N).min().shift(1).values
with np.errstate(all="ignore"):
    chop = 100 * np.log10(path / (hh - ll)) / np.log10(N)
side = chop >= CUT
n = len(c)

# integral of the running sideways stretch, known at each candle
area = np.zeros(n); run = np.zeros(n, int)
for i in range(1, n):
    if side[i] and day[i] == day[i - 1]:
        area[i] = area[i - 1] + (chop[i] - CUT); run[i] = run[i - 1] + 1
    elif side[i]:
        area[i] = chop[i] - CUT; run[i] = 1

ev = []
for i in range(N + 1, n - 1):
    if MIN[i] < 570 or MIN[i] > 870 or day[i + 1] != day[i]: continue
    s = 1 if c[i] > hh[i] else -1 if c[i] < ll[i] else 0
    if not s: continue
    from_side = bool(side[i - 1])
    w = hh[i] - ll[i]; stop = ll[i] if s > 0 else hh[i]
    e = i + 1; x = None; why = "time"; ft = False; f30 = False
    for j in range(e, min(e + HOLD, n)):
        if day[j] != day[i]: x = j - 1; why = "eod"; break
        if MIN[j] + 5 > 920: x = j; why = "eod"; break
        if not ft and ((s > 0 and h[j] >= c[i] + w) or (s < 0 and l[j] <= c[i] - w)): ft = True
        if not f30 and ((s > 0 and h[j] >= o[e] + 30) or (s < 0 and l[j] <= o[e] - 30)): f30 = True
        if (s > 0 and c[j] < stop) or (s < 0 and c[j] > stop): x = j; why = "stop"; break
    if x is None: x = min(e + HOLD - 1, n - 1)
    first1 = int(last[e - 1]) + 1                       # the first 1-minute bar of candle e
    ev.append(dict(i=i, yr=yr[i], side=s, from_side=from_side, area=area[i - 1] if from_side else 0.0,
                   run=run[i - 1] if from_side else 0, width=w, ft=ft, f30=f30, why=why,
                   tr=(s, first1, int(last[x]), o[e], c[x], why)))
E = pd.DataFrame(ev)

S = E[E.from_side].copy()
qa = np.quantile(S[S.yr <= 2022].area, [1 / 3, 2 / 3])
S["grade"] = np.where(S.area >= qa[1], "A", np.where(S.area >= qa[0], "B", "C"))


def line(nm, D):
    r = BL.evaluate(list(D.tr), nm)
    if not r.get("n"): return print(f"| {nm} | 0 |")
    print(f"| {nm} | {r['n']} | {D.run.mean():.0f} | {D.width.median():.0f} | {D.ft.mean() * 100:.0f}% | {(D.why == 'stop').mean() * 100:.0f}% | "
          f"{r['gross_pts']:+.2f} | {r['pfA']:.2f} | {r['pfB']:.2f} | {r['pf26']:.2f} | {r['netA']:+,.0f} | {r['netB']:+,.0f} |")


print(f"#### CHOP({N}) on 5-minute futures, sideways >= {CUT}: {side[np.isfinite(chop)].mean() * 100:.0f}% of candles; "
      f"grade cut points (integral, 2018-22 terciles): C < {qa[0]:.0f} <= B < {qa[1]:.0f} <= A\n")
print("| Breaks | Trades | Avg stretch, candles | Median box, pts | Went 1x box the break's way | Stopped | Gross pts / trade | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ |\n|---|---|---|---|---|---|---|---|---|---|---|---|")
line("not from sideways (reference)", E[~E.from_side])
line("all from sideways", S)
for g in ("A", "B", "C"): line(f"grade {g}", S[S.grade == g])
print("\nby period, follow-through rate per grade:")
for nm, q in (("2018-22", S.yr <= 2022), ("2023-26", S.yr >= 2023)):
    print(nm, {g: f"{S[q & (S.grade == g)].ft.mean() * 100:.0f}% of {int((q & (S.grade == g)).sum())}" for g in "ABC"})
print("reached 30 points the break's way (from the entry) before the stop, within the hour:")
for nm, q in (("2018-22", S.yr <= 2022), ("2023-26", S.yr >= 2023)):
    print(nm, {g: f"{S[q & (S.grade == g)].f30.mean() * 100:.0f}%" for g in "ABC"}, "| not from sideways:", f"{E[~E.from_side & (E.yr <= 2022 if nm == '2018-22' else E.yr >= 2023)].f30.mean() * 100:.0f}%")
print("by length alone (candles in the stretch):", {k: f"{g.ft.mean() * 100:.0f}% ft, {len(g)}" for k, g in S.groupby(pd.cut(S.run, [0, 3, 6, 12, 99]), observed=True)})
