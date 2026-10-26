"""tools/bandlab_entry.py - research bot 2, "bands x entries" (STRATEGY_ANALYSIS_TODO S149).

Which band and which entry give the best edge with simple structure exits? Uses tools/bandlab.py unchanged.

Grid   band in BL.BANDS; entry cross / cross_struct / struct_out (ev choch / bos / any for the struct entries);
       entry structure etf 1 / 5, emode touch / close; exit "choch" on (xtf=etf, xmode=emode) or "inside";
       max_day 1 / 3. Settings that cannot change a run (etf / emode for cross + inside) are collapsed.
Protocol (fixed before results): select on 2018-22 only - rank by pfA among nA >= 300, and by netA / |ddA|;
       read 2023-26 and 2026 for the picks, never re-pick; neighbours (one setting changed) for the top 3.

    python tools/bandlab_entry.py run      # the grid -> results/bandlab/entry_grid.csv (resumes)
    python tools/bandlab_entry.py report   # -> results/bandlab/entry.md
"""
import os
import sys
import time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import numpy as np
import pandas as pd

OUT = os.path.join(HERE, "results", "bandlab")
CSV = os.path.join(OUT, "entry_grid.csv")
KEYS = ["band", "entry", "ev", "etf", "emode", "exit", "max_day"]
COLS = KEYS + ["n", "nA", "nB", "gross_pts", "hold_min", "win", "pfA", "netA", "ddA", "pfB", "netB", "ddB", "pf26", "net26",
               "net", "long_net", "exits", "secs"]


def grid(bands):
    for b in bands:
        for md in (1, 3):
            for entry in ("cross", "cross_struct", "struct_out"):
                for ev in (("-",) if entry == "cross" else ("choch", "bos", "any")):
                    for etf in (1, 5):
                        for em in ("touch", "close"):
                            for ex in ("choch", "inside"):
                                if entry == "cross" and ex == "inside":
                                    if (etf, em) != (1, "touch"): continue
                                    yield dict(band=b, entry=entry, ev="-", etf=0, emode="-", exit=ex, max_day=md)
                                else:
                                    yield dict(band=b, entry=entry, ev=ev, etf=etf, emode=em, exit=ex, max_day=md)


def run():
    import bandlab as BL
    os.makedirs(OUT, exist_ok=True)
    done = set()
    if os.path.exists(CSV):
        d = pd.read_csv(CSV, dtype=str)
        done = {tuple(r) for r in d[KEYS].astype(str).values}
    G = list(grid(BL.BANDS)); print(len(G), "versions,", len(done), "done", flush=True)
    t0 = time.time()
    for k, g in enumerate(G):
        if tuple(str(g[x]) for x in KEYS) in done: continue
        t1 = time.time()
        kw = dict(entry=g["entry"], exit=g["exit"], max_day=g["max_day"])
        if g["entry"] != "cross": kw["ev"] = g["ev"]
        if g["etf"]: kw.update(etf=g["etf"], emode=g["emode"], xtf=g["etf"], xmode=g["emode"])
        r = BL.evaluate(BL.simulate(g["band"], **kw))
        row = dict(g); row.update({c: r.get(c, np.nan) for c in COLS if c not in KEYS})
        row["exits"] = ";".join(f"{a}:{b}" for a, b in r.get("exits", {}).items()); row["secs"] = round(time.time() - t1, 1)
        pd.DataFrame([row])[COLS].to_csv(CSV, mode="a", header=not os.path.exists(CSV), index=False)
        if k % 20 == 0: print(k, g["band"], f"{time.time() - t0:.0f}s", flush=True)
    print("done", f"{time.time() - t0:.0f}s")


# ---------------------------------------------------------------- report
HURDLE = "~4-5 pts to 2024, ~8 in 2025, ~15 from 2026-04"


def name(r):
    s = f"{r.band} {r.entry}"
    if r.entry != "cross": s += f"/{r.ev}"
    if str(r.etf) != "0": s += f" {r.etf}m-{r.emode}"
    return s + f" x:{r.exit} d{r.max_day}"


def fmt(d, cols):
    def f(v, c):
        if isinstance(v, str): return v
        if c.startswith("net") or c.startswith("dd") or c == "long_net": return f"{v / 1e5:+.2f}"
        if c in ("n", "nA", "nB", "max_day"): return str(int(v))
        return f"{v:.2f}"
    h = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return h + "".join("| " + " | ".join(f(r[c], c) for c in cols) + " |\n" for _, r in d.iterrows())


