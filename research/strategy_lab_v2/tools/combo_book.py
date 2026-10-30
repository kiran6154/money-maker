"""tools/combo_book.py - Jilly (Strategy 111, futures) + the four Pine rules (IBS overnight, basis z-score overnight, narrow CPR + ORB, EMA
distance bands 5m) on NIFTY near-month futures, standalone and as one book: one position at a time, the first signal takes
the trade, every other signal is ignored while it is open. 1 lot (65); 0.5 pt slippage a side + futures charges by date."""
import sys, os, time, datetime as Dt
sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
import numpy as np, core
from collections import Counter, defaultdict
t0 = time.time()
JF = core.family("jilly"); S = core.load_strategies(); DAY = core.DAY
f = JF._store_bars("fut"); sp = JF._store_bars("index")
T, O, H, L, C = f.t, f.o, f.h, f.l, f.c; EXP = f.extra["expiry"]
MIN = (T % DAY) // 60                                    # minutes from midnight (IST bars)
cut = np.concatenate([[0], np.nonzero(np.diff(f.day))[0] + 1, [len(T)]])
SES = [(int(a), int(z)) for a, z in zip(cut[:-1], cut[1:])]
DSTR = [core.dstr(int(f.day[a])) for a, z in SES]
CTX = {"lot_size": 65}
D0, D1 = "2018-01-01", "2026-10-23"
def at(a, z, m):                                         # the bar of session (a, z) opening at minute m, else None
    w = np.nonzero(MIN[a:z] == m)[0]; return a + int(w[0]) if len(w) else None
def trade(name, side, ei, xi, xpx, why, epx=None):
    return dict(name=name, side=side, ei=ei, xi=xi, entry_time=int(T[ei]), exit_time=int(T[xi]), entry_px=float(O[ei]) if epx is None else epx,
                exit_px=float(xpx), why=why, position="LONG" if side > 0 else "SHORT")
def weekday_gap(d1, d2):                                 # a weekday holiday between two sessions
    a, b = Dt.date.fromisoformat(d1), Dt.date.fromisoformat(d2); x = a + Dt.timedelta(days=1)
    while x < b:
        if x.weekday() < 5: return True
        x += Dt.timedelta(days=1)
    return False

# ---------------------------------------------------------------- 1. IBS at the 15:19 bar, out next session 09:16
def ibs():
    out = []
    for s in range(len(SES) - 1):
        a, z = SES[s]; d = DSTR[s]
        if not (D0 <= d <= D1): continue
        i = at(a, z, 919)
        if i is None or i + 1 >= z: continue
        if EXP[i] == d: continue                         # expiry day: the contract does not exist overnight
        a2, z2 = SES[s + 1]
        if weekday_gap(d, DSTR[s + 1]): continue         # "tomorrow is holiday" ticked
        if EXP[a2] != EXP[i]: continue
        hi, lo = H[a:i + 1].max(), L[a:i + 1].min()
        if hi <= lo: continue
        v = (C[i] - lo) / (hi - lo)
        side = 1 if v > 0.7 else -1 if v < 0.3 else 0
        if not side: continue
        x = at(a2, z2, 556); x = x if x is not None else a2 + min(1, z2 - a2 - 1)
        out.append(trade("IBS", side, i + 1, x, O[x], "next 09:16"))
    return out

# ---------------------------------------------------------------- 2. basis z-score at 15:19, out next session 15:20
def basis(zth=2.0, lb=60, carry=6.5):
    out, devs = [], []
    for s in range(len(SES) - 1):
        a, z = SES[s]; d = DSTR[s]
        i = at(a, z, 919)
        if i is None or i + 1 >= z: continue
        j = int(np.searchsorted(sp.t, T[i]))
        if j >= len(sp.t) or sp.t[j] != T[i]: continue
        spot = float(sp.c[j]); prem = (C[i] - spot) / spot
        dte = (Dt.date.fromisoformat(EXP[i]) - Dt.date.fromisoformat(d)).days
        dev = prem - carry / 100 * dte / 365
        zz = None
        if len(devs) >= lb:
            w = np.array(devs[-lb:]); sd = w.std()
            zz = (dev - w.mean()) / sd if sd > 0 else None
        devs.append(dev)
        if zz is None or not (D0 <= d <= D1) or abs(zz) <= zth: continue
        if EXP[i] == d: continue                         # expiry day: no overnight in the expiring contract
        a2, z2 = SES[s + 1]
        if EXP[a2] != EXP[i]: continue
        x = at(a2, z2, 920); x = x if x is not None else z2 - 1
        out.append(trade("Basis z", -1 if zz > zth else 1, i + 1, x, O[x], "next 15:20"))
    return out

