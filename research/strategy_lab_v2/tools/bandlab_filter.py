"""tools/bandlab_filter.py - research bot 4 ("filters and continuation") on the band -> structure bench (S149).

Question: WHEN is a band break a real move rather than noise? Which features known AT ENTRY (the signal bar's close)
separate the two, in 2018-22 AND 2023-26.

Base systems (fixed): band in or15 / jilly / vwap2 / ema5; entry "cross" and "cross_struct" (ev any, etf 1, touch);
exit the opposite 5-minute CHoCH (touch), max one entry a session.  8 systems.

    python tools/bandlab_filter.py label     step 1 + the 2018-22 half of step 2 (what the filters are picked from)
    python tools/bandlab_filter.py full      steps 1-3, writes results/bandlab/filter.md + filter_grid.csv

Every feature is read at the signal bar i (entry fills at bar i+1's open); arrays below only use bars <= i.
Step 3's filtered walk is simulate_f: BL.simulate's walk with a `filt(i, side)` check at entry; a rejected signal does
not use the session's entry (a later signal that day may still enter) and leaves cross_struct armed.
"""
import os
import sys
import time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import numpy as np
import pandas as pd
import bandlab as BL
import core

OUT = os.path.join(HERE, "results", "bandlab")
SYSTEMS = [(b, e) for b in ("or15", "jilly", "vwap2", "ema5") for e in ("cross", "cross_struct")]
BASE = dict(ev="any", etf=1, emode="touch", exit="choch", xtf=5, xmode="touch", max_day=1)


# ---------------------------------------------------------------- the filtered walk (BL.simulate + filt at entry)
def simulate_f(band, entry="cross", ev="any", etf=1, emode="touch", exit="choch", xtf=5, xmode="touch",
               first=570, last=870, max_day=1, filt=None):
    f, MIN, cut, ses, year = BL.data(); n = len(f.t)
    up, lo = BL.bands(band)
    E = BL.structure(etf, emode); X = BL.structure(xtf, xmode)
    ee = {"choch": E["choch"], "bos": E["bos"], "any": np.where(E["choch"] != 0, E["choch"], E["bos"])}[ev]
    c, o = f.c, f.o
    out = []; pos = 0; armed = 0; taken = 0; cur_s = -1
    for i in range(1, n - 1):
        s_ = ses[i]
        if s_ != cur_s: cur_s, taken, armed = s_, 0, 0
        if pos:
            last_bar = ses[i + 1] != s_
            why = None
            if last_bar or MIN[i + 1] >= 920: why = "eod"
            elif X["choch"][i] == -pos: why = "choch"
            if why:
                j = i if (last_bar and why == "eod") else i + 1
                out.append((pos, e, j, epx, (c[i] if j == i else o[j]), why)); pos = 0
            continue
        if MIN[i] < first or MIN[i] > last or taken >= max_day or ses[i + 1] != s_ or not np.isfinite(up[i]) or not np.isfinite(up[i - 1]):
            continue
        ci, cp = c[i], c[i - 1]
        crossed = 1 if (cp <= up[i - 1] and ci > up[i]) else -1 if (cp >= lo[i - 1] and ci < lo[i]) else 0
        if entry == "cross":
            s = crossed
        else:  # cross_struct
            if crossed: armed = crossed
            if armed and lo[i] <= ci <= up[i]: armed = 0
            s = armed if (armed and ee[i] == armed) else 0
        if s and filt is not None and not filt(i, s):
            continue                                            # rejected: no entry used, cross_struct stays armed
        if s:
            pos, e, epx, taken, armed = s, i + 1, o[i + 1], taken + 1, 0
    return out


# ---------------------------------------------------------------- per-minute feature arrays (causal)
_F = {}


