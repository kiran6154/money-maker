"""C2C research, EXP-018 - the user's conditions (2026-09-30): does the signal fail when it sits inside yesterday's range,
after a bearish previous day, on a flat / gap-up / gap-down open? Development data only (index 2021-2023, research-fetched
options), the same measures as run_rest.py: sig (directional NIFTY move to the close minus the same-year same-time control),
eod (each signal's own ITM1 monthly option, next open -> session close, net rupees per 65-lot), book (the baseline position
rules on the subset, one position at a time). Conditions are fixed here before any result is read; thresholds are round
numbers (gap 0.25 % and 0.5 %), not fitted. Chosen after the development results were seen, so any split that looks good is
a hypothesis for the 2024 validation, not a finding.

    python studies/c2c/patterns.py      # writes studies/c2c/patterns.json and prints the tables
"""
import json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import c2clib as L  # noqa: E402
import run_rest as RR  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))


def conditions(ctx, x):
    i = x["i"]; j = ctx.di[ctx.day[i]]
    if j == 0: return None
    yO, yH, yL, yC = ctx.dO[j - 1], ctx.dH[j - 1], ctx.dL[j - 1], ctx.dC[j - 1]
    tO, px = ctx.dO[j], ctx.c[i]
    gap = (tO - yC) / yC * 100
    g = lambda th: "gap up" if gap > th else "gap down" if gap < -th else "flat open"
    return {
        "signal vs yesterday's range": "inside" if yL <= px <= yH else ("above yesterday's high" if px > yH else "below yesterday's low"),
        "previous day": "bearish day" if yC < yO else "bullish day",
        "open (0.25% gap)": g(0.25),
        "open (0.5% gap)": g(0.5),
        "open vs yesterday's range": "opened inside" if yL <= tO <= yH else ("opened above high" if tO > yH else "opened below low"),
        "previous day x open": ("bearish day" if yC < yO else "bullish day") + " + " + g(0.25),
    }


def main():
    ctx = L.Ctx()
    out = {}
    for d in ("R-A", "R-B"):
        cands, flips = L.candidates(ctx, d)
        sigs = L.signals(cands)
        for side, dv in (("bearish (PE)", -1), ("bullish (CE)", 1)):
            xs = [x for x in sigs if x["dir"] == dv]
            cond = {id(x): conditions(ctx, x) for x in xs}
            for ck in next(v for v in cond.values() if v):
                groups = {}
                for x in xs:
                    c = cond[id(x)]
                    if c: groups.setdefault(c[ck], []).append(x)
                for g, ys in sorted(groups.items()):
                    tr, _ = L.book(ctx, ys, flips, L.BASE)
                    st = L.stats(tr)
                    yrs = {}
                    for y in ("2021", "2022", "2023"):
                        zs = [x for x in ys if x["time"][:4] == y]
                        yrs[y] = L.summarize([L.ctrl_excess(ctx, x, "eod")[1] for x in zs])
                    out[f"{d} | {side} | {ck} | {g}"] = dict(
                        n=len(ys), sig=L.summarize([L.ctrl_excess(ctx, x, "eod")[1] for x in ys]),
                        eod=L.summarize([RR.per_signal(ctx, x, flips, RR.EOD) for x in ys]),
                        book=dict(trades=st.get("trades"), net=st.get("net"), pf=st.get("pf"), t=st.get("t"), win=st.get("win")),
                        sig_by_year=yrs)
    json.dump(out, open(os.path.join(OUT, "patterns.json"), "w"), indent=1, default=float)
    f = lambda s: f"{s['mean']:+.1f} (t {s['t']:+.2f})" if s.get("mean") is not None else "-"
    for k, v in out.items():
        print(f"{k:<95} n {v['n']:>4} | NIFTY {f(v['sig']):<16} | option {f(v['eod']):<18} | book {v['book']['net']} pf {v['book']['pf']} | yrs "
              + " ".join(f"{y}:{f(s)}" for y, s in v["sig_by_year"].items()))


if __name__ == "__main__":
    main()
