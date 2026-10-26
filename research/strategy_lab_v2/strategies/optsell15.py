"""15-minute NIFTY option-selling books from the user's two hand-off specs (family module for ST139 - ST145).

Built 2026-10-26 at the user's word ("build these and backtest"), from the pasted specs:
  * "Strategy 11 family - hand-off spec" (claude.ai chat "15min RSI rainbow"); the reference code engine.py / structure.py /
    build_store.py / books.py sits read-only in D:/nifty_data/Claude outputs/strategy11_handoff and is ported here line by
    line (s11_* below). Golden trades: 2024-07-25 23850 CE -14,670.11 and 2026-03-30 24600 PE -1,25,098.
  * "Rainbow Book - NIFTY option-selling strategy (handoff spec)"; its rainbow_reference.py and golden CSVs are not on this
    machine, so rb_* is built from the spec text alone and checked against its yearly totals.

Both read the download store (D:/nifty_data, never written) and cache 15-minute bars per expiry under cache/optsell15/.

STRATEGY 11 (`s11`; per lot of 65; 1 pt slippage a side; charges per engine.charges_short)
  bars     monthly expiries (the last of each month); regular strike files, plus the .wide files for expiries from
           2024-06-27 (the reference's WIDE_FROM); duplicate minutes keep the regular row; 1-minute rows with volume 0 are
           dropped (Breeze padding); minutes 09:16 - 15:29 -> 15-minute bars labelled by start 09:15 ... 15:15. Spot: the
           index the same way. A contract needs 40 bars. Indicators run on each contract's own series from its first bar.
  signals  RSI-14 Wilder (seeded with the mean of the first 14 moves); rainbow = 10 recursive SMA-2 of the close, top = max,
           mid = mean (NaN-aware); S11 = max(RSI over 5 bars) >= 70 and the first close below mid. Structure (structure.py):
           K-bar fractal pivots confirmed K bars later; trend / CHOCH_DN / BOS_DN; lastH = the last confirmed swing high.
  gates    DTE 22 - 35 calendar days; OTM 0.5 - 4% against the same bar's spot; premium: the signal close and the fill both
           in 246.675 - 700 ("fixed"; "scaled" = the same band as % of spot at 24,000); universe "clean" = OTM <= 250 points
           (books.py; the spec's front-month clause is not in the reference code) or "spec" = no extra limit.
  variants A_s11, A_nextopen, A_hardstop K, B_choch_bos K, C_s11_bostrail K, D_chochgate K, E_s11_armedbos K, F_choch_rsi K,
           G_choch_s11 K, G_hardstop K (K = 3 / 5), exits as engine.py; unresolved -> intrinsic at the expiry day's last
           spot bar (15:15) close.
  slots    books.alloc: by signal bar, then the lowest strike; at most `slots` (2) open per right; a signal while full is
           dropped (a slot frees when its exit bar label <= the new signal's label).

RAINBOW BOOK (`rb`; spec text)
  bars     every expiry (weekly and monthly); regular strike files (`rb_wide` adds the .wide files); minutes 09:15 - 15:30
           inclusive, de-duplicated, nothing after the expiry day's 15:30; bin = floor((t - 09:15) / 15) clipped to 0..24.
           A contract needs 80 one-minute rows and 40 bars. Spot = the index 15-minute close of the same bar, forward-filled.
  signal   RSI-14 (pandas EWM alpha 1/14, adjust False, min_periods 14); max(RSI over 5 bars) >= 70, RSI falling, close
           below the previous bar's low; fill = the next bar's open. Filters at the signal bar: DTE 8 - 35, fill 200 - 800,
           OTM 0.5 - 4%, close 30 - 700 (all rupee bands x spot / 23,700 when `scaled`). The contract's FIRST passing
           signal decides: a candidate if fill > 246.675 (scaled likewise) and RSI < 64.799, and width = (top - bottom) /
           close <= 0.0918; anything else abandons the contract.
  book     one CE and one PE lane; by fill time, ties higher premium first; a candidate needs the lane free (fill time >=
           the previous exit). Exit from the fill bar on: armed and high >= fill -> fill (BE); armed and close > rainbow top
           -> that close (RBW_X); then best = max(best, 1 - low / fill), armed from the next bar once best >= 0.30; else
           intrinsic at the expiry date's last 1-minute index close (EXP). Costs: the spec's formula, lot 65.
"""
import datetime as Dt
import glob
import os
import numpy as np
import pandas as pd
import core
import store_reader