def adx5(n_=14):
    """Wilder ADX(14) on 09:15-aligned 5-minute bars, mapped to every minute from the last completed 5-minute bar."""
    f = BL.data()[0]; N = len(f.t)
    B, q1 = BL.tf_bars(5)
    h, l, c = B.h, B.l, B.c
    pc = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    upm = h - np.concatenate([[h[0]], h[:-1]]); dnm = np.concatenate([[l[0]], l[:-1]]) - l
    pdm = np.where((upm > dnm) & (upm > 0), upm, 0.0); ndm = np.where((dnm > upm) & (dnm > 0), dnm, 0.0)
    a = 1.0 / n_
    w = lambda x: pd.Series(x).ewm(alpha=a, adjust=False).mean().values
    atr = w(tr)
    with np.errstate(all="ignore"):
        pdi = 100 * w(pdm) / atr; ndi = 100 * w(ndm) / atr
        dx = 100 * abs(pdi - ndi) / (pdi + ndi)
    adx = w(np.nan_to_num(dx))
    last = np.full(N, -1); last[q1] = np.arange(len(q1)); last = np.maximum.accumulate(last)
    out = np.full(N, np.nan); ok = last >= 0; out[ok] = adx[last[ok]]
    di = np.full(N, 0.0); di[ok] = np.sign(pdi[last[ok]] - ndi[last[ok]])
    return out, di


def common():
    if "c" in _F: return _F["c"]
    f, MIN, cut, ses, year = BL.data(); N = len(f.t)
    hi_sf = np.empty(N); lo_sf = np.empty(N); vw = np.full(N, np.nan)
    hlc3 = (f.h + f.l + f.c) / 3
    S = len(cut) - 1
    srange = np.zeros(S); sdir = np.zeros(S)
    for s, (a, z) in enumerate(zip(cut[:-1], cut[1:])):
        hi_sf[a:z] = np.maximum.accumulate(f.h[a:z]); lo_sf[a:z] = np.minimum.accumulate(f.l[a:z])
        v = f.v[a:z]; cv = np.cumsum(v)
        with np.errstate(all="ignore"):
            vw[a:z] = np.where(cv > 0, np.cumsum(hlc3[a:z] * v) / cv, np.nan)
        srange[s] = f.h[a:z].max() - f.l[a:z].min(); sdir[s] = np.sign(f.c[z - 1] - f.o[a])
    avg20 = pd.Series(srange).rolling(20, min_periods=10).mean().shift(1).values   # prior 20 sessions only
    prevdir = np.concatenate([[0], sdir[:-1]])
    # trading sessions to the bar's contract expiry
    days = f.day[cut[:-1]]
    exp = np.array([core.dnum(x) for x in f.extra["expiry"][cut[:-1]]])
    dte = np.searchsorted(days, exp, side="left") - np.arange(S)                     # sessions after today up to expiry
    e20, e50 = BL.ema1(20), BL.ema1(50)
    adx, di = adx5()
    _F["c"] = dict(dayrng=(hi_sf - lo_sf) / avg20[ses], vwap=vw, prevdir=prevdir[ses], dte=dte[ses],
                   e20s=np.sign(e20 - np.concatenate([np.full(5, np.nan), e20[:-5]])),
                   e50s=np.sign(e50 - np.concatenate([np.full(5, np.nan), e50[:-5]])),
                   adx=adx, di=di, t5=BL.structure(5, "touch")["trend"], t15=BL.structure(15, "touch")["trend"])
    return _F["c"]


def band_feats(band):
    key = ("b", band)
    if key in _F: return _F[key]
    f, MIN, cut, ses, year = BL.data(); N = len(f.t)
    up, lo = BL.bands(band)
    wid = up - lo
    since = np.full(N, np.nan); smed = np.full(len(cut) - 1, np.nan)
    for s, (a, z) in enumerate(zip(cut[:-1], cut[1:])):
        k = np.nonzero(np.isfinite(up[a:z]))[0]
        if len(k):
            since[a:z] = np.arange(z - a) - k[0]; smed[s] = np.nanmedian(wid[a:z])
    med20 = pd.Series(smed).rolling(20, min_periods=10).median().shift(1).values
    _F[key] = dict(up=up, lo=lo, wid=wid, since=since, wrel=wid / med20[ses])
    return _F[key]


