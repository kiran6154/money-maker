"""Wave-lifecycle study: event tables, baselines and tests (PREREG.md §5-§10).

python study.py <stage> [...]   stages: primary, grid, null, tf, geometry, decomp, dte, volume, costs, report
Results land in results/*.json and events.csv next to this file.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

import data as DA
import detect as D
import pipeline as P

HERE = Path(__file__).resolve().parent
OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
PREREG_SHA = hashlib.sha256((HERE / "PREREG.md").read_bytes()).hexdigest()

PRIMARY = dict(L=12, c=0.75, k=2.0, m=2, strict=True, v=3.0)
YEARS = [2024, 2025, 2026]
TF_YEARS = {1: [2025, 2026], 3: [2025, 2026], 5: YEARS, 10: YEARS, 15: YEARS}
RNG = np.random.default_rng(20260930)
NBOOT = 5000
NPERM = 2000

_cache: dict = {}


def panel(year, tf, L, k, v=3.0):
    key = (year, tf, L, k)
    if key not in _cache:
        b = P.build_bars(year, tf)
        f = P.features(b, L, k, v)
        o = P.outcomes(b)
        el = P.eligible(b, f, L)
        _cache[key] = (b, f, o, el)
    return _cache[key]


def dte_bucket(d):
    d = np.asarray(d, dtype=float)
    return np.select([d == 0, d == 1, d == 2, d <= 4], ["0", "1", "2", "3-4"], "5+")


def pool_frame(b, f, o, el, extra=None):
    """Eligible bars with the matching keys and outcomes (the A pool)."""
    idx = np.flatnonzero(el)
    x = pd.DataFrame({
        "i": idx, "sid": b.sid.values[idx], "expiry": b.expiry.values[idx], "date": b.date.values[idx],
        "right": b.right.values[idx], "money": np.asarray(b.money.values[idx], dtype=object),
        "role": np.asarray(b.role.values[idx], dtype=object),
        "dte": b.dte.values[idx], "hindsight": b.hindsight.values[idx].astype(bool),
        "hour": b.tod.values[idx] // 60, "trail": f.trail.values[idx],
    })
    x["dteb"] = dte_bucket(x.dte)
    for c in o.columns:
        x[c] = o[c].values[idx]
    return x


def add_deciles(pool):
    q = np.nanquantile(pool.trail, np.linspace(0, 1, 11)[1:-1])
    pool["dec"] = np.searchsorted(q, pool.trail.fillna(0).values)
    return q


def matched_excess(ev, pool, col, keys):
    """ev[col] minus the pool mean of col in the same key cell (NaN when the cell is empty)."""
    m = pool.groupby(keys)[col].mean().rename("_e")
    e = ev.join(m, on=keys)["_e"]
    return ev[col] - e


def cluster_boot(vals, clusters, nboot=NBOOT, rng=RNG):
    """Week-clustered bootstrap of the mean. Returns (mean, lo, hi, n, nclusters)."""
    v = np.asarray(vals, float)
    ok = ~np.isnan(v)
    v, cl = v[ok], np.asarray(clusters)[ok]
    if len(v) < 3:
        return dict(mean=float(np.mean(v)) if len(v) else None, lo=None, hi=None, n=int(len(v)), clusters=0)
    u, inv = np.unique(cl, return_inverse=True)
    s = np.bincount(inv, v)
    c = np.bincount(inv)
    draws = rng.integers(0, len(u), (nboot, len(u)))
    means = s[draws].sum(1) / c[draws].sum(1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return dict(mean=float(v.mean()), lo=float(lo), hi=float(hi), n=int(len(v)), clusters=int(len(u)),
                p_le0=float((means <= 0).mean()))


def perm_test(ev_excess_cells, pool, col, keys, nperm=NPERM, rng=RNG):
    """Label permutation within matched cells: draw the same number of pool bars per cell as there are events,
    mean of their matched excess; p = share of draws >= the events' mean."""
    pool = pool[~pool[col].isna()]
    cm = pool.groupby(keys)[col].transform("mean")
    pex = (pool[col] - cm).values
    gid = pool.groupby(keys).ngroup().values
    evc = ev_excess_cells.dropna(subset=["_x"])
    cells = evc.groupby(keys).size()
    key_to_gid = pool.assign(g=gid).groupby(keys).g.first()
    obs = evc._x.mean()
    order = np.argsort(gid, kind="stable")
    gs = gid[order]
    starts = np.searchsorted(gs, np.arange(gid.max() + 1))
    ends = np.searchsorted(gs, np.arange(gid.max() + 1), side="right")
    tot = np.zeros(nperm)
    ntot = 0
    for kk, cnt in cells.items():
        g = key_to_gid.get(kk)
        if g is None:
            continue
        seg = pex[order[starts[g]:ends[g]]]
        if len(seg) == 0:
            continue
        tot += seg[rng.integers(0, len(seg), (nperm, cnt))].sum(1)
        ntot += cnt
    null = tot / max(ntot, 1)
    return dict(obs=float(obs), null_mean=float(null.mean()), null_sd=float(null.std()),
                p=float((null >= obs).mean()))