ENTRY_RULES = ("optsell15_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT", "INDEX")
OWN_COVERAGE = True
REFUSED_WHY = "the 15-minute option-selling books trade the options themselves; only the Options type runs"
DAY = core.DAY
CDIR = os.path.join(core.CACHE, "optsell15")
_MEM = {}


# ================================================================ store access
def _exp_dirs():
    out = {}
    for d in glob.glob(os.path.join(store_reader.ROOT, "options", "1minute", "*", "*")):
        e = os.path.basename(d)
        if len(e) == 10 and os.path.isdir(d) and glob.glob(os.path.join(d, "*.parquet")): out[e] = d
    return out


def expiries(monthly_only):
    E = sorted(_exp_dirs())
    if not monthly_only: return E
    last = {}
    for e in E: last[e[:7]] = max(last.get(e[:7], ""), e)
    return sorted(set(last.values()))


def _sig(paths):
    return "|".join(f"{os.path.basename(p)}:{int(os.path.getmtime(p))}:{os.path.getsize(p)}" for p in sorted(paths))


def _index_minutes():
    if "idx" in _MEM: return _MEM["idx"]
    fs = sorted(glob.glob(os.path.join(store_reader.ROOT, "index", "1minute", "*", "*.parquet")))
    d = pd.concat([pd.read_parquet(f, columns=["datetime", "close"]) for f in fs], ignore_index=True)
    d = d.drop_duplicates("datetime").sort_values("datetime").reset_index(drop=True)
    _MEM["idx"] = d
    return d


def _mins(s):
    return s.dt.hour * 60 + s.dt.minute


# ---------------------------------------------------------------- Strategy 11 bars (build_store.py)
WIDE_FROM = "2024-06-27"


def _to15_s11(d, keys):
    d = d[(_mins(d.datetime) >= 556) & (_mins(d.datetime) <= 929)].copy()
    d["bar"] = d.datetime.dt.floor("15min")
    agg = {k: (k, f) for k, f in (("open", "first"), ("high", "max"), ("low", "min"), ("close", "last"), ("volume", "sum")) if k in d}
    g = d.groupby(keys + ["bar"], observed=True, sort=True).agg(**agg).reset_index().rename(columns={"bar": "datetime"})
    t = _mins(g.datetime)
    return g[(t >= 555) & (t <= 915)].reset_index(drop=True)


def s11_spot():
    if "s11spot" in _MEM: return _MEM["s11spot"]
    sp = _to15_s11(_index_minutes(), [])[["datetime", "close"]]
    _MEM["s11spot"] = sp.set_index("datetime")["close"]
    return _MEM["s11spot"]


def s11_bars(exp):
    """The expiry's 15-minute bars (datetime, strike, right, src, OHLCV), cached on disk until a source file changes."""
    files = glob.glob(os.path.join(_exp_dirs()[exp], "*.parquet"))
    files = [f for f in files if ".wide" not in f or exp >= WIDE_FROM]
    os.makedirs(os.path.join(CDIR, "s11"), exist_ok=True)
    cp = os.path.join(CDIR, "s11", f"{exp}.parquet"); sp = cp + ".sig"
    sig = _sig(files)
    if os.path.exists(cp) and os.path.exists(sp) and open(sp).read() == sig: return pd.read_parquet(cp)
    parts = []
    for f in files:
        d = pd.read_parquet(f, columns=["datetime", "strike", "right", "open", "high", "low", "close", "volume"])
        d["right"] = d.right.astype(str); d["src"] = "wide" if ".wide" in f else "reg"
        parts.append(d)
    d = pd.concat(parts, ignore_index=True)
    d = d.sort_values(["datetime", "strike", "right", "src"]).drop_duplicates(["datetime", "strike", "right"], keep="first")
    b = _to15_s11(d[d.volume > 0], ["strike", "right", "src"])
    b.to_parquet(cp, index=False); open(sp, "w").write(sig)
    return b