def label(trades, band, sysname):
    f, MIN, cut, ses, year = BL.data()
    C = common(); Bf = band_feats(band)
    rows = []
    for (side, ei, xi, en, ex, why) in trades:
        i = ei - 1
        beyond = side * (f.c[i] - (Bf["up"][i] if side > 0 else Bf["lo"][i]))
        pts = side * (ex - en) - 1.0
        rows.append(dict(sys=sysname, band=band, side=side, ei=ei, i=i, why=why, year=int(year[ei]),
                         day=core.dstr(int(f.day[ei])), gross=pts + 1.0, pts=pts,
                         tod=int(MIN[i]), since=float(Bf["since"][i]), beyond_pts=float(beyond),
                         beyond_w=float(beyond / Bf["wid"][i]) if Bf["wid"][i] > 0 else np.nan,
                         width=float(Bf["wid"][i]), width_rel=float(Bf["wrel"][i]), dayrng=float(C["dayrng"][i]),
                         t5=int(C["t5"][i] * side), t15=int(C["t15"][i] * side),
                         ema=int(C["e20s"][i] * side > 0) + int(C["e50s"][i] * side > 0),
                         adx=float(C["adx"][i]), di=int(C["di"][i] * side),
                         vwap=int(np.sign(f.c[i] - C["vwap"][i]) * side) if np.isfinite(C["vwap"][i]) else 0,
                         prev=int(C["prevdir"][i] * side), dte=int(C["dte"][i])))
    df = pd.DataFrame(rows)
    if len(df):
        chg = np.array([BL.JF._charges(d, "FUT", f.o[e], f.o[e], 65)["total"] / 65 for d, e in zip(df.day, df.ei)])
        df["net"] = (df.pts - chg) * 65
    return df


# ---------------------------------------------------------------- stats
def pf(x):
    x = np.asarray(x); w = x[x > 0].sum(); l = -x[x <= 0].sum(); return float(w / l) if l else float("inf")


def stat(d):
    return dict(n=len(d), pf=pf(d.net) if len(d) else np.nan, gross=float(d.gross.mean()) if len(d) else np.nan,
                net=float(d.net.sum()) if len(d) else 0.0)


FEATS = {  # name -> (column, bucket function on the value)
    "time of day": ("tod", lambda v: "09:30-10:29" if v < 630 else "10:30-11:59" if v < 720 else "12:00-13:29" if v < 810 else "13:30-14:30"),
    "minutes since band known": ("since", None),
    "beyond band (pts)": ("beyond_pts", None),
    "beyond band (widths)": ("beyond_w", None),
    "band width (pts)": ("width", None),
    "band width / 20-session median": ("width_rel", None),
    "day range so far / 20-session avg range": ("dayrng", None),
    "5m structure trend": ("t5", lambda v: {1: "with", -1: "against", 0: "none"}[v]),
    "15m structure trend": ("t15", lambda v: {1: "with", -1: "against", 0: "none"}[v]),
    "1m EMA20/50 5-bar slopes with trade": ("ema", lambda v: {2: "both", 1: "one", 0: "neither"}[v]),
    "ADX(14) 5m": ("adx", None),
    "5m DI+/DI- with trade": ("di", lambda v: {1: "with", -1: "against", 0: "n/a"}[v]),
    "VWAP side": ("vwap", lambda v: {1: "with", -1: "against", 0: "n/a"}[v]),
    "previous session direction": ("prev", lambda v: {1: "with", -1: "against", 0: "flat"}[v]),
    "sessions to monthly expiry": ("dte", lambda v: "0-2" if v <= 2 else "3-7" if v <= 7 else "8-14" if v <= 14 else "15+"),
    "side": ("side", lambda v: "long" if v > 0 else "short"),
}


def bucketize(df):
    """Per feature a bucket column; numeric features by 2018-22 quartiles (pooled over the 8 systems; band-relative
    features are already scale-free; points features are pooled across bands - noted in the report)."""
    A = df[df.year <= 2022]
    for name, (col, fn) in FEATS.items():
        if fn is None:
            q = np.nanquantile(A[col], [0.25, 0.5, 0.75])
            lab = np.array([f"Q1 <= {q[0]:.3g}", f"Q2 {q[0]:.3g} - {q[1]:.3g}", f"Q3 {q[1]:.3g} - {q[2]:.3g}", f"Q4 > {q[2]:.3g}"])
            k = np.searchsorted(q, df[col].fillna(0).values, side="left")
            df["B:" + name] = np.where(df[col].isna().values, "n/a", lab[k])
        else:
            df["B:" + name] = df[col].map(fn)
    return df