# ---------------------------------------------------------------- 3. narrow CPR + 15-minute ORB
def cpr(wlen=20, orb=15):
    out = []; HLC = [(H[a:z].max(), L[a:z].min(), C[z - 1]) for a, z in SES]
    def cp(h, l, c):
        p = (h + l + c) / 3; bc = (h + l) / 2; tc = 2 * p - bc; return max(tc, bc), min(tc, bc)
    W = [abs(x[0] - x[1]) for x in (cp(*hlc) for hlc in HLC)]       # W[s] = the width of the CPR built from session s
    for s in range(wlen + 2, len(SES)):
        a, z = SES[s]; d = DSTR[s]
        if not (D0 <= d <= D1) or MIN[a] != 555: continue
        top, bot = cp(*HLC[s - 1]); ytop, ybot = cp(*HLC[s - 2])
        avg = np.mean(W[s - 1 - wlen:s - 1])                        # the previous wlen days' CPRs, today's excluded
        higher, lower = bot > ytop, top < ybot
        if not ((top - bot) < avg and (higher or lower)): continue
        dr = 1 if higher and O[a] > top else -1 if lower and O[a] < bot else 0
        if not dr: continue
        orm = (MIN[a:z] >= 555) & (MIN[a:z] < 555 + orb)
        orh, orl = H[a:z][orm].max(), L[a:z][orm].min()
        for i in range(a, z - 1):
            if MIN[i] < 555 + orb: continue
            if MIN[i + 1] >= 920: break
            if (dr > 0 and C[i] > orh) or (dr < 0 and C[i] < orl):
                stop = orl if dr > 0 else orh                          # BUILD: the far side of the opening range
                xi, why, xp = z - 1, "eod", C[z - 1]
                for m in range(i + 1, z):
                    if MIN[m] >= 920: xi, why, xp = m, "15:20", O[m]; break
                    if (L[m] <= stop) if dr > 0 else (H[m] >= stop):
                        xi, why = (m + 1, "stop") if m + 1 < z else (m, "stop"); xp = O[xi] if xi > m else C[m]; break
                out.append(trade("CPR+ORB", dr, i + 1, xi, xp, why)); break
    return out

# ---------------------------------------------------------------- 4. EMA distance bands, 5-minute, positional
def emab(n=50, mult=3.0, dl=20):
    b5 = f.day * 1000 + (MIN - 555) // 5
    cb = np.concatenate([[0], np.nonzero(np.diff(b5))[0] + 1, [len(T)]]); q0 = cb[:-1]; q1 = cb[1:] - 1
    c5 = C[q1]; N = len(c5)
    k = 2 / (n + 1); ema = np.empty(N); ema[0] = c5[0]
    for x in range(1, N): ema[x] = c5[x] * k + ema[x - 1] * (1 - k)
    dist = np.abs(c5 - ema); cs = np.cumsum(np.insert(dist, 0, 0)); ad = np.full(N, np.nan); ad[dl - 1:] = (cs[dl:] - cs[:-dl]) / dl
    up, lo = ema + mult * ad, ema - mult * ad
    out, pos, e, econ = [], 0, None, None
    for x in range(max(n, dl) + 1, N - 1):
        nxt = q0[x + 1]
        if pos and EXP[nxt] != econ:                         # the contract changes before the next bar: out at its last close
            out.append(trade("EMA bands", pos, e, q1[x], C[q1[x]], "roll")); pos = 0
        if pos == 1 and c5[x - 1] >= ema[x - 1] and c5[x] < ema[x]: out.append(trade("EMA bands", 1, e, nxt, O[nxt], "ema")); pos = 0
        elif pos == -1 and c5[x - 1] <= ema[x - 1] and c5[x] > ema[x]: out.append(trade("EMA bands", -1, e, nxt, O[nxt], "ema")); pos = 0
        if not pos and np.isfinite(up[x - 1]):
            if c5[x - 1] <= up[x - 1] and c5[x] > up[x]: pos, e, econ = 1, nxt, EXP[nxt]
            elif c5[x - 1] >= lo[x - 1] and c5[x] < lo[x]: pos, e, econ = -1, nxt, EXP[nxt]
    return [t for t in out if D0 <= core.tstr(t["entry_time"])[:10] <= D1]

