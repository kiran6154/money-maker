"""Bars, features, signals and forward outcomes for one (year, timeframe) - PREREG §2, §5, §6.

`build_bars` is parameter-free except for the timeframe; `signals` runs one parameter cell over the bar table.
The same code runs on real bars and on shuffled null bars (`shuffle_bars`).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numba import njit

import data as DA
import detect as D

HORIZONS = [5, 10, 15, 30, 60]
FIRST_TOD = 9 * 60 + 15
LAST_SIGNAL_END = 15 * 60  # signal bar must close by 15:00


def build_bars(year: int, tf: int) -> pd.DataFrame:
    path = DA.CACHE / f"bars_{year}_{tf}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    raw = DA.load_year(year)
    base = 5 if DA.SOURCES[year][1] == "5minute" else 1
    if tf % base:
        raise ValueError(f"{tf}-minute bars cannot be built from {base}-minute data in {year}")
    cal = DA.expiry_calendar()
    ses = DA.sessions(year, raw, cal)
    ses = ses[ses.available].copy()
    # chosen contracts per session (PREREG §1): moneyness from the 09:20 index reference
    pick = []
    for r in ses.itertuples():
        for right in (0, 1):
            for money in DA.MONEYNESS:
                pick.append((r.date, r.expiry, DA.contract_strike(r.atm, right, money), right, money, r.role, r.dte,
                             r.strike_set_hindsight, r.spot_ref))
    pick = pd.DataFrame(pick, columns=["date", "expiry", "strike", "right", "money", "role", "dte", "hindsight", "spot_ref"])
    keys = pick[["expiry", "strike", "right"]].drop_duplicates()
    # one expiry at a time (memory; same arithmetic as the whole-year version)
    parts = []
    for e, raw_e in raw.groupby("expiry", sort=True):
        sub = raw_e.merge(keys, on=["expiry", "strike", "right"], how="inner")
        if len(sub) == 0:
            continue
        be = DA.resample(sub, tf, base)
        fwd = DA.forward(DA.resample(raw_e[raw_e.strike % DA.GRID == 0], tf, base))
        parts.append(be.merge(fwd, on=["expiry", "dt"], how="left"))
    del raw
    bars = pd.concat(parts, ignore_index=True)
    bars["date"] = bars.dt.dt.normalize()
    bars = bars.merge(pick, on=["date", "expiry", "strike", "right"], how="left")
    bars = bars.sort_values(["expiry", "strike", "right", "dt"]).reset_index(drop=True)
    bars["sid"] = bars.groupby(["expiry", "strike", "right"], sort=False).ngroup().astype(np.int32)
    # memory: keep each contract's chosen sessions plus the two sessions before each (ATR warm-up only)
    sd = bars[["sid", "date"]].drop_duplicates().reset_index(drop=True)
    sd["chosen"] = sd.merge(bars.loc[bars.money.notna(), ["sid", "date"]].drop_duplicates().assign(c=True),
                            on=["sid", "date"], how="left").c.fillna(False).values
    nxt = sd.groupby("sid").chosen.shift(-1, fill_value=False) | sd.groupby("sid").chosen.shift(-2, fill_value=False)
    keep = sd[sd.chosen | nxt][["sid", "date"]]
    bars = bars.merge(keep, on=["sid", "date"], how="inner").sort_values(["sid", "dt"]).reset_index(drop=True)
    bars = bars.drop(columns=["ref_time"], errors="ignore")
    for col in ("money", "role"):
        bars[col] = bars[col].astype("category")
    bars["volume"] = bars.volume.astype(np.float64)
    bars["tod"] = (bars.dt.dt.hour * 60 + bars.dt.dt.minute).astype(np.int16)
    bars["newsess"] = (bars.sid != bars.sid.shift(1)) | (bars.date != bars.date.shift(1))
    bars["bis"] = bars.groupby(["sid", "date"]).cumcount().astype(np.int16)
    for col in ("open", "high", "low", "close"):
        bars["l" + col[0]] = np.log(bars[col].clip(lower=0.05))
    bars["tf"] = tf
    bars["year"] = year
    bars["period"] = DA.PERIOD[year]
    bars.to_parquet(path)
    return bars


def shuffle_bars(bars: pd.DataFrame, seed: int) -> pd.DataFrame:
    """Null path (PREREG §10): inside each contract-session, bars 2..n are permuted as units of
    (open, high, low, close) offsets from the previous close, volume and filler flag; prices are re-chained."""
    rng = np.random.default_rng(seed)
    b = bars.copy()
    prev = b.lc.shift(1)
    prev[b.newsess.values] = np.nan
    off = np.c_[b.lo - prev, b.lh - prev, b.ll - prev, b.lc - prev]
    grp = (b.sid.astype(np.int64) * 100000 + (b.date - pd.Timestamp("2020-01-01")).dt.days).values
    idx = np.arange(len(b))
    starts = np.r_[0, np.flatnonzero(np.diff(grp)) + 1]
    ends = np.r_[starts[1:], len(b)]
    perm = idx.copy()
    for s, e in zip(starts, ends):
        if e - s > 2:
            perm[s + 1:e] = rng.permutation(idx[s + 1:e])
    off2 = off[perm]
    vol = b.volume.values[perm]
    fil = b.filler.values[perm]
    lc = b.lc.values.copy()
    lo, lh, ll = b.lo.values.copy(), b.lh.values.copy(), b.ll.values.copy()
    for s, e in zip(starts, ends):
        c = lc[s]
        for i in range(s + 1, e):
            lo[i], lh[i], ll[i] = c + off2[i, 0], c + off2[i, 1], c + off2[i, 2]
            c = c + off2[i, 3]
            lc[i] = c
    b["lo"], b["lh"], b["ll"], b["lc"] = lo, lh, ll, lc
    b["volume"], b["filler"] = vol, fil
    b["open"], b["high"], b["low"], b["close"] = np.exp(lo), np.exp(lh), np.exp(ll), np.exp(lc)
    return b


@njit(cache=True)
def _fwd(lo, lh, ll, lc, send, hb):
    """Forward log return, MFE, MAE over hb bars after t (entry at close t); send[t] = last index of t's session."""
    n = lc.shape[0]
    ret = np.full(n, np.nan)
    mfe = np.full(n, np.nan)
    mae = np.full(n, np.nan)
    retno = np.full(n, np.nan)  # entry at the next bar's open
    for t in range(n):
        e = t + hb if hb > 0 else send[t]
        if e > send[t] or e <= t:
            continue
        hi = -1e18
        lo_ = 1e18
        for j in range(t + 1, e + 1):
            if lh[j] > hi:
                hi = lh[j]
            if ll[j] < lo_:
                lo_ = ll[j]
        ret[t] = lc[e] - lc[t]
        mfe[t] = hi - lc[t]
        mae[t] = lo_ - lc[t]
        retno[t] = lc[e] - lo[t + 1]
    return ret, mfe, mae, retno


