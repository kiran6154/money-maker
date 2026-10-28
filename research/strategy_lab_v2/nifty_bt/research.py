"""Spec §0 priority 7 and the v2 variants without golden lists: §12.3 (1-min ST swings, 5-min signals), §12.6 dual Supertrend
intraday, §5.5 hedge overlay, §12.8 late entry. Same Contract / fill conventions as engine.py."""
import numpy as np, pandas as pd
from . import indicators as I, engine as E
from .costs import costs, LOT


def swings_1m(C, p, m):
    """§12.3 swings from the 1-min Supertrend's segments (confirmed at the flip bar's close)."""
    G1 = C.g[["open", "high", "low", "close"]].astype(float).reset_index(drop=True); d = I.st_dir(G1, p, m).astype(int)
    h, l = G1.high.values, G1.low.values; ct = C.dt + np.timedelta64(1, "m"); sh = []; sl = []; hi = lo = np.nan
    for i in range(len(d)):
        if i > 0 and d[i] != d[i - 1]:
            (sh if d[i - 1] == 1 else sl).append((ct[i], hi if d[i - 1] == 1 else lo)); hi, lo = h[i], l[i]
        else:
            hi = h[i] if np.isnan(hi) else max(hi, h[i]); lo = l[i] if np.isnan(lo) else min(lo, l[i])
    a = lambda xs, k: np.array([x[k] for x in xs])
    return a(sh, 0), a(sh, 1), a(sl, 0), a(sl, 1)


def stswing_1m5m(C, p, m, modes=("positional",), locks=("trail",), lot=LOT):
    """§12.3 events only on 5-min closes, against swings confirmed by that close."""
    sh_t, sh_v, sl_t, sl_v = swings_1m(C, p, m); B5 = C.bars(5); c, ct = B5.close.values, B5.ct.values
    ev = []; trend = 0; Hx = Lx = True; lastH = lastL = -1
    for i in range(len(c)):
        jh = np.searchsorted(sh_t, ct[i], side="right") - 1; jl = np.searchsorted(sl_t, ct[i], side="right") - 1
        if jh != lastH: lastH = jh; Hx = False
        if jl != lastL: lastL = jl; Lx = False
        H = sh_v[jh] if jh >= 0 else np.nan; L = sl_v[jl] if jl >= 0 else np.nan
        if not Hx and not np.isnan(H) and c[i] > H: ev.append((ct[i], 1, "BOS" if trend == 1 else "CHoCH", L)); Hx = True; trend = 1
        if not Lx and not np.isnan(L) and c[i] < L: ev.append((ct[i], -1, "BOS" if trend == -1 else "CHoCH", H)); Lx = True; trend = -1
    out = []
    for t, s, kind, stop0 in ev:
        if np.isnan(stop0): continue
        i0 = C.entry_at(t)
        if i0 is None: continue
        En = C.op[i0]
        if (En - stop0) * s < 2: continue
        tdm = pd.Timestamp(t).hour * 60 + pd.Timestamp(t).minute
        upd_t, upd_v = (sl_t, sl_v) if s > 0 else (sh_t, sh_v)
        for mode in modes:
            if mode == "intraday" and tdm > 870: continue
            for lock in locks:
                k, px, why = E.swing_trade(C, i0, t, s, stop0, upd_t, upd_v, mode, lock == "trail+lock50")
                out.append(dict(side=s, st=f"1m ST({p},{m:g}) swings · 5m signals", kind=kind, mode=mode, lock=lock, right=C.r, sig=t,
                                entry_time=C.dt[i0], exit_time=C.dt[k], entry=En, stop0=stop0, exit=px, why=why,
                                net=s * (px - En) * lot - costs(En, px, s, lot), expiry=C.e, strike=C.K))
    return out


