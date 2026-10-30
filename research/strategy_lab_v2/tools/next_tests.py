"""tools/next_tests.py - the tests that follow S149 / S150 (pre-registered before the run).

Part A, futures, on noise-band break days (the first 1-minute close outside Jilly's UB / LB, 09:30 - 14:00):
  T0  1-minute CHoCH / BOS the break's way, every one (the baseline that loses; this bench's structure engine runs on
      the whole series, jilly_ext's per day - numbers differ a little from S150)
  T1  only the first such trade of the day
  T2  no new trade after a stop the same day
  T3  the stop on the last 5-minute swing instead of the 1-minute one
  T4  T1 + T3
  pick = the best 2018-22 PF with >= 200 trades; 2023-26 / 2026 read without re-picking.
  For reference: H = hold the break (in at the next minute, out at 15:20); C = the S149 frozen candidate (Jilly band, the
  first 5-minute BOS that way after the cross, exit the 1-minute CHoCH, the 15-minute after 20 points).
Part B, the instrument: H, C and the Part-A pick traded through a NIFTY weekly option 100 points in the money (CE for a long,
  PE for a short; ATM = the futures price at the signal rounded to 50 is NOT used - the index at the signal minute is;
  the nearest weekly expiry on or after the day), bought at the entry minute's open, sold at the exit minute's open
  (the first option candle at or after each), the lab's option costs (max(0.5, 0.5%) slippage, charges by date).
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import datetime as Dt
import numpy as np, pandas as pd, core, store_reader
import bandlab as BL, jilly_break_struct as JB
JF = BL.JF
f, MIN, cut, ses, year = BL.data()
o, h, l, c = f.o, f.h, f.l, f.c
_, keyv, E = JB.band_break_engine(dict(core.load_strategies()["ST111"].SPEC["jilly"]))
BRK = {r["a"]: (r["i"], r["signal"]) for r in E if r.get("signal") is not None}
S1, S5 = BL.structure(1, "touch"), BL.structure(5, "touch")
EV1 = np.where(S1["choch"] != 0, S1["choch"], S1["bos"])


def part_a(first_only=False, stop_ends=False, stop_tf=1):
    sw = S1 if stop_tf == 1 else S5
    out = []
    for a, z in zip(cut[:-1], cut[1:]):
        if a not in BRK: continue
        bi, side = BRK[a]
        pos = 0; done = False
        for i in range(bi + 1, z - 1):
            if pos:
                why = None
                if MIN[i + 1] >= 920: why = "eod"
                elif (pos > 0 and c[i] < stop) or (pos < 0 and c[i] > stop): why = "stop"
                elif S1["choch"][i] == -pos: why = "choch"
                if why:
                    out.append((pos, e, i + 1, o[e], o[i + 1], why)); pos = 0
                    if why == "eod": break
                    if first_only or (stop_ends and why == "stop"): done = True
                continue
            if done or MIN[i] > 870 or MIN[i + 1] >= 920: continue
            if EV1[i] == side:
                lvl = sw["swing_lo"][i] if side > 0 else sw["swing_hi"][i]
                if not np.isfinite(lvl) or (side > 0 and lvl >= c[i]) or (side < 0 and lvl <= c[i]): continue
                pos, e, stop = side, i + 1, lvl
        if pos: out.append((pos, e, z - 1, o[e], c[z - 1], "eod"))
    return out


def hold_break():
    out = []
    for a, z in zip(cut[:-1], cut[1:]):
        if a not in BRK: continue
        bi, side = BRK[a]
        j = next((q for q in range(bi + 1, z) if MIN[q] >= 920), z - 1)
        if j > bi + 1: out.append((side, bi + 1, j, o[bi + 1], o[j], "eod"))
    return out


def as_bl(tr):
    """bandlab.evaluate wants (side, entry index, exit index, entry px, exit px, why)."""
    return [(s, e, x, ep, xp, w) for s, e, x, ep, xp, w in tr]


def row(nm, r):
    if not r.get("n"): print(f"| {nm} | 0 |"); return
    print(f"| {nm} | {r['n']} | {r['gross_pts']:+.2f} | {r['win']:.0f} | {r['pfA']:.2f} ({r['nA']}) | {r['pfB']:.2f} ({r['nB']}) | {r['pf26']:.2f} | {r['netA']:+,.0f} | {r['netB']:+,.0f} | {r['net26']:+,.0f} |", flush=True)


HD = "| Version | Trades | Gross pts / trade | Win % | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ |\n|---|---|---|---|---|---|---|---|---|---|"
print("#### Part A - futures on noise-band break days\n" + HD)
A = {"T0 every 1m CHoCH/BOS the break's way": part_a(), "T1 first trade of the day only": part_a(first_only=True),
     "T2 no new trade after a stop": part_a(stop_ends=True), "T3 stop on the 5-minute swing": part_a(stop_tf=5),
     "T4 first trade only + 5-minute swing stop": part_a(first_only=True, stop_tf=5)}
RA = {k: BL.evaluate(as_bl(v), k) for k, v in A.items()}
for k, r in RA.items(): row(k, r)
pick = max((k for k in RA if k != "T0 every 1m CHoCH/BOS the break's way" and RA[k].get("nA", 0) >= 200), key=lambda k: RA[k]["pfA"])
print(f"\npick (best 2018-22 PF, >= 200 trades): **{pick}**")
H = hold_break(); C = BL.simulate("jilly", entry="cross_struct", ev="bos", etf=5, emode="touch", exit="escalate", xtf=1, esc_tf=15, esc_pts=20.0)
row("H hold the break to 15:20 (reference)", BL.evaluate(H, "H")); row("C the S149 frozen candidate (reference)", BL.evaluate(C, "C"))

# ---------------------------------------------------------------- Part B: through an ITM option
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

def orow(nm, R, miss):
    if not R: print(f"| {nm} | 0 |"); return
    def pf(x):
        w = sum(v for v in x if v > 0); L = -sum(v for v in x if v <= 0); return w / L if L else float("inf")
    a = [r["net"] for r in R if r["yy"] <= 2022]; b = [r["net"] for r in R if r["yy"] >= 2023]; z = [r["net"] for r in R if r["yy"] == 2026]
    chg = np.mean([r["chg"]["total"] for r in R]) / 65
    print(f"| {nm} | {len(R)} (missing {miss}) | {chg:.1f} | {pf(a):.2f} | {pf(b):.2f} | {pf(z):.2f} | {sum(a):+,.0f} | {sum(b):+,.0f} | {sum(z):+,.0f} |", flush=True)

print("\n#### Part B - the same signals through a weekly option 100 points in the money\n| Signals | Trades | Charges, option pts / trade | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ |\n|---|---|---|---|---|---|---|---|---|")
for nm, tr in (("H hold the break to 15:20", H), ("C the S149 frozen candidate", C), (f"Part A pick: {pick}", A[pick])):
    R, miss = through_option(tr); orow(nm, R, miss)
