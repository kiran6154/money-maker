"""S55 NIFTY acceleration study (PREREG.md). python accel.py <stage> <tf> <year>[,<year>]

stages: primary (signals, M-excess, controls, splits, translation), options (real ATM options on P / PV),
        null (shuffled bars / shuffled volume), grid (27 cells), dataset (event CSV)
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit

HERE = Path(__file__).resolve().parent
WAVES = HERE.parent / "waves"
sys.path.insert(0, str(WAVES))
import data as WD  # noqa: E402  (S54 data layer: expiry calendar, raw option caches, spot)
import detect as WDET  # noqa: E402
import pipeline as WP  # noqa: E402

OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
CACHE = WD.LAB / "cache" / "accel"
CACHE.mkdir(parents=True, exist_ok=True)
PREREG_SHA = hashlib.sha256((HERE / "PREREG.md").read_bytes()).hexdigest()
F1 = "D:/nifty/niftyfut_nearmonth_minute_2021-10-01_to_2026-09-25.csv"
PERIOD = {2024: "dev", 2025: "val", 2026: "blind"}
PRIMARY = dict(L=6, a=1.5, v=1.5)
GRID = [dict(L=L, a=a, v=v) for L in (4, 6, 8) for a in (1.0, 1.5, 2.0) for v in (1.25, 1.5, 2.0)]
HORIZONS = [5, 15, 30, 60]
RNG = np.random.default_rng(20260930)


# ------------------------------------------------------------------ bars
def fut_bars(tf: int) -> pd.DataFrame:
    path = CACHE / f"fut_{tf}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    x = pd.read_csv(F1, parse_dates=["datetime"], usecols=["datetime", "open", "high", "low", "close", "volume"])
    x = x[x.datetime >= "2024-01-01"].rename(columns={"datetime": "dt"})
    x["date"] = x.dt.dt.normalize()
    n = x.groupby("date").size()
    x = x[x.date.isin(n[n >= 0.9 * 375].index)]
    if tf > 1:
        mins = (x.dt - x.date - pd.Timedelta("9h15min")).dt.total_seconds() // 60
        x["bar"] = x.date + pd.Timedelta("9h15min") + pd.to_timedelta((mins // tf) * tf, unit="m")
        g = x.groupby("bar")
        x = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(), "close": g.close.last(),
                          "volume": g.volume.sum()}).reset_index().rename(columns={"bar": "dt"})
        x["date"] = x.dt.dt.normalize()
    x = x.sort_values("dt").reset_index(drop=True)
    x["bis"] = x.groupby("date").cumcount().astype(np.int16)
    x["newsess"] = x.bis == 0
    x["tod"] = (x.dt.dt.hour * 60 + x.dt.dt.minute).astype(np.int16)
    for c in ("open", "high", "low", "close"):
        x["l" + c[0]] = np.log(x[c])
    cal = np.array(WD.expiry_calendar(), dtype="datetime64[ns]")
    d = x.date.values.astype("datetime64[ns]")
    nxt = cal[np.searchsorted(cal, d)]
    x["expiry"] = nxt
    x["dte"] = ((nxt - d) / np.timedelta64(1, "D")).astype(int)
    x["year"] = x.date.dt.year
    x["tf"] = tf
    x.to_parquet(path)
    return x


def dte_bucket(d):
    d = np.asarray(d, float)
    return np.select([d == 0, d == 1, d == 2, d <= 4], ["0", "1", "2", "3-4"], "5+")


# ------------------------------------------------------------------ features and signals
@njit(cache=True)
def _onset(cond, dirn, newsess, L):
    """Signal direction at onset (cond true at t, false at t-1), then no same-direction signal for L bars."""
    n = cond.shape[0]
    out = np.zeros(n, np.int8)
    last_up = -10 ** 9
    last_dn = -10 ** 9
    for t in range(n):
        if newsess[t]:
            last_up = -10 ** 9
            last_dn = -10 ** 9
        if not cond[t]:
            continue
        if t > 0 and not newsess[t] and cond[t - 1] and dirn[t - 1] == dirn[t]:
            continue
        if dirn[t] > 0 and t - last_up > L:
            out[t] = 1
            last_up = t
        elif dirn[t] < 0 and t - last_dn > L:
            out[t] = -1
            last_dn = t
    return out


@njit(cache=True)
def _window(lc, bis, L):
    n = lc.shape[0]
    RL = np.full(n, np.nan)
    R1 = np.full(n, np.nan)
    R2 = np.full(n, np.nan)
    h = L // 2
    for t in range(n):
        if bis[t] < L:
            continue
        RL[t] = lc[t] - lc[t - L]
        R1[t] = lc[t - h] - lc[t - L]
        R2[t] = lc[t] - lc[t - h]
    return RL, R1, R2


def features(b: pd.DataFrame, L: int) -> pd.DataFrame:
    lh, ll, lc = (b[c].values.astype(np.float64) for c in ("lh", "ll", "lc"))
    ns = b.newsess.values
    atr = WDET.atr_log(lh, ll, lc, np.zeros(len(b), np.bool_), ns, WDET.NV)
    RL, R1, R2 = _window(lc, b.bis.values.astype(np.int64), L)
    atr_pre = np.r_[np.full(L, np.nan), atr[:-L]]
    f = pd.DataFrame(index=b.index)
    f["atr"] = atr
    f["z"] = RL / (atr_pre * np.sqrt(L))
    f["RL"], f["R1"], f["R2"] = RL, R1, R2
    # time-of-day volume ratio: same bar-of-day, previous 10 sessions (>= 5)
    v = pd.Series(b.volume.values.astype(float), index=b.index)
    g = v.groupby(b.bis.values)
    lag = np.column_stack([g.shift(i).values for i in range(1, 11)])
    cnt = (~np.isnan(lag)).sum(1)
    with np.errstate(all="ignore"):
        med = np.where(cnt >= 5, np.nanmedian(np.where(cnt[:, None] > 0, lag, 0.0), axis=1), np.nan)
    f["med_tod"] = med
    f["vr_tod"] = b.volume.values / med
    h = L // 2
    sv = pd.Series(b.volume.values.astype(float)).groupby(b.date.values).transform(lambda s: s.rolling(h, min_periods=h).sum())
    sm = pd.Series(med).groupby(b.date.values).transform(lambda s: s.rolling(h, min_periods=h).sum())
    f["vrw"] = (sv / sm).values
    return f


def eligible(b: pd.DataFrame, f: pd.DataFrame, L: int) -> np.ndarray:
    tf = int(b.tf.iloc[0])
    return (b.bis.values >= L) & (b.tod.values + tf <= 15 * 60) & ~np.isnan(f.z.values)


def signals(b, f, el, L, a, v):
    """dict code -> (bar index array, direction array)."""
    ns = b.newsess.values
    out = {}
    d = np.sign(np.nan_to_num(f.RL.values)).astype(np.int8)
    accel = (np.abs(f.z.values) >= a) & (d * f.R2.values > d * f.R1.values) & (d * f.R1.values > 0)
    accel &= el
    sp = _onset(accel, d, ns, L)
    out["P"] = sp
    vcond = el & (f.vr_tod.values >= v)
    vd = np.sign(b.close.values - b.open.values).astype(np.int8)
    vcond &= vd != 0
    out["V"] = _onset(vcond, vd, ns, L)
    pv = sp.copy()
    pv[~(f.vrw.values >= v)] = 0
    out["PV"] = pv
    pnv = sp.copy()
    pnv[f.vrw.values >= v] = 0
    out["PnoV"] = pnv
    # C: S54 compression -> expansion, wave 1 accepted, on log futures (up) and on -log (down)
    lh, ll, lc = (b[c].values.astype(np.float64) for c in ("lh", "ll", "lc"))
    bis = b.bis.values.astype(np.int64)
    cs = np.zeros(len(b), np.int8)
    for sgn, (h_, l_, c_) in ((1, (lh, ll, lc)), (-1, (-ll, -lh, -lc))):
        at = WDET.atr_log(h_, l_, c_, np.zeros(len(b), np.bool_), ns, WDET.NV)
        cr = WDET.comp_ratio(h_, l_, at, bis, 12)
        sig = WDET.lifecycle(h_, l_, c_, cr, at, bis, ns, 0.75, 12, 2.0, 2, True)[0]
        t = sig[sig[:, WDET.S_WAVE] == 1, WDET.S_T].astype(np.int64)
        t = t[el[t]]
        cs[t] = sgn
    out["C"] = cs
    # O: opening range 09:15-09:30, first close beyond after 09:30, once per direction per day
    tf = int(b.tf.iloc[0])
    orr = b.tod.values < 9 * 60 + 30
    orh = pd.Series(np.where(orr, b.high.values, np.nan)).groupby(b.date.values).transform("max").values
    orl = pd.Series(np.where(orr, b.low.values, np.nan)).groupby(b.date.values).transform("min").values
    oc = np.zeros(len(b), np.int8)
    after = (b.tod.values >= 9 * 60 + 30) & el
    up = after & (b.close.values > orh)
    dn = after & (b.close.values < orl)
    for arr, s in ((up, 1), (dn, -1)):
        first = pd.Series(arr).groupby(b.date.values).cumsum().values == 1
        oc[arr & first] = s
    out["O"] = oc
    return out


# ------------------------------------------------------------------ outcomes
@njit(cache=True)
def _touch(lh, ll, lc, send, thr):
    """+1 if +thr is touched before -thr (log units) after t, -1 if -thr first, 0 if neither by the session end.
    A bar touching both counts as -1 for longs (up array) and +1 for shorts... handled by the caller via two passes."""
    n = lc.shape[0]
    up = np.zeros(n, np.int8)   # for a long: +1 win, -1 loss (ambiguous bar = loss)
    dn = np.zeros(n, np.int8)   # for a short: +1 win, -1 loss (ambiguous bar = loss)
    for t in range(n):
        u = lc[t] + thr
        d = lc[t] - thr
        for j in range(t + 1, send[t] + 1):
            hu = lh[j] >= u
            hd = ll[j] <= d
            if hu or hd:
                up[t] = -1 if hd else 1
                dn[t] = -1 if hu else 1
                break
    return up, dn


def outcomes(b: pd.DataFrame) -> pd.DataFrame:
    lo, lh, ll, lc = (b[c].values.astype(np.float64) for c in ("lo", "lh", "ll", "lc"))
    last = pd.Series(np.arange(len(b))).groupby(b.date.values).transform("max").values.astype(np.int64)
    tf = int(b.tf.iloc[0])
    o = pd.DataFrame(index=b.index)
    for h in HORIZONS + ["eos"]:
        if h != "eos" and h % tf:
            continue
        hb = 0 if h == "eos" else h // tf
        r, mf, ma, _ = WP._fwd(lo, lh, ll, lc, last, hb)
        o[f"r{h}"], o[f"mfe{h}"], o[f"mae{h}"] = r * 1e4, mf * 1e4, ma * 1e4
    up, dn = _touch(lh, ll, lc, last, 0.0025)
    o["t25_up"], o["t25_dn"] = up, dn
    return o


def signed(o: pd.DataFrame, idx, d) -> pd.DataFrame:
    """Direction-signed outcome rows for bar indices idx with directions d (bp)."""
    d = np.asarray(d, float)
    s = pd.DataFrame({"i": idx, "d": d})
    for c in o.columns:
        if c.startswith("r"):
            s["y" + c[1:]] = d * o[c].values[idx]
        elif c.startswith("mfe"):
            s["mfe" + c[3:]] = np.where(d > 0, o[c].values[idx], -o["mae" + c[3:]].values[idx])
        elif c.startswith("mae"):
            s["mae" + c[3:]] = np.where(d > 0, o[c].values[idx], -o["mfe" + c[3:]].values[idx])
    s["t25"] = np.where(d > 0, o.t25_up.values[idx], o.t25_dn.values[idx])
    return s


def pool(b, f, o, el):
    idx = np.flatnonzero(el)
    parts = []
    for d in (1, -1):
        s = signed(o, idx, np.full(len(idx), d))
        s["zs"] = d * f.z.values[idx]
        parts.append(s)
    p = pd.concat(parts, ignore_index=True)
    p["hour"] = b.tod.values[p.i] // 60
    p["dteb"] = dte_bucket(b.dte.values[p.i])
    p["week"] = b.expiry.values[p.i]
    q = np.nanquantile(p.zs, np.linspace(0, 1, 11)[1:-1])
    p["dec"] = np.searchsorted(q, p.zs.fillna(0).values)
    p.attrs["q"] = q
    return p


def events(b, f, o, el, sig, pl):
    rows = []
    q = pl.attrs["q"]
    for code, arr in sig.items():
        idx = np.flatnonzero(arr != 0)
        s = signed(o, idx, arr[idx])
        s["code"] = code
        s["zs"] = arr[idx] * f.z.values[idx]
        rows.append(s)
    ev = pd.concat(rows, ignore_index=True)
    ev["hour"] = b.tod.values[ev.i] // 60
    ev["dteb"] = dte_bucket(b.dte.values[ev.i])
    ev["dte"] = b.dte.values[ev.i]
    ev["week"] = b.expiry.values[ev.i]
    ev["dt"] = b.dt.values[ev.i]
    ev["date"] = b.date.values[ev.i]
    ev["dec"] = np.searchsorted(q, ev.zs.fillna(0).values)
    ev["vrw"] = f.vrw.values[ev.i]
    ev["vr_tod"] = f.vr_tod.values[ev.i]
    ev["z"] = f.z.values[ev.i]
    ev["price"] = b.close.values[ev.i]
    for h in HORIZONS + ["eos"]:
        c = f"y{h}"
        if c not in pl:
            continue
        mM = pl.groupby(["hour", "dteb", "dec"])[c].mean().rename("_m")
        mA = pl.groupby(["hour", "dteb"])[c].mean().rename("_a")
        ev[f"xM{h}"] = ev[c] - ev.join(mM, on=["hour", "dteb", "dec"])["_m"]
        ev[f"xA{h}"] = ev[c] - ev.join(mA, on=["hour", "dteb"])["_a"]
    return ev


# ------------------------------------------------------------------ statistics
def cboot(vals, clusters, nboot=5000, rng=RNG):
    v = np.asarray(vals, float)
    ok = ~np.isnan(v)
    v, cl = v[ok], np.asarray(clusters)[ok]
    if len(v) < 5:
        return dict(n=int(len(v)), mean=float(v.mean()) if len(v) else None, lo=None, hi=None)
    u, inv = np.unique(cl, return_inverse=True)
    s, c = np.bincount(inv, v), np.bincount(inv)
    dr = rng.integers(0, len(u), (nboot, len(u)))
    m = s[dr].sum(1) / c[dr].sum(1)
    return dict(n=int(len(v)), weeks=int(len(u)), mean=float(v.mean()), lo=float(np.percentile(m, 2.5)),
                hi=float(np.percentile(m, 97.5)))


def cboot_diff(a, wa, b_, wb, nboot=5000, rng=RNG):
    """Week-clustered bootstrap of mean(a) - mean(b), resampling weeks jointly."""
    weeks = np.unique(np.r_[np.asarray(wa), np.asarray(wb)])
    ia = np.searchsorted(weeks, wa)
    ib = np.searchsorted(weeks, wb)
    a, b_ = np.asarray(a, float), np.asarray(b_, float)
    ka, kb = ~np.isnan(a), ~np.isnan(b_)
    sa, ca = np.bincount(ia[ka], a[ka], len(weeks)), np.bincount(ia[ka], None, len(weeks))
    sb, cb = np.bincount(ib[kb], b_[kb], len(weeks)), np.bincount(ib[kb], None, len(weeks))
    dr = rng.integers(0, len(weeks), (nboot, len(weeks)))
    with np.errstate(all="ignore"):
        dd = sa[dr].sum(1) / ca[dr].sum(1) - sb[dr].sum(1) / cb[dr].sum(1)
    return dict(diff=float(a[ka].mean() - b_[kb].mean()), lo=float(np.nanpercentile(dd, 2.5)),
                hi=float(np.nanpercentile(dd, 97.5)))


def perm(ev, pl, col, nperm=2000, rng=RNG):
    keys = ["hour", "dteb", "dec"]
    p = pl.dropna(subset=[col])
    ex = (p[col] - p.groupby(keys)[col].transform("mean")).values
    gid = p.groupby(keys).ngroup().values
    k2g = p.assign(g=gid).groupby(keys).g.first()
    order = np.argsort(gid, kind="stable")
    gs = gid[order]
    obs = ev["xM" + col[1:]].mean()
    tot, ntot = np.zeros(nperm), 0
    for kk, cnt in ev.dropna(subset=["xM" + col[1:]]).groupby(keys).size().items():
        g = k2g.get(kk)
        if g is None or cnt == 0:
            continue
        seg = ex[order[np.searchsorted(gs, g):np.searchsorted(gs, g, side="right")]]
        tot += seg[rng.integers(0, len(seg), (nperm, cnt))].sum(1)
        ntot += cnt
    null = tot / max(ntot, 1)
    return dict(obs=float(obs), null_sd=float(null.std()), p=float((null >= obs).mean()))


def jdump(obj, name):
    obj = dict(prereg_sha256=PREREG_SHA, generated=time.strftime("%Y-%m-%d %H:%M:%S"), **obj)
    (OUT / name).write_text(json.dumps(obj, indent=1, default=lambda x: None if x is None else (
        float(x) if isinstance(x, (np.floating, float, np.integer)) else str(x))))


# ------------------------------------------------------------------ one period
def run_period(b_all, tf, year, prm, detail=True):
    b = b_all[b_all.year == year].reset_index(drop=True)
    # ATR warm-up: prepend the previous session's bars
    prev = b_all[(b_all.year < year)]
    if len(prev):
        lastd = prev.date.max()
        b = pd.concat([prev[prev.date == lastd], b], ignore_index=True)
    f = features(b, prm["L"])
    el = eligible(b, f, prm["L"]) & (b.year.values == year)
    o = outcomes(b)
    sig = signals(b, f, el, prm["L"], prm["a"], prm["v"])
    pl = pool(b, f, o, el)
    ev = events(b, f, o, el, sig, pl)
    return b, f, o, el, sig, pl, ev


def summarize(ev, pl, b, with_perm=True):
    res = {}
    for code, g in ev.groupby("code"):
        r = dict(n=int(len(g)))
        for h in HORIZONS + ["eos"]:
            if f"xM{h}" in g:
                r[f"xM{h}"] = cboot(g[f"xM{h}"], g.week)
                r[f"y{h}"] = cboot(g[f"y{h}"], g.week)
        r["xA30"] = cboot(g.xA30, g.week) if "xA30" in g else None
        r["hit"] = {f"ge{t}": float((g.y30 >= t).mean()) for t in (10, 25, 50)} if "y30" in g else None
        r["p25_first"] = float((g.t25 == 1).sum() / max((g.t25 != 0).sum(), 1))
        r["mfe30"], r["mae30"] = (float(g.mfe30.mean()), float(g.mae30.mean())) if "mfe30" in g else (None, None)
        if with_perm and code in ("P", "PV") and "y30" in pl:
            r["perm30"] = perm(g, pl, "y30")
        res[code] = r
    res["A"] = dict(n=int(len(pl)), y30=cboot(pl.y30, pl.week) if "y30" in pl else None,
                    hit={f"ge{t}": float((pl.y30 >= t).mean()) for t in (10, 25, 50)} if "y30" in pl else None,
                    p25_first=float((pl.t25 == 1).sum() / max((pl.t25 != 0).sum(), 1)))
    # descriptive: signed forward 30-min return by trailing-z decile (is there momentum at all?)
    if "y30" in pl:
        res["decile_curve_y30"] = {int(k): float(v) for k, v in pl.groupby("dec").y30.mean().items()}
    # H2: PV vs P without volume
    if "xM30" in ev:
        pv, pn = ev[ev.code == "PV"], ev[ev.code == "PnoV"]
        res["H2_PV_minus_PnoV_xM30"] = cboot_diff(pv.xM30, pv.week, pn.xM30, pn.week)
    return res


def splits(ev, b):
    ref = WD.spot_reference()
    out = {}
    e = ev[ev.code.isin(["P", "PV"])].copy()
    day = ref.reindex(pd.to_datetime(e.date.values))
    e["dir"] = np.where(e.d > 0, "up", "down")
    e["vol_causal"] = np.where(day.prev_range_pct.values > day.prev_range_med20.values, "high_prev_range", "low_prev_range")
    e["hourb"] = np.select([e.hour < 11, e.hour < 13], ["09-11", "11-13"], "13-15")
    for code, g in e.groupby("code"):
        out[code] = {col: {str(k): cboot(x.xM30, x.week) for k, x in g.groupby(col)}
                     for col in ("dteb", "dir", "vol_causal", "hourb")}
    return out


def translate(ev, year):
    """PREREG §5: 15-minute futures move through the S54 ATM response of the same period and DTE bucket."""
    per = PERIOD[year]
    tb = json.load(open(WAVES / "results" / f"dte_tf5_{year}.json"))["results"][per]
    out = {}
    for code in ("P", "PV", "C", "O"):
        g = ev[(ev.code == code) & ev.y15.notna()]
        rows = []
        for db, x in g.groupby("dteb"):
            vals = []
            for side, sg in (("CE", 1), ("PE", -1)):
                k = f"{db}|ATM|{side}"
                if k not in tb:
                    continue
                c = tb[k]
                xx = x[x.d == sg]
                mv = xx.d.values * xx.y15.values / 1e4  # the raw futures log move (y is signed)
                vals += list(c["intercept"] + c["elasticity"] * mv + c["convexity"] * mv * mv)
            if vals:
                up, dn = [tb.get(f"{db}|ATM|CE"), tb.get(f"{db}|ATM|PE")]
                be = None
                if up:
                    m = 0.0025
                    w, l_ = up["intercept"] + up["elasticity"] * m + up["convexity"] * m * m, \
                        up["intercept"] - up["elasticity"] * m + up["convexity"] * m * m
                    be = float(-l_ / (w - l_)) if w > l_ else None
                rows.append((db, len(vals), float(np.mean(vals)) * 100,
                             float((x.y15 > 0).mean()), be))
        out[code] = [dict(dte=r[0], n=r[1], mean_option_ret_pct=r[2], hit_rate_15m=r[3], breakeven_hit_025=r[4]) for r in rows]
    return out


# ------------------------------------------------------------------ stages
def stage_primary(tf, years):
    b_all = fut_bars(tf)
    res, trans, spl, evs = {}, {}, {}, []
    for y in years:
        b, f, o, el, sig, pl, ev = run_period(b_all, tf, y, PRIMARY)
        res[PERIOD[y]] = summarize(ev, pl, b)
        spl[PERIOD[y]] = splits(ev, b)
        if tf == 5 and "y15" in ev:
            trans[PERIOD[y]] = translate(ev, y)
        ev["period"] = PERIOD[y]
        evs.append(ev)
        print(y, "tf", tf, {k: int((v != 0).sum()) for k, v in sig.items()}, flush=True)
    tag = "_".join(map(str, years))
    jdump(dict(tf=tf, params=PRIMARY, results=res, splits=spl, translation=trans), f"primary_tf{tf}_{tag}.json")
    pd.concat(evs).to_parquet(OUT / f"events_tf{tf}_{tag}.parquet")


def shuffle(b, seed):
    rng = np.random.default_rng(seed)
    b = b.copy()
    prev = b.lc.shift(1).values
    prev[b.newsess.values] = np.nan
    off = np.c_[b.lo - prev, b.lh - prev, b.ll - prev, b.lc - prev]
    starts = np.flatnonzero(b.newsess.values)
    ends = np.r_[starts[1:], len(b)]
    perm_ = np.arange(len(b))
    for s, e in zip(starts, ends):
        perm_[s + 1:e] = rng.permutation(perm_[s + 1:e])
    off, vol = off[perm_], b.volume.values[perm_]
    lo, lh, ll, lc = b.lo.values.copy(), b.lh.values.copy(), b.ll.values.copy(), b.lc.values.copy()
    for s, e in zip(starts, ends):
        c = lc[s]
        for i in range(s + 1, e):
            lo[i], lh[i], ll[i] = c + off[i, 0], c + off[i, 1], c + off[i, 2]
            c += off[i, 3]
            lc[i] = c
    b["lo"], b["lh"], b["ll"], b["lc"], b["volume"] = lo, lh, ll, lc, vol
    b["open"], b["high"], b["low"], b["close"] = np.exp(lo), np.exp(lh), np.exp(ll), np.exp(lc)
    return b


def shuffle_volume(b, seed):
    rng = np.random.default_rng(seed)
    b = b.copy()
    v = b.volume.values.copy()
    starts = np.flatnonzero(b.newsess.values)
    for s, e in zip(starts, np.r_[starts[1:], len(b)]):
        v[s:e] = rng.permutation(v[s:e])
    b["volume"] = v
    return b


def stage_null(tf, years, reps=20):
    b_all = fut_bars(tf)
    out = {}
    for y in years:
        per = PERIOD[y]
        rows = {"bars": [], "volume": []}
        for kind, fn in (("bars", shuffle), ("volume", shuffle_volume)):
            for r in range(reps if kind == "bars" else 10):
                bs = fn(b_all[b_all.year.isin([y - 1, y])].reset_index(drop=True), 5000 + r)
                _, _, _, _, sig, pl, ev = run_period(bs, tf, y, PRIMARY)
                row = {c: dict(n=int((ev.code == c).sum()), xM30=float(ev.xM30[ev.code == c].mean()))
                       for c in ("P", "PV", "PnoV", "V", "C", "O")}
                rows[kind].append(row)
            print(per, kind, "done", flush=True)
        out[per] = {kind: {c: dict(n_mean=float(np.mean([r[c]["n"] for r in rr])),
                                   xM30_mean=float(np.nanmean([r[c]["xM30"] for r in rr])),
                                   xM30_lo=float(np.nanpercentile([r[c]["xM30"] for r in rr], 2.5)),
                                   xM30_hi=float(np.nanpercentile([r[c]["xM30"] for r in rr], 97.5)))
                           for c in rr[0]} for kind, rr in rows.items()}
    jdump(dict(tf=tf, results=out), f"null_tf{tf}_{'_'.join(map(str, years))}.json")


def stage_grid(tf, years):
    b_all = fut_bars(tf)
    out = {}
    for y in years:
        rows = []
        for prm in GRID:
            _, _, _, _, sig, pl, ev = run_period(b_all, tf, y, prm)
            for c in ("P", "PV"):
                g = ev[ev.code == c]
                rows.append(dict(**prm, code=c, n=int(len(g)), xM30=float(g.xM30.mean()) if len(g) else None))
        out[PERIOD[y]] = rows
        print(PERIOD[y], "grid done", flush=True)
    jdump(dict(tf=tf, results=out), f"grid_tf{tf}_{'_'.join(map(str, years))}.json")


# ------------------------------------------------------------------ real options (H3)
def option_series(year, expiry, strike, right):
    """Option bars of one contract from the S54 raw cache (5-minute: native in 2024, resampled from 1-minute after)."""
    import pyarrow.parquet as pq
    path = WD.CACHE / f"raw_{year}.parquet"
    t = pq.read_table(path, filters=[("expiry", "=", pd.Timestamp(expiry)), ("strike", "=", int(strike)),
                                     ("right", "=", int(right))]).to_pandas()
    return t


def stage_options(tf, years):
    sys.path.insert(0, str(WAVES))
    import stages as WS
    sp5 = WD.spot5().set_index("dt").close
    out = {}
    for y in years:
        per = PERIOD[y]
        ev = pd.read_parquet(OUT / f"events_tf{tf}_{y}.parquet")
        ev = ev[ev.code.isin(["P", "PV", "C", "O"])].copy()
        sig_end = pd.to_datetime(ev.dt) + pd.Timedelta(minutes=tf)
        last5 = (sig_end - pd.Timedelta(minutes=5)).dt.floor("5min")
        spot = sp5.reindex(last5.values).values
        ev["strike"] = np.round(spot / 100) * 100
        ev["right"] = np.where(ev.d > 0, 0, 1)
        rows = []
        for (e, k, r), g in ev.groupby([ev.week, ev.strike, ev.right]):
            if np.isnan(k):
                continue
            ey = pd.Timestamp(e).year
            if ey not in WD.SOURCES:
                continue
            s = option_series(ey, e, k, r)
            if len(s) == 0:
                for row in g.itertuples():
                    rows.append(dict(code=row.code, week=e, missing=True))
                continue
            base = 5 if WD.SOURCES[ey][1] == "5minute" else 1
            s["expiry"] = pd.Timestamp(e)
            bars = WD.resample(s, tf, base) if tf != base else s
            bars = bars.set_index("dt").sort_index()
            ref = s.ref_time.iloc[0]
            for row in g.itertuples():
                t0 = pd.Timestamp(row.dt)
                if t0 not in bars.index:
                    rows.append(dict(code=row.code, week=e, missing=True))
                    continue
                p0 = bars.loc[t0, "close"]
                t30 = t0 + pd.Timedelta(minutes=30)
                day = bars[bars.index.normalize() == t0.normalize()]
                p30 = bars.loc[t30, "close"] if t30 in bars.index else np.nan
                peos = day.close.iloc[-1]
                nxt = day[day.index > t0]
                pno = nxt.open.iloc[0] if len(nxt) else np.nan
                rows.append(dict(code=row.code, week=e, missing=False, dteb=row.dteb, dir=row.d, p0=p0, p30=p30,
                                 peos=peos, pno=pno, hind=bool(ref is not None and pd.notna(ref) and t0 < pd.Timestamp(ref)),
                                 filler0=bool(bars.loc[t0, "filler"]) if "filler" in bars else False))
        R = pd.DataFrame(rows)
        res = {}
        for code, g in R.groupby("code"):
            gm = g[~g.missing.astype(bool)]
            clean = gm[~gm.hind.astype(bool) & ~gm.filler0.astype(bool) & gm.p0.gt(5)]
            r = dict(n_signals=int(len(g)), missing_strike=int(g.missing.sum()), hindsight=int(gm.hind.sum()), n_clean=int(len(clean)))
            q = np.array([WS.lot_size(x) for x in clean.week.values])
            for slip in (0.0025, 0.005, 0.01):
                for exitc in ("p30", "peos"):
                    for entry in ("p0", "pno"):
                        z = clean.dropna(subset=[exitc, entry])
                        qq = np.array([WS.lot_size(x) for x in z.week.values])
                        nl, rs = WS.net_log(z[entry].values, z[exitc].values, qq, slip)
                        wk = pd.Series(rs).groupby(z.week.values).sum()
                        r[f"{exitc}_{entry}_slip{slip}"] = dict(
                            n=int(len(z)), net_pct=cboot((np.exp(nl) - 1) * 100, z.week.values),
                            rs_per_lot=float(np.mean(rs)) if len(rs) else None,
                            win_rate=float((rs > 0).mean()) if len(rs) else None,
                            worst_week_rs=float(wk.min()) if len(wk) else None,
                            positive_weeks=f"{int((wk > 0).sum())}/{len(wk)}")
            r["by_dte_p30_p0_slip0.005"] = {}
            for db, z in clean.dropna(subset=["p30"]).groupby("dteb"):
                qq = np.array([WS.lot_size(x) for x in z.week.values])
                nl, rs = WS.net_log(z.p0.values, z.p30.values, qq, 0.005)
                r["by_dte_p30_p0_slip0.005"][db] = cboot((np.exp(nl) - 1) * 100, z.week.values)
            res[code] = r
        out[per] = res
        print(per, "options done", flush=True)
    jdump(dict(tf=tf, results=out), f"options_tf{tf}_{'_'.join(map(str, years))}.json")


if __name__ == "__main__":
    st, tf = sys.argv[1], int(sys.argv[2])
    yrs = [int(x) for x in sys.argv[3].split(",")]
    t0 = time.time()
    {"primary": stage_primary, "null": stage_null, "grid": stage_grid, "options": stage_options}[st](tf, yrs)
    print(st, "done", round(time.time() - t0), "s")