def report():
    d = pd.read_csv(CSV)
    d["etf"] = d["etf"].astype(int); d["version"] = [name(r) for r in d.itertuples()]
    d["ratioA"] = d.netA / d.ddA.abs().replace(0, np.nan)
    d["ratioB"] = d.netB / d.ddB.abs().replace(0, np.nan)
    elig = d[d.nA >= 300]
    T = ["version", "nA", "pfA", "netA", "ddA", "nB", "pfB", "netB", "pf26", "net26", "gross_pts", "hold_min", "long_net"]
    top_pf = elig.sort_values("pfA", ascending=False).head(10)
    top_ra = elig.sort_values("ratioA", ascending=False).head(10)
    L = [f"# Bands x entries (research bot 2, S149)\n\n",
         f"Grid: {len(d)} versions (8 bands x cross / cross_struct / struct_out x ev x entry tf 1/5 x touch/close x exit choch "
         f"(same tf/mode) or inside x max_day 1/3). Net in Rs lakh per 1 lot of 65 after slippage and charges. "
         f"Selection on 2018-22 only (nA >= 300: {len(elig)} versions eligible); 2023-26 and 2026 are read, never picked on. "
         f"`gross_pts` = average gross points per trade over all years; the cost hurdle is {HURDLE}.\n\n",
         "## Selection 1 - top 10 by pfA (nA >= 300)\n\n", fmt(top_pf, T),
         "\n## Selection 2 - top 10 by netA / |ddA| (nA >= 300)\n\n", fmt(top_ra, T)]
    # gross points per period are not in evaluate; the all-years number is the honest proxy
    picks = list(dict.fromkeys(list(top_pf.index[:3]) + list(top_ra.index[:1])))
    L.append("\n## Robustness - neighbours of the top 3 by pfA (same band, one setting changed)\n\n")
    for p in top_pf.index[:3]:
        r = d.loc[p]; nb = []
        for k2, q in d[(d.band == r.band) & (d.index != p)].iterrows():
            diff = [k for k in KEYS[1:] if str(q[k]) != str(r[k])]
            # an exit-tf move goes with the entry tf (xtf = etf), so etf counts as one setting
            if len(diff) == 1 or (set(diff) <= {"ev", "etf", "emode"} and q.entry == "cross" == r.entry and len(diff) <= 1):
                nb.append(k2)
        L.append(f"**{r.version}** (pfA {r.pfA:.2f}, pfB {r.pfB:.2f})\n\n")
        L.append(fmt(d.loc[[p] + nb], ["version", "nA", "pfA", "netA", "pfB", "netB", "pf26", "gross_pts"]) + "\n")
        L.append(f"Neighbours: median pfA {d.loc[nb].pfA.median():.2f}, median pfB {d.loc[nb].pfB.median():.2f}, "
                 f"{int((d.loc[nb].pfA > 1).sum())}/{len(nb)} with pfA > 1.\n\n")
    # summaries
    def summ(by):
        g = d.groupby(by).agg(versions=("pfA", "size"), med_nA=("nA", "median"), med_pfA=("pfA", "median"), med_pfB=("pfB", "median"),
                              med_pf26=("pf26", "median"), max_pfA=("pfA", "max"), med_gross=("gross_pts", "median"),
                              share_pfA_gt1=("pfA", lambda x: (x > 1).mean() * 100), share_both_gt1=("pfA", lambda x: 0.0))
        g["share_both_gt1"] = d.groupby(by).apply(lambda x: ((x.pfA > 1) & (x.pfB > 1)).mean() * 100)
        return g.reset_index()
    def tab(g):
        cols = list(g.columns)
        h = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
        return h + "".join("| " + " | ".join(str(v) if isinstance(v, str) else (f"{v:.0f}" if c in ("versions", "med_nA", "share_pfA_gt1", "share_both_gt1", "etf", "max_day") else f"{v:.2f}")
                                             for c, v in zip(cols, r)) + " |\n" for r in g.itertuples(index=False))
    L.append("## By band\n\n" + tab(summ("band").sort_values("med_pfA", ascending=False)))
    d["style"] = [r.entry if r.entry == "cross" else f"{r.entry}/{r.ev}" for r in d.itertuples()]
    L.append("\n## By entry style\n\n" + tab(summ("style").sort_values("med_pfA", ascending=False)))
    L.append("\n## By exit, entry timeframe, mode, max_day\n\n" + tab(summ("exit")) + "\n" + tab(summ(["etf", "emode"])) + "\n" + tab(summ("max_day")))
    # long vs short
    d["short_net"] = d.net - d.long_net
    ls = d.groupby("band").agg(long_net=("long_net", "median"), short_net=("short_net", "median")).reset_index()
    L.append("\n## Long vs short (median net per band over all years, Rs lakh)\n\n| band | long_net | short_net |\n|---|---|---|\n" +
             "".join(f"| {r.band} | {r.long_net / 1e5:+.2f} | {r.short_net / 1e5:+.2f} |\n" for r in ls.itertuples()))
    L.append(f"\nAll versions: long side net > 0 in {int((d.long_net > 0).sum())}/{len(d)}, short side in {int((d.short_net > 0).sum())}/{len(d)}.\n")
    # hurdle
    both = d[(d.pfA > 1) & (d.pfB > 1) & (d.nA >= 300)]
    L.append(f"\n## Cost hurdle\n\nVersions with gross_pts >= 5: {int((d.gross_pts >= 5).sum())}; >= 8: {int((d.gross_pts >= 8).sum())}; "
             f">= 15: {int((d.gross_pts >= 15).sum())} of {len(d)}. Max gross_pts {d.gross_pts.max():.2f} ({d.loc[d.gross_pts.idxmax(), 'version']}).\n\n"
             f"Versions with pfA > 1 and pfB > 1 (nA >= 300): {len(both)}.\n\n")
    if len(both): L.append(fmt(both.sort_values("pfA", ascending=False).head(15), T))
    pp = os.path.join(OUT, "entry_periods.csv")
    if os.path.exists(pp):
        q = pd.read_csv(pp)
        L.append("\n## Gross points vs cost per trade, by period (the picks and every pfA>1 & pfB>1 version)\n\n"
                 "cost = 1 pt slippage + charges per trade (points). A period clears the hurdle when gross > cost.\n\n"
                 "| version | gross A | cost A | gross B | cost B | gross 23-24 | cost | gross 25 | cost | gross 26 | cost |\n" + "|---|" * 11 + "\n")
        for r in q.itertuples():
            L.append(f"| {r.version} | {r.gross_A:.1f} | {r.cost_A:.1f} | {r.gross_B:.1f} | {r.cost_B:.1f} | {r.gross_23_24:.1f} | {r.cost_23_24:.1f} | "
                     f"{r.gross_25:.1f} | {r.cost_25:.1f} | {r.gross_26:.1f} | {r.cost_26:.1f} |\n")
    L.append("\n## Conclusions\n\n")
    open(os.path.join(OUT, "entry.md"), "w", encoding="utf-8").write("".join(L))
    print("".join(L))


