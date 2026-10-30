"""Candidate generation per contract and sequencing per leg (spec §3.4, §5, §6, §12).

Pattern (§12.1): for each expiry, load the picked contracts once; every study emits candidates (each signal on a watched
day with its fully simulated outcome - outcomes do not depend on other trades); then `sequence()` keeps one open position
per leg (CE / PE) per book. Fills: entry at the next 1-min open after the signal bar closes; state exits at the next 1-min
open after the exit bar closes; stops at the worse of open / stop; limits at the better of open / limit; the expiry exit
at the 15:15 open (or the next bar, or the last close)."""
import numpy as np, pandas as pd
from . import indicators as I
from .costs import costs, LOT

FAR = np.datetime64("2100-01-01")


class Contract:
    """one option contract's 1-min arrays, trimmed to 3 sessions before its first watched day (§3.3)."""
    def __init__(self, e, K, r, g, wd, first):
        days = np.sort(g.date.unique()); fi = np.searchsorted(days, np.datetime64(first))
        g = g[g.date >= days[max(0, fi - 3)]].reset_index(drop=True)
        self.e, self.K, self.r, self.g, self.wd = e, K, r, g, wd
        self.dt = g.datetime.values; self.op = g.open.values.astype(float); self.hi = g.high.values.astype(float)
        self.lo = g.low.values.astype(float); self.cl = g.close.values.astype(float)
        self.dday = pd.to_datetime(self.dt).normalize().values
        self.exp_close = np.datetime64(pd.Timestamp(e) + pd.Timedelta(minutes=915))
        self.j_exp = min(np.searchsorted(self.dt, self.exp_close), len(self.dt) - 1) if len(self.dt) else 0
        self._bars = {}

    def ok(self): return len(self.g) >= 200

    def bars(self, tf):
        if tf not in self._bars: self._bars[tf] = I.agg(self.g, tf)
        return self._bars[tf]

    def entry_at(self, t, lo_tod=560, hi_tod=900):
        """the 1-min index of the entry for a signal at bar-close time t, or None (watched day, window, same-day bar, premium >= 2)."""
        tt = pd.Timestamp(t); day = tt.normalize(); tdm = tt.hour * 60 + tt.minute
        if day not in self.wd or not (lo_tod <= tdm <= hi_tod): return None
        i0 = np.searchsorted(self.dt, t)
        if i0 >= len(self.dt) or self.dday[i0] != np.datetime64(day) or self.op[i0] < 2: return None
        return int(i0)

    def state_exit(self, i0, tx):
        """exit index and price for a state exit at time tx (or the expiry close if earlier)."""
        i1 = min(np.searchsorted(self.dt, tx), len(self.dt) - 1)
        return i1, (self.op[i1] if self.dt[i1] >= tx else self.cl[i1])


def _first_after(times, t):
    nx = times[times > t]; return nx[0] if len(nx) else FAR