# ---------------------------------------------------------------- Strategy 11 indicators and structure (engine / structure.py)
def wilder_rsi(c, n=14):
    c = np.asarray(c, float)
    if len(c) < n + 2: return np.full(len(c), np.nan)
    d = np.diff(c); up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = np.full(len(c), np.nan); ad = np.full(len(c), np.nan); au[n] = up[:n].mean(); ad[n] = dn[:n].mean()
    for i in range(n + 1, len(c)):
        au[i] = (au[i - 1] * (n - 1) + up[i - 1]) / n; ad[i] = (ad[i - 1] * (n - 1) + dn[i - 1]) / n
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100 - 100 / (1 + au / ad)
    return np.where((ad == 0) & (au > 0), 100.0, r)


def rainbow(c, depth=10):
    """(top, mid, bottom) of the 10 recursive SMA-2 bands, NaN-aware."""
    s = pd.Series(np.asarray(c, float)); b = []
    for _ in range(depth):
        s = s.rolling(2).mean(); b.append(s.values)
    B = np.vstack(b)
    with np.errstate(all="ignore"), np.testing.suppress_warnings() as w:
        w.filter(RuntimeWarning)
        return np.nanmax(B, 0), np.nanmean(B, 0), np.nanmin(B, 0)


def pivots(h, l, K):
    n = len(h); ph = np.zeros(n, bool); pl = np.zeros(n, bool)
    for i in range(K, n - K):
        w = h[i - K:i + K + 1]
        if h[i] == w.max() and (h[i] > h[i - K:i]).all() and (h[i] >= h[i + 1:i + K + 1]).all(): ph[i] = True
        w = l[i - K:i + K + 1]
        if l[i] == w.min() and (l[i] < l[i - K:i]).all() and (l[i] <= l[i + 1:i + K + 1]).all(): pl[i] = True
    return ph, pl


def walk(h, l, c, K):
    n = len(c); ph, pl = pivots(h, l, K)
    event = np.array([""] * n, dtype=object); lastH = np.full(n, -1); lastL = np.full(n, -1); trend = np.array([""] * n, dtype=object)
    hist_H, hist_L, tr = [], [], ""; curH = curL = armH = armL = -1
    for i in range(n):
        p = i - K
        if p >= 0:
            if ph[p]:
                hist_H.append(p)
                if tr == "" and len(hist_H) >= 2: tr = "up" if h[p] > h[hist_H[-2]] else "down"
                curH = p; armH = p
            if pl[p]:
                hist_L.append(p)
                if tr == "" and len(hist_L) >= 2: tr = "up" if l[p] > l[hist_L[-2]] else "down"
                curL = p; armL = p
        ev = ""
        if tr == "up":
            if armL >= 0 and c[i] < l[armL]: ev = "CHOCH_DN"; tr = "down"; armL = -1
            elif armH >= 0 and c[i] > h[armH]: ev = "BOS_UP"; armH = -1
        elif tr == "down":
            if armH >= 0 and c[i] > h[armH]: ev = "CHOCH_UP"; tr = "up"; armH = -1
            elif armL >= 0 and c[i] < l[armL]: ev = "BOS_DN"; armL = -1
        event[i] = ev; lastH[i] = curH; lastL[i] = curL; trend[i] = tr
    return event, lastH, lastL, trend


DECAY = 0.30; LOT = 65; SLIP = 1.0


def charges_short(sell_px, buy_px, sell_dt):
    v_s = sell_px * LOT; v_b = buy_px * LOT
    stt = (0.001 if str(sell_dt)[:10] >= "2024-10-01" else 0.000625) * v_s
    txn = 0.0005 * (v_s + v_b); sebi = 0.000001 * (v_s + v_b); stamp = 0.00003 * v_b; brok = 40.0
    gst = 0.18 * (brok + txn + sebi)
    return dict(brokerage=brok, stt=stt, exchange=txn, sebi=sebi, stamp=stamp, gst=gst, total=stt + txn + sebi + stamp + brok + gst)


def _s11_exit(h, l, c, TOP, i0, e, start=None):
    armed = False; worst = 0.0
    for j in range((i0 + 1) if start is None else start, len(c)):
        worst = min(worst, e - h[j])
        if not armed and l[j] <= e * (1 - DECAY): armed = True
        if armed:
            if h[j] >= e: return e, "breakeven", j, worst
            if c[j] > TOP[j]: return float(c[j]), "rainbow", j, worst
    return None, "open", None, worst


