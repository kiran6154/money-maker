"""tools/bandlab_window.py - research bot 5: do MOVING-WINDOW sideways zones beat the session-anchored bands? (S149)

Uses the shared bench tools/bandlab.py unchanged: each band below is a causal (up, lo) pair per 1-minute bar, known at that
bar's close, registered in BL._D[("band", name)] so BL.simulate(name, ...) runs it like any other band.

Bands (near-month futures, 1-minute; 5-minute bars from BL.tf_bars(5), continuous across sessions, mapped to 1-minute by the
last COMPLETED 5-minute bar):
  donN       highest high / lowest low of the previous N one-minute bars (current bar excluded), N 30 / 60 / 120 / 240
  kelt_n_k   EMA(n) of 5-minute closes +/- k x ATR(n) (Wilder), n 20 / 50, k 1.5 / 2.5
  boll_n_k   SMA(n) of 5-minute closes +/- k x population stdev, n 20 / 50, k 2.0 / 2.5
  boxN_q     compression box: when the session's rolling N-minute range (N 30 / 60, needs N bars into the session) is below
             q x the median of the previous 20 sessions' median rolling range (q 0.5 / 0.75), the box freezes at that
             window's high / low. It stays frozen while price closes inside. A close outside is the breakout; the box is
             KEPT after the breakout (so "inside" exits and cross-then-structure entries can refer to it) but may then be
             replaced by the next compression. The session end clears it. Before the first compression of a session: NaN.
             (Deviation from "until price closes outside it": dropping the box at the breakout would make the "inside"
             exit and the cross_struct entry impossible.)
  rvwN_k     rolling VWAP (hlc3, futures volume) of the last N minutes of the session (expanding until N bars), +/- k x
             its rolling volume-weighted stdev, from 09:30; N 60 / 120, k 1.5 / 2
Reference: BL bands or15, jilly, vwap2 through the same grid.

Grid per band: entries cross | cross_struct (ev any / bos x etf 1 / 5, emode touch); exits choch xtf 5 / 15 | inside |
escalate (xtf 1 -> esc_tf 15, esc_pts 20); max_day 1 / 3.  = 5 x 4 x 2 = 40 runs a band.
Protocol: pick on 2018-22 (pfA, nA >= 300; netA/|ddA| too), read 2023-26 and 2026 without re-picking.

Run:  PYTHONIOENCODING=utf-8 python tools/bandlab_window.py          (resumes from results/bandlab/window_grid.csv)
      PYTHONIOENCODING=utf-8 python tools/bandlab_window.py report   (writes results/bandlab/window.md)
"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import bandlab as BL

HERE = BL.HERE
OUT = os.path.join(HERE, "results", "bandlab")
CSV = os.path.join(OUT, "window_grid.csv")
MD = os.path.join(OUT, "window.md")


# ---------------------------------------------------------------- bands
def _map5(u5, l5):
    f = BL.data()[0]; n = len(f.t)
    B, q1 = BL.tf_bars(5)
    last = np.full(n, -1); last[q1] = np.arange(len(q1)); last = np.maximum.accumulate(last)
    up = np.full(n, np.nan); lo = np.full(n, np.nan); ok = last >= 0
    up[ok], lo[ok] = u5[last[ok]], l5[last[ok]]
    return up, lo


def make_bands():
    f, MIN, cut, ses, year = BL.data(); n = len(f.t)
    names = []

    def reg(name, up, lo):
        BL._D[("band", name)] = (up, lo); names.append(name)

    H, L = pd.Series(f.h), pd.Series(f.l)
    for N in (30, 60, 120, 240):
        reg(f"don{N}", H.rolling(N).max().shift(1).values, L.rolling(N).min().shift(1).values)

    B, q1 = BL.tf_bars(5)
    c5 = pd.Series(np.asarray(B.c, float)); h5 = np.asarray(B.h, float); l5 = np.asarray(B.l, float)
    pc = c5.shift(1).values
    tr = np.nanmax(np.vstack([h5 - l5, np.abs(h5 - pc), np.abs(l5 - pc)]), axis=0)
    for nn in (20, 50):
        ema = c5.ewm(span=nn, adjust=False, min_periods=nn).mean().values
        atr = pd.Series(tr).ewm(alpha=1 / nn, adjust=False, min_periods=nn).mean().values
        sma = c5.rolling(nn).mean().values; sd = c5.rolling(nn).std(ddof=0).values
        for k in (1.5, 2.5):
            reg(f"kelt{nn}_{k}", *_map5(ema + k * atr, ema - k * atr))
        for k in (2.0, 2.5):
            reg(f"boll{nn}_{k}", *_map5(sma + k * sd, sma - k * sd))

    # compression box
    for N in (30, 60):
        rng = np.full(n, np.nan); hh = np.full(n, np.nan); ll = np.full(n, np.nan)
        for a, z in zip(cut[:-1], cut[1:]):
            if z - a < N: continue
            hs = pd.Series(f.h[a:z]).rolling(N).max().values; ls = pd.Series(f.l[a:z]).rolling(N).min().values
            hh[a:z], ll[a:z], rng[a:z] = hs, ls, hs - ls
        smed = np.array([np.nanmedian(rng[a:z]) if np.isfinite(rng[a:z]).any() else np.nan for a, z in zip(cut[:-1], cut[1:])])
        ref = pd.Series(smed).rolling(20, min_periods=20).median().shift(1).values   # previous 20 sessions only
        for q in (0.5, 0.75):
            up = np.full(n, np.nan); lo = np.full(n, np.nan)
            for s, (a, z) in enumerate(zip(cut[:-1], cut[1:])):
                if not np.isfinite(ref[s]): continue
                thr = q * ref[s]; bu = bl = np.nan; frozen = False
                for i in range(a, z):
                    broke = False
                    if frozen and (f.c[i] > bu or f.c[i] < bl):
                        frozen, broke = False, True                             # the breakout bar still carries the box
                    if not frozen and not broke and np.isfinite(rng[i]) and rng[i] < thr:
                        bu, bl, frozen = hh[i], ll[i], True
                    up[i], lo[i] = bu, bl
            reg(f"box{N}_{q}", up, lo)

    # rolling VWAP
    hlc3 = (f.h + f.l + f.c) / 3; v = f.v.astype(float)
    for N in (60, 120):
        vw_ = np.full(n, np.nan); sd_ = np.full(n, np.nan)
        for a, z in zip(cut[:-1], cut[1:]):
            vv = pd.Series(v[a:z]); pv = pd.Series(hlc3[a:z] * v[a:z]); p2 = pd.Series(hlc3[a:z] ** 2 * v[a:z])
            sv = vv.rolling(N, min_periods=1).sum().values
            with np.errstate(all="ignore"):
                m = pv.rolling(N, min_periods=1).sum().values / sv
                s2 = p2.rolling(N, min_periods=1).sum().values / sv - m ** 2
            ok = (MIN[a:z] >= 570) & (sv > 0)
            vw_[a:z] = np.where(ok, m, np.nan); sd_[a:z] = np.where(ok, np.sqrt(np.maximum(s2, 0)), np.nan)
        for k in (1.5, 2.0):
            reg(f"rvw{N}_{k}", vw_ + k * sd_, vw_ - k * sd_)
    return names


def family(b):
    for p in ("don", "kelt", "boll", "box", "rvw"):
        if b.startswith(p): return p
    return "anchored"


# ---------------------------------------------------------------- grid
ENTRIES = [("cross", "any", 1)] + [("cross_struct", ev, etf) for ev in ("any", "bos") for etf in (1, 5)]
EXITS = [("choch", 5), ("choch", 15), ("inside", 1), ("escalate", 1)]
MAXD = (1, 3)
_CHG = {}


def evaluate(tr):
    """BL.evaluate plus gross points and cost (slippage + charges, points) per trade for 2018-22 / 2023-26 / 2026."""
    r = BL.evaluate(tr)
    if not tr: return r
    f, MIN, cut, ses, year = BL.data()
    a = np.array([x[1] for x in tr]); g = np.array([x[0] * (x[4] - x[3]) for x in tr])
    for i in a:
        if i not in _CHG: _CHG[i] = BL.JF._charges(BL.core.dstr(int(f.day[i])), "FUT", f.o[i], f.o[i], 65)["total"] / 65
    cost = np.array([_CHG[i] for i in a]) + 1.0; yy = year[a]
    for k, m in (("A", yy <= 2022), ("B", yy >= 2023), ("26", yy == 2026)):
        r["gross" + k] = float(g[m].mean()) if m.any() else np.nan
        r["cost" + k] = float(cost[m].mean()) if m.any() else np.nan
    r["n26"] = int((yy == 2026).sum())
    r["exits"] = ";".join(f"{k}:{v}" for k, v in r["exits"].items())
    return r


def run():
    os.makedirs(OUT, exist_ok=True)
    t0 = time.time()
    names = make_bands() + ["or15", "jilly", "vwap2"]
    print("bands", len(names), f"{time.time() - t0:.0f}s", flush=True)
    for b in names:
        up, lo = BL.bands(b); print(f"  {b}: known {np.isfinite(up).mean() * 100:.0f}% of minutes", flush=True)
    done = set(pd.read_csv(CSV)["label"]) if os.path.exists(CSV) else set()
    for b in names:
        for (en, ev, etf) in ENTRIES:
            for (ex, xtf) in EXITS:
                for md in MAXD:
                    lab = f"{b}|{en}|{ev}|{etf}|{ex}|{xtf}|{md}"
                    if lab in done: continue
                    kw = dict(entry=en, ev=ev, etf=etf, emode="touch", exit=ex, xtf=xtf, max_day=md)
                    if ex == "escalate": kw.update(esc_tf=15, esc_pts=20.0)
                    r = evaluate(BL.simulate(b, **kw)); r["label"] = lab
                    r.update(band=b, family=family(b), entry=en, ev=ev, etf=etf, exit=ex, xtf=xtf, max_day=md)
                    pd.DataFrame([r]).to_csv(CSV, mode="a", header=not os.path.exists(CSV), index=False)
                    print(lab, r.get("n"), round(r.get("pfA", 0), 3), round(r.get("pfB", 0), 3), f"{time.time() - t0:.0f}s", flush=True)


# ---------------------------------------------------------------- report
def report():
    d = pd.read_csv(CSV)
    d["entry_k"] = np.where(d.entry == "cross", "cross", d.entry + "/" + d.ev + "/" + d.etf.astype(str) + "m")
    d["exit_k"] = np.where(d.exit == "choch", "choch" + d.xtf.astype(str) + "m", d.exit)
    d["mar"] = d.netA / d.ddA.abs().replace(0, np.nan)
    ok = d[d.nA >= 300].copy()
    L = ["# Moving-window bands vs session-anchored bands (research bot 5, S149)", "",
         "Bench: `tools/bandlab.py` (unchanged); bands and grid: `tools/bandlab_window.py`; every run: `window_grid.csv`.",
         "Near-month NIFTY futures, 1 lot (65), 0.5 pt slippage a side + charges by date. Pick on 2018-22 (A) only, "
         "with nA >= 300; 2023-26 (B) and 2026 are read, never used to pick.", "",
         f"{len(d)} runs ({d.band.nunique()} bands x 40), {len(ok)} with nA >= 300.", ""]

    def fmt(x, nd=2):
        return "" if pd.isna(x) else (f"{x:,.0f}" if abs(x) >= 1000 else f"{x:.{nd}f}")

    cols = ["band", "entry_k", "exit_k", "max_day", "nA", "nB", "n26", "pfA", "pfB", "pf26", "netA", "netB", "net26", "ddA",
            "grossA", "costA", "grossB", "costB", "gross26", "cost26"]

    def table(df):
        out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for _, r in df.iterrows():
            out.append("| " + " | ".join(str(r[c]) if c in ("band", "entry_k", "exit_k", "max_day", "nA", "nB", "n26") else fmt(r[c]) for c in cols) + " |")
        return out

    L += ["## Family medians (all 40 runs a band; and runs with nA >= 300)", "",
          "| family | runs | median pfA | median pfB | median pf26 | share pfA>1 | share pfB>1 | runs nA>=300 | median pfA (nA>=300) | median pfB (nA>=300) | median grossA - costA | median grossB - costB |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for fam, g in d.groupby("family"):
        gg = ok[ok.family == fam]
        L.append(f"| {fam} | {len(g)} | {g.pfA.median():.3f} | {g.pfB.median():.3f} | {g.pf26.median():.3f} | {(g.pfA > 1).mean():.0%} | "
                 f"{(g.pfB > 1).mean():.0%} | {len(gg)} | {gg.pfA.median():.3f} | {gg.pfB.median():.3f} | "
                 f"{(g.grossA - g.costA).median():.2f} | {(g.grossB - g.costB).median():.2f} |")
    L += ["", "Per band (median over its 40 runs):", "", "| band | median pfA | median pfB | best pfA (nA>=300) | its pfB |", "|---|---|---|---|---|"]
    for b, g in d.groupby("band"):
        gg = ok[ok.band == b]
        if len(gg):
            r = gg.sort_values("pfA").iloc[-1]; bb = f"{r.pfA:.3f} | {r.pfB:.3f}"
        else:
            bb = "- | -"
        L.append(f"| {b} | {g.pfA.median():.3f} | {g.pfB.median():.3f} | {bb} |")

    top = ok.sort_values("pfA", ascending=False).head(10)
    L += ["", "## Top 10 by pfA (nA >= 300) - their B and 2026 read without re-picking", ""] + table(top)
    topm = ok.sort_values("mar", ascending=False).head(10)
    L += ["", "## Top 10 by netA / |ddA| (nA >= 300)", ""] + table(topm)
    bestfam = ok.sort_values("pfA", ascending=False).groupby("family").head(1)
    L += ["", "## Best pfA per family (nA >= 300)", ""] + table(bestfam)

    # neighbours of the top 3 picks
    mv = ok[ok.family != "anchored"]
    topmv = mv.sort_values("pfA", ascending=False).head(10)
    L += ["", "## Moving-window bands only: top 10 by pfA (nA >= 300)", ""] + table(topmv)
    L += ["", "## Grid neighbours of the top 3 pfA picks overall and the top 3 moving-window picks (one setting changed; band neighbours = same family, other parameter)", ""]
    keys = ["band", "entry", "ev", "etf", "exit", "xtf", "max_day"]
    for _, p in pd.concat([top.head(3), topmv.head(3)]).iterrows():
        L += [f"### {p.band} | {p.entry_k} | {p.exit_k} | max_day {p.max_day}: pfA {p.pfA:.3f}, pfB {p.pfB:.3f}", ""]
        nb = []
        for _, r in d.iterrows():
            diff = [k for k in keys if r[k] != p[k]]
            if len(diff) == 1 and (diff[0] != "band" or r.family == p.family): nb.append(r)
            elif diff == ["ev", "etf"] or diff == ["xtf", "exit"]: nb.append(r)
        nbd = pd.DataFrame(nb)
        L += table(nbd) if len(nbd) else ["(none)"]
        if len(nbd):
            L += ["", f"neighbours: median pfA {nbd.pfA.median():.3f} (pick {p.pfA:.3f}), median pfB {nbd.pfB.median():.3f}; "
                      f"{(nbd.pfA > 1).mean():.0%} have pfA > 1", ""]

    both = d[(d.nA >= 300) & (d.grossA > d.costA) & (d.grossB > d.costB)]
    L += ["", "## Clears the cost hurdle in both periods (gross points a trade > cost a trade, A and B)", "",
          f"{len(both)} of {len(d)} runs (nA >= 300)."]
    if len(both):
        L += [""] + table(both.sort_values("pfA", ascending=False).head(15))
    with open(MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L[:60]))


if __name__ == "__main__":
    report() if len(sys.argv) > 1 and sys.argv[1] == "report" else run()