# ------------------------------------------------------------------ §12.2 / §12.4 swing trades (trail, lock50)
def swing_trade(C, i0, t, s, stop0, upd_t, upd_v, mode, lock, lock_pts=50.0):
    """walk a swing-stop trade: trail to newly confirmed swings (never loosen), optional lock at +lock_pts (SL floor = entry)."""
    dt, op, hi1, lo1, dday = C.dt, C.op, C.hi, C.lo, C.dday; E = op[i0]
    day = pd.Timestamp(t).normalize()
    eod_t = C.exp_close if mode == "positional" else np.datetime64(day + pd.Timedelta(minutes=915))
    j_end = min(np.searchsorted(dt, eod_t), len(dt) - 1)
    if mode == "intraday" and dday[j_end] != np.datetime64(day): j_end -= 1
    m_ = upd_t > t; upd_t, upd_v = upd_t[m_], upd_v[m_]
    stop = stop0; k = i0; px = None; why = "end"; locked = False
    bounds = list(np.searchsorted(dt, upd_t[upd_t < dt[j_end]])) + [j_end + 1]
    seg_start = i0
    for bi, bnd in enumerate(bounds):
        a, z = seg_start, min(bnd, j_end + 1)
        if a < z:
            if lock and not locked:
                fav = np.flatnonzero((hi1[a:z] >= E + lock_pts) if s > 0 else (lo1[a:z] <= E - lock_pts))
                hitst = np.flatnonzero((lo1[a:z] <= stop) if s > 0 else (hi1[a:z] >= stop))
                if len(fav) and (not len(hitst) or fav[0] < hitst[0]):
                    aa = a + fav[0]; locked = True; stop = max(stop, E) if s > 0 else min(stop, E)
                    h2 = np.flatnonzero((lo1[aa + 1:z] <= stop) if s > 0 else (hi1[aa + 1:z] >= stop))
                    if len(h2):
                        k = aa + 1 + h2[0]; px = min(op[k], stop) if s > 0 else max(op[k], stop); why = "stop"; break
                    seg_start = z
                    if bi < len(upd_v): stop = max(stop, upd_v[bi]) if s > 0 else min(stop, upd_v[bi])
                    continue
            hit = np.flatnonzero((lo1[a:z] <= stop) if s > 0 else (hi1[a:z] >= stop))
            if len(hit):
                k = a + hit[0]; px = min(op[k], stop) if s > 0 else max(op[k], stop); why = "stop" if stop == stop0 else "trail stop"; break
        seg_start = z
        if bi < len(upd_v): stop = max(stop, upd_v[bi]) if s > 0 else min(stop, upd_v[bi])
    if px is None: k = j_end; px = op[j_end]; why = "expiry 15:15" if mode == "positional" else "eod 15:15"
    return k, px, why


def stswing(C, tf, p, m, modes=("positional",), locks=("trail+lock50",), lot=LOT):
    """§12.2 Supertrend-segment CHoCH / BOS on the premium chart: bullish -> BUY (SL swing low), bearish -> SELL (SL swing high)."""
    B = C.bars(tf); ev, sh_t, sh_v, sl_t, sl_v = I.st_segment_structure(B, I.st_dir(B, p, m).astype(int))
    out = []
    for t, s, kind, stop0 in ev:
        if np.isnan(stop0): continue
        i0 = C.entry_at(t)
        if i0 is None: continue
        E = C.op[i0]
        if (E - stop0) * s < 2: continue
        tdm = pd.Timestamp(t).hour * 60 + pd.Timestamp(t).minute
        upd_t, upd_v = (sl_t, sl_v) if s > 0 else (sh_t, sh_v)
        for mode in modes:
            if mode == "intraday" and tdm > 870: continue
            for lock in locks:
                k, px, why = swing_trade(C, i0, t, s, stop0, upd_t, upd_v, mode, lock == "trail+lock50")
                out.append(dict(side=s, st=f"{tf}m ST({p},{m:g})", kind=kind, mode=mode, lock=lock, right=C.r, sig=t, entry_time=C.dt[i0],
                                exit_time=C.dt[k], entry=E, stop0=stop0, exit=px, why=why, net=s * (px - E) * lot - costs(E, px, s, lot),
                                expiry=C.e, strike=C.K))
    return out


def choch_then_st(B, N, d, confirm, max_wait=200):
    """§12.4 pivot CHoCH / BOS, then wait (<= max_wait bars) for the same-TF Supertrend to agree; discard on an opposite
    break or a close through the setup's stop."""
    st = I.pivot_structure(B, N); ev, lsl, lsh = st["ev"], st["last_sl"], st["last_sh"]; c, ct = B.close.values, B.ct.values; n = len(c)
    ish = np.flatnonzero(~np.isnan(st["new_sh"])); isl = np.flatnonzero(~np.isnan(st["new_sl"]))
    out = []
    for i in np.flatnonzero(ev != 0):
        s_ = 1 if ev[i] > 0 else -1; kind = "CHoCH" if abs(ev[i]) == 2 else "BOS"; stop = lsl[i] if s_ > 0 else lsh[i]
        if np.isnan(stop): continue
        if not confirm: out.append((ct[i], s_, kind, stop, 0)); continue
        for j in range(i, min(n, i + max_wait)):
            if j > i and (ev[j] * s_ < 0 or (c[j] - stop) * s_ <= 0): break
            if d[j] == s_: out.append((ct[j], s_, kind, lsl[j] if s_ > 0 else lsh[j], j - i)); break
    return out, ct[ish], st["new_sh"][ish], ct[isl], st["new_sl"][isl]