def _hardstop_exit(o, h, l, c, TOP, i0, e, stop):
    armed = False; worst = 0.0
    for j in range(i0 + 1, len(c)):
        worst = min(worst, e - h[j])
        if stop is not None and h[j] >= stop: return float(max(o[j], stop)), "hard-stop", j, worst
        if not armed and l[j] <= e * (1 - DECAY): armed = True
        if armed:
            if h[j] >= e: return e, "breakeven", j, worst
            if c[j] > TOP[j]: return float(c[j]), "rainbow", j, worst
    return None, "open", None, worst


def _struct_trail(h, c, i0, e, ev, lastH):
    stop = h[lastH[i0]] if lastH[i0] >= 0 else None; worst = 0.0
    for j in range(i0 + 1, len(c)):
        worst = min(worst, e - h[j])
        if stop is not None and c[j] > stop: return float(c[j]), "structure-stop", j, worst
        if ev[j] == "BOS_DN" and lastH[j] >= 0:
            cand = h[lastH[j]]; stop = cand if stop is None else min(stop, cand)
    return None, "open", None, worst


def _armed_struct_exit(h, l, c, i0, e, ev, lastH):
    armed = False; worst = 0.0; stop = None
    for j in range(i0 + 1, len(c)):
        worst = min(worst, e - h[j])
        if ev[j] == "BOS_DN" and lastH[j] >= 0:
            cand = h[lastH[j]]; stop = cand if stop is None else min(stop, cand)
        if not armed and l[j] <= e * (1 - DECAY):
            armed = True
            if lastH[j] >= 0: stop = h[lastH[j]] if stop is None else min(stop, h[lastH[j]])
        if armed:
            if h[j] >= e: return e, "breakeven", j, worst
            if stop is not None and c[j] > stop: return float(c[j]), "bos-trail", j, worst
    return None, "open", None, worst