def feature_table(df, isonly=False):
    rows = []
    for name in FEATS:
        for b, d in df.groupby("B:" + name):
            A, Bd = d[d.year <= 2022], d[d.year >= 2023]
            sa, sb = stat(A), stat(Bd)
            r = dict(feature=name, bucket=b, nA=sa["n"], pfA=sa["pf"], grossA=sa["gross"])
            if not isonly: r.update(nB=sb["n"], pfB=sb["pf"], grossB=sb["gross"])
            rows.append(r)
    return pd.DataFrame(rows)


def build():
    t0 = time.time(); parts = []
    for b, e in SYSTEMS:
        tr = BL.simulate(b, entry=e, **BASE)
        parts.append(label(tr, b, f"{b}/{e}")); print(f"{b}/{e}: {len(tr)} trades {time.time() - t0:.0f}s", flush=True)
    return bucketize(pd.concat(parts, ignore_index=True))


# ---------------------------------------------------------------- step 3: pre-registered filters
# Picked from the 2018-22 half of step 2 ONLY (`python tools/bandlab_filter.py label` prints nothing after 2022), before
# any 2023-26 number was looked at.  The 2018-22 reading (pooled AND in each of the 4 bands):
#   day range so far / 20-session avg range, top quartile (> 0.643): PF 1.36 pooled, 1.10 - 1.49 in every band
#   15m structure trend with the trade: PF 1.15 vs 0.95 against, "with" better in every band
#   5m structure trend with the trade: PF 1.12 vs 0.98, "with" better in every band
#   previous session closed against the trade: PF 1.20 vs 0.95 with, better in every band
# Rejected at pre-registration: time of day, band width / median, beyond-band distance, ADX, EMA slopes (not the same
# way in every band), VWAP side (98% "with" - a band break is nearly always on the VWAP side), expiry (non-monotone).
DAYRNG_Q = 0.75                                     # the threshold is the 2018-22 pooled 75th percentile (0.643)
FILTERS = {
    "none":               lambda C, i, s, k: True,
    "F1 dayrng>=Q4":      lambda C, i, s, k: C["dayrng"][i] > k,
    "F2 HTF 15m with":    lambda C, i, s, k: C["t15"][i] == s,
    "F3 5m with":         lambda C, i, s, k: C["t5"][i] == s,
    "F4 prev day against": lambda C, i, s, k: C["prevdir"][i] == -s,
    "F5 dayrng>=Q4 & 15m with": lambda C, i, s, k: C["dayrng"][i] > k and C["t15"][i] == s,
    "F6 dayrng>=Q4 & prev against": lambda C, i, s, k: C["dayrng"][i] > k and C["prevdir"][i] == -s,
}


def split_stats(tr):
    """gross points / cost points per trade in 2018-22, 2023-26, 2026."""
    f, MIN, cut, ses, year = BL.data()
    if not tr: return {}
    ei = np.array([x[1] for x in tr]); g = np.array([x[0] * (x[4] - x[3]) for x in tr]); y = year[ei]
    cost = 1.0 + np.array([BL.JF._charges(core.dstr(int(f.day[i])), "FUT", f.o[i], f.o[i], 65)["total"] / 65 for i in ei])
    out = {}
    for nm, m in (("A", y <= 2022), ("B", y >= 2023), ("26", y == 2026)):
        out["gross" + nm] = float(g[m].mean()) if m.any() else np.nan
        out["cost" + nm] = float(cost[m].mean()) if m.any() else np.nan
        out["n" + nm] = int(m.sum())
    return out