def dual_st(C, tf, slow=(10, 4.0), fast=(5, 2.0), sides=(-1, 1), entries=("pullback", "agree"),
            exits=("fast", "slow", "slow+lock20", "slow+lock40"), lot=LOT):
    """§12.6 intraday: slow ST = direction, fast ST = timing; entries 09:20-14:30 on watched days, flat by 15:15.
    Cap per leg per day is applied after sequencing (sequence_capped)."""
    dt, op, lo1, hi1 = C.dt, C.op, C.lo, C.hi
    B = C.bars(tf); ct = B.ct.values; ds = I.st_dir(B, *slow).astype(int); dfst = I.st_dir(B, *fast).astype(int); out = []
    for d in sides:
        fl_f = np.r_[0, np.diff(dfst)]; both = (ds == d) & (dfst == d)
        sig = {"pullback": ct[(ds == d) & (fl_f * d > 0)], "agree": ct[both & ~np.r_[False, both[:-1]]]}
        ex_t = {"fast": ct[np.r_[0, np.diff(dfst)] * d < 0], "slow": ct[np.r_[0, np.diff(ds)] * d < 0]}
        for ent in entries:
            for t in sig[ent]:
                i0 = C.entry_at(t, 560, 870)
                if i0 is None: continue
                day = pd.Timestamp(t).normalize()
                eod_t = np.datetime64(day + pd.Timedelta(minutes=915)); j_eod = min(np.searchsorted(dt, eod_t), len(dt) - 1)
                if C.dday[j_eod] != np.datetime64(day): j_eod -= 1
                En = op[i0]
                for ex in exits:
                    tx = E._first_after(ex_t["fast" if ex == "fast" else "slow"], t)
                    i1 = min(np.searchsorted(dt, tx), j_eod) if tx < eod_t else j_eod; why = ex.split("+")[0] if i1 < j_eod else "eod"; px = op[i1]; k_ = i1
                    if "lock" in ex:
                        L = 20 if ex.endswith("20") else 40
                        hit = np.flatnonzero((hi1[i0:i1 + 1] >= En + L) if d > 0 else (lo1[i0:i1 + 1] <= En - L))
                        if len(hit) and i0 + hit[0] < i1:
                            s = i0 + hit[0] + 1; bb = np.flatnonzero((lo1[s:j_eod + 1] <= En) if d > 0 else (hi1[s:j_eod + 1] >= En))
                            if len(bb) and s + bb[0] < j_eod: k_ = s + bb[0]; px = min(op[k_], En) if d > 0 else max(op[k_], En); why = "locked: back to entry"
                            else: k_ = j_eod; px = op[j_eod]; why = "locked: eod"
                    out.append(dict(side=d, tf=f"{tf}m", pair=f"{slow[0]},{slow[1]:g}/{fast[0]},{fast[1]:g}", entry_rule=ent, exit_rule=ex, right=C.r,
                                    sig=t, entry_time=dt[i0], exit_time=dt[k_], entry=En, exit=px, why=why, net=d * (px - En) * lot - costs(En, px, d, lot)))
    return out


def sequence_capped(x, cap=None):
    """§3.4 sequencing plus an intraday cap of `cap` trades per leg per day."""
    if cap is None: return E.sequence(x)
    x = x.sort_values("sig"); keep = []
    for rr in ("CE", "PE"):
        y = x[x.right == rr]; free = np.datetime64("1900-01-01"); n = {}
        for i, s_, xt in zip(y.index.values, y.sig.values, y.exit_time.values):
            d = pd.Timestamp(s_).normalize()
            if s_ < free or n.get(d, 0) >= cap: continue
            keep.append(i); free = np.datetime64(xt); n[d] = n.get(d, 0) + 1
    T = x.loc[keep].sort_values("exit_time"); T["year"] = pd.to_datetime(T.entry_time).dt.year
    return T