def chochst(C, tf, N, p, m, modes=("positional",), locks=("trail",), lot=LOT):
    """§12.4: pivot CHoCH / BOS -> Supertrend confirmation (p = 0: no confirmation), swing stop + trail."""
    B = C.bars(tf)
    if p == 0: ev, sh_t, sh_v, sl_t, sl_v = choch_then_st(B, N, None, False)
    else: ev, sh_t, sh_v, sl_t, sl_v = choch_then_st(B, N, I.st_dir(B, p, m).astype(int), True)
    name = f"{tf}m CHoCH → ST({p},{m:g}) confirm" if p else f"{tf}m CHoCH, no ST"
    out = []
    for t, s, kind, stop0, lag in ev:
        if np.isnan(stop0): continue
        i0 = C.entry_at(t)
        if i0 is None: continue
        E = C.op[i0]
        if (E - stop0) * s < 2: continue
        tdm = pd.Timestamp(t).hour * 60 + pd.Timestamp(t).minute
        upd_t, upd_v = (sl_t, sl_v) if s > 0 else (sh_t, sh_v)
        for mode in modes:
            if mode == "intraday" and tdm > 870: continue
            for lock in locks:
                k, px, why = swing_trade(C, i0, t, s, stop0, upd_t, upd_v, mode, lock == "trail+lock50")
                out.append(dict(side=s, st=name, kind=kind, mode=mode, lock=lock, right=C.r, sig=t, entry_time=C.dt[i0], exit_time=C.dt[k],
                                entry=E, stop0=stop0, exit=px, why=why, net=s * (px - E) * lot - costs(E, px, s, lot), expiry=C.e, strike=C.K))
    return out


# ------------------------------------------------------------------ §6.3 / §6.5 ST + confirmation, positional, exits + lock
def _exit_states(B15, side):
    """15-min exit-state times for a short (side -1) or a long (side +1)."""
    c15, ct15 = B15.close.values, B15.ct.values
    em = I.ema(c15, 20); atr22 = I.atr_wilder(B15, 22)
    if side < 0:
        ll22 = pd.Series(B15.low).rolling(22, min_periods=1).min().values
        st = dict(ema20=c15 > em, chandelier=c15 > ll22 + 3 * atr22, psar=I.psar_bull(B15.high.values, B15.low.values), rsi30=I.rsi(c15) < 30)
    else:
        hh22 = pd.Series(B15.high).rolling(22, min_periods=1).max().values
        st = dict(ema20=c15 < em, chandelier=c15 < hh22 - 3 * atr22)
    return {k: ct15[v] for k, v in st.items()}


def _lock_short(C, i0, i1, E, trig=50.0, target=50.0):
    """§5.4 SELL lock on a candidate that would exit at i1: returns (k, px, why, locked) or None if never triggered."""
    dt, op, hi, lo, cl = C.dt, C.op, C.hi, C.lo, C.cl
    hit = np.flatnonzero(lo[i0:i1 + 1] <= E - trig)
    if not len(hit) or i0 + hit[0] >= i1: return None
    j1 = C.j_exp; s = i0 + hit[0] + 1
    st = np.flatnonzero(hi[s:j1 + 1] >= E); ks = s + st[0] if len(st) else 10 ** 9; kt = 10 ** 9
    if target is not None and E - trig > target:
        tg = np.flatnonzero(lo[s:j1 + 1] <= target); kt = s + tg[0] if len(tg) else 10 ** 9
    if min(ks, kt) <= j1:
        if ks <= kt: return ks, max(op[ks], E), "locked: back to entry"
        return kt, min(op[kt], float(target)), "locked: premium 50 target"
    return j1, (op[j1] if dt[j1] >= C.exp_close else cl[j1]), "locked: expiry 15:15"