def s11_expiry(exp, spot):
    """Every short candidate of one monthly expiry, every variant (engine.run_expiry, the short side)."""
    b = s11_bars(exp); E = pd.Timestamp(exp)
    sday = spot[spot.index.normalize() == E.normalize()]
    s_settle = float(sday.iloc[-1]) if len(sday) else np.nan
    out = []
    for (k, r), g in b.groupby(["strike", "right"], sort=False):
        g = g.sort_values("datetime").reset_index(drop=True)
        if len(g) < 40: continue
        k = int(k); o, h, l, c = (g[x].values.astype(float) for x in ("open", "high", "low", "close"))
        rsi = wilder_rsi(c); top, mid, _ = rainbow(c)
        st = {K: walk(h, l, c, K) for K in (3, 5)}
        dts = g.datetime; n = len(g); src = g.src.iloc[0]
        armed = pd.Series(rsi).rolling(5, min_periods=1).max().values >= 70
        rsi10 = pd.Series(rsi).rolling(10, min_periods=1).max().values >= 70
        below = c < mid; s11 = armed & below & np.r_[False, ~below[:-1]] & ~np.isnan(rsi) & ~np.isnan(mid)
        settle = (float(c[-1]) if np.isnan(s_settle) else max(0.0, (s_settle - k) if r == "CE" else (k - s_settle)))
        for i in range(n):
            trig = bool(s11[i]); chs = {K: st[K][0][i] == "CHOCH_DN" for K in (3, 5)}
            if not (trig or chs[3] or chs[5]): continue
            dt = dts.iloc[i]; dte = (E.normalize() - dt.normalize()).days
            if not (22 <= dte <= 35): continue
            s = spot.get(dt)
            if s is None or np.isnan(s): continue
            otm_pts = (k - s) if r == "CE" else (s - k); otm = otm_pts / s
            if not (0.005 <= otm <= 0.04): continue
            px = float(c[i])
            base = dict(exp=exp, strike=k, side=r, src=src, entry_t=dt, sig_px=px, spot=float(s), otm_pts=otm_pts, dte=dte)

            def emit(var, K, e, x, why, xi, worst, stop0=None, fill_t=None):
                if x is None: x, why, xi = settle, "expiry", n - 1
                chg = charges_short(e, x, dt)
                gross = (e - SLIP - (x + SLIP)) * LOT
                out.append(dict(base, var=var, K=K, fill=e, fill_t=fill_t if fill_t is not None else dt, exit_t=dts.iloc[xi], exit_px=float(x),
                                reason=why, gross=gross, chg=chg, net=gross - chg["total"], worst_mtm=worst * LOT, stop0=stop0))
            if trig:
                x, why, xi, w = _s11_exit(h, l, c, top, i, px); emit("A_s11", 0, px, x, why, xi, w)
                if i + 1 < n:
                    e2 = float(o[i + 1]); x, why, xi, w = _s11_exit(h, l, c, top, i + 1, e2)
                    emit("A_nextopen", 0, e2, x, why, xi, w, fill_t=dts.iloc[i + 1])
                for K in (3, 5):
                    ev, lastH, lastL, trend = st[K]
                    stop0 = float(h[lastH[i]]) if lastH[i] >= 0 else None
                    x, why, xi, w = _hardstop_exit(o, h, l, c, top, i, px, stop0); emit("A_hardstop", K, px, x, why, xi, w, stop0)
                    x, why, xi, w = _struct_trail(h, c, i, px, ev, lastH); emit("C_s11_bostrail", K, px, x, why, xi, w, stop0)
                    x, why, xi, w = _armed_struct_exit(h, l, c, i, px, ev, lastH); emit("E_s11_armedbos", K, px, x, why, xi, w, stop0)
                    if trend[i] == "down" or ev[i] == "CHOCH_DN":
                        x, why, xi, w = _s11_exit(h, l, c, top, i, px); emit("D_chochgate", K, px, x, why, xi, w, stop0)
            for K in (3, 5):
                if not chs[K]: continue
                ev, lastH, lastL, trend = st[K]
                stop0 = float(h[lastH[i]]) if lastH[i] >= 0 else None
                x, why, xi, w = _struct_trail(h, c, i, px, ev, lastH); emit("B_choch_bos", K, px, x, why, xi, w, stop0)
                x, why, xi, w = _s11_exit(h, l, c, top, i, px); emit("G_choch_s11", K, px, x, why, xi, w, stop0)
                if rsi10[i]: emit("F_choch_rsi", K, px, x, why, xi, w, stop0)
                x, why, xi, w = _hardstop_exit(o, h, l, c, top, i, px, stop0); emit("G_hardstop", K, px, x, why, xi, w, stop0)
    return out


def s11_candidates():
    """Every expiry's candidates, cached on disk (a pickle keyed by the bar files' signatures)."""
    if "s11c" in _MEM: return _MEM["s11c"]
    import pickle
    spot = s11_spot(); rows = []
    os.makedirs(os.path.join(CDIR, "s11"), exist_ok=True)
    for exp in expiries(True):
        cp = os.path.join(CDIR, "s11", f"{exp}.cand.pkl")
        bsig = os.path.join(CDIR, "s11", f"{exp}.parquet.sig")
        s11_bars(exp)
        sig = open(bsig).read() + "|v1"
        if os.path.exists(cp):
            got = pickle.load(open(cp, "rb"))
            if got[0] == sig: rows += got[1]; continue
        r = s11_expiry(exp, spot)
        pickle.dump((sig, r), open(cp, "wb")); rows += r
    D = pd.DataFrame(rows)
    _MEM["s11c"] = D
    return D


def s11_book(var, K, gate="fixed", universe="clean", slots=2):
    """books.py: the premium gate, the strike universe, then the slots."""
    D = s11_candidates()
    d = D[(D["var"] == var) & (D["K"] == K)]
    if gate == "fixed": m = d.fill.between(246.675, 700.0) & d.sig_px.between(246.675, 700.0)
    else: m = (d.fill / d.spot).between(246.675 / 24000, 700 / 24000) & (d.sig_px / d.spot).between(246.675 / 24000, 700 / 24000)
    d = d[m]
    if universe == "clean": d = d[d.otm_pts <= 250]
    d = d.sort_values(["entry_t", "strike"], kind="mergesort")
    keep = []; free = {"CE": [], "PE": []}
    for t in d.itertuples(index=False):
        f = [z for z in free[t.side] if z > t.entry_t]
        if len(f) >= slots: continue
        free[t.side] = f + [t.exit_t]; keep.append(t)
    return pd.DataFrame(keep, columns=d.columns).reset_index(drop=True)


