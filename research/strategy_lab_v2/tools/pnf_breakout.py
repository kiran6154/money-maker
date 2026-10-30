"""tools/pnf_breakout.py - Point & Figure breakouts, 0.5% box / 1% reversal, with the stop and reward : risk grid (S159).

The user, 2026-10-28: "Use point and figure with 0.5% box size, 1% reversal size; if a new box is printed above the highest
high of two previous green boxes buy, vice versa for sell. Optimise risk to reward."

Fixed before the run:
  Chart   : NIFTY index closes (close method), percentage boxes on a log grid - box k spans 1.005^k .. 1.005^(k+1); reversal
            = 2 boxes (1%). An X column extends when a close reaches a new box above its top; it reverses to O when a close is
            2 boxes below its top (and mirrored). The chart is fed by 1-minute, 15-minute, 60-minute (09:15-aligned) or daily
            closes - four charts.
  Signal  : BUY the first time the current X column's top box is above the tops of BOTH previous X columns ("a new box
            printed above the highest high of the two previous green columns"); SELL mirrored on O columns (below the lows of
            both previous O columns). One signal per column.
  Trade   : NIFTY near-month futures, 1 lot of 65, entry at the signal bar's last-minute close (no entry on the 09:15
            print). The opposite signal always closes the trade and reverses. Stops and targets are levels on the index,
            checked on every 1-minute index close, filled at that minute's futures close.
  Stops   : B1  one box beyond the breakout box (about 0.5% risk)
            REV the chart's own reversal point, trailing (2 boxes beyond the column's extreme - the trade ends when the
                column reverses)
            COL one box beyond the far end of the breakout column (the classic P&F stop; risk = the column's height)
            SAR none - only the opposite signal (stop and reverse)
  Targets : 1R, 1.5R, 2R, 3R, 5R or none, R = the entry's distance to its initial stop (B1 / REV / COL; SAR has no target)
  Hold    : intraday (entries 09:16 - 15:00, flat at 15:20) or positional (held overnight; at a futures roll the trade is
            carried to the next contract - the overnight index move is counted and the roll costs one more round trip).
            The daily chart is positional only.
  Costs   : 1 point slippage + the dated futures charges per round trip.
  Report  : every combination PF 2018-22 / 2023-26 / 2026; the pick = best 2018-22 PF with >= 100 trades, read after
            without re-picking; reward : risk curves per stop.
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from numba import njit
import core, bandlab as BL
JF = BL.JF
f, MIN, cut, ses, year = BL.data()
LOT = 65
LB = np.log(1.005)
FT = np.asarray(f.t, np.int64); FC = np.asarray(f.c, float); N = len(FT)
EXP = np.asarray(f.extra["expiry"])
sp = JF._store_bars("index"); SPT = np.asarray(sp.t, np.int64)
j = np.clip(np.searchsorted(SPT, FT, side="right") - 1, 0, len(SPT) - 1)
IC = np.asarray(sp.c, float)[j]                               # index close at (or just before) each futures minute
DAYS = np.array([core.dstr(int(d)) for d in f.day])
CHG = {}


@njit(cache=True)
def pnf(c, lb):
    """per feed bar: signal (+1 / -1 / 0), and the levels (log-box numbers) for the stops."""
    n = len(c)
    sig = np.zeros(n, np.int8); trL = np.zeros(n); trS = np.zeros(n); b1 = np.zeros(n); col = np.zeros(n)
    d = 0; top = 0; low = 0; x1 = -10 ** 9; x2 = -10 ** 9; o1 = 10 ** 9; o2 = 10 ** 9; nx = 0; no = 0; fired = False
    base = 0                                                   # the far end of the current column
    for i in range(n):
        lc = np.log(c[i]) / lb
        kf = int(np.floor(lc)); kc = int(np.ceil(lc))
        if d == 0:
            d = 1; top = kf; base = kf; fired = False
        elif d == 1:
            if kf > top:
                top = kf
                if nx >= 2 and not fired and top > max(x1, x2):
                    sig[i] = 1; fired = True; b1[i] = top - 1; col[i] = base - 1
            elif kc <= top - 2:
                x2 = x1; x1 = top; nx += 1
                d = -1; low = kc; base = top; fired = False
                if no >= 2 and low < min(o1, o2):
                    sig[i] = -1; fired = True; b1[i] = low + 1; col[i] = base + 1
        else:
            if kc < low:
                low = kc
                if no >= 2 and not fired and low < min(o1, o2):
                    sig[i] = -1; fired = True; b1[i] = low + 1; col[i] = base + 1
            elif kf >= low + 2:
                o2 = o1; o1 = low; no += 1
                d = 1; top = kf; base = low; fired = False
                if nx >= 2 and top > max(x1, x2):
                    sig[i] = 1; fired = True; b1[i] = top - 1; col[i] = base - 1
        trL[i] = (top - 2) if d == 1 else -10 ** 9            # trailing reversal stop for a long (needs an X column)
        trS[i] = (low + 2) if d == -1 else 10 ** 9
    return sig, trL, trS, b1, col


def feed(tf):
    if tf == "D": q1 = cut[1:] - 1
    else: q1 = BL.tf_bars(tf)[1]
    return np.asarray(q1, np.int64)


def charges(day, px):
    k = (day, round(px, -2))
    if k not in CHG: CHG[k] = JF._charges(day, "FUT", px, px, LOT)["total"] / LOT + 1.0
    return CHG[k]


def run(tf, stop, rr, intraday):
    q1 = feed(tf)
    sig, trL, trS, b1, col = pnf(IC[q1], LB)
    lev = lambda k: np.exp(np.asarray(k, float) * LB)
    # per-minute trailing stops (a feed bar's state is known after its last minute)
    TL = np.full(N, -np.inf); TS = np.full(N, np.inf); OPP = np.zeros(N, np.int8)
    nxt = np.r_[q1[1:], N]
    for a, z, l_, s_ in zip(q1 + 1, nxt + 1, trL, trS):
        TL[a:z] = lev(l_) if l_ > -1e8 else -np.inf; TS[a:z] = lev(s_) if s_ < 1e8 else np.inf
    OPP[q1] = sig
    ks = np.nonzero(sig)[0]
    trades = []; busy = -1
    for b in ks:
        i = int(q1[b]); s = int(sig[b])
        if i <= busy: continue
        if MIN[i] <= 555: continue
        if intraday and MIN[i] > 900: continue
        e_ix = IC[i]
        st0 = {"B1": lev(b1[b] + (0 if s > 0 else 0)), "COL": lev(col[b]), "REV": TL[min(i + 1, N - 1)] if s > 0 else TS[min(i + 1, N - 1)], "SAR": np.nan}[stop]
        if stop == "REV":
            st0 = lev(trL[b]) if s > 0 else lev(trS[b])
        risk = abs(e_ix - st0) if stop != "SAR" else np.nan
        tgt = e_ix + s * rr * risk if (rr and stop != "SAR") else np.nan
        # scan forward
        end = cut[np.searchsorted(cut, i, side="right")] if intraday else N
        m = np.arange(i + 1, end)
        if not len(m): continue
        hit = np.zeros(len(m), bool); why = np.empty(len(m), object)
        if intraday:
            e = MIN[m] >= 920; hit |= e
        x = IC[m]
        if stop == "REV": stp = TL[m] if s > 0 else TS[m]
        elif stop == "SAR": stp = np.full(len(m), -np.inf if s > 0 else np.inf)
        else: stp = np.full(len(m), st0)
        h_stop = (x <= stp) if s > 0 else (x >= stp)
        h_tgt = ((x >= tgt) if s > 0 else (x <= tgt)) if np.isfinite(tgt) else np.zeros(len(m), bool)
        h_opp = OPP[m] == -s
        cond = hit | h_stop | h_tgt | h_opp
        k = int(np.argmax(cond)) if cond.any() else len(m) - 1
        xi = int(m[k])
        w = "eod" if (intraday and MIN[xi] >= 920) else "stop" if h_stop[k] else "target" if h_tgt[k] else "opposite" if h_opp[k] else "end"
        # P&L in futures points, rolls carried
        rolls = np.nonzero(EXP[i + 1:xi + 1] != EXP[i:xi])[0] + i + 1
        pts = 0.0; a = i; cost = 0.0; pa = FC[i]
        for r in rolls:
            pts += s * (FC[r - 1] - pa); cost += charges(DAYS[a], pa)
            pts += s * (IC[r] - IC[r - 1]); pa = FC[r]; a = r
        pts += s * (FC[xi] - pa); cost += charges(DAYS[a], pa)
        trades.append((s, i, xi, pts, (pts - cost) * LOT, w, s * (IC[xi] - e_ix) / risk if risk == risk and risk > 0 else np.nan, len(rolls)))
        busy = xi - (1 if w == "opposite" else 0)              # an opposite signal reverses at the same minute
    T = pd.DataFrame(trades, columns=["side", "i", "x", "pts", "net", "why", "R", "rolls"])
    T["yy"] = year[T.i.values] if len(T) else []
    T["wk"] = (f.day[T.i.values] + 3) // 7 if len(T) else []
    return T


def pf(x):
    if not len(x): return np.nan
    w = x[x > 0].sum(); l_ = -x[x <= 0].sum(); return w / l_ if l_ else np.inf


def summ(T):
    A, B, Z = T[T.yy <= 2022].net, T[T.yy >= 2023].net, T[T.yy == 2026].net
    eq = T.net.cumsum()
    return dict(n=len(T), win=(T.net > 0).mean() * 100, gross=T.pts.mean(), R=T.R.mean(), held=(T.x - T.i).mean(),
                pfA=pf(A), pfB=pf(B), pf26=pf(Z), netA=A.sum(), netB=B.sum(), net26=Z.sum(), dd=(eq - eq.cummax()).min())


if __name__ == "__main__":
    rows = []; keep = {}
    for tf in (1, 15, 60, "D"):
        for intraday in ((True, False) if tf != "D" else (False,)):
            for stop in ("B1", "REV", "COL", "SAR"):
                for rr in ((1, 1.5, 2, 3, 5, 0) if stop != "SAR" else (0,)):
                    T = run(tf, stop, rr, intraday)
                    if not len(T): continue
                    key = (str(tf) if tf == "D" else f"{tf}m", "intraday" if intraday else "positional", stop, f"{rr:g}R" if rr else "none")
                    keep[key] = T
                    rows.append(dict(zip(("chart", "hold", "stop", "target"), key), **summ(T)))
                    print(key, len(T), f"{rows[-1]['pfA']:.2f} {rows[-1]['pfB']:.2f} {rows[-1]['pf26']:.2f}", flush=True)
    G = pd.DataFrame(rows)
    os.makedirs("results/pnf_breakout", exist_ok=True); G.to_csv("results/pnf_breakout/combinations.csv", index=False)
    H = "| Chart | Hold | Stop | Target | Trades | Win % | Gross pts | Avg R | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ | Max DD ₹ |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"
    def row(r):
        print(f"| {r.chart} | {r.hold} | {r.stop} | {r.target} | {int(r.n)} | {r.win:.0f} | {r.gross:+.1f} | {r.R:+.2f} | {r.pfA:.2f} | {r.pfB:.2f} | {r.pf26:.2f} | {r.netA:+,.0f} | {r.netB:+,.0f} | {r.net26:+,.0f} | {r.dd:+,.0f} |")
    print("\n**All combinations:**\n"); print(H); [row(r) for _, r in G.iterrows()]
    ok = G[(G.pfA > 1) & (G.pfB > 1) & (G.n >= 100)]
    print(f"\nPF > 1 in both halves (>= 100 trades): {len(ok)} of {len(G)}")
    P = G[G.n >= 100].sort_values("pfA", ascending=False).iloc[0]
    print("\n**Pick (best 2018-22 PF, >= 100 trades):**\n"); print(H); row(P)
    T = keep[(P.chart, P.hold, P.stop, P.target)]
    print("by year:", T.groupby("yy").net.agg(["count", "sum"]).round(0).to_dict("index"))
    print("exits:", T.why.value_counts().to_dict())
    wk = T.groupby("wk").net.sum()
    print(f"weeks traded {len(wk)}, positive {(wk > 0).mean() * 100:.0f}%, worst week {wk.min():+,.0f}, "
          f"t-stat per trade {T.net.mean() / T.net.std() * np.sqrt(len(T)):.2f}, net pts/trade {(T.net / LOT).mean():+.1f}")