EVCOLS = ["i", "code"]


def events(year, tf, prm, codes=("A", "B", "C", "D", "E", "F", "G", "H", "I", "I3"), bars=None):
    """Event table for one period/timeframe/cell with lifecycle fields and matched excess returns."""
    L, c, k, m, strict, v = prm["L"], prm["c"], prm["k"], prm["m"], prm["strict"], prm["v"]
    if bars is None:
        b, f, o, el = panel(year, tf, L, k, v)
    else:
        b = bars
        f = P.features(b, L, k, v)
        o = P.outcomes(b)
        el = P.eligible(b, f, L)
    sigs, cell = P.control_signals(b, f, el, L, c, k, m, strict, v)
    sig, lcs, waves, fails = cell
    pool = pool_frame(b, f, o, el)
    add_deciles(pool)
    rows = []
    for code in codes:
        if code == "A":
            continue
        for i in sigs[code]:
            rows.append((i, code))
    ev = pd.DataFrame(rows, columns=["i", "code"])
    ev = ev.merge(pool, on="i", how="left")
    # lifecycle fields for G / I / I3
    st = sig[:, D.S_T].astype(np.int64)
    lif = pd.DataFrame({"i": st, "wave": sig[:, D.S_WAVE], "lc": sig[:, D.S_LC].astype(np.int64),
                        "base_high": np.exp(sig[:, D.S_BH]), "base_low": np.exp(sig[:, D.S_BL]),
                        "breakout_price": np.exp(sig[:, D.S_LEVEL]), "retests": sig[:, D.S_RET],
                        "higher_lows": sig[:, D.S_HL], "failed_before": sig[:, D.S_FAIL],
                        "bo": sig[:, D.S_BO].astype(np.int64), "start": sig[:, D.S_START].astype(np.int64)})
    ev = ev.merge(lif.drop_duplicates("i"), on="i", how="left")
    ev.loc[~ev.code.isin(["G", "I", "I3"]), ["wave", "lc"]] = np.nan
    # outcomes of the lifecycle after the signal
    maxw = lcs[:, D.L_MAXW] if len(lcs) else np.array([])
    has_lc = ev.lc.notna()
    lcid = ev.lc.fillna(0).astype(int).values
    ev["lc_maxwave"] = np.where(has_lc, maxw[lcid] if len(maxw) else np.nan, np.nan)
    ev["lc_reason"] = np.where(has_lc, lcs[lcid, D.L_REASON] if len(lcs) else np.nan, np.nan)
    ev["next_wave"] = ev.lc_maxwave > ev.wave
    nxt = np.full(len(ev), np.nan)
    for j in np.flatnonzero(has_lc.values):
        w = int(ev.wave.values[j])
        if w < D.MAXW and not np.isnan(waves[lcid[j], w, D.W_ACC]):
            nxt[j] = (waves[lcid[j], w, D.W_ACC] - ev.i.values[j]) * tf
    ev["min_to_next_wave"] = nxt
    ev["vr"] = f.vr.values[ev.i.values]
    ev["vr_tod"] = f.vr_tod.values[ev.i.values]
    ev["vr_bo"] = np.where(has_lc, f.vr.values[ev.bo.fillna(0).astype(int).values], np.nan)
    ev["cr"] = f.cr.values[ev.i.values]
    ev["atr"] = f.atr.values[ev.i.values]
    ev["price"] = b.close.values[ev.i.values]
    ev["F"] = b.F.values[ev.i.values]
    ev["spot_ref"] = b.spot_ref.values[ev.i.values]
    ev["dt"] = b.dt.values[ev.i.values]
    ev["strike"] = b.strike.values[ev.i.values]
    ev["year"] = year
    ev["tf"] = tf
    ev["period"] = DA.PERIOD[year]
    ev["week"] = ev.expiry
    for h in P.HORIZONS + ["eos"]:
        col = f"r{h}"
        if col not in pool:
            continue
        ev[f"xA{h}"] = matched_excess(ev, pool, col, ["right", "money", "role", "dteb", "hour"])
        ev[f"xJ{h}"] = matched_excess(ev, pool, col, ["right", "money", "role", "dteb", "hour", "dec"])
    return ev, pool, (sig, lcs, waves, fails), (b, f, o, el)


def primary_mask(ev, clean=True):
    m = (ev.role == "front") & (ev.money == "ATM")
    if clean:
        m &= ~ev.hindsight.astype(bool)
    return m


JKEYS = ["right", "money", "role", "dteb", "hour", "dec"]
AKEYS = ["right", "money", "role", "dteb", "hour"]