def conf_sell(C, p=4, m=3.0, confs=("5m",), exits=("st_up",), locks=("none", "tgt50", "exp"), lot=LOT):
    """§6.3 SELL: trend = 15-min ST on the premium down; entry on the flip ('none') or a bearish 1m (N=5) / 5m (N=3) event."""
    dt, op, lo1, hi1 = C.dt, C.op, C.lo, C.hi
    B15 = C.bars(15); ct15 = B15.ct.values
    d15 = I.st_dir(B15, p, m); flip = np.r_[0, np.diff(d15.astype(int))]
    ex_t = _exit_states(B15, -1); ex_t["st_up"] = ct15[flip > 0]
    sig = {"none": ct15[flip < 0]}
    if "5m" in confs or "choch5_up" in exits:
        B5 = C.bars(5); s5 = I.pivot_structure(B5, 3); sig["5m"] = B5.ct.values[s5["ev"] < 0]; ex_t["choch5_up"] = B5.ct.values[s5["ev"] > 0]
    if "1m" in confs:
        s1 = I.pivot_structure(C.g[["open", "high", "low", "close"]].astype(float), 5); sig["1m"] = dt[s1["ev"] < 0] + np.timedelta64(1, "m")
    out = []
    for conf in confs:
        for t in sig[conf]:
            i0 = C.entry_at(t)
            if i0 is None: continue
            if conf != "none":
                j = np.searchsorted(ct15, t, side="right") - 1
                if j < 0 or d15[j] != -1: continue
            E = op[i0]
            for ex in exits:
                base = "st_up" if ex in ("tgt50", "rsi30") else ex
                tx = min(_first_after(ex_t[base], t), C.exp_close); why = ex if tx < C.exp_close else "expiry"
                if ex == "rsi30":
                    nr = _first_after(ex_t["rsi30"], t)
                    if nr < tx: tx = nr; why = "rsi30 target"
                i1, px = C.state_exit(i0, tx)
                if ex == "tgt50":
                    tg = 0.5 * E; hit = np.flatnonzero(lo1[i0:i1 + 1] <= tg)
                    if len(hit): i1 = i0 + hit[0]; px = min(op[i1], tg); why = "tgt50 target"
                for lk in locks:
                    k, px_, w, locked = i1, px, why, False
                    if lk != "none":
                        r = _lock_short(C, i0, i1, E, 50.0, 50.0 if lk == "tgt50" else None)
                        if r: (k, px_, w), locked = r, True
                    out.append(dict(st=f"15m ST({p},{m:g})", conf=conf, exit_rule=ex, lock=lk, right=C.r, sig=t, expiry=C.e, strike=C.K,
                                    entry_time=dt[i0], exit_time=dt[k], entry=E, exit=px_, why=w, net=(E - px_) * lot - costs(E, px_, -1, lot),
                                    worst_open=-(hi1[i0:i1 + 1].max() - E) * lot, locked=locked, side=-1))
    return out


def conf_buy(C, p=4, m=3.0, confs=("5m",), exits=("st_dn",), locks=("normal", "lock_exp", "lock_2x"), lot=LOT):
    """§6.5 BUY mirror: trend = 15-min ST up; entry on the flip or a bullish 1m / 5m event; exits + §5.4 BUY lock."""
    dt, op, lo1, hi1, cl1 = C.dt, C.op, C.lo, C.hi, C.cl
    B15 = C.bars(15); ct15 = B15.ct.values
    d15 = I.st_dir(B15, p, m); flip = np.r_[0, np.diff(d15.astype(int))]
    ex_t = _exit_states(B15, 1); ex_t["st_dn"] = ct15[flip < 0]
    sig = {"none": ct15[flip > 0]}
    if "5m" in confs:
        B5 = C.bars(5); s5 = I.pivot_structure(B5, 3); sig["5m"] = B5.ct.values[s5["ev"] > 0]
    if "1m" in confs:
        s1 = I.pivot_structure(C.g[["open", "high", "low", "close"]].astype(float), 5); sig["1m"] = dt[s1["ev"] > 0] + np.timedelta64(1, "m")
    j_exp = C.j_exp; out = []
    for conf in confs:
        for t in sig[conf]:
            i0 = C.entry_at(t)
            if i0 is None: continue
            if conf != "none":
                j = np.searchsorted(ct15, t, side="right") - 1
                if j < 0 or d15[j] != 1: continue
            E = op[i0]
            for ex in exits:
                base = "st_dn" if ex == "tgt2x" else ex
                tx = min(_first_after(ex_t[base], t), C.exp_close); why = ex if tx < C.exp_close else "expiry"
                i1, px = C.state_exit(i0, tx)
                if ex == "tgt2x":
                    hit = np.flatnonzero(hi1[i0:i1 + 1] >= 2 * E)
                    if len(hit): i1 = i0 + hit[0]; px = max(op[i1], 2 * E); why = "tgt2x target"
                outs = {"normal": (i1, px, why)}
                hit = np.flatnonzero(hi1[i0:i1 + 1] >= E + 50)
                for lk in ("lock_exp", "lock_2x"):
                    if not len(hit) or i0 + hit[0] >= i1: outs[lk] = (i1, px, why); continue
                    s = i0 + hit[0] + 1; st_ = np.flatnonzero(lo1[s:j_exp + 1] <= E); ks = s + st_[0] if len(st_) else 10 ** 9; kt = 10 ** 9
                    if lk == "lock_2x":
                        tg = np.flatnonzero(hi1[s:j_exp + 1] >= 2 * E); kt = s + tg[0] if len(tg) else 10 ** 9
                    if min(ks, kt) <= j_exp:
                        outs[lk] = (ks, min(op[ks], E), "locked: back to entry") if ks <= kt else (kt, max(op[kt], 2 * E), "locked: 2x target")
                    else: outs[lk] = (j_exp, op[j_exp] if dt[j_exp] >= C.exp_close else cl1[j_exp], "locked: expiry 15:15")
                for lk in locks:
                    k, px_, w = outs[lk]
                    out.append(dict(st=f"15m ST({p},{m:g})", conf=conf, exit_rule=ex, lock=lk, right=C.r, sig=t, expiry=C.e, strike=C.K,
                                    entry_time=dt[i0], exit_time=dt[k], entry=E, exit=px_, why=w, net=(px_ - E) * lot - costs(E, px_, 1, lot), side=1))
    return out