@njit(cache=True)
def _vr(vol, filler, newsess, date_id, bis, nwin):
    """VR = vol / median(previous nwin non-filler volumes) and a time-of-day VR against the same bar-of-day in the
    previous 5 sessions of the contract."""
    n = vol.shape[0]
    vr = np.full(n, np.nan)
    vrt = np.full(n, np.nan)
    buf = np.zeros(nwin)
    cnt = 0
    pos = 0
    for t in range(n):
        if t > 0 and newsess[t] and date_id[t] < date_id[t - 1]:
            cnt = 0  # new contract
        if cnt >= nwin // 2:
            med = np.median(buf[:min(cnt, nwin)])
            if med > 0:
                vr[t] = vol[t] / med
        if not filler[t]:
            buf[pos] = vol[t]
            pos = (pos + 1) % nwin
            cnt += 1
    return vr, vrt


@njit(cache=True)
def _roll(lh, lc, filler, newsess, L):
    n = lh.shape[0]
    prevmax = np.full(n, np.nan)
    trail = np.full(n, np.nan)
    fshare = np.full(n, np.nan)
    s0 = 0
    for t in range(n):
        if newsess[t]:
            s0 = t
        if t - s0 >= L:
            m = -1e18
            for j in range(t - L, t):
                if lh[j] > m:
                    m = lh[j]
            prevmax[t] = m
            trail[t] = lc[t] - lc[t - L]
        a = max(s0, t - L)
        f = 0
        for j in range(a, t + 1):
            f += filler[j]
        fshare[t] = f / (t - a + 1)
    return prevmax, trail, fshare