def summarize(ev, pool, mask, h=30, perm=True, pool_mask=None):
    e = ev[mask]
    out = {}
    for code, g in e.groupby("code"):
        r = dict(n=int(len(g)))
        for base in ("A", "J"):
            col = f"x{base}{h}"
            if col in g:
                r[f"excess_{base}"] = cluster_boot(g[col].values, g.week.values)
        r["raw"] = cluster_boot(g[f"r{h}"].values, g.week.values) if f"r{h}" in g else None
        if perm and f"r{h}" in g and code in ("I", "I3", "G", "H"):
            pm = pool[pool.i.isin(pool.i) & (pool.role == "front") & (pool.money == "ATM") & ~pool.hindsight] \
                if mask is not None else pool
            gg = g.assign(_x=g[f"xJ{h}"])
            r["perm_J"] = perm_test(gg, pm, f"r{h}", JKEYS)
        out[code] = r
    return out


def jdump(obj, name):
    obj = dict(prereg_sha256=PREREG_SHA, generated=time.strftime("%Y-%m-%d %H:%M:%S"), **obj)
    (OUT / name).write_text(json.dumps(obj, indent=1, default=lambda x: None if x is None else
                                       (float(x) if isinstance(x, (np.floating, float)) else str(x))))


def stage_primary(tf=5, years=YEARS, tag=""):
    """H1 and the control comparison (Parts 13, 14, 16) for one timeframe, every period separately."""
    res = {}
    allev = []
    for y in years:
        t0 = time.time()
        ev, pool, cell, pn = events(y, tf, PRIMARY)
        per = DA.PERIOD[y]
        res[per] = {}
        for label, mask in (("primary_clean", primary_mask(ev)), ("primary_all_sessions", primary_mask(ev, False)),
                            ("all_contracts_front", ev.role == "front"),
                            ("all_contracts_front_clean", (ev.role == "front") & ~ev.hindsight.astype(bool))):
            pmask = (pool.role == "front") & (pool.money == "ATM") & ~pool.hindsight
            res[per][label] = {str(h): summarize(ev, pool, mask, h, perm=(h == 30 and label == "primary_clean"),
                                                 pool_mask=pmask)
                               for h in P.HORIZONS + ["eos"] if f"r{h}" in pool}
        # Part 14 tail probabilities and lifecycle continuation, primary contracts
        tails = {}
        pm = primary_mask(ev)
        for code, g in ev[pm].groupby("code"):
            d = dict(n=int(len(g)))
            for x in (5, 10, 20, 30, 50):
                d[f"p_mfe_eos_ge_{x}"] = float((g.mfeeos >= np.log(1 + x / 100)).mean())
            d["p_mae_eos_le_-20"] = float((g.maeeos <= np.log(0.8)).mean())
            if code in ("G", "I", "I3"):
                d["p_next_wave"] = float(g.next_wave.mean())
                d["median_min_to_next_wave"] = float(np.nanmedian(g.min_to_next_wave)) if g.next_wave.any() else None
                d["p_failed_base"] = float((g.lc_reason == 1).mean())
                d["p_stalled"] = float((g.lc_reason == 2).mean())
            for h in (5, 10, 15, 30, 60):
                if f"mfe{h}" in g:
                    d[f"mean_mfe{h}"] = float(np.nanmean(g[f"mfe{h}"]))
                    d[f"mean_mae{h}"] = float(np.nanmean(g[f"mae{h}"]))
            d["mean_points_r30"] = float(np.nanmean(g.price * (np.exp(g.r30) - 1))) if "r30" in g else None
            tails[code] = d
        # the same probabilities for the pool (every eligible primary bar)
        pp = pool[(pool.role == "front") & (pool.money == "ATM") & ~pool.hindsight]
        tails["A"] = {f"p_mfe_eos_ge_{x}": float((pp.mfeeos >= np.log(1 + x / 100)).mean()) for x in (5, 10, 20, 30, 50)}
        tails["A"]["n"] = int(len(pp))
        res[per]["tails"] = tails
        allev.append(ev[ev.code != "A"])
        print(f"{y} tf{tf}: {len(ev)} events, {time.time() - t0:.0f}s", flush=True)
    jdump(dict(tf=tf, params=PRIMARY, results=res), f"primary_tf{tf}{tag}.json")
    evs = pd.concat(allev, ignore_index=True)
    evs.to_parquet(OUT / f"events_tf{tf}{tag}.parquet")
    return res, evs


if __name__ == "__main__":
    stage = sys.argv[1]
    if stage == "primary":
        tf = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        yrs = [int(x) for x in sys.argv[3].split(",")] if len(sys.argv) > 3 else TF_YEARS[tf]
        stage_primary(tf, yrs, tag="" if yrs == TF_YEARS[tf] else "_" + "_".join(map(str, yrs)))