# ================================================================ Rainbow Book (spec text)
RB_REF = 23700.0


def _bin15(t):
    m = _mins(t); b = ((m - 555) // 15).clip(0, 24)
    return t.dt.normalize() + pd.to_timedelta(555 + b * 15, unit="m")


def rb_spot():
    if "rbspot" in _MEM: return _MEM["rbspot"]
    d = _index_minutes(); m = _mins(d.datetime); d = d[(m >= 555) & (m <= 930)].copy()
    d["bar"] = _bin15(d.datetime)
    s15 = d.groupby("bar")["close"].last()
    d["day"] = d.datetime.dt.normalize()
    sexp = d.groupby("day")["close"].last()                 # the last 1-minute close of each day (09:15 - 15:30)
    _MEM["rbspot"] = (s15, sexp)
    return _MEM["rbspot"]


def rb_bars(exp, wide=False):
    """(15-minute bars, one-minute row count per contract) of one expiry under the Rainbow Book's rules, cached."""
    files = glob.glob(os.path.join(_exp_dirs()[exp], "*.parquet"))
    files = [f for f in files if wide or ".wide" not in f]
    tag = "rbw" if wide else "rb"
    os.makedirs(os.path.join(CDIR, tag), exist_ok=True)
    cp = os.path.join(CDIR, tag, f"{exp}.parquet"); sp = cp + ".sig"; sig = _sig(files)
    if os.path.exists(cp) and os.path.exists(sp) and open(sp).read() == sig: return pd.read_parquet(cp)
    d = pd.concat([pd.read_parquet(f, columns=["datetime", "strike", "right", "open", "high", "low", "close"]) for f in files], ignore_index=True)
    d["right"] = d.right.astype(str)
    m = _mins(d.datetime); d = d[(m >= 555) & (m <= 930)]
    d = d.drop_duplicates(["datetime", "strike", "right"]).sort_values(["strike", "right", "datetime"])
    d = d[d.datetime <= pd.Timestamp(exp) + pd.Timedelta(hours=15, minutes=30)]
    n1 = d.groupby(["strike", "right"], observed=True).size().rename("n1")
    d = d.assign(bar=_bin15(d.datetime))
    g = d.groupby(["strike", "right", "bar"], observed=True, sort=True).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                                                                           close=("close", "last")).reset_index().rename(columns={"bar": "datetime"})
    g = g.merge(n1.reset_index(), on=["strike", "right"])
    g.to_parquet(cp, index=False); open(sp, "w").write(sig)
    return g