def features(bars: pd.DataFrame, L: int, k: float, v: float) -> pd.DataFrame:
    """Per-bar features used by the controls and the outcome table (parameter-dependent ones take L, k)."""
    b = bars
    lo, lh, ll, lc = (b[c].values.astype(np.float64) for c in ("lo", "lh", "ll", "lc"))
    newsess = b.newsess.values
    bis = b.bis.values.astype(np.int64)
    filler = b.filler.values
    atr = D.atr_log(lh, ll, lc, filler, newsess, D.NV)
    cr = D.comp_ratio(lh, ll, atr, bis, L)
    out = pd.DataFrame(index=b.index)
    out["atr"] = atr
    out["cr"] = cr
    # Donchian breakout (control D): close > max high of previous L bars, all today
    prevmax, trail, fshare = _roll(lh, lc, filler, newsess, L)
    out["don"] = lc > prevmax
    out["swl"] = D.swing_lows(lh, ll, atr, newsess, k)
    date_id = (b.date - pd.Timestamp("2020-01-01")).dt.days.values.astype(np.int64)
    vr, _ = _vr(b.volume.values.astype(np.float64), filler, newsess, date_id, bis, 20)
    out["vr"] = vr
    # time-of-day VR: volume / median volume of the same bar-of-day in the previous 5 sessions of this contract
    v = pd.Series(np.where(filler, np.nan, b.volume.values.astype(float)), index=b.index)
    g = v.groupby([b.sid.values, b.bis.values])
    lag = np.column_stack([g.shift(i).values for i in range(1, 6)])
    with np.errstate(all="ignore"):
        cnt = (~np.isnan(lag)).sum(1)
        med = np.where(cnt >= 3, np.nanmedian(np.where(cnt[:, None] > 0, lag, 0.0), axis=1), np.nan)
        out["vr_tod"] = np.where(med > 0, b.volume.values / med, np.nan)
    out["trail"] = trail  # trailing L-bar log return, same session
    out["fill_share"] = fshare  # filler share over [t-L, t], same session
    return out


def outcomes(bars: pd.DataFrame) -> pd.DataFrame:
    b = bars
    lo, lh, ll, lc = (b[c].values.astype(np.float64) for c in ("lo", "lh", "ll", "lc"))
    grp = b.sid.values.astype(np.int64) * 100000 + (b.date - pd.Timestamp("2020-01-01")).dt.days.values
    last = pd.Series(np.arange(len(b))).groupby(grp).transform("max").values.astype(np.int64)
    tf = int(b.tf.iloc[0])
    out = pd.DataFrame(index=b.index)
    for h in HORIZONS + ["eos"]:
        if h == "eos":
            hb = 0
        else:
            if h % tf:
                continue
            hb = h // tf
        r, mf, ma, rno = _fwd(lo, lh, ll, lc, last, hb)
        out[f"r{h}"], out[f"mfe{h}"], out[f"mae{h}"], out[f"rno{h}"] = r, mf, ma, rno
    return out


def eligible(bars: pd.DataFrame, feat: pd.DataFrame, L: int) -> np.ndarray:
    tf = int(bars.tf.iloc[0])
    end = bars.tod.values + tf
    return ((bars.bis.values > 0) & (end <= LAST_SIGNAL_END) & bars.money.notna().values
            & (feat.fill_share.values <= 0.10) & (~bars.filler.values) & (bars.close.values >= 5)
            & ~np.isnan(feat.atr.values))