def periods():
    """Gross points per trade and charges per trade by period for the picks (top 4 by pfA / ratio + every pfA>1 & pfB>1)."""
    import bandlab as BL
    import core
    d = pd.read_csv(CSV); d["etf"] = d["etf"].astype(int); d["version"] = [name(r) for r in d.itertuples()]
    d["ratioA"] = d.netA / d.ddA.abs()
    e = d[d.nA >= 300]
    idx = list(dict.fromkeys(list(e.sort_values("pfA", ascending=False).index[:4]) + list(e.sort_values("ratioA", ascending=False).index[:4])
                             + list(e[(e.pfA > 1) & (e.pfB > 1)].index)))
    f, MIN, cut, ses, year = BL.data(); rows = []
    for p in idx:
        g = d.loc[p]
        kw = dict(entry=g.entry, exit=g.exit, max_day=int(g.max_day))
        if g.entry != "cross": kw["ev"] = g.ev
        if g.etf: kw.update(etf=int(g.etf), emode=g.emode, xtf=int(g.etf), xmode=g.emode)
        tr = BL.simulate(g.band, **kw)
        a = np.array([x[1] for x in tr]); gross = np.array([x[0] * (x[4] - x[3]) for x in tr]); yy = year[a]
        cost = np.array([1.0 + BL.JF._charges(core.dstr(int(f.day[i])), "FUT", f.o[i], f.o[i], 65)["total"] / 65 for i in a])
        row = dict(version=g.version)
        for lab, m in (("A", yy <= 2022), ("B", yy >= 2023), ("23_24", (yy >= 2023) & (yy <= 2024)), ("25", yy == 2025), ("26", yy == 2026)):
            row[f"gross_{lab}"] = gross[m].mean() if m.any() else np.nan; row[f"cost_{lab}"] = cost[m].mean() if m.any() else np.nan
        rows.append(row); print(row, flush=True)
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "entry_periods.csv"), index=False)


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["run"])[0]
    run() if cmd == "run" else periods() if cmd == "periods" else report()