# ---------------------------------------------------------------- 5. Jilly, Strategy 111's futures trades
def jilly():
    m = S["ST111"]; ctx = core.context(m, "FUT", "minute", "FUT", "15:20", "2018-01-02", D1)
    out = []
    for x in m.run(ctx)["-"]["trades"]:
        ei = int(np.searchsorted(T, x["entry_time"])); xi = int(np.searchsorted(T, x["exit_time"]))
        out.append(trade("Jilly", 1 if x["position"] == "LONG" else -1, ei, xi, x["exit_px"], x["exit_reason"], epx=x["entry_px"]))
    return out

BOOKS = {"Jilly": jilly(), "IBS": ibs(), "Basis z": basis(), "CPR+ORB": cpr(), "EMA bands": emab()}
PRIO = list(BOOKS)                                         # a tie on the same entry minute: this order
for v in BOOKS.values():
    for t in v: JF._price(CTX, t, "FUT")
print(f"<!-- built in {time.time() - t0:.0f}s -->")

def pf(x):
    w = sum(v for v in x if v > 0); l = -sum(v for v in x if v <= 0); return w / l if l else float("inf")
Y = lambda t: core.tstr(t["entry_time"])[:4]
def row(nm, X, extra=""):
    n = [t["net"] for t in X]
    if not n: print(f"| {nm} | 0 |"); return
    a = [t["net"] for t in X if Y(t) <= "2022"]; b = [t["net"] for t in X if Y(t) >= "2023"]
    eq = pk = dd = 0
    for t in sorted(X, key=lambda t: t["exit_time"]): eq += t["net"]; pk = max(pk, eq); dd = min(dd, eq - pk)
    print(f"| {nm} | {len(X)} | {100 * sum(v > 0 for v in n) / len(n):.1f} | {sum(n) / len(n):+,.0f} | {pf(n):.3f} | {pf(a):.2f} / {pf(b):.2f} | {sum(a):+,.0f} / {sum(b):+,.0f} | {sum(n):+,.0f} | {dd:,.0f} |{extra}")
HD = "| Book | Trades | Win % | Avg net ₹ | PF | PF 2018-22 / 2023-26 | Net 2018-22 / 2023-26 ₹ | Net ₹ | Max DD ₹ |"
print("\n#### Standalone (each on its own, 1 lot)\n" + HD + "\n|---|---|---|---|---|---|---|---|---|")
for k, v in BOOKS.items(): row(k, v)
row("sum of the five (if all could run at once)", [t for v in BOOKS.values() for t in v])

# ---------------------------------------------------------------- the combined book: one position, first signal wins
allt = sorted((t for v in BOOKS.values() for t in v), key=lambda t: (t["entry_time"], PRIO.index(t["name"])))
taken, skipped, busy, by = [], Counter(), -1, None
blocker = Counter()
for t in allt:
    if t["entry_time"] >= busy:
        taken.append(t); busy, by = t["exit_time"], t["name"]
    else:
        skipped[t["name"]] += 1; blocker[(t["name"], by)] += 1
print("\n#### Combined: one position at a time, first signal takes it\n" + HD + " Skipped (busy) |\n|---|---|---|---|---|---|---|---|---|---|")
row("combined book", taken, f" {sum(skipped.values())} |")
for k in BOOKS: row(f"- {k} trades taken", [t for t in taken if t["name"] == k], f" {skipped[k]} of {len(BOOKS[k])} |")
print("\nwho blocked whom (skipped book <- the book holding the position):", {f"{a} <- {b}": n for (a, b), n in blocker.most_common()})
yr = defaultdict(float)
for t in taken: yr[Y(t)] += t["net"]
print("combined by year:", {y: round(v) for y, v in sorted(yr.items())})
held = sum(t["exit_time"] - t["entry_time"] for t in taken) / 60
print(f"time in a position: {held / 60:,.0f} h; by book (h):", {k: round(sum(t['exit_time'] - t['entry_time'] for t in taken if t['name'] == k) / 3600) for k in BOOKS})
print("exits:", {k: dict(Counter(t["why"] for t in v)) for k, v in BOOKS.items() if k != "Jilly"})
print(f"<!-- {time.time() - t0:.0f}s -->")