def _rsi_ewm(c):
    s = pd.Series(c); dl = s.diff()
    ag = dl.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    al = (-dl.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100 - 100 / (1 + ag / al)
    r = r.where(~((al == 0) & ag.notna()), 100.0)
    return r.values


def rb_costs(fill, exit_px, L=LOT):
    return 40 + 20 + 10.8 + 0.0010 * fill * L + 0.000625 * max(exit_px, 0) * L + 0.00003 * fill * L + 1.0 * L


def rb_candidates(scaled=False, wide=False):
    key = ("rbc", scaled, wide)
    if key in _MEM: return _MEM[key]
    s15, sexp = rb_spot(); s15f = s15.sort_index()
    out = []
    for exp in expiries(False):
        E = pd.Timestamp(exp)
        b = rb_bars(exp, wide)
        if b.empty: continue
        S_exp = sexp.get(E.normalize(), np.nan)
        for (k, r), g in b.groupby(["strike", "right"], sort=False):
            if int(g.n1.iloc[0]) < 80 or len(g) < 40: continue
            g = g.sort_values("datetime").reset_index(drop=True); k = int(k)
            o, h, l, c = (g[x].values.astype(float) for x in ("open", "high", "low", "close"))
            rsi = _rsi_ewm(c); top, _, bot = rainbow(c); width = (top - bot) / c
            arm5 = pd.Series(rsi).rolling(5, min_periods=1).max().values >= 70
            dts = g.datetime
            spot = s15f.reindex(dts, method="ffill").values
            n = len(g)
            for i in range(1, n):
                if not (arm5[i] and not np.isnan(rsi[i]) and rsi[i] < rsi[i - 1] and c[i] < l[i - 1]): continue
                if i + 1 >= n: break
                fill = float(o[i + 1]); S = float(spot[i])
                if np.isnan(S): continue
                f = S / RB_REF if scaled else 1.0
                dte = (E.normalize() - dts.iloc[i].normalize()).days
                otm = ((k - S) / S) if r == "CE" else ((S - k) / S)
                if not (8 <= dte <= 35 and 200 * f <= fill <= 800 * f and 0.005 <= otm <= 0.04 and 30 * f <= c[i] <= 700 * f): continue
                # the first passing signal decides the contract
                if fill > 246.675 * f and rsi[i] < 64.799 and width[i] <= 0.0918:
                    best, armed, res = 0.0, False, None
                    for j in range(i + 1, n):
                        if armed and h[j] >= fill: res = (j, fill, "BE"); break
                        if armed and c[j] > top[j]: res = (j, float(c[j]), "RBW_X"); break
                        best = max(best, 1 - l[j] / fill)
                        if best >= 0.30: armed = True
                    if res is None:
                        x = max(S_exp - k, 0.0) if r == "CE" else max(k - S_exp, 0.0)
                        res = (None, float(x), "EXP")
                    j, x, why = res
                    out.append(dict(exp=exp, strike=k, side=r, sig_t=dts.iloc[i], fill_t=dts.iloc[i + 1], fill=fill, sig_close=float(c[i]),
                                    rsi=float(rsi[i]), width=float(width[i]), spot=S, dte=dte, otm=otm,
                                    exit_t=(dts.iloc[j] if j is not None else E + pd.Timedelta(hours=15, minutes=30)), exit_px=x, reason=why))
                break
    D = pd.DataFrame(out)
    _MEM[key] = D
    return D


def rb_book(scaled=False, wide=False):
    D = rb_candidates(scaled, wide)
    if D.empty: return D
    keep = []
    for side in ("CE", "PE"):
        d = D[D.side == side].sort_values(["fill_t", "fill"], ascending=[True, False], kind="mergesort")
        free = pd.Timestamp.min
        for t in d.itertuples(index=False):
            if t.fill_t >= free: keep.append(t); free = t.exit_t
    B = pd.DataFrame(keep, columns=D.columns).sort_values("fill_t").reset_index(drop=True)
    B["gross"] = (B.fill - B.exit_px) * LOT
    B["costs"] = [rb_costs(f, x) for f, x in zip(B.fill, B.exit_px)]
    B["net"] = B.gross - B.costs
    return B


# ================================================================ the lab
def _ts(x):
    return int(pd.Timestamp(x).value // 10**9)


def run(ctx):
    spec = ctx["spec"]; d0, d1 = ctx["date_from"], ctx["date_to"]; trs = []
    if "s11" in spec:
        P = spec["s11"]; B = s11_book(P["var"], P["K"], P.get("gate", "fixed"), P.get("universe", "clean"), P.get("slots", 2))
        for t in B.itertuples(index=False):
            if not (d0 <= str(t.entry_t)[:10] <= d1): continue
            close_fill = t.var != "A_nextopen"
            et = _ts(t.fill_t) + (900 if close_fill else 0)
            xt = _ts(t.exit_t) + (900 if t.reason in ("rainbow", "structure-stop", "bos-trail") else 0)
            if t.reason == "expiry": xt = _ts(pd.Timestamp(t.exp)) + 15 * 3600 + 30 * 60
            name = f"NIFTY {Dt.date.fromisoformat(t.exp):%d%b%y} {t.strike} {t.side}".upper()
            trs.append(dict(dir="down", signal="BEARISH", choch_time=_ts(t.entry_t), und_entry=t.spot, und_exit=None, stale=False, lots=1, tranche="",
                            position="SHORT", opt_type=t.side, kind="OPT", instrument=name, strike=t.strike, expiry=t.exp, entry_time=et, entry_px=t.fill,
                            exit_time=xt, exit_px=t.exit_px, exit_reason=t.reason, open=False, sl=None if t.stop0 is None or t.stop0 != t.stop0 else float(t.stop0), pts=t.gross / LOT, gross=t.gross, chg=t.chg,
                            net=t.net, label=f"SELL {t.side} · {t.var}{' K' + str(t.K) if t.K else ''} · {t.src}", worst_mtm=float(t.worst_mtm)))
    else:
        P = spec["rb"]; B = rb_book(P.get("scaled", False), P.get("wide", False))
        for t in B.itertuples(index=False):
            if not (d0 <= str(t.fill_t)[:10] <= d1): continue
            xt = _ts(t.exit_t) + (900 if t.reason == "RBW_X" else 0) if t.reason != "EXP" else _ts(t.exit_t)
            name = f"NIFTY {Dt.date.fromisoformat(t.exp):%d%b%y} {t.strike} {t.side}".upper()
            c = rb_costs(t.fill, t.exit_px)
            trs.append(dict(dir="down", signal="BEARISH", choch_time=_ts(t.sig_t), und_entry=t.spot, und_exit=None, stale=False, lots=1, tranche="",
                            position="SHORT", opt_type=t.side, kind="OPT", instrument=name, strike=t.strike, expiry=t.exp, entry_time=_ts(t.fill_t),
                            entry_px=t.fill, exit_time=xt, exit_px=t.exit_px, exit_reason=t.reason, open=False, sl=None, pts=t.gross / LOT,
                            gross=t.gross, chg=dict(total=c), net=t.net, label=f"SELL {t.side} · RSI {t.rsi:.1f} · width {t.width:.3f}"))
    trs.sort(key=lambda x: x["entry_time"])
    return {ch: dict(trades=trs, skipped=[], signals=[]) for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL")}


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """The traded contract's own 15-minute bars (the first trade entered in the range, else the latest one open by then) with
    the rainbow top / mid / bottom, and every trade on that contract."""
    spec = ctx["spec"]; C = {k: i for i, k in enumerate(body["cols"])}
    rows = body["trades"]
    pick = next((x for x in rows if day <= str(x[C["entry_time"]])[:10] <= to), None)
    if pick is None:
        live = [x for x in rows if str(x[C["entry_time"]])[:10] <= to and str(x[C["exit_time"]])[:10] >= day]
        pick = live[-1] if live else None
    if pick is None: raise ValueError(f"no trade open between {day} and {to}")
    exp, k, r = str(pick[C["expiry"]]), int(pick[C["strike"]]), str(pick[C["opt_type"]])
    if "s11" in spec:
        g = s11_bars(exp)
    else:
        g = rb_bars(exp, spec["rb"].get("wide", False))
    g = g[(g.strike == k) & (g.right == r)].sort_values("datetime").reset_index(drop=True)
    c = g.close.values.astype(float); top, mid, bot = rainbow(c)
    dd = g.datetime.dt.strftime("%Y-%m-%d")
    first = max(day, str(pick[C["entry_time"]])[:10]) if False else day
    sel = np.nonzero(((dd >= first) & (dd <= to)).values)[0]
    if not len(sel): sel = np.nonzero((dd >= str(pick[C["entry_time"]])[:10]).values)[0][:50]
    candles, L = [], [[], [], []]
    for i in sel:
        tt = _ts(g.datetime.iloc[i])
        candles.append([tt, float(g.open.iloc[i]), float(g.high.iloc[i]), float(g.low.iloc[i]), float(c[i]), 0.0])
        for n_, arr in enumerate((top, mid, bot)):
            if np.isfinite(arr[i]): L[n_].append([tt, round(float(arr[i]), 2)])
    nm = f"NIFTY {Dt.date.fromisoformat(exp):%d%b%y} {k} {r}".upper()
    trades = [x for x in rows if str(x[C["instrument"]]) == nm]
    return dict(day=day, to=to, inst=nm, candles=candles, cols=body["cols"], trades=trades, own=True, lines=L,
                line_names=["rainbow top", "rainbow mid", "rainbow bottom"], line_colors=["#e5484d", "#f5a524", "#30a46c"],
                sessions=len(set(dd.iloc[sel])) if len(sel) else 1, derived=dict(what=f"{nm}, 15-minute bars, with its rainbow"))