def late_entry(C, T, Xs=(50, 100, 150), lot=LOT):
    """§12.8 for long candidates T on contract C: buy-stop at entry + X, valid until the normal exit. Exits after the fill:
    'st' the normal exit; 'sl50' a 50-point stop; 'lock' normal exit until a further +50, then stop = late entry, hold to expiry."""
    dt, op, hi, lo, cl = C.dt, C.op, C.hi, C.lo, C.cl; out = []
    for r in T.itertuples():
        i0 = np.searchsorted(dt, np.datetime64(r.entry_time)); i1 = min(np.searchsorted(dt, np.datetime64(r.exit_time)), len(dt) - 1); En = r.entry
        rec = dict(right=r.right, sig=r.sig, entry_time=r.entry_time, E=En, mfe=hi[i0:i1 + 1].max() - En)
        for X in Xs:
            hit = np.flatnonzero(hi[i0:i1 + 1] >= En + X)
            if not len(hit) or i0 + hit[0] >= i1:
                for v in ("st", "sl50", "lock"): rec[f"{v}{X}"] = np.nan
                continue
            k = i0 + hit[0]; L = max(op[k], En + X)
            outs = {"st": (i1, op[i1] if dt[i1] >= np.datetime64(r.exit_time) else cl[i1])}
            s = np.flatnonzero(lo[k + 1:i1 + 1] <= L - 50)
            outs["sl50"] = (k + 1 + s[0], min(op[k + 1 + s[0]], L - 50)) if len(s) else outs["st"]
            a = np.flatnonzero(hi[k + 1:i1 + 1] >= L + 50)
            if len(a):
                s2 = k + 1 + a[0] + 1; b = np.flatnonzero(lo[s2:C.j_exp + 1] <= L)
                outs["lock"] = (s2 + b[0], min(op[s2 + b[0]], L)) if len(b) else (C.j_exp, op[C.j_exp] if dt[C.j_exp] >= C.exp_close else cl[C.j_exp])
            else: outs["lock"] = outs["st"]
            for v, (kk, px) in outs.items(): rec[f"{v}{X}"] = (px - L) * lot - costs(L, px, 1, lot)
        out.append(rec)
    return out


def hedge(T, chain0919, read_expiry, targets=(5, 10, 20), lot=LOT):
    """§5.5 per-trade hedge for a short book T (columns expiry, strike, right, entry_time, exit_time, entry, net): buy the same
    expiry / right OTM strike whose 09:19 premium is closest to the target at the short's entry minute open, sell it at the
    short's exit minute open. Returns per-trade net hedged / naked."""
    S = chain0919[chain0919.close > 0].copy(); S["otm"] = np.where(S.right == "CE", S.strike > S.spot, S.strike < S.spot); S = S[S.otm]
    H = {}
    for (d, e, r), g in S.groupby(["date", "expiry", "right"]):
        for t in targets:
            row = g.iloc[(g.close - t).abs().argmin()]; H[(d, e, r, t)] = (int(row.strike), row.close)
    T = T.copy(); T["d"] = pd.to_datetime(T.entry_time).dt.normalize(); out = []
    for e, g in T.groupby("expiry"):
        ks = {H[(r.d, e, r.right, t)][0] for r in g.itertuples() for t in targets if (r.d, e, r.right, t) in H}
        X = read_expiry(e, strikes=ks)
        if X is None: continue
        X = X.set_index(["strike", "right", "datetime"]).sort_index()
        for r in g.itertuples():
            rec = dict(entry_time=r.entry_time, right=r.right, net_naked=r.net)
            for t in targets:
                h = H.get((r.d, e, r.right, t)); rec[f"net_h{t}"] = r.net
                if not h or (h[0], r.right) not in X.index.droplevel(2): continue
                hx = X.loc[(h[0], r.right)]; i0 = hx.index.searchsorted(r.entry_time); i1 = hx.index.searchsorted(r.exit_time)
                if i0 < len(hx) and (hx.index[i0] - pd.Timestamp(r.entry_time)) <= pd.Timedelta(minutes=5):
                    i1 = min(i1, len(hx) - 1); he = float(hx.open.iloc[i0])
                    hxp = float(hx.open.iloc[i1]) if hx.index[i1] >= pd.Timestamp(r.exit_time) else float(hx.close.iloc[i1])
                    rec[f"net_h{t}"] = r.net + (hxp - he) * lot - costs(he, hxp, 1, lot)
            out.append(rec)
    return pd.DataFrame(out)
