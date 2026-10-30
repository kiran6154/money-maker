"""tools/supertrend_mtf.py - multi-timeframe Supertrend on 1-minute futures (S153).

The user, 2026-10-28: "if day supertrend, 15min and 5min are in the same direction, do a trade in 1min in the same direction".

Pre-registered before the run:
  Supertrend(10, 3) on hl2 with Wilder ATR (TradingView's default), on near-month futures from the download store.
  Daily  : the direction of the last COMPLETED daily bar (yesterday's) - today's daily candle is not known intraday.
  15m/5m : the direction of the last completed candle (09:15-aligned), known at its last minute.
  1m     : the 1-minute Supertrend.
  Entries (09:30 - 14:30, in at the next minute's open, any number a day, one position at a time):
    E1 flip   - the 1-minute Supertrend flips to the side the daily, 15m and 5m all agree on
    E2 align  - all four agree and did not the minute before (a 1m flip OR the 5m / 15m joining)
  Exits (out at the next minute's open; always out at 15:20):
    X1 the 1-minute Supertrend flips against;  X2 the 5-minute flips against;  X3 the 15-minute flips against
  pick = the best 2018-22 PF with >= 200 trades; 2023-26 and 2026 read without re-picking. Then the pick and its
  neighbours traded through a weekly option 100 points in the money (as S150 Part B).
Costs: tools/bandlab.evaluate (0.5-point slippage each side + the dated futures charges, 1 lot of 65).
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from numba import njit
import core, store_reader
import bandlab as BL
JF = BL.JF
f, MIN, cut, ses, year = BL.data(); n = len(f.t)
o, h, l, c = f.o, f.h, f.l, f.c


@njit(cache=True)
def _st(h, l, c, n, m):
    out = np.zeros(len(h), np.int8); line = np.zeros(len(h))
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
        out[i] = d; line[i] = fl if d == 1 else fu
    return out, line


def st_dir(tf, N=10, M=3.0):
    """Supertrend direction known at each 1-minute bar."""
    B, last = BL.tf_bars(tf)
    d, _ = _st(np.asarray(B.h, float), np.asarray(B.l, float), np.asarray(B.c, float), N, M)
    if tf == 1: return d
    out = np.zeros(n, np.int8); k = np.full(n, -1); k[last] = np.arange(len(last)); k = np.maximum.accumulate(k)
    ok = k >= 0; out[ok] = d[k[ok]]
    return out


def daily_dir(N=10, M=3.0):
    a, z = cut[:-1], cut[1:]
    H = np.maximum.reduceat(h, a); L = np.minimum.reduceat(l, a); C = c[z - 1]
    d, _ = _st(H.astype(float), L.astype(float), C.astype(float), N, M)
    out = np.zeros(n, np.int8)
    for s in range(1, len(a)): out[a[s]:z[s]] = d[s - 1]          # yesterday's completed bar
    return out


D1, D5, D15, DD = st_dir(1), st_dir(5), st_dir(15), daily_dir()
HTF = np.where((DD == D15) & (D15 == D5), DD, 0).astype(np.int8)    # the three higher frames agree
ALL = np.where(HTF == D1, HTF, 0).astype(np.int8)
XS = {"X1 1m flip": D1, "X2 5m flip": D5, "X3 15m flip": D15}


def run(entry, exit_):
    X = XS[exit_]; out = []
    for a, z in zip(cut[:-1], cut[1:]):
        pos = 0
        for i in range(a + 1, z - 1):
            if pos:
                why = "eod" if MIN[i + 1] >= 920 else ("flip" if X[i] == -pos else None)
                if why:
                    out.append((pos, e, i + 1, o[e], o[i + 1], why)); pos = 0
                    if why == "eod": break
                continue
            if MIN[i] < 570 or MIN[i] > 870 or MIN[i + 1] >= 920: continue
            s = HTF[i]
            if not s: continue
            sig = (D1[i] == s and D1[i - 1] == -s) if entry == "E1" else (ALL[i] == s and ALL[i - 1] != s)
            if sig: pos, e = s, i + 1
        if pos: out.append((pos, e, z - 1, o[e], c[z - 1], "eod"))
    return out


m = (MIN >= 570) & (MIN <= 870)
print(f"#### Supertrend(10,3) daily + 15m + 5m agree: {(HTF[m] != 0).mean() * 100:.0f}% of 09:30-14:30 minutes "
      f"(long {(HTF[m] > 0).mean() * 100:.0f}%, short {(HTF[m] < 0).mean() * 100:.0f}%); daily long on {(DD[cut[1:-1]] > 0).mean() * 100:.0f}% of days\n")
HD = "| Version | Trades | Avg hold, min | Gross pts / trade | Win % | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ | Long net ₹ |\n|---|---|---|---|---|---|---|---|---|---|---|---|"
print(HD)
T, R = {}, {}
for e_ in ("E1", "E2"):
    for x_ in XS:
        k = f"{e_} {'1m flip' if e_ == 'E1' else 'fresh 4-way align'} / {x_}"
        T[k] = run(e_, x_); r = BL.evaluate(T[k], k); R[k] = r
        print(f"| {k} | {r['n']} | {r['hold_min']:.0f} | {r['gross_pts']:+.2f} | {r['win']:.0f} | {r['pfA']:.2f} | {r['pfB']:.2f} | {r['pf26']:.2f} | "
              f"{r['netA']:+,.0f} | {r['netB']:+,.0f} | {r['net26']:+,.0f} | {r['long_net']:+,.0f} |", flush=True)
pick = max((k for k in R if R[k].get("nA", 0) >= 200), key=lambda k: R[k]["pfA"])
print(f"\npick (best 2018-22 PF, >= 200 trades): **{pick}**")

# by year for the pick
tr = T[pick]; yy = np.array([year[x[1]] for x in tr])
pts = np.array([x[0] * (x[4] - x[3]) for x in tr]) - 1.0
chg = np.array([JF._charges(core.dstr(int(f.day[x[1]])), "FUT", o[x[1]], o[x[1]], 65)["total"] / 65 for x in tr])
net = (pts - chg) * 65; lg = np.array([x[0] > 0 for x in tr])
print("\n| Year | Trades | Gross pts / trade | Cost pts / trade | Net ₹ | Long ₹ | Short ₹ |\n|---|---|---|---|---|---|---|")
for y in sorted(set(yy)):
    q = yy == y
    print(f"| {y} | {q.sum()} | {pts[q].mean() + 1:+.2f} | {chg[q].mean() + 1:.2f} | {net[q].sum():+,.0f} | {net[q & lg].sum():+,.0f} | {net[q & ~lg].sum():+,.0f} |")

# ---------------------------------------------------------------- through a 100-point ITM weekly option (as S150)
sp = JF._store_bars("index"); exps = sorted(e["expiry"] for e in store_reader.expiries())
_oc = {}
def ocand(ex, k, right, day):
    key = (ex, k, right, day)
    if key not in _oc:
        if len(_oc) > 3000: _oc.clear()
        oc = store_reader.option_candles(ex, k, right, day, day, "minute")
        _oc[key] = (np.array([x[0] for x in oc], dtype=np.int64), np.array([x[1] for x in oc])) if oc else None
    return _oc[key]

def through_option(tr, itm=100):
    out, miss = [], 0
    for s, e, x, ep, xp, why in tr:
        day = core.dstr(int(f.day[e])); te, tx = int(f.t[e]), int(f.t[x])
        si = int(np.searchsorted(sp.t, int(f.t[e - 1])))
        if si >= len(sp.t) or abs(int(sp.t[si]) - int(f.t[e - 1])) > 120: miss += 1; continue
        atm = int(round(float(sp.c[si]) / 50) * 50); right = "CE" if s > 0 else "PE"
        k = atm - itm if s > 0 else atm + itm
        ex = next((q for q in exps if q >= day), None)
        got = ocand(ex, k, right, day) if ex else None
        if got is None: miss += 1; continue
        ot, oo = got
        ie, ix = int(np.searchsorted(ot, te)), int(np.searchsorted(ot, tx))
        if ie >= len(ot) or ot[ie] - te > 300 or ix >= len(ot): miss += 1; continue
        rec = dict(position="LONG", entry_time=int(ot[ie]), exit_time=int(ot[ix]), entry_px=float(oo[ie]), exit_px=float(oo[ix]))
        JF._price({"lot_size": 65}, rec, "OPT"); rec["yy"] = int(day[:4]); out.append(rec)
    return out, miss

def pf(x):
    w = sum(v for v in x if v > 0); L_ = -sum(v for v in x if v <= 0); return w / L_ if L_ else float("inf")

print("\n#### Through a weekly option 100 points in the money\n| Version | Trades (no option candle) | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ |\n|---|---|---|---|---|---|---|---|")
for k in sorted(R, key=lambda k: -R[k]["pfA"])[:3]:
    Ro, miss = through_option(T[k])
    a = [r["net"] for r in Ro if r["yy"] <= 2022]; b = [r["net"] for r in Ro if r["yy"] >= 2023]; z = [r["net"] for r in Ro if r["yy"] == 2026]
    print(f"| {k} | {len(Ro)} ({miss}) | {pf(a):.2f} | {pf(b):.2f} | {pf(z):.2f} | {sum(a):+,.0f} | {sum(b):+,.0f} | {sum(z):+,.0f} |", flush=True)
