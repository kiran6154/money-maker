"""tools/bandlab_exit.py - research bot 3 ("exits") on the band -> structure bench (S149).

Entries fixed (not tuned): band in or15 / or30 / jilly / vwap2 / ema5 / pdhl, entry "cross" and "cross_struct"
(ev any, etf 1, emode touch), max_day 1. Exits: choch (xtf 1/5/15 x touch/close), swing (xtf 1/5/15), inside,
ema (20/50/100), escalate (xtf 1 -> esc_tf 5/15 after 10/20/40 points), each with stop None / "band".

Protocol (fixed before looking): per entry, the exit with the best pfA (nA >= 200); overall, exits ranked by the median
pfA across the 12 entries. OOS (2023-26) and 2026 are read for the chosen ones, never re-picked.

Run: PYTHONIOENCODING=utf-8 python tools/bandlab_exit.py   (writes results/bandlab/exit_grid.csv and exit.md)
"""
import os
import sys
import time
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import pandas as pd
import bandlab as BL

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "results", "bandlab")
BANDS = ("or15", "or30", "jilly", "vwap2", "ema5", "pdhl")
ENTRIES = ("cross", "cross_struct")


def exits():
    xs = []
    for tf in (1, 5, 15):
        for m in ("touch", "close"): xs.append(("choch_%d%s" % (tf, m[0]), dict(exit="choch", xtf=tf, xmode=m)))
    for tf in (1, 5, 15): xs.append(("swing_%d" % tf, dict(exit="swing", xtf=tf)))
    xs.append(("inside", dict(exit="inside")))
    for n_ in (20, 50, 100): xs.append(("ema_%d" % n_, dict(exit="ema", ema_n=n_)))
    for et in (5, 15):
        for p in (10, 20, 40): xs.append(("esc_1to%d_%d" % (et, p), dict(exit="escalate", xtf=1, esc_tf=et, esc_pts=float(p))))
    out = []
    for name, kw in xs:
        for st in (None, "band"): out.append((name + ("+bstop" if st else ""), dict(kw, stop=st)))
    return out


def extra(tr):
    """Per-period gross points / trade, cost points / trade (slippage + charges), winner / loser averages, hold."""
    f, MIN, cut, ses, year = BL.data()
    a = np.array([x[1] for x in tr]); g = np.array([x[0] * (x[4] - x[3]) for x in tr])
    chg = np.array([BL.JF._charges(BL.core.dstr(int(f.day[i])), "FUT", f.o[i], f.o[i], 65)["total"] / 65 for i in a]) + 1.0
    hold = np.array([x[2] - x[1] for x in tr]); yy = year[a]; net = g - chg
    eod = np.array([x[5] == "eod" for x in tr])
    r = {}
    for k, m in (("A", yy <= 2022), ("B", yy >= 2023), ("26", yy == 2026)):
        if not m.any(): continue
        r["gross" + k] = float(g[m].mean()); r["cost" + k] = float(chg[m].mean()); r["hold" + k] = float(hold[m].mean())
        w = net[m] > 0
        r["avgwin" + k] = float(net[m][w].mean()) if w.any() else 0.0
        r["avgloss" + k] = float(net[m][~w].mean()) if (~w).any() else 0.0
        r["eodpct" + k] = float(eod[m].mean() * 100)
    return r


def run():
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "exit_grid.csv")
    done = set()
    rows = []
    if os.path.exists(path):
        old = pd.read_csv(path); rows = old.to_dict("records"); done = {(r["band"], r["entry"], r["exit"]) for r in rows}
    t0 = time.time()
    for b in BANDS:
        for en in ENTRIES:
            for xn, kw in exits():
                if (b, en, xn) in done: continue
                tr = BL.simulate(b, entry=en, ev="any", etf=1, emode="touch", max_day=1, **kw)
                r = BL.evaluate(tr, "%s/%s/%s" % (b, en, xn))
                if r["n"]:
                    r.update(extra(tr))
                r.update(band=b, entry=en, exit=xn, exits=json.dumps(r.get("exits", {})))
                rows.append(r)
                pd.DataFrame(rows).to_csv(path, index=False)
                print(f"{b:6s} {en:12s} {xn:20s} n={r['n']:5d} pfA={r.get('pfA', 0):.2f} pfB={r.get('pfB', 0):.2f} "
                      f"gross={r.get('gross_pts', 0):.1f} {time.time() - t0:.0f}s", flush=True)
    return pd.DataFrame(rows)