# ------------------------------------------------------------------ §12.5 intraday grid (5m / 15m premium ST, confirm, exits, lock)
def intraday(C, d, tf, p, m, confs=("5m",), exits=("ema20",), locks=("none",), lot=LOT):
    """§12.5: d = -1 SELL (premium ST down + bearish confirm) / +1 BUY; flat by 15:15 the same day; entries 09:20-14:30."""
    dt, op, lo1, hi1 = C.dt, C.op, C.lo, C.hi
    B5 = C.bars(5); ct5 = B5.ct.values; ev = {}
    if "5m" in confs:
        s5 = I.pivot_structure(B5, 3); ev["5m"] = ct5[s5["ev"] * d > 0]
    if "1m" in confs:
        s1 = I.pivot_structure(C.g[["open", "high", "low", "close"]].astype(float), 5); ev["1m"] = (dt + np.timedelta64(1, "m"))[s1["ev"] * d > 0]
    B = C.bars(tf); c = B.close.values; ct = B.ct.values
    em = I.ema(c, 20); atr = I.atr_wilder(B, 22)
    hh = pd.Series(B.high).rolling(22, min_periods=1).max().values; ll = pd.Series(B.low).rolling(22, min_periods=1).min().values
    dd_ = I.st_dir(B, p, m); flip = np.r_[0, np.diff(dd_.astype(int))]
    ex_t = {"st": ct[flip * d < 0], "chandelier": ct[(c > ll + 3 * atr) if d < 0 else (c < hh - 3 * atr)], "ema20": ct[(c > em) if d < 0 else (c < em)]}
    LOCKS = {"none": None, "lock20": 20, "lock40": 40}; out = []
    for conf in confs:
        times = ct[flip * d > 0] if conf == "none" else ev[conf]
        for t in times:
            i0 = C.entry_at(t, 560, 870)
            if i0 is None: continue
            if conf != "none":
                j = np.searchsorted(ct, t, side="right") - 1
                if j < 0 or dd_[j] != d: continue
            day = pd.Timestamp(t).normalize()
            eod_t = np.datetime64(day + pd.Timedelta(minutes=915)); j_eod = min(np.searchsorted(dt, eod_t), len(dt) - 1)
            if C.dday[j_eod] != np.datetime64(day): j_eod -= 1
            E = op[i0]
            for ex in exits:
                tx = _first_after(ex_t[ex], t)
                i1 = min(np.searchsorted(dt, tx), j_eod) if tx < eod_t else j_eod; why = ex if (tx < eod_t and i1 < j_eod) else "eod"
                px = op[i1]
                for lk in locks:
                    L = LOCKS[lk]; k_, px_, w_ = i1, px, why
                    if L is not None:
                        fav = (hi1[i0:i1 + 1] >= E + L) if d > 0 else (lo1[i0:i1 + 1] <= E - L); hit = np.flatnonzero(fav)
                        if len(hit) and i0 + hit[0] < i1:
                            s = i0 + hit[0] + 1; adv = (lo1[s:j_eod + 1] <= E) if d > 0 else (hi1[s:j_eod + 1] >= E); b = np.flatnonzero(adv)
                            if len(b) and s + b[0] < j_eod: k_ = s + b[0]; px_ = min(op[k_], E) if d > 0 else max(op[k_], E); w_ = "locked: back to entry"
                            else: k_ = j_eod; px_ = op[j_eod]; w_ = "locked: eod"
                    out.append(dict(side=d, st=f"{tf}m ST({p},{m:g})", conf=conf, exit_rule=ex, lock=lk, right=C.r, sig=t, entry_time=dt[i0],
                                    exit_time=dt[k_], entry=E, exit=px_, why=w_, net=d * (px_ - E) * lot - costs(E, px_, d, lot), expiry=C.e, strike=C.K))
    return out