def report(df):
    os.makedirs(OUT, exist_ok=True)
    C = common()
    A = df[df.year <= 2022]
    k = float(np.nanquantile(A.dayrng, DAYRNG_Q))
    rows = []
    for b, e in SYSTEMS:
        for fn, fun in FILTERS.items():
            tr = simulate_f(b, entry=e, **BASE, filt=lambda i, s: bool(fun(C, i, s, k)))
            r = BL.evaluate(tr); ss = split_stats(tr)
            rows.append(dict(system=f"{b}/{e}", filter=fn, n=r["n"], nA=r.get("nA", 0), nB=r.get("nB", 0), n26=ss.get("n26", 0),
                             pfA=r.get("pfA"), pfB=r.get("pfB"), pf26=r.get("pf26"),
                             grossA=ss.get("grossA"), grossB=ss.get("grossB"), gross26=ss.get("gross26"),
                             costA=ss.get("costA"), costB=ss.get("costB"), cost26=ss.get("cost26"),
                             netA=r.get("netA"), netB=r.get("netB"), net26=r.get("net26"), ddA=r.get("ddA"), ddB=r.get("ddB"),
                             win=r.get("win"), hold_min=r.get("hold_min")))
            print(f"{b}/{e} | {fn}: n {r['n']} pfA {r.get('pfA', 0):.2f} pfB {r.get('pfB', 0):.2f}", flush=True)
    G = pd.DataFrame(rows)
    G.round(3).to_csv(os.path.join(OUT, "filter_grid.csv"), index=False)

    # step 2, both periods
    T = feature_table(df)
    base = {p: stat(d) for p, d in (("A", df[df.year <= 2022]), ("B", df[df.year >= 2023]))}
    T["liftA"] = T.pfA - base["A"]["pf"]; T["liftB"] = T.pfB - base["B"]["pf"]
    T["both"] = np.where((T.nA >= 100) & (T.nB >= 100) & (np.sign(T.liftA) == np.sign(T.liftB)) & (T.liftA.abs() >= 0.05) & (T.liftB.abs() >= 0.05),
                         np.where(T.liftA > 0, "better both", "worse both"), "")
    T.round(3).to_csv(os.path.join(OUT, "filter_features.csv"), index=False)
    perband = []
    for name in ("day range so far / 20-session avg range", "15m structure trend", "5m structure trend", "previous session direction",
                 "time of day", "band width / 20-session median", "ADX(14) 5m", "side"):
        for (bd, bk), d in df.groupby(["band", "B:" + name]):
            sa, sb = stat(d[d.year <= 2022]), stat(d[d.year >= 2023])
            perband.append(dict(feature=name, band=bd, bucket=bk, nA=sa["n"], pfA=sa["pf"], grossA=sa["gross"], nB=sb["n"], pfB=sb["pf"], grossB=sb["gross"]))
    PB = pd.DataFrame(perband)

    # selection on 2018-22 PF, nA >= 200
    ok = G[(G.nA >= 200) & (G["filter"] != "none")].sort_values("pfA", ascending=False)
    pick = ok.iloc[0]
    perf = ok.groupby("filter").head(1)                 # the IS-best system per filter (selected on pfA too)
    bases = G[G["filter"] == "none"]

    def fmt(d, cols):
        d = d[cols].copy()
        for c_ in d.columns:
            if d[c_].dtype.kind == "f": d[c_] = d[c_].map(lambda v: "" if pd.isna(v) else (f"{v:,.0f}" if abs(v) >= 1000 else f"{v:.2f}"))
        return "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n" + "\n".join("| " + " | ".join(str(x) for x in r) + " |" for r in d.values)

    cols = ["system", "filter", "nA", "nB", "n26", "pfA", "pfB", "pf26", "grossA", "costA", "grossB", "costB", "gross26", "cost26", "netA", "netB", "net26"]
    L = []
    L.append("# Band breaks: which entry-time filters separate a real move from noise (research bot 4, S149)\n")
    L.append("Bench `tools/bandlab.py`; code `tools/bandlab_filter.py` (`python tools/bandlab_filter.py full`). Base systems fixed: "
             "band or15 / jilly / vwap2 / ema5 x entry cross / cross_struct (ev any, etf 1, touch), exit the opposite 5-minute CHoCH (touch), "
             "max 1 entry a session, entries 09:30-14:30, flat 15:20. NIFTY near-month futures 1-minute 2018-01 - 2026-10-23, 1 lot of 65, "
             "0.5 pt slippage a side + charges by date. IS = 2018-22, OOS = 2023-26. gross = points per trade before costs, cost = slippage + "
             "charges in points per trade (the hurdle).\n")
    L.append("## Base systems\n"); L.append(fmt(bases, cols) + "\n")
    L.append("## Step 1 - features (all read at the signal bar's close; entry fills at the next bar's open)\n")
    L.append("time of day; minutes since the band became known that session; close beyond the band in points and in band widths; band width "
             "in points and vs the median of the prior 20 sessions' median widths; the day's high-low so far vs the prior 20 sessions' mean "
             "range; the 5- and 15-minute structure trend (`BL.structure(tf)['trend']`) with / against the trade; the 1-minute EMA 20 and 50 "
             "5-bar slopes with the trade (both / one / neither); Wilder ADX(14) and DI+/DI- on the last completed 5-minute bar; the close vs "
             "session VWAP; the previous session's close-vs-open direction vs the trade; sessions to the near-month contract's expiry; long / "
             "short. Numeric features are bucketed by the 2018-22 pooled quartiles (the same edges for 2023-26). Points-based features "
             "(beyond pts, width pts) pool four bands and two index levels - read the scale-free versions.\n")
    L.append(f"{len(df)} labelled base trades ({(df.year <= 2022).sum()} IS, {(df.year >= 2023).sum()} OOS) over the 8 systems (pooled - "
             "the same break often appears in several systems).\n")
    L.append("## Step 2 - PF and gross points per trade by bucket, pooled over the 8 systems\n")
    L.append(f"Pooled base: IS PF {base['A']['pf']:.2f}, gross {base['A']['gross']:.1f} pts; OOS PF {base['B']['pf']:.2f}, gross {base['B']['gross']:.1f} pts. "
             "`both` = the bucket's PF is >= 0.05 above (below) the period's pooled PF in BOTH periods with n >= 100 in each.\n")
    L.append(fmt(T, ["feature", "bucket", "nA", "pfA", "grossA", "nB", "pfB", "grossB", "both"]) + "\n")
    L.append("### Per band, both periods (the features that could be filters)\n")
    L.append(fmt(PB, ["feature", "band", "bucket", "nA", "pfA", "grossA", "nB", "pfB", "grossB"]) + "\n")
    L.append("## Step 3 - pre-registered filters (from the 2018-22 half only)\n")
    L.append(f"Day-range threshold = the 2018-22 pooled 75th percentile = {k:.3f} of the 20-session average range. A rejected signal does "
             "not use the session's one entry (a later signal that day may enter); cross_struct stays armed.\n")
    for fn in FILTERS:
        if fn != "none": L.append(f"- **{fn}**")
    L.append("\n### Every system x filter\n")
    L.append(fmt(G, cols) + "\n")
    L.append("### Selected on 2018-22 PF (nA >= 200), no re-pick\n")
    L.append(f"Overall pick: **{pick.system} + {pick['filter']}** - IS PF {pick.pfA:.2f} (n {pick.nA}), OOS PF {pick.pfB:.2f} (n {pick.nB}), "
             f"2026 PF {pick.pf26:.2f} (n {pick.n26}); gross {pick.grossA:.1f} / {pick.grossB:.1f} / {pick.gross26:.1f} pts vs cost "
             f"{pick.costA:.1f} / {pick.costB:.1f} / {pick.cost26:.1f}.\n")
    L.append("The IS-best system for each filter:\n"); L.append(fmt(perf, cols) + "\n")
    open(os.path.join(OUT, "filter.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(fmt(perf, cols)); print("PICK", pick.to_dict())


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "label"
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 500)
    df = build()
    if stage == "label":
        print(feature_table(df, isonly=True).round(3).to_string(index=False))
        A = df[df.year <= 2022]
        for name in ("time of day", "minutes since band known", "beyond band (widths)", "band width / 20-session median",
                     "day range so far / 20-session avg range", "5m structure trend", "15m structure trend",
                     "1m EMA20/50 5-bar slopes with trade", "ADX(14) 5m", "previous session direction", "side"):
            t = A.groupby(["band", "B:" + name]).apply(lambda d: pd.Series(stat(d)), include_groups=False)[["n", "pf", "gross"]].unstack(0)
            print(); print("IS per band:", name); print(t.round(2).to_string())
        sys.exit(0)
    report(df)