def report(df):
    L = ["# Band -> structure: exits (research bot 3, S149)", "",
         "Bench: `tools/bandlab.py` (NIFTY near-month futures 1-min, 1 lot of 65, 0.5 pt slippage a side + charges by date).",
         "Entries held fixed: band in or15 / or30 / jilly / vwap2 / ema5 / pdhl x entry cross / cross_struct (ev any, etf 1, "
         "emode touch), max_day 1. 38 exits each (19 exit rules x stop None / band). Grid: `exit_grid.csv`.", "",
         "Protocol, fixed before looking: per entry, the exit with the best pfA (nA >= 200); overall, exits ranked by median "
         "pfA across the 12 entries. IS = 2018-22, OOS = 2023-26, 2026 alone; OOS is read, never picked on.", ""]
    ok = df[df.nA >= 200].copy()
    # per-entry pick
    L += ["## Per entry: the best exit on 2018-22", "",
          "| band | entry | exit | nA | pfA | netA | pfB | netB | pf26 | net26 | gross A/B/26 pts | cost A/B/26 | hold min | avg win / loss B (Rs) | eod % B | exit mix |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (b, en), g in ok.groupby(["band", "entry"], sort=False):
        r = g.sort_values("pfA", ascending=False).iloc[0]
        L.append(f"| {b} | {en} | {r.exit} | {r.nA} | {r.pfA:.2f} | {r.netA:,.0f} | {r.pfB:.2f} | {r.netB:,.0f} | {r.pf26:.2f} | {r.net26:,.0f} | "
                 f"{r.grossA:.1f} / {r.grossB:.1f} / {r.get('gross26', np.nan):.1f} | {r.costA:.1f} / {r.costB:.1f} / {r.get('cost26', np.nan):.1f} | "
                 f"{r.hold_min:.0f} | {r.avgwinB * 65:,.0f} / {r.avglossB * 65:,.0f} | {r.eodpctB:.0f} | {r.exits} |")
    # overall ranking
    agg = ok.groupby("exit").agg(entries=("pfA", "size"), med_pfA=("pfA", "median"), med_pfB=("pfB", "median"),
                                 med_pf26=("pf26", "median"), sum_netA=("netA", "sum"), sum_netB=("netB", "sum"),
                                 sum_net26=("net26", "sum"), grossA=("grossA", "mean"), grossB=("grossB", "mean"),
                                 costB=("costB", "mean"), hold=("hold_min", "mean"), eodB=("eodpctB", "mean"),
                                 avgwinB=("avgwinB", "mean"), avglossB=("avglossB", "mean")).sort_values("med_pfA", ascending=False)
    L += ["", "## All exits ranked by median pfA across entries (IS); OOS read alongside", "",
          "| rank | exit | entries | med pfA | med pfB | med pf26 | sum netA | sum netB | sum net26 | gross A / B pts | cost B | hold min | avg win / loss B pts | eod % B |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, (x, r) in enumerate(agg.iterrows(), 1):
        L.append(f"| {k} | {x} | {r.entries} | {r.med_pfA:.3f} | {r.med_pfB:.3f} | {r.med_pf26:.3f} | {r.sum_netA:,.0f} | {r.sum_netB:,.0f} | "
                 f"{r.sum_net26:,.0f} | {r.grossA:.1f} / {r.grossB:.1f} | {r.costB:.1f} | {r.hold:.0f} | {r.avgwinB:.1f} / {r.avglossB:.1f} | {r.eodB:.0f} |")
    # families
    df2 = ok.copy()
    df2["family"] = df2.exit.str.replace(r"\+bstop", "", regex=True).str.extract(r"^(choch_\d+[tc]|swing|inside|ema|esc_1to5|esc_1to15)")[0]
    df2["bstop"] = df2.exit.str.endswith("+bstop")
    fam = df2.groupby("family").agg(med_pfA=("pfA", "median"), med_pfB=("pfB", "median"), grossA=("grossA", "mean"),
                                    grossB=("grossB", "mean"), avgwinB=("avgwinB", "mean"), hold=("hold_min", "mean")).sort_values("med_pfA", ascending=False)
    L += ["", "## By family (all settings pooled)", "", "| family | med pfA | med pfB | gross A / B pts | avg win B pts | hold min |", "|---|---|---|---|---|---|"]
    for x, r in fam.iterrows():
        L.append(f"| {x} | {r.med_pfA:.3f} | {r.med_pfB:.3f} | {r.grossA:.1f} / {r.grossB:.1f} | {r.avgwinB:.1f} | {r.hold:.0f} |")
    # band stop paired
    base = ok[~ok.exit.str.endswith("+bstop")].set_index(["band", "entry", "exit"])
    st = ok[ok.exit.str.endswith("+bstop")].copy(); st["exit"] = st.exit.str.replace("+bstop", "", regex=False)
    st = st.set_index(["band", "entry", "exit"])
    j = base[["pfA", "pfB", "netA", "netB", "grossA"]].join(st[["pfA", "pfB", "netA", "netB", "grossA"]], rsuffix="_s", how="inner")
    L += ["", "## Band stop, paired (same entry + exit with vs without)", "",
          f"- pairs {len(j)}; pfA higher with the stop in {(j.pfA_s > j.pfA).mean() * 100:.0f}%, pfB higher in {(j.pfB_s > j.pfB).mean() * 100:.0f}%",
          f"- median pfA {j.pfA.median():.3f} -> {j.pfA_s.median():.3f}; median pfB {j.pfB.median():.3f} -> {j.pfB_s.median():.3f}",
          f"- sum netA {j.netA.sum():,.0f} -> {j.netA_s.sum():,.0f}; sum netB {j.netB.sum():,.0f} -> {j.netB_s.sum():,.0f}"]
    # escalation vs its base (choch_1t)
    L += ["", "## Escalation vs the plain 1-minute CHoCH it starts from (stop None)", "",
          "| exit | med pfA | med pfB | gross A / B pts | avg win B pts | avg loss B pts | hold min |", "|---|---|---|---|---|---|---|"]
    for x in ["choch_1t", "esc_1to5_10", "esc_1to5_20", "esc_1to5_40", "esc_1to15_10", "esc_1to15_20", "esc_1to15_40", "choch_5t", "choch_15t"]:
        if x in agg.index:
            r = agg.loc[x]
            L.append(f"| {x} | {r.med_pfA:.3f} | {r.med_pfB:.3f} | {r.grossA:.1f} / {r.grossB:.1f} | {r.avgwinB:.1f} | {r.avglossB:.1f} | {r.hold:.0f} |")
    L += ["", "Costs: 'cost' = 1 pt slippage + charges per round trip in points; gross = mean points per trade before both. "
          "Hurdle ~4-5 pts to 2024, ~8 in 2025, ~15 from 2026-04.", "", "## Findings", "", "(see the summary below, written after the run)", ""]
    open(os.path.join(OUT, "exit.md"), "w", encoding="utf-8").write("\n".join(L))
    return agg


if __name__ == "__main__":
    df = run() if "--report" not in sys.argv else pd.read_csv(os.path.join(OUT, "exit_grid.csv"))
    agg = report(df)
    print(agg.head(15).to_string())