# ------------------------------------------------------------------ §6.1 positional SELL on the ATM contract's own chart
def possell(g, e, K, r, watched, tf, p, m):
    """§6.1 candidates on one front-expiry ATM contract (its whole history in the expiry folder): sell when its tf-minute
    ST turns down (bar close 09:20-15:00 on a watched day), exit when it turns up or 15:15 on expiry day.
    Returns (t, e, K, r, fn) entries; fn(t) simulates - possell sequences on the signal before simulating, as the reference."""
    g = g.sort_values("datetime").reset_index(drop=True)
    B = I.agg(g, tf); d = I.st_dir(B, p, m); flip = np.r_[0, np.diff(d.astype(int))]; ct = B.ct.values
    dn, up = ct[flip < 0], ct[flip > 0]
    return [(pd.Timestamp(t), (g, up)) for t in dn
            if (pd.Timestamp(t).normalize(), e, K, r) in watched and 560 <= pd.Timestamp(t).hour * 60 + pd.Timestamp(t).minute <= 900]


def possell_trade(g, up, t, e, lot=LOT):
    dt = g.datetime.values; i0 = np.searchsorted(dt, np.datetime64(t))
    if i0 >= len(g) or g.date.iloc[i0] != t.normalize(): return None
    entry = float(g.open.iloc[i0])
    if entry < 2: return None
    nx = up[up > np.datetime64(t)]; t_up = pd.Timestamp(nx[0]) if len(nx) else pd.Timestamp("2100-01-01")
    exp_close = pd.Timestamp(e) + pd.Timedelta(minutes=915)
    t_x = min(t_up, exp_close); why = "ST turned up" if t_up < exp_close else "expiry 15:15"
    i1 = min(np.searchsorted(dt, np.datetime64(t_x)), len(g) - 1)
    px = float(g.open.iloc[i1] if g.datetime.iloc[i1] >= t_x else g.close.iloc[i1])
    return dict(entry_time=g.datetime.iloc[i0], exit_time=g.datetime.iloc[i1], entry=entry, exit=px, why=why, pts=entry - px,
                cost=costs(entry, px, -1, lot), net=(entry - px) * lot - costs(entry, px, -1, lot),
                worst_open_loss=-(float(g.high.iloc[i0:i1 + 1].max()) - entry) * lot)


# ------------------------------------------------------------------ sequencing (§3.4)
def sequence(x, legs=("CE", "PE")):
    """one open position per leg: take a candidate if its signal time >= the previous taken trade's exit time."""
    if not len(x): return x
    x = x.sort_values("sig"); keep = []
    for rr in legs:
        y = x[x.right == rr]; free = np.datetime64("1900-01-01")
        for i, s_, xt in zip(y.index.values, y.sig.values, y.exit_time.values):
            if s_ < free: continue
            keep.append(i); free = np.datetime64(xt)
    T = x.loc[keep].sort_values("exit_time")
    T["year"] = pd.to_datetime(T.entry_time).dt.year
    return T
