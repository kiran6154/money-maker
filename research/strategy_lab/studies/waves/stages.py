"""Remaining study stages (PREREG §4, §8-§11): grid, null, timeframes, geometry, decomposition, DTE, volume,
regimes, costs, reversal / mirror. python stages.py <stage> <years comma list> [tf]"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import norm

import data as DA
import detect as D
import pipeline as P
import study as S

GRID_L = [8, 10, 12, 14, 16]
GRID_C = [0.6, 0.75, 0.9]
GRID_K = [1.5, 2.0, 2.5, 3.0]
GRID_M = [1, 2, 3]
GRID_S = [True, False]
NNULL = 20


# ---------------------------------------------------------------- grid (Part 18)
def stage_grid(years, tf=5):
    out = {}
    for y in years:
        per = DA.PERIOD[y]
        rows = []
        for L in GRID_L:
            for k in GRID_K:
                b, f, o, el = S.panel(y, tf, L, k)
                pool = S.pool_frame(b, f, o, el)
                S.add_deciles(pool)
                for c in GRID_C:
                    for m in GRID_M:
                        for st in GRID_S:
                            sig = P.run_cell(b, f, L, c, k, m, st)[0]
                            t = sig[:, D.S_T].astype(np.int64)
                            wv = sig[:, D.S_WAVE]
                            for code, w in (("G", 1), ("I", 2)):
                                ii = t[el[t] & (wv == w)]
                                ev = pool[pool.i.isin(ii)].copy()
                                ev["xJ30"] = S.matched_excess(ev, pool, "r30", S.JKEYS)
                                pm = S.primary_mask(ev)
                                fr = ev[(ev.role == "front") & ~ev.hindsight]
                                rows.append(dict(L=L, c=c, k=k, m=m, strict=st, code=code,
                                                 n_primary=int(pm.sum()), xJ30_primary=float(ev.xJ30[pm].mean()) if pm.any() else None,
                                                 n_front=int(len(fr)), xJ30_front=float(fr.xJ30.mean()) if len(fr) else None))
                S._cache.clear()
            print(per, "L", L, "done", flush=True)
        out[per] = rows
    S.jdump(dict(tf=tf, grid=out), f"grid_tf{tf}_{'_'.join(map(str, years))}.json")


# ---------------------------------------------------------------- lifecycle geometry helpers
def lifecycle_levels(cell, b, el, which="front_clean"):
    """One row per lifecycle that reached wave >= 1, with levels and times (prices, not logs)."""
    sig, lcs, waves, fails = cell
    rows = []
    lh = b.lh.values
    grp_last = None
    for j in range(len(lcs)):
        mw = lcs[j, D.L_MAXW]
        if np.isnan(mw) or mw < 1:
            continue
        box0 = int(lcs[j, D.L_BOX0])
        role, money, hind = b.role.values[box0], b.money.values[box0], b.hindsight.values[box0]
        if role != "front" or (hind is True or hind == 1):
            continue
        if which == "primary" and money != "ATM":
            continue
        r = dict(lc=j, i0=box0, start=int(lcs[j, D.L_START]), end=int(lcs[j, D.L_END]), maxwave=int(mw),
                 reason=int(lcs[j, D.L_REASON]), P0=np.exp(lcs[j, D.L_P0]), B0=np.exp(lcs[j, D.L_BL]),
                 right=int(b.right.values[box0]), money=money, dte=b.dte.values[box0], expiry=b.expiry.values[box0],
                 date=b.date.values[box0], sid=int(b.sid.values[box0]))
        for w in range(min(int(mw), 4)):
            r[f"R{w + 1}"] = np.exp(waves[j, w, D.W_PEAK]) if not np.isnan(waves[j, w, D.W_PEAK]) else np.nan
            r[f"R{w + 1}i"] = waves[j, w, D.W_PEAKI]
            r[f"B{w + 1}"] = np.exp(waves[j, w, D.W_BLOW]) if not np.isnan(waves[j, w, D.W_BLOW]) else np.nan
            r[f"B{w + 1}i"] = waves[j, w, D.W_BLOWI]
            r[f"acc{w + 1}"] = waves[j, w, D.W_ACC]
            r[f"bo{w + 1}"] = waves[j, w, D.W_BO]
        rows.append(r)
    x = pd.DataFrame(rows)
    if len(x) == 0:
        return x
    # target peak for a wave whose peak was never confirmed: the max high from its breakout to the session end
    sess_end = pd.Series(np.arange(len(b))).groupby(
        b.sid.values.astype(np.int64) * 100000 + (b.date - pd.Timestamp("2020-01-01")).dt.days.values).transform("max").values
    for w in (1, 2, 3):
        if f"acc{w}" not in x:
            continue
        tgt = []
        for r in x.itertuples():
            acc = getattr(r, f"acc{w}")
            pk = getattr(r, f"R{w}")
            if np.isnan(acc):
                tgt.append(np.nan)
            elif not np.isnan(pk):
                tgt.append(pk)
            else:
                bo = int(getattr(r, f"bo{w}"))
                tgt.append(np.exp(lh[bo:sess_end[bo] + 1].max()))
        x[f"T{w}"] = tgt
    return x


def ratios(lv):
    """Increment / ratio statistics (Parts 5-6) from a lifecycle level table."""
    out = {}
    if len(lv) == 0 or "R2" not in lv:
        return out
    z = lv.dropna(subset=["R1", "R2"])
    d1, d2 = z.R1 - z.P0, z.R2 - z.R1
    g1, g2 = np.log(z.R1 / z.P0), np.log(z.R2 / z.R1)
    E1, E2 = np.log(z.R1 / z.B0), np.log(z.R2 / z.B1)
    D1 = np.log(z.R1 / z.B1)
    out["n_R2"] = int(len(z))
    for name, v in (("d2_over_d1", d2 / d1), ("g2_over_g1", g2 / g1), ("E2_over_E1", E2 / E1), ("retr1_over_E1", D1 / E1),
                    ("g1", g1), ("g2", g2), ("E1", E1), ("E2", E2)):
        v = v.replace([np.inf, -np.inf], np.nan).dropna()
        out[name] = dict(median=float(v.median()) if len(v) else None, mean=float(v.mean()) if len(v) else None,
                         q25=float(v.quantile(.25)) if len(v) else None, q75=float(v.quantile(.75)) if len(v) else None,
                         share_gt1=float((v > 1).mean()) if len(v) else None, n=int(len(v)))
    if len(z) >= 5:
        # E2 = f(E1): slope of log-amplitudes and of raw amplitudes
        out["fit_E2_on_E1"] = dict(slope=float(np.polyfit(E1, E2, 1)[0]), corr=float(np.corrcoef(E1, E2)[0, 1]))
    if "R3" in lv:
        z3 = lv.dropna(subset=["R1", "R2", "R3"])
        if len(z3):
            out["n_R3"] = int(len(z3))
            out["d3_over_d2"] = float(((z3.R3 - z3.R2) / (z3.R2 - z3.R1)).median())
            out["g3_over_g2"] = float((np.log(z3.R3 / z3.R2) / np.log(z3.R2 / z3.R1)).median())
    return out


MODELS = ["linear", "log", "exponential", "power", "geometric"]


def fit_predict(levels, n_pred):
    """Fit the §9 models to P(n), n = 0..len-1, predict at n_pred. Returns dict model -> (pred, fitted array)."""
    y = np.asarray(levels, float)
    n = np.arange(len(y), dtype=float)
    out = {}
    ly = np.log(y)
    X = np.c_[np.ones_like(n), n]
    a, bb = np.linalg.lstsq(X, y, rcond=None)[0]
    out["linear"] = (a + bb * n_pred, a + bb * n)
    Xl = np.c_[np.ones_like(n), np.log(n + 1)]
    a, bb = np.linalg.lstsq(Xl, y, rcond=None)[0]
    out["log"] = (a + bb * np.log(n_pred + 1), a + bb * np.log(n + 1))
    a, bb = np.linalg.lstsq(X, ly, rcond=None)[0]
    out["exponential"] = (np.exp(a + bb * n_pred), np.exp(a + bb * n))
    a, bb = np.linalg.lstsq(Xl, ly, rcond=None)[0]
    out["power"] = (np.exp(a + bb * np.log(n_pred + 1)), np.exp(a + bb * np.log(n + 1)))
    r = np.sum(n * (ly - ly[0])) / max(np.sum(n * n), 1e-12)
    out["geometric"] = (y[0] * np.exp(r * n_pred), y[0] * np.exp(r * n))
    return out


def model_study(lv, dev_median_g=None):
    """In-sample fits on lifecycles with >= 4 levels and out-of-sample next-peak prediction (H3)."""
    res = {}
    # out of sample at the E2 acceptance: levels P0, R1 known; target T2
    z = lv.dropna(subset=["R1", "T2"]) if "T2" in lv else lv.iloc[0:0]
    err = {k: [] for k in ["linear", "log", "power", "geometric", "no_gain", "dev_median"]}
    for r in z.itertuples():
        P0, R1, T = r.P0, r.R1, r.T2
        pr = {"linear": R1 + (R1 - P0), "geometric": R1 * R1 / P0, "log": P0 + (R1 - P0) / np.log(2) * np.log(3),
              "power": P0 * 3 ** (np.log(R1 / P0) / np.log(2)), "no_gain": R1}
        # the price at the signal is at least the breakout level; "no gain" = the level itself
        if dev_median_g is not None:
            pr["dev_median"] = R1 * np.exp(dev_median_g)
        for kk, v in pr.items():
            if v > 0:
                err[kk].append(np.log(v / T))
    res["oos_at_E2"] = {k: dict(n=len(v), mae_log=float(np.mean(np.abs(v))) if v else None,
                                bias_log=float(np.mean(v)) if v else None) for k, v in err.items()}
    # out of sample at the E3 acceptance: P0, R1, R2 known, target T3
    z = lv.dropna(subset=["R1", "R2", "T3"]) if "T3" in lv else lv.iloc[0:0]
    err3 = {k: [] for k in MODELS + ["no_gain"]}
    for r in z.itertuples():
        fp = fit_predict([r.P0, r.R1, r.R2], 3)
        for kk in MODELS:
            if fp[kk][0] > 0:
                err3[kk].append(np.log(fp[kk][0] / r.T3))
        err3["no_gain"].append(np.log(r.R2 / r.T3))
    res["oos_at_E3"] = {k: dict(n=len(v), mae_log=float(np.mean(np.abs(v))) if v else None,
                                bias_log=float(np.mean(v)) if v else None) for k, v in err3.items()}
    # in-sample on >= 4 confirmed levels
    z = lv.dropna(subset=["R1", "R2", "R3"]) if "R3" in lv else lv.iloc[0:0]
    stats = {k: dict(r2=[], rmse=[], mae=[], aicc=[], resid=[]) for k in MODELS}
    for r in z.itertuples():
        y = np.array([r.P0, r.R1, r.R2, r.R3])
        fp = fit_predict(y, 4)
        for kk in MODELS:
            fit = fp[kk][1]
            e = y - fit
            rss = float(np.sum(e ** 2))
            npar = 1 if kk == "geometric" else 2
            nn = len(y)
            sst = float(np.sum((y - y.mean()) ** 2))
            stats[kk]["r2"].append(1 - rss / sst if sst > 0 else np.nan)
            stats[kk]["rmse"].append(np.sqrt(rss / nn) / y[0])
            stats[kk]["mae"].append(np.mean(np.abs(e)) / y[0])
            stats[kk]["aicc"].append(nn * np.log(max(rss, 1e-12) / nn) + 2 * npar + 2 * npar * (npar + 1) / max(nn - npar - 1, 1e-9))
            stats[kk]["resid"].append(e / y[0])
    res["in_sample_4_levels"] = {k: dict(n=len(v["r2"]), r2_median=float(np.nanmedian(v["r2"])) if v["r2"] else None,
                                         rmse_rel=float(np.mean(v["rmse"])) if v["rmse"] else None,
                                         mae_rel=float(np.mean(v["mae"])) if v["mae"] else None,
                                         aicc_mean=float(np.mean(v["aicc"])) if v["aicc"] else None,
                                         resid_by_n=[float(x) for x in np.mean(v["resid"], 0)] if v["resid"] else None)
                                 for k, v in stats.items()}
    if len(z):
        best = []
        for r in z.itertuples():
            y = np.array([r.P0, r.R1, r.R2, r.R3])
            fp = fit_predict(y, 4)
            a = {}
            for kk in MODELS:
                rss = float(np.sum((y - fp[kk][1]) ** 2))
                npar = 1 if kk == "geometric" else 2
                a[kk] = 4 * np.log(max(rss, 1e-12) / 4) + 2 * npar + 2 * npar * (npar + 1) / max(4 - npar - 1, 1e-9)
            best.append(min(a, key=a.get))
        res["in_sample_best_aicc_share"] = pd.Series(best).value_counts(normalize=True).to_dict()
    return res


def continuation(lv):
    """P(wave 3 | wave 2), P(wave 2 | wave 1) from a lifecycle level table (H2)."""
    if len(lv) == 0:
        return {}
    w1 = lv.maxwave >= 1
    w2 = lv.maxwave >= 2
    w3 = lv.maxwave >= 3
    return dict(n_w1=int(w1.sum()), n_w2=int(w2.sum()), n_w3=int(w3.sum()),
                p2_given_1=float(w2[w1].mean()), p3_given_2=float(w3[w2].mean()) if w2.any() else None)


def boot_cont(lv, nboot=2000, rng=S.RNG):
    """Week-clustered bootstrap of P(w3 | w2)."""
    z = lv[lv.maxwave >= 2]
    if len(z) < 3:
        return None
    u, inv = np.unique(z.expiry.values, return_inverse=True)
    s = np.bincount(inv, (z.maxwave >= 3).values.astype(float))
    c = np.bincount(inv)
    d = rng.integers(0, len(u), (nboot, len(u)))
    v = s[d].sum(1) / c[d].sum(1)
    return v


def stage_null(years, tf=5):
    """H2 / H3 against shuffled bars (PREREG §10) + frequency and forward excess of I on null paths."""
    prm = S.PRIMARY
    out = {}
    for y in years:
        per = DA.PERIOD[y]
        b, f, o, el = S.panel(y, tf, prm["L"], prm["k"])
        cell = P.run_cell(b, f, prm["L"], prm["c"], prm["k"], prm["m"], prm["strict"])
        real = {}
        for which in ("primary", "front_clean"):
            lv = lifecycle_levels(cell, b, el, which)
            real[which] = dict(cont=continuation(lv), ratios=ratios(lv), boot=boot_cont(lv))
        nulls = {"primary": [], "front_clean": []}
        null_ratios = {"primary": [], "front_clean": []}
        null_I = []
        for rep in range(NNULL):
            nb = P.shuffle_bars(b, seed=1000 + rep)
            nf = P.features(nb, prm["L"], prm["k"], prm["v"])
            nel = P.eligible(nb, nf, prm["L"])
            ncell = P.run_cell(nb, nf, prm["L"], prm["c"], prm["k"], prm["m"], prm["strict"])
            for which in ("primary", "front_clean"):
                lv = lifecycle_levels(ncell, nb, nel, which)
                nulls[which].append(continuation(lv))
                null_ratios[which].append(ratios(lv))
            # forward excess of I on null paths (null has no serial structure: expected ~0)
            no = P.outcomes(nb)
            pool = S.pool_frame(nb, nf, no, nel)
            S.add_deciles(pool)
            t = ncell[0][:, D.S_T].astype(np.int64)
            ii = t[nel[t] & (ncell[0][:, D.S_WAVE] == 2)]
            ev = pool[pool.i.isin(ii)].copy()
            ev["xJ30"] = S.matched_excess(ev, pool, "r30", S.JKEYS)
            pm = S.primary_mask(ev)
            null_I.append(dict(n=int(pm.sum()), xJ30=float(ev.xJ30[pm].mean()) if pm.any() else None,
                               n_front=int(((ev.role == "front") & ~ev.hindsight).sum()),
                               xJ30_front=float(ev.xJ30[(ev.role == "front") & ~ev.hindsight].mean())))
            print(per, "null rep", rep, flush=True)
        res = {}
        for which in ("primary", "front_clean"):
            rc = real[which]["cont"]
            nc = pd.DataFrame(nulls[which])
            bt = real[which]["boot"]
            p3n = nc.p3_given_2.mean() if "p3_given_2" in nc else np.nan
            diff = None
            if bt is not None and not np.isnan(p3n):
                # null uncertainty: resample the replica means
                dn = bt - np.random.default_rng(1).choice(nc.p3_given_2.dropna().values, len(bt))
                diff = dict(mean=float(rc["p3_given_2"] - p3n), lo=float(np.percentile(dn, 2.5)), hi=float(np.percentile(dn, 97.5)))
            nr = {}
            for key in ("d2_over_d1", "g2_over_g1", "E2_over_E1", "retr1_over_E1", "g1", "g2"):
                vals = [r[key]["median"] for r in null_ratios[which] if key in r and r[key]["median"] is not None]
                if vals:
                    nr[key] = dict(null_median_mean=float(np.mean(vals)), null_lo=float(np.percentile(vals, 2.5)),
                                   null_hi=float(np.percentile(vals, 97.5)))
            res[which] = dict(real=rc, null_mean={k: float(nc[k].mean()) for k in nc.columns},
                              p3_given_2_diff=diff, real_ratios=real[which]["ratios"], null_ratios=nr)
        res["null_I_forward"] = null_I
        out[per] = res
    S.jdump(dict(tf=tf, nnull=NNULL, results=out), f"null_tf{tf}_{'_'.join(map(str, years))}.json")


# ---------------------------------------------------------------- geometry (Parts 3-6, H3)
def stage_geometry(years, tf=5, dev_g=None):
    prm = S.PRIMARY
    out = {}
    for y in years:
        per = DA.PERIOD[y]
        b, f, o, el = S.panel(y, tf, prm["L"], prm["k"])
        cell = P.run_cell(b, f, prm["L"], prm["c"], prm["k"], prm["m"], prm["strict"])
        res = {}
        for which in ("primary", "front_clean"):
            lv = lifecycle_levels(cell, b, el, which)
            if len(lv) == 0:
                continue
            g2 = np.log(lv.R2 / lv.R1).dropna() if "R2" in lv else pd.Series(dtype=float)
            res[which] = dict(n_lifecycles=int(len(lv)), ratios=ratios(lv), models=model_study(lv, dev_g),
                              median_g2=float(g2.median()) if len(g2) else None,
                              by_dte={k: ratios(g) for k, g in lv.groupby(S.dte_bucket(lv.dte))},
                              by_right={("CE" if k == 0 else "PE"): ratios(g) for k, g in lv.groupby("right")})
            lv.to_parquet(S.OUT / f"lifecycles_tf{tf}_{y}_{which}.parquet")
        out[per] = res
    S.jdump(dict(tf=tf, results=out), f"geometry_tf{tf}_{'_'.join(map(str, years))}.json")


# ---------------------------------------------------------------- Black-76 (Parts 8, 9)
def b76(F, K, T, sig, right):
    T = np.maximum(T, 1 / (365 * 24 * 60))
    sd = sig * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sd * sd) / sd
    d2 = d1 - sd
    df = np.exp(-DA.R * T)
    call = df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    put = df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))
    return np.where(right == 0, call, put)


def implied_vol(p, F, K, T, right):
    lo = np.full(np.shape(p), 0.005)
    hi = np.full(np.shape(p), 4.0)
    for _ in range(60):
        mid = (lo + hi) / 2
        v = b76(F, K, T, mid, right)
        hi = np.where(v > p, mid, hi)
        lo = np.where(v > p, lo, mid)
    iv = (lo + hi) / 2
    intrinsic = np.where(right == 0, np.maximum(F - K, 0), np.maximum(K - F, 0)) * np.exp(-DA.R * np.maximum(T, 0))
    return np.where((p > intrinsic + 0.01) & (iv < 3.99), iv, np.nan)


def greeks(F, K, T, sig, right):
    T = np.maximum(T, 1 / (365 * 24 * 60))
    sd = sig * np.sqrt(T)
    d1 = (np.log(F / K) + 0.5 * sd * sd) / sd
    df = np.exp(-DA.R * T)
    delta = np.where(right == 0, df * norm.cdf(d1), -df * norm.cdf(-d1))
    h = 1 / 365
    theta = (b76(F, K, T - h, sig, right) - b76(F, K, T, sig, right))  # per calendar day
    return delta, theta


def tyears(dt, expiry):
    return ((pd.to_datetime(expiry) + pd.Timedelta("15h30min")) - pd.to_datetime(dt)).dt.total_seconds().values / (365 * 86400)


def stage_decomp(years, tf=5):
    """Each expansion leg (base low -> peak, closes) split into delta-linear, convexity, theta, vega, residual."""
    prm = S.PRIMARY
    out = {}
    for y in years:
        per = DA.PERIOD[y]
        b, f, o, el = S.panel(y, tf, prm["L"], prm["k"])
        cell = P.run_cell(b, f, prm["L"], prm["c"], prm["k"], prm["m"], prm["strict"])
        lv = lifecycle_levels(cell, b, el, "front_clean")
        legs = []
        for r in lv.itertuples():
            box = np.arange(r.start, r.i0)
            i_start = int(box[np.argmin(b.ll.values[box])]) if len(box) else r.i0
            prev = i_start
            for w in range(1, min(r.maxwave, 3) + 1):
                pk = getattr(r, f"R{w}i", np.nan)
                if np.isnan(pk):
                    break
                legs.append((r.lc, w, prev, int(pk), r.money, r.right))
                bl = getattr(r, f"B{w}i", np.nan)
                if np.isnan(bl):
                    break
                prev = int(bl)
        if not legs:
            continue
        L_ = pd.DataFrame(legs, columns=["lc", "wave", "i0", "i1", "money", "right"])
        s0, s1 = b.iloc[L_.i0.values], b.iloc[L_.i1.values]
        K = s0.strike.values.astype(float)
        rt = L_.right.values
        F0, F1 = s0.F.values, s1.F.values
        T0, T1 = tyears(s0.dt.reset_index(drop=True), s0.expiry.reset_index(drop=True)), \
            tyears(s1.dt.reset_index(drop=True), s1.expiry.reset_index(drop=True))
        p0, p1 = s0.close.values, s1.close.values
        iv0, iv1 = implied_vol(p0, F0, K, T0, rt), implied_vol(p1, F1, K, T1, rt)
        m0 = b76(F0, K, T0, iv0, rt)
        d0, _ = greeks(F0, K, T0, iv0, rt)
        m_F = b76(F1, K, T0, iv0, rt)  # spot move only
        m_FT = b76(F1, K, T1, iv0, rt)  # + time
        m_all = b76(F1, K, T1, iv1, rt)  # + IV
        dP = p1 - p0
        comp = pd.DataFrame({
            "dP": dP, "delta_lin": d0 * (F1 - F0), "convexity": (m_F - m0) - d0 * (F1 - F0),
            "theta": m_FT - m_F, "vega": m_all - m_FT, "resid": dP - (m_all - m0),
            "dlnF": np.log(F1 / F0), "iv0": iv0, "iv1": iv1, "wave": L_.wave.values, "money": L_.money.values,
            "right": rt, "minutes": (L_.i1.values - L_.i0.values) * tf})
        comp = comp.dropna(subset=["iv0", "iv1", "dP"])
        comp = comp[comp.dP > 0]
        tot = comp.dP.sum()
        share = {c: float(comp[c].sum() / tot) for c in ("delta_lin", "convexity", "theta", "vega", "resid")}
        per_leg = {c: float((comp[c] / comp.dP).median()) for c in ("delta_lin", "convexity", "theta", "vega", "resid")}
        # direction check: does NIFTY move with the option wave (CE up, PE down)?
        sgn = np.where(comp.right == 0, 1, -1) * comp.dlnF
        out[per] = dict(n_legs=int(len(comp)), share_of_total_gain=share, median_share_per_leg=per_leg,
                        share_nifty_moved_with_wave=float((sgn > 0).mean()),
                        median_nifty_move_pct=float(np.median(np.abs(comp.dlnF)) * 100),
                        median_iv_change_pts=float(np.median(comp.iv1 - comp.iv0) * 100),
                        by_wave={int(w): {c: float(g[c].sum() / g.dP.sum()) for c in ("delta_lin", "convexity", "theta", "vega", "resid")}
                                 for w, g in comp.groupby("wave")})
        comp.to_parquet(S.OUT / f"decomp_tf{tf}_{y}.parquet")
    S.jdump(dict(tf=tf, results=out), f"decomp_tf{tf}_{'_'.join(map(str, years))}.json")


def stage_dte(years, tf=5, h=15):
    """Part 9: option log return on forward log return (+ quadratic) over non-overlapping h-minute windows."""
    out = {}
    for y in years:
        per = DA.PERIOD[y]
        b = P.build_bars(y, tf)
        b = b[b.money.notna() & ~b.hindsight.astype(bool)].copy()
        step = h // tf
        b = b[(b.bis % step) == 0]
        b = b.sort_values(["sid", "dt"])
        g = b.groupby(["sid", "date"])
        b["y"] = g.lc.shift(-1) - b.lc
        b["x"] = np.log(g.F.shift(-1) / b.F)
        b = b.dropna(subset=["x", "y"])
        b = b[b.close >= 5]
        b["dteb"] = S.dte_bucket(b.dte)
        res = {}
        for (db, money, right), z in b.groupby(["dteb", "money", "right"]):
            if len(z) < 50:
                continue
            X = np.c_[np.ones(len(z)), z.x, z.x ** 2]
            coef, *_ = np.linalg.lstsq(X, z.y.values, rcond=None)
            pred = X @ coef
            r2 = 1 - np.sum((z.y - pred) ** 2) / np.sum((z.y - z.y.mean()) ** 2)
            # the option move for a +/-0.25 % NIFTY move in the option's direction
            sgn = 1 if right == 0 else -1
            mv = 0.0025 * sgn
            res[f"{db}|{money}|{'CE' if right == 0 else 'PE'}"] = dict(
                n=int(len(z)), elasticity=float(coef[1]), convexity=float(coef[2]), intercept=float(coef[0]), r2=float(r2),
                opt_move_for_025pct_up=float(coef[0] + coef[1] * mv + coef[2] * mv * mv),
                opt_move_for_025pct_down=float(coef[0] - coef[1] * mv + coef[2] * mv * mv))
        out[per] = res
    S.jdump(dict(tf=tf, window_min=h, results=out), f"dte_tf{tf}_{'_'.join(map(str, years))}.json")


# ---------------------------------------------------------------- volume (Part 7)
def stage_volume(years, tf=5):
    prm = S.PRIMARY
    out = {}
    for y in years:
        per = DA.PERIOD[y]
        ev, pool, cell, (b, f, o, el) = S.events(y, tf, prm, codes=("C", "F", "G", "I"))
        res = {}
        vr = f.vr.values
        for code in ("G", "I"):
            e = ev[(ev.code == code) & (ev.role == "front") & ~ev.hindsight.astype(bool)]
            prof = {}
            for off in range(-10, 6):
                idx = e.bo.values.astype(int) + off
                ok = (idx >= 0) & (idx < len(b))
                same = ok & (b.date.values[np.clip(idx, 0, len(b) - 1)] == b.date.values[e.bo.values.astype(int)])
                prof[off] = float(np.nanmedian(vr[idx[same]])) if same.any() else None
            res[f"vr_profile_around_breakout_{code}"] = prof
            hi = e.vr_bo >= prm["v"]
            res[f"{code}_split_by_breakout_volume"] = dict(
                high=S.cluster_boot(e.xJ30[hi].values, e.week[hi].values),
                low=S.cluster_boot(e.xJ30[~hi].values, e.week[~hi].values))
        # lead / lag: corr(VR_t, |r_{t+j}|) pooled over primary eligible bars (1-bar returns)
        pm = (b.role.values == "front") & (b.money.values == "ATM") & ~b.hindsight.astype(bool).values
        r1 = np.r_[np.nan, np.diff(b.lc.values)]
        r1[b.newsess.values] = np.nan
        ar = np.abs(r1)
        lv = np.log(np.where(vr > 0, vr, np.nan))
        cc = {}
        for j in range(-3, 4):
            a = lv[pm]
            idx = np.flatnonzero(pm) + j
            ok = (idx >= 0) & (idx < len(b))
            bb = np.full(len(a), np.nan)
            bb[ok] = ar[idx[ok]]
            m = ~np.isnan(a) & ~np.isnan(bb)
            cc[j] = float(np.corrcoef(a[m], bb[m])[0, 1])
        res["corr_logVR_t_absret_t_plus_j"] = cc
        # shuffled volume: C and F signals with volume permuted inside each contract-session
        real = {c: float(ev[(ev.code == c) & S.primary_mask(ev)].xJ30.mean()) for c in ("C", "F")}
        shuf = {"C": [], "F": []}
        rng = np.random.default_rng(7)
        grp = b.sid.values.astype(np.int64) * 100000 + (b.date - pd.Timestamp("2020-01-01")).dt.days.values
        for rep in range(10):
            bb = b.copy()
            v = bb.volume.values.copy()
            order = np.lexsort((rng.random(len(bb)), grp))
            # permute within group: sort by group then random key, then map back group-wise
            starts = np.r_[0, np.flatnonzero(np.diff(grp)) + 1]
            ends = np.r_[starts[1:], len(grp)]
            newv = v.copy()
            for s0, e0 in zip(starts, ends):
                newv[s0:e0] = rng.permutation(v[s0:e0])
            bb["volume"] = newv
            ff = P.features(bb, prm["L"], prm["k"], prm["v"])
            sg, _ = P.control_signals(bb, ff, el, prm["L"], prm["c"], prm["k"], prm["m"], prm["strict"], prm["v"],
                                      cell=cell)
            for c in ("C", "F"):
                e2 = pool[pool.i.isin(sg[c])].copy()
                e2["x"] = S.matched_excess(e2, pool, "r30", S.JKEYS)
                shuf[c].append(float(e2.x[S.primary_mask(e2)].mean()))
        res["shuffled_volume"] = {c: dict(real=real[c], shuffled_mean=float(np.mean(shuf[c])),
                                          shuffled_range=[float(min(shuf[c])), float(max(shuf[c]))]) for c in ("C", "F")}
        out[per] = res
    S.jdump(dict(tf=tf, results=out), f"volume_tf{tf}_{'_'.join(map(str, years))}.json")


# ---------------------------------------------------------------- regimes, splits, costs, reversal (10, 11, 15, 17)
def lot_size(expiry):
    e = pd.Timestamp(expiry)
    return 50 if e <= pd.Timestamp("2024-04-25") else 25 if e <= pd.Timestamp("2024-12-26") else 75 if e <= pd.Timestamp("2025-12-30") else 65


def net_log(p0, p1, q, slip):
    buy_turn = p0 * (1 + slip) * q
    sell_turn = p1 * (1 - slip) * q
    exch = 0.0003503
    buy_ch = 20 + buy_turn * (exch + 1e-6 + 0.00003) + 0.18 * (20 + buy_turn * (exch + 1e-6))
    sell_ch = 20 + sell_turn * (0.001 + exch + 1e-6) + 0.18 * (20 + sell_turn * (exch + 1e-6))
    return np.log(np.maximum(sell_turn - sell_ch, 1e-9) / (buy_turn + buy_ch)), (sell_turn - sell_ch) - (buy_turn + buy_ch)


def stage_splits(years, tf=5):
    prm = S.PRIMARY
    ref = DA.spot_reference()
    sp5 = DA.spot5().set_index("dt").close
    out = {}
    for y in years:
        per = DA.PERIOD[y]
        ev, pool, cell, (b, f, o, el) = S.events(y, tf, prm, codes=("G", "I", "I3"))
        ev = ev[(ev.role == "front") & ~ev.hindsight.astype(bool)].copy()
        ev["dts"] = pd.to_datetime(ev.dt)
        # regimes
        day = ref.reindex(ev.date.values)
        ev["day_ret"] = (day.s_close.values / day.s_open.values - 1) * 100
        ev["regime_expost"] = np.select([ev.day_ret > 0.4, ev.day_ret < -0.4], ["bull", "bear"], "flat")
        sig_end = ev.dts + pd.Timedelta(minutes=tf)
        last5 = (sig_end - pd.Timedelta(minutes=5)).dt.floor("5min")
        spot_now = sp5.reindex(last5.values).values
        ev["ret_open_to_signal"] = (spot_now / day.s_open.values - 1) * 100
        ev["regime_causal"] = np.select([ev.ret_open_to_signal > 0.25, ev.ret_open_to_signal < -0.25], ["up_so_far", "down_so_far"], "flat_so_far")
        ev["vol_causal"] = np.where(day.prev_range_pct.values > day.prev_range_med20.values, "high_prev_range", "low_prev_range")
        rng_t = ref.loc[(ref.index >= ev.date.min()) & (ref.index <= ev.date.max()), "range_pct"]
        q = rng_t.quantile([1 / 3, 2 / 3]).values
        ev["vol_expost"] = np.select([day.range_pct.values <= q[0], day.range_pct.values >= q[1]], ["low", "high"], "mid")
        ev["expiry_class"] = np.select([ev.dte == 0, ev.dte == 1], ["expiry_day", "pre_expiry"], "normal")
        ev["side"] = np.where(ev.right == 0, "CE", "PE")
        # does the option lifecycle foresee NIFTY? forward move of F in the option's direction over 30 minutes
        Fv = b.F.values
        j = ev.i.values.astype(int)
        j6 = j + 30 // tf
        ok = (j6 < len(b)) & (b.date.values[np.clip(j6, 0, len(b) - 1)] == b.date.values[j])
        fwdF = np.full(len(ev), np.nan)
        fwdF[ok] = np.log(Fv[j6[ok]] / Fv[j[ok]])
        ev["nifty_fwd30_dir"] = np.where(ev.right == 0, 1, -1) * fwdF
        res = {}
        for code in ("G", "I", "I3"):
            e = ev[ev.code == code]
            r = {}
            for col in ("side", "money", "expiry_class", "regime_expost", "regime_causal", "vol_causal", "vol_expost"):
                r[col] = {str(k): dict(n=int(len(g)), xJ30=S.cluster_boot(g.xJ30.values, g.week.values),
                                       raw30=float(g.r30.mean()))
                          for k, g in e.groupby(col)}
            r["dte"] = {str(k): dict(n=int(len(g)), xJ30=S.cluster_boot(g.xJ30.values, g.week.values))
                        for k, g in e.groupby(S.dte_bucket(e.dte))}
            r["nifty_fwd30_in_option_direction_bp"] = S.cluster_boot(e.nifty_fwd30_dir.values * 1e4, e.week.values)
            # costs (Part 15), primary contracts, 30-minute exit, trades are 1 lot
            pm = e[e.money == "ATM"]
            cst = {}
            for slip in (0.0025, 0.005, 0.01):
                for entry in ("close", "next_open"):
                    rr = pm.r30 if entry == "close" else pm.rno30
                    p0 = pm.price.values if entry == "close" else pm.price.values * np.exp(pm.r30.values - pm.rno30.values)
                    p1 = pm.price.values * np.exp(pm.r30.values)
                    q = np.array([lot_size(x) for x in pm.expiry.values])
                    nl, rs = net_log(p0, p1, q, slip)
                    ok = ~np.isnan(nl)
                    wk = pd.Series(rs[ok]).groupby(pm.week.values[ok]).sum()
                    cst[f"slip{slip}_{entry}"] = dict(
                        n=int(ok.sum()), mean_net_log=float(np.nanmean(nl)), mean_rs_per_lot=float(np.nanmean(rs)),
                        t_stat=float(np.nanmean(rs) / (np.nanstd(rs, ddof=1) / np.sqrt(ok.sum()))) if ok.sum() > 2 else None,
                        worst_week_rs=float(wk.min()) if len(wk) else None, positive_weeks=f"{int((wk > 0).sum())}/{len(wk)}",
                        net_excess_log=float(np.nanmean(nl - rr + pm.xJ30)) if entry == "close" else None)
            r["costs_atm_30min"] = cst
            # CE/PE reversal: same-strike opposite option's 30-minute return at the same bar
            opp = pool.set_index(["expiry", "right", "date", "i"])
            res[code] = r
        # reversal via bar keys
        bk = pd.DataFrame({"expiry": b.expiry.values, "strike": b.strike.values, "right": b.right.values, "dt": b.dt.values,
                           "i": np.arange(len(b))})
        o30 = o["r30"].values
        e = ev[(ev.code == "I") & (ev.money == "ATM")].copy()
        e2 = e[["expiry", "strike", "right", "dt"]].copy()
        e2["right"] = 1 - e2.right
        mm = e2.merge(bk, on=["expiry", "strike", "right", "dt"], how="left")
        e["opp_r30"] = np.where(mm.i.notna(), o30[mm.i.fillna(0).astype(int).values], np.nan)
        res["reversal_opposite_leg_r30"] = S.cluster_boot(e.opp_r30.values, e.week.values)
        # mirror: the same machine on the inverted price (a descending lifecycle); forward excess on the real option
        lh, ll, lc = -b.ll.values, -b.lh.values, -b.lc.values
        sids = b.sid.values
        starts = np.r_[0, np.flatnonzero(np.diff(sids)) + 1]
        ends = np.r_[starts[1:], len(b)]
        atr = D.atr_log(lh, ll, lc, b.filler.values, b.newsess.values, D.NV)
        bis = b.bis.values.astype(np.int64)
        cr = D.comp_ratio(lh, ll, atr, bis, prm["L"])
        mi = []
        for s0, e0 in zip(starts, ends):
            sg = D.lifecycle(lh[s0:e0], ll[s0:e0], lc[s0:e0], cr[s0:e0], atr[s0:e0], bis[s0:e0], b.newsess.values[s0:e0],
                             prm["c"], prm["L"], prm["k"], prm["m"], prm["strict"])[0]
            t = sg[:, D.S_T].astype(np.int64) + s0
            mi += list(t[sg[:, D.S_WAVE] == 2])
        mi = np.array(mi, dtype=np.int64)
        mi = mi[el[mi]] if len(mi) else mi
        me = pool[pool.i.isin(mi)].copy()
        me["xJ30"] = S.matched_excess(me, pool, "r30", S.JKEYS)
        pm = S.primary_mask(me)
        res["mirror_descending_I"] = dict(primary=S.cluster_boot(me.xJ30[pm].values, me.expiry[pm].values),
                                          front=S.cluster_boot(me.xJ30[(me.role == "front") & ~me.hindsight].values,
                                                               me.expiry[(me.role == "front") & ~me.hindsight].values))
        out[per] = res
        ev.to_parquet(S.OUT / f"splits_events_tf{tf}_{y}.parquet")
    S.jdump(dict(tf=tf, results=out), f"splits_tf{tf}_{'_'.join(map(str, years))}.json")


# ---------------------------------------------------------------- event dataset (Part 19) and plot data (Part 20)
REASON = {0: "open", 1: "failed_base", 2: "stalled", 3: "session_end", 4: "failed_e1"}


def stage_dataset(years, tf=5):
    import json
    prm = S.PRIMARY
    rows, plots = [], []
    for y in years:
        ev, pool, cell, (b, f, o, el) = S.events(y, tf, prm, codes=("G", "I", "I3"))
        sig, lcs, waves, fails = cell
        ev = ev[ev.role == "front"].reset_index(drop=True)
        i = ev.i.values.astype(int)
        K = ev.strike.values.astype(float)
        T = tyears(pd.Series(b.dt.values[i]) + pd.Timedelta(minutes=tf), pd.Series(b.expiry.values[i]))
        rt = ev.right.values
        iv = implied_vol(ev.price.values, ev.F.values, K, T, rt)
        dl, th = greeks(ev.F.values, K, T, iv, rt)
        lcid = ev.lc.values.astype(int)
        wv = ev.wave.values.astype(int)

        def amp(j, w, kind):
            if w < 1 or w > D.MAXW:
                return np.nan
            pk = waves[j, w - 1, D.W_PEAK]
            if kind == "exp":
                bl_prev = lcs[j, D.L_BL] if w == 1 else waves[j, w - 2, D.W_BLOW]
                return (np.exp(pk - bl_prev) - 1) * 100
            return (1 - np.exp(waves[j, w - 1, D.W_BLOW] - pk)) * 100

        def dur(j, w):
            return (waves[j, w - 1, D.W_PEAKI] - waves[j, w - 1, D.W_BO]) * tf if 1 <= w <= D.MAXW else np.nan

        Fv = b.F.values
        j30 = i + 30 // tf
        okj = (j30 < len(b)) & (b.date.values[np.clip(j30, 0, len(b) - 1)] == b.date.values[i])
        nm = np.full(len(ev), np.nan)
        nm[okj] = (Fv[j30[okj]] / Fv[i[okj]] - 1) * 100
        st = ev.start.values.astype(int)
        d = pd.DataFrame({
            "period": ev.period.values, "tf_min": tf, "control": ev.code.values,
            "date": pd.to_datetime(ev.date.values).strftime("%Y-%m-%d"),
            "time": (pd.to_datetime(ev.dt.values) + pd.Timedelta(minutes=tf)).strftime("%H:%M"),
            "symbol": "NIFTY", "expiry": pd.to_datetime(ev.expiry.values).strftime("%Y-%m-%d"),
            "CE_PE": np.where(rt == 0, "CE", "PE"), "strike": ev.strike.values.astype(int), "moneyness_0920": ev.money.values,
            "DTE": ev.dte.values.astype(int), "strike_set_hindsight": ev.hindsight.values.astype(bool),
            "spot": ev.F.values.round(2), "option_price": ev.price.values,
            "base_low": ev.base_low.values.round(2), "base_high": ev.base_high.values.round(2),
            "number_of_resistance_tests": ev.retests.values, "higher_low_count": ev.higher_lows.values,
            "volume_ratio": ev.vr.values.round(3), "volume_ratio_breakout_bar": ev.vr_bo.values.round(3),
            "breakout_price": ev.breakout_price.values.round(2), "wave_number": wv,
            "prev_expansion_pct_known": [amp(a, w - 1, "exp") for a, w in zip(lcid, wv)],
            "prev_retracement_pct_known": [amp(a, w - 1, "ret") for a, w in zip(lcid, wv)],
            "nifty_move_since_start_pct_known": (Fv[i] / Fv[st] - 1) * 100,
            "IV": iv, "delta": dl, "theta_per_day": th,
            "OUTCOME_expansion_size_pct": [amp(a, w, "exp") for a, w in zip(lcid, wv)],
            "OUTCOME_retracement_size_pct": [amp(a, w, "ret") for a, w in zip(lcid, wv)],
            "OUTCOME_next_expansion_size_pct": [amp(a, w + 1, "exp") for a, w in zip(lcid, wv)],
            "OUTCOME_expansion_duration_min": [dur(a, w) for a, w in zip(lcid, wv)],
            "OUTCOME_r30_pct": (np.exp(ev.r30.values) - 1) * 100,
            "OUTCOME_excess30_vs_matched_pct": ev.xJ30.values * 100,
            "OUTCOME_MFE30_pct": (np.exp(ev.mfe30.values) - 1) * 100, "OUTCOME_MAE30_pct": (np.exp(ev.mae30.values) - 1) * 100,
            "OUTCOME_MFE_session_pct": (np.exp(ev.mfeeos.values) - 1) * 100,
            "OUTCOME_MAE_session_pct": (np.exp(ev.maeeos.values) - 1) * 100,
            "OUTCOME_NIFTY_move_30m_pct": nm,
            "outcome": np.where(ev.next_wave.values.astype(bool), "next_wave",
                                [REASON.get(int(x), "?") if not np.isnan(x) else "?" for x in ev.lc_reason.values]),
        })
        rows.append(d)
        # plot payload: every I / I3 event on front contracts, strike-set-clean sessions
        sidv, datev = b.sid.values, b.date.values
        for e in ev.itertuples():
            if e.code not in ("I", "I3") or bool(e.hindsight):
                continue
            j, ii = int(e.lc), int(e.i)
            idx = np.flatnonzero((sidv == sidv[ii]) & (datev == datev[ii]))
            s0 = idx[0]
            w = int(e.wave)
            known = [float(np.exp(lcs[j, D.L_P0]))] + [float(np.exp(waves[j, q, D.W_PEAK])) for q in range(w - 1)]
            mw = min(int(lcs[j, D.L_MAXW]), D.MAXW)
            peaks = [(int(waves[j, q, D.W_PEAKI] - s0), float(np.exp(waves[j, q, D.W_PEAK])), int(waves[j, q, D.W_CONF] - s0))
                     for q in range(mw) if not np.isnan(waves[j, q, D.W_PEAK])]
            lows = [(int(waves[j, q, D.W_BLOWI] - s0), float(np.exp(waves[j, q, D.W_BLOW])))
                    for q in range(mw) if not np.isnan(waves[j, q, D.W_BLOW])]
            nn = np.arange(len(known) + 2)
            if len(known) >= 3:
                fits = {k: [float(x) for x in v[0]] for k, v in fit_predict(known, nn).items()}
            else:
                P0, R1 = known
                fits = {"linear": P0 + (R1 - P0) * nn, "geometric": P0 * (R1 / P0) ** nn,
                        "log": P0 + (R1 - P0) / np.log(2) * np.log(nn + 1),
                        "power": P0 * (nn + 1) ** (np.log(R1 / P0) / np.log(2))}
                fits = {k: [float(x) for x in v] for k, v in fits.items()}
            plots.append(dict(
                id=f"{e.period}-{pd.Timestamp(e.date).strftime('%Y%m%d')}-{'CE' if e.right == 0 else 'PE'}{int(e.strike)}-{e.code}-{ii - s0}",
                period=e.period, code=e.code, date=pd.Timestamp(e.date).strftime("%Y-%m-%d"),
                side="CE" if e.right == 0 else "PE", strike=int(e.strike), money=e.money, dte=int(e.dte), wave=w,
                t0=pd.Timestamp(b.dt.values[s0]).strftime("%H:%M"), tf=tf,
                c=[round(float(x), 2) for x in b.close.values[idx]], h=[round(float(x), 2) for x in b.high.values[idx]],
                l=[round(float(x), 2) for x in b.low.values[idx]],
                sig=ii - s0, box=[int(lcs[j, D.L_START] - s0), int(lcs[j, D.L_BOX0] - s0)],
                base=[float(e.base_low), float(e.base_high)], known=known, peaks=peaks, lows=lows, fits=fits,
                r30=None if np.isnan(e.r30) else float(e.r30), x30=None if np.isnan(e.xJ30) else float(e.xJ30),
                nxt=bool(e.next_wave)))
    ds = pd.concat(rows, ignore_index=True)
    tag = "_".join(map(str, years))
    ds.to_csv(S.HERE / f"events_tf{tf}_{tag}.csv", index=False, float_format="%.4f")
    (S.OUT / f"plots_tf{tf}_{tag}.json").write_text(json.dumps(plots, default=lambda x: x.item() if hasattr(x, "item") else str(x)))
    print(len(ds), "rows,", len(plots), "plots")


if __name__ == "__main__":
    st = sys.argv[1]
    yrs = [int(x) for x in sys.argv[2].split(",")]
    tf = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    t0 = time.time()
    {"grid": stage_grid, "null": stage_null, "geometry": stage_geometry, "decomp": stage_decomp, "dte": stage_dte,
     "volume": stage_volume, "splits": stage_splits, "dataset": stage_dataset}[st](yrs, tf)
    print(st, "done", round(time.time() - t0), "s")