def run_cell(bars: pd.DataFrame, feat: pd.DataFrame, L: int, c: float, k: float, m: int, strict: bool):
    """Lifecycle detector over every series. Returns (signals, lifecycles, waves, fails) with global bar indices."""
    lh, ll, lc = (bars[x].values.astype(np.float64) for x in ("lh", "ll", "lc"))
    atr = feat.atr.values
    cr = feat.cr.values  # features() was built with this L
    newsess = bars.newsess.values
    bis = bars.bis.values.astype(np.int64)
    sids = bars.sid.values
    starts = np.r_[0, np.flatnonzero(np.diff(sids)) + 1]
    ends = np.r_[starts[1:], len(bars)]
    S, LC, W, F = [], [], [], []
    lc_off = 0
    for s, e in zip(starts, ends):
        sig, lcs, waves, fails = D.lifecycle(lh[s:e], ll[s:e], lc[s:e], cr[s:e], atr[s:e], bis[s:e], newsess[s:e],
                                             c, L, k, m, strict)
        if len(sig):
            sig = sig.copy()
            for col in (D.S_T, D.S_START, D.S_BO):
                sig[:, col] += s
            sig[:, D.S_LC] += lc_off
            S.append(sig)
        if len(lcs):
            lcs = lcs.copy()
            for col in (D.L_START, D.L_END, D.L_BOX0):
                lcs[:, col] += s
            LC.append(lcs)
            w = waves.copy()
            for col in (D.W_BO, D.W_ACC, D.W_PEAKI, D.W_CONF, D.W_BLOWI):
                w[:, :, col] += s
            W.append(w)
        if len(fails):
            f = fails.copy()
            f[:, 0] += s
            f[:, 2] += lc_off
            F.append(f)
        lc_off += len(lcs)
    cat = lambda xs, shape: np.concatenate(xs) if xs else np.zeros(shape)
    return (cat(S, (0, D.NS)), cat(LC, (0, D.NL)), cat(W, (0, D.MAXW, D.NW)), cat(F, (0, 3)))


def control_signals(bars, feat, elig, L, c, k, m, strict, v, cell=None):
    """Signal bar indices per control code (PREREG §5). Returns dict code -> array of bar indices (eligible only),
    plus the lifecycle tables of the primary machine."""
    cell = cell or run_cell(bars, feat, L, c, k, m, strict)
    sig, lcs, waves, fails = cell
    out = {}
    # A: every eligible bar
    out["A"] = np.flatnonzero(elig)
    cr = feat.cr.values
    comp = cr <= c
    prevcomp = np.r_[False, comp[:-1]] & ~bars.newsess.values
    out["B"] = np.flatnonzero(elig & comp & ~prevcomp)
    vr = feat.vr.values
    out["C"] = np.flatnonzero(elig & (vr >= v))
    don = feat.don.values
    out["D"] = np.flatnonzero(elig & don & ~(np.r_[False, don[:-1]] & ~bars.newsess.values))
    out["E"] = np.flatnonzero(elig & (feat.swl.values == 1))
    out["F"] = np.flatnonzero(elig & don & (vr >= v))
    t = sig[:, D.S_T].astype(np.int64)
    wv = sig[:, D.S_WAVE]
    ok = elig[t]
    out["G"] = t[ok & (wv == 1)]
    out["I"] = t[ok & (wv == 2)]
    out["I3"] = t[ok & (wv == 3)]
    # H: loose support, no acceptance (m = 1) - E1 -> higher swing low -> close > R1
    hsig = run_cell(bars, feat, L, c, k, 1, False)[0]
    ht = hsig[:, D.S_T].astype(np.int64)
    out["H"] = ht[elig[ht] & (hsig[:, D.S_WAVE] == 2)]
    return out, cell
