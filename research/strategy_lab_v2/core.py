"""Strategy lab v2: everything the strategies share, in one file.

    data        candle files -> numpy arrays, cached under cache/ (a CSV is parsed once, then loads in milliseconds)
    engine      the Foundation engine (swings -> protected level -> CHoCH / BOS -> AVWAP pair -> SETUP -> trades),
                compiled with numba; the same rules as v1 engine.py, decision for decision
    options     option chain (expiry calendar, per-expiry files cached as numpy), strike picking, coverage
    positions   strike lock, scale-out tranches, square-off, contract expiry, excursion, slippage, charges, stats
    runner      one strategy x one backtest window x one type -> priced trades per choice
    results     results/<CODE>/<run>/meta.json + <TYPE>/<choice>.json, and day charts computed on request

A strategy is a file in strategies/ (SPEC + signals()); the UI (ui/) and the server (server.py) only read what this
module writes. Times are int64 seconds of the exchange wall clock read as UTC (v1's ts()), so a day is t // 86400.
Nothing here places orders or touches a broker.
"""
import os, sys, json, glob, math, re, bisect, hashlib, importlib.util, datetime as D, time as _time
import numpy as np
import pandas as pd
from numba import njit

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
RESULTS = os.path.join(HERE, "results")
STRATDIR = os.path.join(HERE, "strategies")
DATA = json.load(open(os.path.join(HERE, "config", "data.json"), encoding="utf-8"))
CHARGES = {k: v for k, v in json.load(open(os.path.join(HERE, "config", "charges.json"), encoding="utf-8")).items()
           if not k.startswith("_")}
FUT1, FUT5 = DATA["futures"]["minute"], DATA["futures"]["5minute"]
SPOT1, SPOT5 = DATA["spot"]["minute"], DATA["spot"]["5minute"]

TF_MIN = {"minute": 1, "3minute": 3, "5minute": 5, "15minute": 15, "30minute": 30, "60minute": 60}
TF_LABEL = {"minute": "1m", "3minute": "3m", "5minute": "5m", "15minute": "15m", "30minute": "30m", "60minute": "1h"}
# (type, v1 code suffix, label)
TYPES = (("FUT", "", "Futures"), ("OPT_FUT_SIGNAL", "_FB", "Options (via futures)"), ("OPT_NATIVE", "_NB", "Options (standalone)"))
PRESETS = ("MTD", "1M", "3M", "6M", "YTD", "1Y", "5Y")
POSITION_DEFAULT = {"lots": 1, "lock": "strike", "scale_out": [], "exit": "strategy", "stop": None, "trail": None,
                    "square_off": None, "reverse": None}
NATIVE_SCAN_DEFAULT = {"choices": ["ATR2", "ATM", "ITM1", "OTM1"], "every_minutes": 5, "one_per_side": True}
INDEX_WHY_NATIVE = "standalone options run on each option's own candles; the signal source does not apply"
DAY = 86400


# ================================================================ time helpers
def ts(s):
    """'YYYY-MM-DD[ HH:MM:SS]' -> int seconds (wall clock read as UTC)."""
    return int(np.datetime64(s.replace(" ", "T"), "s").astype(np.int64))


def tstr(x):
    return str(np.datetime64(int(x), "s")).replace("T", " ")


def dstr(day):
    return str(np.datetime64(int(day), "D"))


def dnum(s):
    return int(np.datetime64(s[:10], "D").astype(np.int64))


def tstrs(arr):
    return np.char.replace(np.datetime_as_string(np.asarray(arr, dtype="datetime64[s]")).astype("U19"), "T", " ")


def hhmm_sec(s):
    return int(s[:2]) * 3600 + int(s[3:5]) * 60


# ================================================================ data
class Bars:
    """Candles of one instrument: t (int64 s), o h l c v (float64), day (int64)."""
    __slots__ = ("t", "o", "h", "l", "c", "v", "day", "extra", "_ix")

    def __init__(self, t, o, h, l, c, v, extra=None):
        self.t = np.ascontiguousarray(t, dtype=np.int64)
        self.o, self.h, self.l, self.c, self.v = (np.ascontiguousarray(x, dtype=np.float64) for x in (o, h, l, c, v))
        self.day = self.t // DAY
        self.extra = extra or {}
        self._ix = None

    def __len__(self):
        return len(self.t)

    def slice(self, i0, i1):
        """bars[i0:i1] (end exclusive)."""
        return Bars(self.t[i0:i1], self.o[i0:i1], self.h[i0:i1], self.l[i0:i1], self.c[i0:i1], self.v[i0:i1])

    def find(self, when):
        """Index of the candle at exactly `when`, else -1."""
        i = int(np.searchsorted(self.t, when))
        return i if i < len(self.t) and self.t[i] == when else -1

    def at(self, when):
        """(close at `when`, else the last close earlier the same day (stale), else None; stale flag)."""
        i = self.find(when)
        if i >= 0: return float(self.c[i]), False
        j = int(np.searchsorted(self.t, when, "right")) - 1
        if j >= 0 and self.day[j] == when // DAY: return float(self.c[j]), True
        return None, False


def _sig(paths):
    h = hashlib.sha1()
    for p in paths:
        if os.path.exists(p): h.update(f"{p}:{os.path.getsize(p)}:{int(os.path.getmtime(p))}".encode())
    return h.hexdigest()[:16]


def _read_csv(path, cols, strike=False):
    """A candle CSV as columns. Floats parsed round-trip (bit-identical to Python's float(), as v1 reads them)."""
    df = pd.read_csv(path, float_precision="round_trip", dtype={"datetime": str}, keep_default_na=True)
    out = {"t": pd.to_datetime(df["datetime"], format="%Y-%m-%d %H:%M:%S").values.astype("datetime64[s]").astype(np.int64)}
    for k in ("open", "high", "low", "close"): out[k] = df[k].astype(np.float64).values
    out["volume"] = df["volume"].fillna(0).astype(np.float64).values if "volume" in df else np.zeros(len(df))
    if strike: out["strike"] = df["strike_price"].astype(np.float64).astype(np.int64).values
    for k in cols:
        if k in df: out[k] = df[k].fillna("").astype(str).values.astype("U")
    return out


_BARS = {}
def load_file(path):
    """Whole candle file as Bars, via a numpy cache (cache/csv/<name>.<signature>.npz)."""
    if path in _BARS: return _BARS[path]
    os.makedirs(os.path.join(CACHE, "csv"), exist_ok=True)
    npz = os.path.join(CACHE, "csv", f"{os.path.basename(path)}.{_sig([path])}.npz")
    if os.path.exists(npz):
        z = np.load(npz, allow_pickle=False)
        d = {k: z[k] for k in z.files}
    else:
        d = _read_csv(path, ("contract", "expiry", "front_month"))
        np.savez(npz, **d)
    extra = {k: d[k] for k in ("contract", "expiry", "front_month") if k in d}
    b = Bars(d["t"], d["open"], d["high"], d["low"], d["close"], d["volume"], extra)
    _BARS[path] = b
    return b


@njit(cache=True)
def _resample(t, o, h, l, c, v, minutes):
    """Candles -> `minutes` candles aligned to 09:15 (v1 resample_rows: consecutive rows with the same bucket)."""
    n = len(t)
    keys = np.empty(n, np.int64)
    for i in range(n):
        tod = t[i] % 86400
        m = tod // 60
        b = 555 + ((m - 555) // minutes) * minutes
        keys[i] = t[i] - tod + b * 60
    ot = np.empty(n, np.int64); oo = np.empty(n); oh = np.empty(n); ol = np.empty(n); oc = np.empty(n); ov = np.empty(n)
    k = -1
    for i in range(n):
        if k < 0 or keys[i] != ot[k]:
            k += 1
            ot[k] = keys[i]; oo[k] = o[i]; oh[k] = h[i]; ol[k] = l[i]; oc[k] = c[i]; ov[k] = v[i]
        else:
            if h[i] > oh[k]: oh[k] = h[i]
            if l[i] < ol[k]: ol[k] = l[i]
            oc[k] = c[i]; ov[k] = ov[k] + v[i]
    k += 1
    return ot[:k], oo[:k], oh[:k], ol[:k], oc[:k], ov[:k]


def resample(b, minutes, cut_1529=False):
    if cut_1529:
        keep = (b.t % DAY) <= 15 * 3600 + 29 * 60 + 59
        b = Bars(b.t[keep], b.o[keep], b.h[keep], b.l[keep], b.c[keep], b.v[keep])
    return Bars(*_resample(b.t, b.o, b.h, b.l, b.c, b.v, minutes))


_TF = {}
def series(kind, tf):
    """Futures ('fut') or index ('spot') candles at timeframe tf: the 1- and 5-minute files as given, other timeframes
    resampled from the 1-minute file (rows after 15:29 dropped first, as v1's tf_file does)."""
    key = (kind, tf)
    if key not in _TF:
        b1, b5 = (FUT1, FUT5) if kind == "fut" else (SPOT1, SPOT5)
        if tf == "minute": _TF[key] = load_file(b1)
        elif tf == "5minute": _TF[key] = load_file(b5)
        else: _TF[key] = resample(load_file(b1), TF_MIN[tf], cut_1529=True)
    return _TF[key]


def window(b, date_from, date_to, warmup_days):
    """(bars from `warmup_days` sessions before date_from to date_to, index of the first shown candle) - v1 engine.window."""
    d0, d1 = dnum(date_from), dnum(date_to)
    days = np.unique(b.day[b.day <= d1])
    shown = days[days >= d0]
    if not len(shown): raise ValueError(f"no data from {date_from}")
    k = int(np.searchsorted(days, shown[0]))
    start = days[max(0, k - warmup_days)]
    i0 = int(np.searchsorted(b.day, start)); i1 = int(np.searchsorted(b.day, d1, "right"))
    w = b.slice(i0, i1)
    s0 = int(np.searchsorted(w.day, d0))
    return w, s0


_SESS = {}
def sessions():
    """Trading sessions (day numbers) in the 1-minute futures file, from history_from."""
    if "d" not in _SESS:
        d = np.unique(load_file(FUT1).day)
        if DATA.get("history_from"): d = d[d >= dnum(DATA["history_from"])]
        _SESS["d"] = d
    return _SESS["d"]


_KNOWN = {}
def known_sessions():
    """Every session in the futures file and the long index 5-minute files under the data root (holiday-aware expiries)."""
    if "d" not in _KNOWN:
        days = set(int(x) for x in sessions())
        root = os.path.dirname(os.path.normpath(DATA["options"]["weekly_dir"]))
        for f in glob.glob(os.path.join(root, "nifty50_5minute_*.csv")):
            if " - Copy" not in f: days |= set(int(x) for x in np.unique(load_file(f).day))
        _KNOWN["d"] = days
    return _KNOWN["d"]


_FC = {}
def fut_contracts():
    """(1-minute futures times, contract per time, expiry per time ('' = none), {contract: last time})."""
    if "x" not in _FC:
        b = load_file(FUT1)
        con = b.extra.get("contract"); exp = b.extra.get("expiry")
        con = np.where(con == "", "NIFTY FUT", con) if con is not None else np.full(len(b), "NIFTY FUT")
        exp = exp if exp is not None else np.full(len(b), "")
        last = {}
        for i, cc in enumerate(con): last[cc] = int(b.t[i])
        _FC["x"] = (b.t, con, exp, last)
    return _FC["x"]


# ================================================================ engine (numba)
@njit(cache=True)
def _below(touch, l, c, i, lvl):
    return l[i] <= lvl if touch else c[i] < lvl


@njit(cache=True)
def _above(touch, h, c, i, lvl):
    return h[i] >= lvl if touch else c[i] > lvl


@njit(cache=True)
def _av(cum, cw, tp, a, i):
    if cw[i + 1] > cw[a]: return (cum[i + 1] - cum[a]) / (cw[i + 1] - cw[a])
    return tp[a]


@njit(cache=True)
def _engine(o, h, l, c, w, day, touch, ch_touch, sl_rule):
    """The Foundation engine (v1 engine.run) on arrays. sl_rule: 0 none, 1 choch_candle, 2 prev_swing.
    Swing kind: 1 = H, -1 = L. Exit reason: 0 next_choch, 1 open, 2 stop_loss."""
    n = len(h)
    # ---- swings (Pine port; confirmation by break_mode) ----
    sk = np.empty(n, np.int8); sb = np.empty(n, np.int64); sp = np.empty(n); sc = np.empty(n, np.int64)
    candh = np.full(n, np.nan); candl = np.full(n, np.nan)
    ns = 0; mode = 0
    has_ch = False; chv = 0.0; chb = -1
    has_cl = False; clv = 0.0; clb = -1
    for i in range(n):
        he = mode == 0 or mode == 1
        le = mode == 0 or mode == -1
        if he and ((not has_ch) or h[i] >= chv):
            chv = h[i]; chb = i; has_ch = True
        if le and ((not has_cl) or l[i] <= clv):
            clv = l[i]; clb = i; has_cl = True
        sh = he and has_ch and i > chb and _below(touch, l, c, i, l[chb])
        sl = le and has_cl and i > clb and _above(touch, h, c, i, h[clb])
        if mode == 0 and sh and sl:
            if clb < chb: sh = False
            else: sl = False
        if sh:
            sk[ns] = 1; sb[ns] = chb; sp[ns] = chv; sc[ns] = i; ns += 1
            mode = -1; has_ch = False; chb = -1; clv = l[i]; clb = i; has_cl = True
        if sl:
            sk[ns] = -1; sb[ns] = clb; sp[ns] = clv; sc[ns] = i; ns += 1
            mode = 1; has_cl = False; clb = -1; chv = h[i]; chb = i; has_ch = True
        if he and has_ch: candh[i] = chv
        if le and has_cl: candl[i] = clv

    # ---- AVWAP from any anchor bar ----
    tp = np.empty(n); cum = np.zeros(n + 1); cw = np.zeros(n + 1)
    for i in range(n):
        tp[i] = (h[i] + l[i] + c[i]) / 3
    for i in range(n):
        cum[i + 1] = cum[i] + tp[i] * w[i]; cw[i + 1] = cw[i] + w[i]

    # ---- trend, protected level, CHoCH / BOS ----
    broken = np.zeros(ns, np.bool_); bos_used = np.zeros(ns, np.bool_)
    unb = np.empty(ns, np.int64); nunb = 0
    cands = np.empty(ns, np.int64); ncand = 0
    prot = np.full(n, np.nan)
    trend = 0; anchor = -1; lastH = -1; lastL = -1
    # events: kind 0 BOS, 1 CHoCH; dir 1 up, -1 down
    ei = np.empty(2 * n, np.int64); ek = np.empty(2 * n, np.int8); ed = np.empty(2 * n, np.int8); ne = 0
    qi = np.empty(n, np.int64); qd = np.empty(n, np.int8); qflip = np.empty(n, np.bool_); qlvl = np.empty(n)
    qsw = np.empty(n, np.int64); qav = np.empty(n); qtr = np.empty(n, np.int8); qhi = np.empty(n, np.int64)
    qlo = np.empty(n, np.int64); nq = 0
    nxt = 0
    for i in range(n):
        if anchor >= 0:
            ab = sb[anchor]
            v = _av(cum, cw, tp, ab, i)
            P = -1
            for q in range(ncand - 1, -1, -1):
                if not broken[cands[q]]:
                    P = cands[q]; break
            if P >= 0: prot[i] = sp[P]
            if trend == 1 and lastH >= 0 and not bos_used[lastH] and _above(touch, h, c, i, sp[lastH]):
                bos_used[lastH] = True; ei[ne] = i; ek[ne] = 0; ed[ne] = 1; ne += 1
            if trend == -1 and lastL >= 0 and not bos_used[lastL] and _below(touch, l, c, i, sp[lastL]):
                bos_used[lastL] = True; ei[ne] = i; ek[ne] = 0; ed[ne] = -1; ne += 1
            if P >= 0 and ((trend == 1 and _below(ch_touch, l, c, i, sp[P])) or (trend == -1 and _above(ch_touch, h, c, i, sp[P]))):
                fl = (trend == 1 and _below(ch_touch, l, c, i, v)) or (trend == -1 and _above(ch_touch, h, c, i, v))
                fl = fl and ((lastH if trend == 1 else lastL) >= 0)
                ei[ne] = i; ek[ne] = 1; ed[ne] = -1 if trend == 1 else 1; ne += 1
                qi[nq] = i; qd[nq] = -1 if trend == 1 else 1; qflip[nq] = fl; qlvl[nq] = sp[P]; qsw[nq] = P
                qav[nq] = v; qtr[nq] = trend; qhi[nq] = lastH; qlo[nq] = lastL; nq += 1
                if fl:
                    if lastL >= 0: bos_used[lastL] = True
                    if lastH >= 0: bos_used[lastH] = True
                    trend = -trend
                    anchor = lastH if trend == -1 else lastL
                    ab = sb[anchor]
                    ncand = 0
                    # rebuild: confirmed before i, unbroken, anchored at or after the new anchor, qualifying.
                    # sb[s] >= ab implies sc[s] > ab, so the scan starts at the first swing confirmed after ab.
                    s = np.searchsorted(sc[:ns], ab, "right")
                    while s < ns and sc[s] < i:
                        if (not broken[s]) and sb[s] >= ab:
                            a = _av(cum, cw, tp, ab, sc[s])
                            if (trend == 1 and sk[s] == -1 and sp[s] < a) or (trend == -1 and sk[s] == 1 and sp[s] > a):
                                cands[ncand] = s; ncand += 1
                        s += 1
        # swings touched / closed through by this candle are used up
        k = 0
        for q in range(nunb):
            s = unb[q]
            if (sk[s] == -1 and _below(touch, l, c, i, sp[s])) or (sk[s] == 1 and _above(touch, h, c, i, sp[s])):
                broken[s] = True
            else:
                unb[k] = s; k += 1
        nunb = k
        while nxt < ns and sc[nxt] == i:
            s = nxt; nxt += 1
            if sk[s] == 1: lastH = s
            else: lastL = s
            unb[nunb] = s; nunb += 1
            if anchor < 0:
                trend = -1 if sk[s] == 1 else 1
                anchor = s
                a = _av(cum, cw, tp, sb[s], sc[s])
                ok = (trend == 1 and sk[s] == -1 and sp[s] < a) or (trend == -1 and sk[s] == 1 and sp[s] > a)
                ncand = 0
                if ok:
                    cands[0] = s; ncand = 1
            elif sb[s] >= sb[anchor]:
                a = _av(cum, cw, tp, sb[anchor], sc[s])
                if (trend == 1 and sk[s] == -1 and sp[s] < a) or (trend == -1 and sk[s] == 1 and sp[s] > a):
                    cands[ncand] = s; ncand += 1

    # ---- AVWAP pair per CHoCH + SETUP ----
    qend = np.empty(nq, np.int64)
    ui = np.empty(nq, np.int64); ud = np.empty(nq, np.int8); uch = np.empty(nq, np.int64); nu = 0
    for j in range(nq):
        end = qi[j + 1] if j + 1 < nq else n - 1
        qend[j] = end
        if qhi[j] < 0 or qlo[j] < 0: continue
        aH = sb[qhi[j]]; aL = sb[qlo[j]]; ci = qi[j]
        mx = aH if aH > aL else aL
        for k in range(ci + 1, end + 1):
            if k - 1 <= mx: continue
            dH = _av(cum, cw, tp, aH, k) - _av(cum, cw, tp, aH, k - 1)
            dL = _av(cum, cw, tp, aL, k) - _av(cum, cw, tp, aL, k - 1)
            if (qd[j] == -1 and c[k] < l[ci] and dH < 0 and dL < 0) or (qd[j] == 1 and c[k] > h[ci] and dH > 0 and dL > 0):
                ui[nu] = k; ud[nu] = qd[j]; uch[nu] = ci; nu += 1
                break

    # ---- trades ----
    te = np.empty(nu, np.int64); tx = np.empty(nu, np.int64); tpx = np.empty(nu); tdir = np.empty(nu, np.int8)
    tch = np.empty(nu, np.int64); tsl = np.empty(nu); tpts = np.empty(nu); trs = np.empty(nu, np.int8); nt = 0
    ke = np.empty(nu, np.int64); kd = np.empty(nu, np.int8); ksl = np.empty(nu); nk = 0
    for x in range(nu):
        k0 = ui[x]; ci = uch[x]; up = ud[x] == 1
        sg = 1.0 if up else -1.0
        slv = np.nan
        if sl_rule == 1:
            slv = l[ci] if up else h[ci]
        elif sl_rule == 2:
            want = -1 if up else 1
            j = np.searchsorted(sc[:ns], k0, "right") - 1
            while j >= 0 and sk[j] != want: j -= 1
            if j >= 0: slv = sp[j]
        if not np.isnan(slv) and ((slv >= c[k0]) if up else (slv <= c[k0])):
            ke[nk] = k0; kd[nk] = ud[x]; ksl[nk] = slv; nk += 1
            continue
        nx = -1
        for j in range(nq):
            if qi[j] > k0:
                nx = qi[j]; break
        last = nx if nx >= 0 else n - 1
        xi = last; px = c[last]; reason = 0 if nx >= 0 else 1
        if not np.isnan(slv):
            for k in range(k0 + 1, last + 1):
                gap = (o[k] <= slv) if up else (o[k] >= slv)
                hit = _below(touch, l, c, k, slv) if up else _above(touch, h, c, k, slv)
                if gap or hit:
                    xi = k; reason = 2
                    if day[k] != day[k - 1]:
                        px = c[k]
                    else:
                        px = o[k] if (gap and touch) else (slv if touch else c[k])
                    break
        te[nt] = k0; tx[nt] = xi; tpx[nt] = px; tdir[nt] = ud[x]; tch[nt] = ci; tsl[nt] = slv
        tpts[nt] = sg * (px - c[k0]); trs[nt] = reason; nt += 1
    return (sk[:ns], sb[:ns], sp[:ns], sc[:ns], candh, candl, prot, cum, cw, tp,
            ei[:ne], ek[:ne], ed[:ne],
            qi[:nq], qd[:nq], qflip[:nq], qlvl[:nq], qsw[:nq], qav[:nq], qtr[:nq], qhi[:nq], qlo[:nq], qend,
            ui[:nu], ud[:nu], uch[:nu],
            te[:nt], tx[:nt], tpx[:nt], tdir[:nt], tch[:nt], tsl[:nt], tpts[:nt], trs[:nt],
            ke[:nk], kd[:nk], ksl[:nk])


REASONS = ("next_choch", "open", "stop_loss")
SL_RULES = {"none": 0, "choch_candle": 1, "prev_swing": 2}


class Signals:
    """What a strategy's signals() returns: the engine's view of one window, as arrays.
    trades: entry / exit bar, exit_px, dir (+1 up / -1 down), choch bar, sl (nan = none), pts, reason (REASONS);
    the rest feeds the signal list and the chart overlays."""

    def __init__(self, bars, out):
        (self.sk, self.sb, self.sp, self.sc, self.candh, self.candl, self.prot, self._cum, self._cw, self._tp,
         self.ei, self.ek, self.ed,
         self.qi, self.qd, self.qflip, self.qlvl, self.qsw, self.qav, self.qtr, self.qhi, self.qlo, self.qend,
         self.ui, self.ud, self.uch,
         self.te, self.tx, self.tpx, self.tdir, self.tch, self.tsl, self.tpts, self.trs,
         self.ke, self.kd, self.ksl) = out
        self.bars = bars
        self.custom, self.lines = None, None

    def av(self, a, i):
        return float(_av(self._cum, self._cw, self._tp, a, i))

    def with_trades(self, trades, lines=None):
        """A copy whose trades are a strategy's own (dicts in the trades() shape) instead of the engine's SETUP trades;
        the engine's structure stays for the CHoCH list and the chart. `lines`: extra overlay lines (lines x candles)."""
        s = object.__new__(Signals); s.__dict__.update(self.__dict__)
        s.custom, s.lines = trades, lines
        s.ui = s.ud = s.uch = np.empty(0, np.int64)        # the engine's SETUPs did not open these trades
        return s

    def trades(self):
        """Trades as dicts (bar indices), v1 engine.run's trade shape."""
        if self.custom is not None: return [dict(x) for x in self.custom]
        return [dict(entry=int(self.te[k]), exit=int(self.tx[k]), exit_px=float(self.tpx[k]),
                     dir="up" if self.tdir[k] == 1 else "down", choch=int(self.tch[k]),
                     sl=None if np.isnan(self.tsl[k]) else float(self.tsl[k]), pts=float(self.tpts[k]),
                     open=self.trs[k] == 1, exit_reason=REASONS[self.trs[k]]) for k in range(len(self.te))]


def foundation(bars, rules, avwap_weight=None):
    """The Foundation engine on `bars` with a strategy's `rules` (break_mode, choch_mode, avwap_weight, sl_rule)."""
    touch = rules["break_mode"] == "touch"
    ch_touch = (rules.get("choch_mode") or rules["break_mode"]) == "touch"
    w = bars.v if (avwap_weight or rules["avwap_weight"]) == "volume" else np.ones(len(bars))
    return Signals(bars, _engine(bars.o, bars.h, bars.l, bars.c, np.ascontiguousarray(w, dtype=np.float64), bars.day,
                                 touch, ch_touch, SL_RULES[rules.get("sl_rule", "none")]))


# ================================================================ indicators
@njit(cache=True)
def _atr(h, l, c, n):
    out = np.empty(len(h)); a = 0.0; s = 0.0
    for i in range(len(h)):
        tr = h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        s += tr
        a = s / (i + 1) if i < n else (a * (n - 1) + tr) / n      # simple mean until n candles, then Wilder
        out[i] = a
    return out


_ATR = {}
def atr(b, n):
    key = (id(b), n)
    if key not in _ATR: _ATR[key] = _atr(b.h, b.l, b.c, n)
    return _ATR[key]


def pick_strike(choice, side, spot, atr_v, step):
    """Strike from spot at decision time. OTM = away from spot (CE above, PE below)."""
    rnd = lambda x: round(x / step) * step
    sg = 1 if side == "CE" else -1
    if choice.startswith("ATR"):
        return rnd(spot + sg * float(choice[3:]) * atr_v)
    a = rnd(spot)
    if choice == "ATM": return a
    k = int(choice[3:])
    return a + sg * k * step if choice.startswith("OTM") else a - sg * k * step


# ================================================================ options
def monthly_expiry(ym):
    """NIFTY monthly expiry of 'YYYY-MM': last Thursday up to Aug 2025, last Tuesday from Sep 2025, moved to the session
    before when that day is a holiday (where the candle files know the sessions)."""
    y, m = int(ym[:4]), int(ym[5:7])
    d = D.date(y + (m == 12), m % 12 + 1, 1) - D.timedelta(days=1)
    wd = 3 if (y, m) < (2025, 9) else 1
    while d.weekday() != wd: d -= D.timedelta(days=1)
    days = known_sessions()
    if days and dnum(d.isoformat()) <= max(days):
        while dnum(d.isoformat()) not in days and d.month == m: d -= D.timedelta(days=1)
    return d.isoformat()


class OptionChain:
    """Option candles by (expiry, strike, CE/PE) at one timeframe. Local ICICI weekly files (one combined CSV per expiry and
    right plus per-strike chunk files, later files win) and the Kite chain for the Kite expiry. The local files hold only
    strikes near the settlement ATM, so they are used for prices only: the strike always comes from spot at decision time
    and a strike not in the file is reported missing, never replaced."""
    _shared = {}

    def __new__(cls, tf):
        if tf not in cls._shared:
            self = super().__new__(cls); self._init(tf); cls._shared[tf] = self
        return cls._shared[tf]

    def _init(self, tf):
        o = DATA["options"]
        self.tf, self.local, self.kite, self.kite_exp, self.pre = tf, o["weekly_dir"], o["kite_dir"], o["kite_expiry"], o["kite_prefix"]
        self.base = "minute" if tf in ("minute", "3minute") else "5minute"
        self.sub = "nifty_options" if self.base == "5minute" else "nifty_options_1minute"
        self.root = os.path.join(self.local, self.sub)
        cal = {self.kite_exp}
        for y in os.listdir(self.root) if os.path.isdir(self.root) else []:
            if y.isdigit(): cal |= {e for e in os.listdir(os.path.join(self.root, y)) if len(e) == 10}
        self.calendar = sorted(cal)
        self.cal_days = np.array([dnum(e) for e in self.calendar], dtype=np.int64)
        months = sorted({monthly_expiry(e[:7]) for e in self.calendar})
        self.monthly, self.monthly_days = months, np.array([dnum(e) for e in months], dtype=np.int64)
        self._rights, self._cache, self._exp = {}, {}, {}

    def expiry_for(self, day, min_days, kind="WEEKLY"):
        """Nearest expiry of `kind` at least min_days calendar days after `day` (a day number)."""
        key = (day, min_days, kind)
        if key not in self._exp:
            cal, cd = (self.monthly, self.monthly_days) if kind == "MONTHLY" else (self.calendar, self.cal_days)
            j = int(np.searchsorted(cd, day + min_days))
            self._exp[key] = cal[j] if j < len(cal) else None
        return self._exp[key]

    def _local_right(self, expiry, right):
        """{strike: (start, end)} rows of one expiry and right in a cached numpy table (cache/opt/...)."""
        key = (expiry, right)
        if key in self._rights: return self._rights[key]
        base = os.path.join(self.root, expiry[:4], expiry)
        files = [os.path.join(base, f"NIFTY_{expiry}_{right}_{'5minute' if self.base == '5minute' else '1minute'}.csv")]
        files += sorted(glob.glob(os.path.join(base, ".chunks", "options", right, "*", "*.csv")))
        files = [f for f in files if os.path.exists(f)]
        tab = None
        if files:
            os.makedirs(os.path.join(CACHE, "opt"), exist_ok=True)
            npz = os.path.join(CACHE, "opt", f"{self.sub}_{expiry}_{right}.{_sig(files)}.npz")
            if os.path.exists(npz):
                z = np.load(npz); tab = {k: z[k] for k in z.files}
            else:
                parts = []
                for n_, f in enumerate(files):
                    d = _read_csv(f, (), strike=True)
                    parts.append(pd.DataFrame(dict(strike=d["strike"], t=d["t"], o=d["open"], h=d["high"], l=d["low"],
                                                   c=d["close"], v=d["volume"], seq=n_)))
                df = pd.concat(parts, ignore_index=True)
                df = df[(df["t"] % DAY) <= 15 * 3600 + 29 * 60 + 59]
                df = df.drop_duplicates(["strike", "t"], keep="last").sort_values(["strike", "t"], kind="mergesort")
                tab = {k: df[k].values for k in ("strike", "t", "o", "h", "l", "c", "v")}
                np.savez(npz, **tab)
        idx = {}
        if tab is not None and len(tab["strike"]):
            ks, starts = np.unique(tab["strike"], return_index=True)
            ends = list(starts[1:]) + [len(tab["strike"])]
            idx = {int(k): (int(a), int(b)) for k, a, b in zip(ks, starts, ends)}
        while len(self._rights) >= 60: del self._rights[next(iter(self._rights))]
        self._rights[key] = (tab, idx)
        return self._rights[key]

    def get(self, expiry, strike, right):
        """Bars of one contract at the chain's timeframe, or None."""
        key = (expiry, int(strike), right)
        if key in self._cache: return self._cache[key]
        s = None
        if expiry == self.kite_exp:
            p = os.path.join(self.kite, self.base, f"{self.pre}{int(strike)}{right}.csv")
            if os.path.exists(p) and os.path.getsize(p) > 100:
                s = load_file(p)
        else:
            tab, idx = self._local_right(expiry, right)
            if int(strike) in idx:
                a, b = idx[int(strike)]
                s = Bars(tab["t"][a:b], tab["o"][a:b], tab["h"][a:b], tab["l"][a:b], tab["c"][a:b], tab["v"][a:b])
        if s is not None and TF_MIN[self.tf] != TF_MIN[self.base]: s = resample(s, TF_MIN[self.tf])
        if s is not None and not len(s): s = None
        while len(self._cache) >= 2000: del self._cache[next(iter(self._cache))]
        self._cache[key] = s
        return s

    @staticmethod
    def name(expiry, strike, right):
        return f"NIFTY {D.date.fromisoformat(expiry):%d%b%y} {int(strike)} {right}".upper()


def prepare(log=print):
    """Parse every candle file and every option expiry into cache/ ahead of the first backtest."""
    t0 = _time.time()
    for kind in ("fut", "spot"):
        for tf in TF_MIN: series(kind, tf)
    known_sessions()
    log(f"candles cached in {_time.time() - t0:.1f}s")
    for base in ("minute", "5minute"):
        ch = OptionChain(base); t1 = _time.time()
        for e in ch.calendar:
            if e == ch.kite_exp: continue
            for right in ("CE", "PE"): ch._local_right(e, right)
            ch._rights.clear()
        log(f"options {base}: {len(ch.calendar)} expiries cached in {_time.time() - t1:.1f}s")


_COV = {}
def option_coverage(tf, expiry_types, min_days):
    """First session (day number) from which every session's contracts (each expiry type, nearest expiry >= min_days) have
    full-chain data (manifest.json 'full_chain', or the Kite expiry) through the end of the data; None if never."""
    base = "minute" if tf in ("minute", "3minute") else "5minute"
    key = (base, tuple(expiry_types), min_days)
    if key not in _COV:
        chain = OptionChain(base)
        full = {}
        def ok(e):
            if e is None: return False
            if e == chain.kite_exp: return True
            if e not in full:
                f = os.path.join(chain.root, e[:4], e, "manifest.json")
                full[e] = os.path.exists(f) and "full_chain" in json.load(open(f, encoding="utf-8"))
            return full[e]
        start = None
        for d in sessions():
            good = all(ok(chain.expiry_for(int(d), min_days, k)) for k in expiry_types)
            if good and start is None: start = int(d)
            if not good: start = None
        _COV[key] = start
    return _COV[key]


# ================================================================ strategies
def _num(f):
    return [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", os.path.basename(f))]


def load_strategies():
    """{code: module} for every strategies/st*.py, in file order. A module has SPEC (dict) and signals(bars, spec)."""
    out = {}
    for path in sorted(glob.glob(os.path.join(STRATDIR, "st*.py")), key=_num):
        name = os.path.splitext(os.path.basename(path))[0]
        spec = importlib.util.spec_from_file_location(f"strategies.{name}", path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        validate(mod.SPEC, os.path.basename(path), getattr(mod, "ENTRY_RULES", ()))
        if mod.SPEC["code"] in out: sys.exit(f"{path}: duplicate code {mod.SPEC['code']}")
        mod.PATH = path
        out[mod.SPEC["code"]] = mod
    return out


_FAM = {}
def family(name):
    """A family module shared by several strategy files (strategies/<name>.py), loaded once."""
    if name not in _FAM:
        path = os.path.join(STRATDIR, f"{name}.py")
        sp = importlib.util.spec_from_file_location(f"strategies.{name}", path)
        mod = importlib.util.module_from_spec(sp); sp.loader.exec_module(mod)
        _FAM[name] = mod
    return _FAM[name]


def allowed(mod, typ, und, tf=None):
    """None if the strategy runs this type on this signal source and timeframe, else the reason it does not."""
    if hasattr(mod, "refuse"): return mod.refuse(typ, und, tf, mod.SPEC)
    if typ not in getattr(mod, "TYPES", (typ,)) or und not in getattr(mod, "UNDERLYINGS", (und,)):
        return getattr(mod, "REFUSED_WHY", "not supported by this strategy")
    if tf and tf not in getattr(mod, "TIMEFRAMES", (tf,)):
        return getattr(mod, "TF_WHY", f"not run on {tf} candles")
    return None


def validate(s, where, rules_ok=()):
    for k in ("code", "name", "description", "timeframe", "warmup_days", "rules", "lot_size", "types", "options", "backtests"):
        if k not in s: raise ValueError(f"{where}: missing '{k}'")
    if s["timeframe"] not in TF_MIN: raise ValueError(f"{where}: timeframe must be one of {tuple(TF_MIN)}")
    p = position_of(s)
    unknown = set(p) - set(POSITION_DEFAULT)
    if unknown: raise ValueError(f"{where}: position: unknown key(s) {sorted(unknown)}")
    if p["exit"] not in ("strategy", "position"): raise ValueError(f"{where}: position.exit is 'strategy' or 'position'")
    if p["exit"] == "position" and not p["stop"]: raise ValueError(f"{where}: exit 'position' needs a stop")
    if p["stop"] and p["stop"].get("from", "fixed") not in ("fixed", "signal"): raise ValueError(f"{where}: position.stop.from is 'fixed' or 'signal'")
    if p["stop"] and p["stop"].get("from") == "signal" and s["rules"].get("sl_rule", "none") == "none":
        raise ValueError(f"{where}: position.stop.from 'signal' needs a rules.sl_rule (the engine's stop is 1R)")
    if p["exit"] == "strategy" and (p["reverse"] or p["trail"] or any("target_r" in so for so in p["scale_out"])):
        raise ValueError(f"{where}: trail / target_r / reverse need exit 'position'")
    if p["reverse"] and (p["reverse"].get("trigger") != "initial_stop" or int(p["reverse"].get("max", 0)) < 1):
        raise ValueError(f"{where}: reverse is {{'trigger': 'initial_stop', 'max': n >= 1}}")
    if s["rules"].get("entry_rule", "setup_v1") not in ("setup_v1",) + tuple(rules_ok):
        raise ValueError(f"{where}: entry_rule {s['rules']['entry_rule']} is not ported to v2 yet")
    if sum(1 for b in s["backtests"] if b.get("default")) != 1: raise ValueError(f"{where}: exactly one default backtest")


def position_of(spec):
    return dict(POSITION_DEFAULT, **(spec.get("position") or {}))


def native_scan_of(spec):
    return dict(NATIVE_SCAN_DEFAULT, **(spec["options"].get("native_scan") or {}))


def slug(label):
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def resolve_backtest(bt, warmup, first=None):
    """(date_from, date_to, status, reason) as 'YYYY-MM-DD'. Refused when the data does not cover it plus its warm-up.
    `first`: a strategy whose memory starts at a fixed session (FZ) resolves against the sessions from it."""
    ss = sessions(); last = dstr(ss[-1])
    if first: ss = ss[ss >= dnum(first)]
    kind = bt["kind"]
    if kind == "all":
        if len(ss) <= warmup: return None, None, "refused", "not enough data for the warm-up"
        return dstr(ss[warmup]), last, "ok", None
    if kind == "preset":
        p, to = bt["preset"], D.date.fromisoformat(last)
        if p == "YTD": frm = D.date(to.year, 1, 1)
        elif p == "MTD": frm = D.date(to.year, to.month, 1)
        else:
            months = {"1M": 1, "3M": 3, "6M": 6, "1Y": 12, "5Y": 60}[p]
            y, m = to.year, to.month - months
            while m <= 0: y, m = y - 1, m + 12
            frm = D.date(y, m, min(to.day, 28)) + D.timedelta(days=1)
        frm, to = frm.isoformat(), last
    else:
        frm, to = bt["from"], min(bt["to"], last)
    f = dnum(frm)
    if int(np.searchsorted(ss, f)) < warmup:
        return frm, to, "refused", f"needs data from before {frm} (plus {warmup} sessions of warm-up); futures data starts {dstr(ss[0])}"
    j = int(np.searchsorted(ss, f))
    if j >= len(ss) or dstr(ss[j]) > to: return frm, to, "refused", "no sessions in this range"
    return dstr(ss[j]), to, "ok", None


def run_key(bt, spec):
    """Result folder name of a backtest: label, timeframe, signal source and holding (as v1)."""
    tf = bt.get("timeframe") or spec["timeframe"]
    und = bt.get("underlying") or spec.get("underlying") or "FUT"
    sq0 = position_of(spec).get("square_off")
    sq = sq0 if "square_off" not in bt else bt["square_off"]
    return (f"{slug(bt['label'])}_{TF_LABEL[tf]}" + ("_idx" if und == "INDEX" else "")
            + ("" if sq == sq0 else "_pos" if sq is None else "_intra")), tf, und, sq


# ================================================================ positions, pricing, stats
def trade_charges(cs, buy_px, sell_px, qty):
    """Round-trip charges for one buy order and one sell order of qty units."""
    buy, sell = buy_px * qty, sell_px * qty
    pct = lambda v, p: v * p / 100
    if cs.get("brokerage_flat"):
        brokerage = 2 * cs["brokerage_flat"]
    else:
        brokerage = min(pct(buy, cs["brokerage_pct"]), cs["brokerage_cap"]) + min(pct(sell, cs["brokerage_pct"]), cs["brokerage_cap"])
    stt = pct(buy, cs["stt_buy_pct"]) + pct(sell, cs["stt_sell_pct"])
    exch = pct(buy + sell, cs["exchange_pct"])
    sebi = pct(buy + sell, cs["sebi_pct"])
    stamp = pct(buy, cs["stamp_buy_pct"])
    gst = pct(brokerage + exch + sebi, cs["gst_pct"])
    return dict(brokerage=brokerage, stt=stt, exchange=exch, sebi=sebi, stamp=stamp, gst=gst,
                total=brokerage + stt + exch + sebi + stamp + gst)


def price_trade(ctx, rec):
    """Slippage, gross, charges, net for its `lots` (a scale-out tranche is charged as its own round trip)."""
    lot, slip = ctx["lot_size"] * rec.setdefault("lots", 1), ctx["slippage_pts"]
    if rec["position"] == "SHORT": sell, buy = rec["entry_px"] - slip, rec["exit_px"] + slip
    else: buy, sell = rec["entry_px"] + slip, rec["exit_px"] - slip
    pts = sell - buy
    rec.update(pts=pts, gross=pts * lot, chg=trade_charges(ctx["charges"], buy, sell, lot))
    rec["net"] = rec["gross"] - rec["chg"]["total"]
    return rec


def excursion(b, rec, long):
    """Max favourable / adverse move after the entry candle up to and including the exit candle (before slippage)."""
    i0 = int(np.searchsorted(b.t, rec["entry_time"], "right")); i1 = int(np.searchsorted(b.t, rec["exit_time"], "right")) - 1
    if i1 < i0:
        rec.update(mfe=0.0, mae=0.0); return rec
    hi, lo, e = float(b.h[i0:i1 + 1].max()), float(b.l[i0:i1 + 1].min()), rec["entry_px"]
    fav, adv = (hi - e, lo - e) if long else (e - lo, e - hi)
    rec.update(mfe=round(max(fav, 0.0), 2), mae=round(min(adv, 0.0), 2))
    return rec


class StrikeLock:
    """lock 'strike': one open position per traded instrument; an exit and an entry on the same candle = exit first."""

    def __init__(self, on):
        self.on, self.until = on, {}

    def held(self, inst, entry_time):
        u = self.until.get(inst)
        if not self.on or u is None: return None
        t, still_open = u
        return t if (entry_time <= t if still_open else entry_time < t) else None

    def hold(self, inst, exit_time, still_open=False):
        cur = self.until.get(inst)
        if cur is None or exit_time > cur[0] or (exit_time == cur[0] and still_open): self.until[inst] = (exit_time, still_open)


def tranches(P, rec, b):
    """One position as its lots: each scale_out tranche exits at entry +/- target_pts on the first candle after the entry
    candle that reaches it (open if it gaps beyond, else the target; a session's first candle only on its close); a target
    reached only on the stop candle counts as not reached. The rest keep the strategy's exit."""
    if not P["scale_out"]: return [dict(rec, lots=P["lots"], tranche="")]
    long, e = rec["position"] == "LONG", rec["entry_px"]
    i0 = int(np.searchsorted(b.t, rec["entry_time"], "right")); i1 = int(np.searchsorted(b.t, rec["exit_time"], "right")) - 1
    out, left = [], P["lots"]
    for n, so in enumerate(P["scale_out"], 1):
        tgt, hit = (e + so["target_pts"] if long else e - so["target_pts"]), None
        for k in range(i0, i1 + 1):
            if k == i1 and rec["exit_reason"] == "stop_loss": break
            gap = b.o[k] >= tgt if long else b.o[k] <= tgt
            first = k > 0 and b.day[k] != b.day[k - 1]
            if first:
                if b.c[k] >= tgt if long else b.c[k] <= tgt: hit = (k, float(b.c[k])); break
            elif gap or (b.h[k] >= tgt if long else b.l[k] <= tgt):
                hit = (k, float(b.o[k]) if gap else tgt); break
        t = dict(rec, lots=so["lots"], tranche=f"T{n} +{so['target_pts']:g}")
        if hit: t.update(exit_time=int(b.t[hit[0]]), exit_px=hit[1], exit_reason=f"target {so['target_pts']:g}", open=False)
        out.append(t); left -= so["lots"]
    if left: out.append(dict(rec, lots=left, tranche="rest"))
    return out


def square_off_at(sq, entry_time):
    """The session-end cut (int time) for a position entered at entry_time, or None."""
    return None if not sq else entry_time - entry_time % DAY + hhmm_sec(sq)


def eod_cut(sq, rec, b):
    """Intraday: a position still open after its entry day's square-off closes at the close of the last candle opening at
    or before it (reason 'eod'). False for an entry at or after that time (not taken)."""
    e = square_off_at(sq, rec["entry_time"])
    if not e: return True
    if rec["entry_time"] >= e: return False
    if rec["exit_time"] > e:
        j = int(np.searchsorted(b.t, e, "right")) - 1
        if j >= 0 and b.day[j] == e // DAY and b.t[j] >= rec["entry_time"]:
            rec.update(exit_time=int(b.t[j]), exit_px=float(b.c[j]), exit_reason="eod", open=False)
    return True


def manage(P, rec, b, cap, expiry=None):
    """exit 'position': the position managed from the entry fill on its own candles (v1 manage); the strategy's exit is not
    used. R = stop.futures_pts (futures) or stop.option_pct % of the entry premium (options), or - stop.from 'signal' - the
    distance from the entry to the engine's own stop (rules.sl_rule, on the signal's own candles); the stop starts 1R against the
    entry. Candle by candle after the entry candle up to `cap` (int time; and the square-off): 1. stop - all open lots
    (open if it gaps beyond, a session's first candle at its close); 2. targets - each scale_out lot at entry +/- target_r x
    R (or target_pts); 3. trail - once start_r whole R are reached the stop moves to (reached - lag_r) x R, never back,
    from the next candle. Lots still open at the end close there: 'expiry' at the contract's end, 'eod' at the square-off
    candle, else 'open'. Returns one record per lot group."""
    long, e, kind = rec["position"] == "LONG", rec["entry_px"], rec["kind"]
    sg = 1 if long else -1
    if P["stop"].get("from") == "signal":
        if kind == "OPT" and rec.get("und_entry") is not None:      # via futures: the engine's stop is a futures price
            raise ValueError("stop.from 'signal' needs the signal on the traded instrument's own candles (futures or options standalone)")
        if rec.get("sl") is None or not math.isfinite(rec["sl"]) or sg * (e - rec["sl"]) <= 0:
            raise ValueError(f"stop.from 'signal': no usable engine stop for {rec['instrument']} at {tstr(rec['entry_time'])}")
        R = sg * (e - rec["sl"])
    else:
        R = P["stop"]["futures_pts"] if kind == "FUT" else e * P["stop"]["option_pct"] / 100
    stop = e - sg * R
    tag = lambda so: f"{so['target_r']:g}R" if "target_r" in so else f"+{so['target_pts']:g}"
    lots = [dict(lots=so["lots"], tranche=f"T{n} {tag(so)}", tgt=e + sg * (so["target_r"] * R if "target_r" in so else so["target_pts"]),
                 why=f"target {tag(so)}") for n, so in enumerate(P["scale_out"], 1)]
    left = P["lots"] - sum(so["lots"] for so in P["scale_out"])
    if left: lots.append(dict(lots=left, tranche="rest" + (" (trail)" if P["trail"] else ""), tgt=None))
    eod = square_off_at(P["square_off"], rec["entry_time"])
    if eod: cap = min(cap, eod)
    tl, ol, hl, ll, cl, dl = b.t, b.o, b.h, b.l, b.c, b.day
    i0 = int(np.searchsorted(tl, rec["entry_time"], "right")); iend = int(np.searchsorted(tl, cap, "right")) - 1
    best, trailing, out = e, False, []
    base = dict(rec, sl=round(stop, 2))

    def close(lot, k, px, why):
        out.append(dict(base, lots=lot["lots"], tranche=lot["tranche"], exit_time=int(tl[k]), exit_px=round(float(px), 2),
                        exit_reason=why, open=False))

    tr = P["trail"]
    for k in range(i0, iend + 1):
        o_, h_, l_, c_ = float(ol[k]), float(hl[k]), float(ll[k]), float(cl[k])
        first = k > 0 and dl[k] != dl[k - 1]
        gap = o_ <= stop if long else o_ >= stop
        if gap or (l_ <= stop if long else h_ >= stop):
            px = c_ if first else (o_ if gap else stop)
            for lot in lots: close(lot, k, px, "trail_stop" if trailing else "stop_loss")
            lots = []; break
        for lot in [x for x in lots if x["tgt"] is not None]:
            g = o_ >= lot["tgt"] if long else o_ <= lot["tgt"]
            if first:
                if c_ >= lot["tgt"] if long else c_ <= lot["tgt"]:
                    close(lot, k, c_, lot["why"]); lots.remove(lot)
            elif g or (h_ >= lot["tgt"] if long else l_ <= lot["tgt"]):
                close(lot, k, o_ if g else lot["tgt"], lot["why"]); lots.remove(lot)
        if not lots: break
        if tr:
            best = max(best, h_) if long else min(best, l_)
            reached = math.floor(sg * (best - e) / R + 1e-9)
            if reached >= tr["start_r"]:
                new = e + sg * (reached - tr["lag_r"]) * R
                if (new > stop) if long else (new < stop): stop, trailing = new, True
    if lots:
        k = max(iend, i0 - 1)
        n = len(tl)
        ended = expiry is not None and k >= 0 and dl[k] >= dnum(expiry)
        at_eod = bool(eod) and k >= 0 and dl[k] == eod // DAY and (tl[k] >= eod or (k + 1 < n and tl[k + 1] > eod))
        for lot in lots:
            out.append(dict(base, lots=lot["lots"], tranche=lot["tranche"], exit_time=int(tl[k]), exit_px=float(cl[k]),
                            exit_reason="expiry" if ended else "eod" if at_eod else "open", open=not (ended or at_eod)))
    return out


def reversal_of(P, parts, depth):
    """position.reverse: (time, price) where the opposite position opens when the managed lots left at the initial stop
    (not a trail stop); not at or after the square-off, at most `max` per signal."""
    rv = P.get("reverse")
    if not rv or depth >= rv["max"]: return None
    hit = [p_ for p_ in parts if p_["exit_reason"] == "stop_loss"]
    if not hit: return None
    t0, px = hit[0]["exit_time"], hit[0]["exit_px"]
    sq = square_off_at(P["square_off"], t0)
    if sq and t0 >= sq: return None
    return t0, px


def flip(rec, t0, px, depth):
    """The opposite position of rec, opened at t0 / px: same instrument, other side."""
    up = rec["position"] != "LONG"
    return dict(rec, position="LONG" if up else "SHORT", dir="up" if up else "down", signal="BULLISH" if up else "BEARISH",
                entry_time=t0, entry_px=px, exit_time=t0, exit_px=None, exit_reason="open", open=True, reversal=depth + 1)


def rev_tag(tr):
    d = tr.get("reversal") or 0
    if d: tr["tranche"] = f"REV{d if d > 1 else ''} {tr['tranche']}".strip()
    return tr


def managed_with_reversals(P, rec, b, cap, expiry):
    """manage() plus stop-and-reverse on the same instrument."""
    parts = manage(P, rec, b, cap, expiry)
    cur_rec, cur, depth = rec, parts, 0
    while (rv := reversal_of(P, cur, depth)):
        cur_rec = flip(cur_rec, rv[0], rv[1], depth); depth += 1
        cur = [rev_tag(p_) for p_ in manage(P, cur_rec, b, cap, expiry)]; parts = parts + cur
    return parts


def expire(rec, s, expiry):
    """A position still open after its contract's last candle closes at that candle (reason 'expiry')."""
    last = int(np.searchsorted(s.t, dnum(expiry) * DAY + DAY - 1, "right")) - 1
    if last >= 0 and s.t[last] < rec["exit_time"]:
        rec.update(exit_time=int(s.t[last]), exit_px=float(s.c[last]), exit_reason="expiry", open=False)
    return rec


def stats(trs):
    """Headline numbers over priced trades (v1 stats)."""
    net = [x["net"] for x in trs]
    eq = peak = dd = 0.0
    for v in net: eq += v; peak = max(peak, eq); dd = min(dd, eq - peak)
    wk = {}
    for x in trs:
        y, w, _ = D.date.fromisoformat(tstr(x["entry_time"])[:10]).isocalendar()
        wk[f"{y}-W{w:02d}"] = wk.get(f"{y}-W{w:02d}", 0) + x["net"]
    m = sum(net) / len(net) if net else 0
    sd = math.sqrt(sum((v - m) ** 2 for v in net) / (len(net) - 1)) if len(net) > 1 else 0
    wins = [v for v in net if v > 0]; loss = [v for v in net if v <= 0]
    return dict(trades=len(trs), wins=len(wins), pts=round(sum(x["pts"] for x in trs), 2),
                gross_inr=round(sum(x["gross"] for x in trs), 2), charges_inr=round(sum(x["chg"]["total"] for x in trs), 2),
                net_inr=round(sum(net), 2), max_dd_inr=round(dd, 2),
                pf=round(sum(wins) / -sum(loss), 2) if loss and sum(loss) else None,
                t_stat=round(m / (sd / math.sqrt(len(net))), 2) if sd else None,
                weeks=len(wk), pos_weeks=sum(1 for v in wk.values() if v > 0),
                worst_week=list(min(wk.items(), key=lambda kv: kv[1])) if wk else None)


# ================================================================ runner
def choice_keys(spec, typ):
    """'-' for futures; '<W|M>-<strike choice>' for options via futures; '<W|M>-SCAN' for standalone options."""
    if typ == "FUT": return ["-"]
    ex = spec["options"]["expiry_types"]
    if typ == "OPT_NATIVE": return [f"{e[0]}-SCAN" for e in ex]
    return [f"{e[0]}-{c}" for e in ex for c in spec["options"]["strike_choices"]]


def split_choice(key):
    kind, strike = key.split("-", 1)
    return ("MONTHLY" if kind == "M" else "WEEKLY"), strike


def context(mod, typ, tf, und, sq, frm, to, period=None):
    """Everything one (strategy, backtest, type) run reads. `period` is the run key (FZ seeds its controls with it). A
    strategy with FIRST_SESSION (FZ) warms up on every session from that date, so each window is a slice of one run."""
    spec = mod.SPEC
    t = spec["types"][typ]
    warm = spec["warmup_days"]
    if getattr(mod, "FIRST_SESSION", None):
        warm = int(np.count_nonzero((sessions() >= dnum(mod.FIRST_SESSION)) & (sessions() < dnum(frm))))
    return dict(mod=mod, spec=spec, type=typ, tf=tf, underlying=und, square_off=sq, date_from=frm, date_to=to, period=period,
                warmup=warm, rules=spec["rules"], lot_size=spec["lot_size"],
                charges=CHARGES[t["charge_code"]], charge_code=t["charge_code"], slippage_pts=t["slippage_pts"],
                position=dict(position_of(spec), square_off=sq), options=spec["options"])


def signal_bars(ctx):
    """(window bars the strategy reads, first shown index): near-month futures, or the index (underlying INDEX)."""
    return window(series("spot" if ctx["underlying"] == "INDEX" else "fut", ctx["tf"]), ctx["date_from"], ctx["date_to"], ctx["warmup"])


def strategy_signals(ctx, bars):
    """The strategy's own signals() on these bars; the index has no volume, so INDEX runs weight the AVWAP equally."""
    rules = dict(ctx["rules"])
    if ctx["underlying"] == "INDEX": rules["avwap_weight"] = "equal"
    return ctx["mod"].signals(bars, dict(ctx["spec"], rules=rules))


def run_type(ctx):
    """{choice: dict(trades, skipped, signals)} for one strategy type over one window (v1 run_variant). A strategy module
    with its own run(ctx) (c2c) produces the trades itself; pricing, stats and results stay here."""
    if hasattr(ctx["mod"], "run"): return ctx["mod"].run(ctx)
    typ, spec, P = ctx["type"], ctx["spec"], ctx["position"]
    sq = P["square_off"]
    pmode = P["exit"] == "position"
    fut, s0 = signal_bars(ctx)
    index_sig = ctx["underlying"] == "INDEX"
    ct_t, ct_con, ct_exp, clast = fut_contracts()
    spot = series("spot", ctx["tf"]); spot_atr = atr(spot, spec["options"]["atr_period"])
    step = spec["options"]["strike_step"]
    chain = OptionChain(ctx["tf"]) if typ != "FUT" else None
    lock_on = P["lock"] == "strike"
    # a strategy may veto single option legs (e.g. a trend filter on the option's own candles): leg_filter(ctx, rec, series)
    # returns None to take the leg, or the reason it is not taken
    leg_filter = getattr(ctx["mod"], "leg_filter", None)
    sq_txt = f"entry at or after the square-off time ({sq})"
    out = {}
    if typ in ("FUT", "OPT_FUT_SIGNAL"):
        r = strategy_signals(ctx, fut)
        F = None
        if hasattr(ctx["mod"], "gate"):           # FZ: the gate's positions replace the engine's SETUP trades
            r, F = ctx["mod"].gate(ctx, fut, s0, r)
        t = fut.t
        sig = [x for x in r.trades() if x["entry"] >= s0]
        setup_at = {int(ch): int(t[i]) for i, ch in zip(r.ui, r.uch)}
        signals = []
        for j in range(len(r.qi)):
            if r.qi[j] < s0: continue
            hi, lo = int(r.qhi[j]), int(r.qlo[j])
            signals.append(dict(time=int(t[r.qi[j]]), dir="up" if r.qd[j] == 1 else "down", flipped=bool(r.qflip[j]),
                                lvl=float(r.qlvl[j]), av=float(r.qav[j]),
                                hi=(int(t[r.sb[hi]]), float(r.sp[hi])) if hi >= 0 else None,
                                lo=(int(t[r.sb[lo]]), float(r.sp[lo])) if lo >= 0 else None,
                                setup=setup_at.get(int(r.qi[j]))))
        FS = series("fut", ctx["tf"]) if index_sig else None
        PT = FS if index_sig else fut
        for ch in choice_keys(spec, typ):
            ekind, sc = split_choice(ch) if ch != "-" else (None, None)
            trs, skipped = [], []

            def legs_of(x, skipped):
                """The priced legs one signal opens under this choice; unpriceable legs go to `skipped`."""
                legs = _legs_of(x, skipped)
                for rec, _ in legs:                   # which position a leg belongs to (FZ's report groups by it)
                    rec.update(_entry=x["entry"], _setup=x.get("setup_i", x["entry"]), _gate=x.get("gate") or "RAW")
                return legs

            def _legs_of(x, skipped):
                bull = x["dir"] == "up"
                te, tx = int(t[x["entry"]]), int(t[x["exit"]])
                base = dict(dir=x["dir"], signal="BULLISH" if bull else "BEARISH", choch_time=int(t[x["choch"]]),
                            entry_time=te, exit_time=tx, exit_reason=x["exit_reason"], open=x["open"], sl=x["sl"],
                            und_entry=float(fut.c[x["entry"]]), und_exit=x["exit_px"], expiry=None)
                if F is not None: base.update({k: x.get(k) for k in ("gate", "reenter_reason", "zone_id", "fill_used")})
                if typ == "FUT":
                    ci = int(np.searchsorted(ct_t, te))
                    if ci < len(ct_t) and ct_t[ci] == te: c_, e_ = str(ct_con[ci]), (str(ct_exp[ci]) or None)
                    else: c_, e_ = "NIFTY FUT", None
                    if index_sig:
                        fe, _ = FS.at(te); fxc, _ = FS.at(tx)
                        if fe is None or fxc is None:
                            skipped.append(dict(base, position="LONG" if bull else "SHORT", opt_type="FUT",
                                                why=f"no futures candle at {tstr(te if fe is None else tx)}")); return []
                        fx = x["exit_px"] + (fxc - float(fut.c[x["exit"]])) if x["exit_reason"] == "stop_loss" else fxc
                    else:
                        fe, fx = float(fut.c[x["entry"]]), x["exit_px"]
                    rec = dict(base, kind="FUT", position="LONG" if bull else "SHORT", opt_type="FUT",
                               instrument=c_, expiry=e_, strike=None, entry_px=fe, exit_px=fx)
                    cap = int(t[-1])
                    if e_:                                       # near month: the contract's last candle ends the position
                        cap = min(cap, clast[c_])
                        if not pmode and rec["exit_time"] > clast[c_]:
                            j = int(np.searchsorted(PT.t, clast[c_], "right")) - 1
                            rec.update(exit_time=int(PT.t[j]), exit_px=float(PT.c[j]), exit_reason="expiry", open=False)
                    if (not pmode and not eod_cut(sq, rec, PT)) or (pmode and sq and te >= square_off_at(sq, te)):
                        skipped.append(dict(base, position=rec["position"], opt_type="FUT", instrument=c_, why=sq_txt)); return []
                    parts = managed_with_reversals(P, rec, PT, cap, e_) if pmode else tranches(P, rec, PT)
                    return [(price_trade(ctx, excursion(PT, tr, tr["position"] == "LONG")),
                             tr["position"] + (f" · {tr['tranche']}" if tr["tranche"] else "")) for tr in parts]
                legs = []
                for pos in ("LONG", "SHORT"):
                    right = ("CE" if bull else "PE") if pos == "LONG" else ("PE" if bull else "CE")
                    si = spot.find(te)
                    if si < 0: skipped.append(dict(base, position=pos, opt_type=right, why="no spot candle")); continue
                    k = pick_strike(sc, right, float(spot.c[si]), float(spot_atr[si]), step)
                    exp = chain.expiry_for(te // DAY, spec["options"]["expiry_min_days"], ekind)
                    os_ = chain.get(exp, k, right) if exp else None
                    nm = chain.name(exp, k, right) if exp else f"{int(k)} {right}"
                    if os_ is None:
                        skipped.append(dict(base, position=pos, opt_type=right, why=f"no data for {nm}")); continue
                    en, st1 = os_.at(te)
                    if en is None:
                        skipped.append(dict(base, position=pos, opt_type=right, why=f"{nm} has no candle at entry")); continue
                    rec = dict(base, kind="OPT", position=pos, opt_type=right, instrument=nm, strike=k, expiry=exp,
                               entry_px=en, exit_px=None, stale=st1)
                    why = leg_filter(ctx, rec, os_) if leg_filter else None
                    if why:
                        skipped.append(dict(base, position=pos, opt_type=right, instrument=nm, expiry=exp, why=why, filtered=True)); continue
                    e = square_off_at(sq, te)
                    if e and te >= e:
                        skipped.append(dict(base, position=pos, opt_type=right, instrument=nm, why=sq_txt)); continue
                    if pmode:                     # managed on the option's own candles up to the backtest end
                        end_ = dnum(ctx["date_to"]) * DAY + DAY - 1
                        cur = manage(P, rec, os_, end_, exp)
                        for tr in cur:
                            excursion(os_, tr, pos == "LONG")
                            legs.append((price_trade(ctx, tr), f"{pos} {right}" + (f" · {tr['tranche']}" if tr["tranche"] else "")))
                        # stop and reverse: the opposite signal's leg (long CE -> long PE, short PE -> short CE), strike
                        # from the index at the stop, entered at that option's close of the stop candle
                        depth, r_right = 0, right
                        while (rv := reversal_of(P, cur, depth)):
                            t0 = rv[0]; r_right = "PE" if r_right == "CE" else "CE"
                            si2 = spot.find(t0)
                            if si2 < 0:
                                skipped.append(dict(base, position=pos, opt_type=r_right, entry_time=t0, why="reverse: no spot candle")); break
                            k2 = pick_strike(sc, r_right, float(spot.c[si2]), float(spot_atr[si2]), step)
                            exp2 = chain.expiry_for(t0 // DAY, spec["options"]["expiry_min_days"], ekind)
                            os2 = chain.get(exp2, k2, r_right) if exp2 else None
                            nm2 = chain.name(exp2, k2, r_right) if exp2 else f"{int(k2)} {r_right}"
                            en2 = os2.at(t0)[0] if os2 is not None else None
                            if en2 is None:
                                skipped.append(dict(base, position=pos, opt_type=r_right, entry_time=t0, why=f"reverse: no data for {nm2}")); break
                            rdir = "down" if (cur[0]["dir"] if cur else rec["dir"]) == "up" else "up"
                            rec2 = dict(rec, dir=rdir, signal="BULLISH" if rdir == "up" else "BEARISH", opt_type=r_right,
                                        instrument=nm2, strike=k2, expiry=exp2, entry_time=t0, entry_px=en2, exit_time=t0,
                                        exit_px=None, exit_reason="open", open=True, reversal=depth + 1)
                            depth += 1
                            cur = [rev_tag(p_) for p_ in manage(P, rec2, os2, end_, exp2)]
                            for tr in cur:
                                excursion(os2, tr, pos == "LONG")
                                legs.append((price_trade(ctx, tr), f"{pos} {r_right}" + (f" · {tr['tranche']}" if tr["tranche"] else "")))
                        continue
                    if e and rec["exit_time"] > e:
                        j = int(np.searchsorted(os_.t, e, "right")) - 1
                        if j >= 0 and os_.day[j] == e // DAY and os_.t[j] >= te:
                            rec.update(exit_time=int(os_.t[j]), exit_px=float(os_.c[j]), exit_reason="eod", open=False)
                    expire(rec, os_, exp)
                    if rec["exit_px"] is None:
                        ex, st2 = os_.at(rec["exit_time"])
                        if ex is None:
                            skipped.append(dict(base, position=pos, opt_type=right, why=f"{nm} has no candle at exit")); continue
                        rec.update(exit_px=ex, stale=st1 or st2)
                    for tr in tranches(P, rec, os_):
                        excursion(os_, tr, pos == "LONG")
                        legs.append((price_trade(ctx, tr), f"{pos} {right}" + (f" · {tr['tranche']}" if tr["tranche"] else "")))
                return legs

            lock = StrikeLock(lock_on)
            for x in sig:
                legs = legs_of(x, skipped)
                for inst in dict.fromkeys(rec["instrument"] for rec, _ in legs):
                    mine = [lg for lg in legs if lg[0]["instrument"] == inst]
                    u = lock.held(inst, mine[0][0]["entry_time"])
                    if u:
                        r0 = mine[0][0]
                        skipped.append(dict({k: r0.get(k) for k in ("dir", "signal", "choch_time", "entry_time", "position",
                                                                     "opt_type", "instrument", "expiry")},
                                            why=f"strike locked: {inst} open until {tstr(u)}"))
                        legs = [lg for lg in legs if lg[0]["instrument"] != inst]
                    else:
                        lock.hold(inst, max(lg[0]["exit_time"] for lg in mine), any(lg[0]["open"] for lg in mine))
                for rec, lbl in legs:
                    rec["label"] = lbl; trs.append(rec)
            out[ch] = dict(trades=trs, skipped=skipped, signals=signals)
            if F is not None:                         # Foundation's own trades priced the same way, for FZ's bridge
                raw = [leg[0] for x in F["raw"] if x["entry"] >= s0 for leg in legs_of(x, [])]
                out[ch]["fz"] = ctx["mod"].payload(ctx, fut, s0, F, trs, raw)
        return out

    # OPT_NATIVE: the engine on each option's own candles. Every native_scan.every_minutes the strike of each scan choice
    # is picked for CE and PE from the index candle that has just completed; that contract is watched until the next scan.
    # A SETUP on a watched contract whose entry candle closes inside the watch opens a position (bullish -> long, bearish
    # -> short); first wins (ties: scan-list order); one_per_side holds the side until the position closes.
    NS = native_scan_of(spec)
    sp_ = series("spot", {1: "minute", 3: "3minute", 5: "5minute", 15: "15minute", 30: "30minute"}[NS["every_minutes"]])
    satr = atr(sp_, spec["options"]["atr_period"])
    tfm = TF_MIN[ctx["tf"]] * 60
    days = np.unique(fut.day[s0:])
    scan_j = np.nonzero(np.isin(sp_.day, days))[0]
    scan_T = sp_.t[scan_j] + NS["every_minutes"] * 60
    runs = {}

    def contract_run(exp, k, right, nm):
        key = (exp, int(k), right)
        if key not in runs:
            os_ = chain.get(exp, k, right) if exp else None
            runs[key] = None
            if os_ is not None:
                try:
                    ob, _ = window(os_, ctx["date_from"], ctx["date_to"], ctx["warmup"])
                except ValueError:
                    ob = None
                if ob is not None:
                    r = strategy_signals(dict(ctx, underlying="FUT"), ob)
                    xs = r.trades()
                    ends = sorted(((int(ob.t[x["entry"]]) + tfm, x) for x in xs), key=lambda z: (z[0], z[1]["entry"]))
                    runs[key] = (ob, r, np.array([z[0] for z in ends], dtype=np.int64), [z[1] for z in ends])
        return runs[key]

    for ch in choice_keys(spec, typ):
        ekind, _ = split_choice(ch)
        trs, skipped = [], []
        for right in ("CE", "PE"):
            events, missing = [], set()
            for n in range(len(scan_T)):
                T = int(scan_T[n]); j = int(scan_j[n])
                T2 = int(scan_T[n + 1]) if n + 1 < len(scan_T) and scan_T[n + 1] // DAY == T // DAY else T - T % DAY + DAY - 1
                exp = chain.expiry_for(T // DAY, spec["options"]["expiry_min_days"], ekind)
                for rank, c in enumerate(NS["choices"]):
                    k = pick_strike(c, right, float(sp_.c[j]), float(satr[j]), step)
                    nm = chain.name(exp, k, right) if exp else f"{int(k)} {right}"
                    cr = contract_run(exp, k, right, nm)
                    if cr is None:
                        if (T // DAY, nm) not in missing:
                            missing.add((T // DAY, nm))
                            skipped.append(dict(signal="", opt_type=right, instrument=nm, expiry=exp, entry_time=dstr(T // DAY),
                                                why=f"no data for {nm} (scan {c})"))
                        continue
                    _, _, ends, xs = cr
                    for q in range(int(np.searchsorted(ends, T)), int(np.searchsorted(ends, T2))):
                        events.append((int(ends[q]), rank, c, exp, int(k), nm, xs[q]))
            events.sort(key=lambda z: (z[0], z[1]))
            side_free, lock, seen = -1, StrikeLock(lock_on), set()
            for when, rank, c, exp, k, nm, x in events:
                if (nm, x["entry"]) in seen: continue
                seen.add((nm, x["entry"]))
                ob = runs[(exp, k, right)][0]; t_ = ob.t
                lng = x["dir"] == "up"
                rec = dict(dir=x["dir"], signal="BULLISH" if lng else "BEARISH", position="LONG" if lng else "SHORT",
                           opt_type=right, kind="OPT", instrument=nm, strike=k, expiry=exp, scan=c,
                           choch_time=int(t_[x["choch"]]), entry_time=int(t_[x["entry"]]), exit_time=int(t_[x["exit"]]),
                           exit_reason=x["exit_reason"], open=x["open"], sl=x["sl"], entry_px=float(ob.c[x["entry"]]),
                           exit_px=x["exit_px"], und_entry=None, und_exit=None)
                why = leg_filter(ctx, rec, chain.get(exp, k, right)) if leg_filter else None
                if why:                                    # vetoed before the lock: a refused leg holds nothing
                    skipped.append(dict(signal=rec["signal"], position=rec["position"], opt_type=right, instrument=nm,
                                        expiry=exp, entry_time=rec["entry_time"], why=why, filtered=True))
                    continue
                held = (side_free if NS["one_per_side"] and rec["entry_time"] < side_free else None) or lock.held(nm, rec["entry_time"])
                if held:
                    skipped.append(dict(signal=rec["signal"], position=rec["position"], opt_type=right, instrument=nm,
                                        expiry=exp, entry_time=rec["entry_time"],
                                        why=f"strike locked: {right} side open until {tstr(held)} ({nm}, scan {c})"))
                    continue
                if x["open"] and ob.day[x["exit"]] == dnum(exp):
                    rec.update(exit_reason="expiry", open=False)
                e = square_off_at(sq, rec["entry_time"])
                if e and rec["entry_time"] >= e: continue
                if pmode:
                    parts = managed_with_reversals(P, rec, ob, int(t_[-1]), exp)
                else:
                    eod_cut(sq, rec, ob)
                    parts = tranches(P, rec, ob)
                end = max(p_["exit_time"] for p_ in parts)
                side_free = max(side_free, end); lock.hold(nm, end, any(p_["open"] for p_ in parts))
                for tr in parts:
                    excursion(ob, tr, tr["position"] == "LONG")
                    tr["label"] = f"{tr['position']} {right}" + (f" · {tr['tranche']}" if tr["tranche"] else "")
                    trs.append(price_trade(ctx, tr))
        trs.sort(key=lambda x: x["entry_time"])
        out[ch] = dict(trades=trs, skipped=skipped, signals=[])
    return out


# ================================================================ backtest + results
TRADE_COLS = ("position", "opt_type", "instrument", "strike", "expiry", "signal", "choch_time", "entry_time", "entry_px", "sl",
              "exit_time", "exit_px", "exit_reason", "pts", "gross", "charges", "net", "open", "lots", "tranche", "label",
              "und_entry", "und_exit", "stale", "mfe", "mae", "scan", "gate", "zone_id", "reenter_reason", "fill_used", "kind",
              "chg_parts")


def _r2(v):
    return round(v, 2) if isinstance(v, float) else v


def trade_rows(trs):
    rows = []
    for x in trs:
        d = dict(x, charges=x["chg"]["total"], entry_time=tstr(x["entry_time"]), exit_time=tstr(x["exit_time"]),
                 choch_time=tstr(x["choch_time"]), chg_parts={k: round(v, 2) for k, v in x["chg"].items() if k != "total"})
        rows.append([_r2(d.get(k)) if k not in ("entry_px", "exit_px", "sl") else d.get(k) for k in TRADE_COLS])
    return rows


def _jsonable(v):
    if isinstance(v, dict): return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)): return [_jsonable(x) for x in v]
    if isinstance(v, (np.integer,)): return int(v)
    if isinstance(v, (np.floating,)): return float(v)
    if isinstance(v, np.bool_): return bool(v)
    return v


def _skipped_out(sk):
    out = []
    for s in sk:
        d = dict(s)
        for k in ("entry_time", "exit_time", "choch_time"):
            if isinstance(d.get(k), (int, np.integer)): d[k] = tstr(d[k])
        d.pop("chg", None)
        out.append(d)
    return out


def backtest(code, bt, types=None, log=print):
    """Run one strategy over one backtest (a dict like the SPEC's backtests entries) for the given types (default all).
    Writes results/<code>/<run>/ and returns its meta dict."""
    t0 = _time.time()
    mods = load_strategies()
    if code not in mods: raise ValueError(f"unknown strategy {code}")
    mod = mods[code]; spec = mod.SPEC
    rk, tf, und, sq = run_key(bt, spec)
    frm, to, status, reason = resolve_backtest(bt, spec["warmup_days"], getattr(mod, "FIRST_SESSION", None))
    folder = os.path.join(RESULTS, code, rk)
    os.makedirs(folder, exist_ok=True)
    meta = dict(code=code, run=rk, label=bt["label"], kind=bt["kind"], preset=bt.get("preset"), notes=bt.get("notes"),
                timeframe=tf, underlying=und, holding=f"intraday {sq}" if sq else "positional", square_off=sq,
                date_from=frm, date_to=to, status=status, reason=reason, at=D.datetime.now().isoformat(timespec="seconds"),
                spec_hash=hashlib.sha1(open(mod.PATH, "rb").read()).hexdigest()[:12], types={})
    for typ, _, label in TYPES:
        if types and typ not in types:
            old = _old_type(folder, typ)
            if old: meta["types"][typ] = old
            continue
        tm = dict(label=label, status=status, reason=reason, date_from=frm, choices={})
        meta["types"][typ] = tm
        if status != "ok": continue
        why = allowed(mod, typ, und, tf)
        if not why and getattr(mod, "FIXED_HOLDING", None) and sq != position_of(spec).get("square_off"):
            why = mod.FIXED_HOLDING                   # the strategy's own exits carry their square-off (the learner)
        if why:
            tm.update(status="refused", reason=why); continue
        f_ = frm
        if typ != "FUT" and not getattr(mod, "OWN_COVERAGE", False):
            cov = option_coverage(tf, spec["options"]["expiry_types"], spec["options"]["expiry_min_days"])
            if cov is None:
                tm.update(status="refused", reason="no full-chain option data"); continue
            if dnum(frm) < cov:
                if bt["kind"] == "all": f_ = dstr(cov)
                else:
                    tm.update(status="refused", reason=f"options have full-chain data from {dstr(cov)}"); continue
        if und == "INDEX" and typ == "OPT_NATIVE":
            tm.update(status="refused", reason=INDEX_WHY_NATIVE); continue
        tm["date_from"] = f_
        t1 = _time.time()
        res = run_type(context(mod, typ, tf, und, sq, f_, to, rk))
        os.makedirs(os.path.join(folder, typ), exist_ok=True)
        for f in glob.glob(os.path.join(folder, typ, "*.json")): os.remove(f)
        for ch, rr in res.items():
            trs = rr["trades"]
            s = stats(trs)
            part = lambda f: stats([x for x in trs if f(x)])
            sides = dict(long=part(lambda x: x["position"] == "LONG"), short=part(lambda x: x["position"] == "SHORT"),
                         ce=part(lambda x: x["opt_type"] == "CE"), pe=part(lambda x: x["opt_type"] == "PE"))
            skl = rr["skipped"]
            n_lock = sum(str(k.get("why", "")).startswith("strike locked") for k in skl)
            n_filt = sum(1 for k in skl if k.get("filtered"))           # refused by the strategy's own leg filter
            body = dict(code=code, run=rk, type=typ, choice=ch, date_from=f_, date_to=to, lot_size=spec["lot_size"],
                        slippage_pts=spec["types"][typ]["slippage_pts"], capital=spec.get("capital") or {},
                        stats=s, sides=sides, charges=CHARGES[spec["types"][typ]["charge_code"]],
                        cols=TRADE_COLS, trades=trade_rows(trs), skipped=_skipped_out(skl),
                        signals=[dict(g, time=tstr(g["time"]), setup=g["setup"] and tstr(g["setup"]),
                                      hi=g["hi"] and [tstr(g["hi"][0]), g["hi"][1]], lo=g["lo"] and [tstr(g["lo"][0]), g["lo"][1]])
                                 for g in rr["signals"]])
            for k in ("fz", "rl"):                    # a strategy family's own payload (FZ report, learner journal)
                if rr.get(k): body[k] = rr[k]
            fn = f"{ch}.json"
            with open(os.path.join(folder, typ, fn), "w", encoding="utf-8") as fh:
                json.dump(_jsonable(body), fh, separators=(",", ":"))
            brief = lambda z: {k: z[k] for k in ("trades", "wins", "pts", "net_inr", "pf")}
            tm["choices"][ch] = dict(file=f"{typ}/{fn}", skipped=len(skl) - n_lock - n_filt, locked=n_lock, filtered=n_filt, **s,
                                     **{k: brief(v) for k, v in sides.items()},
                                     **({"fz": rr["fz"]["headline"]} if rr.get("fz") else {}),
                                     **({"rl": rr["rl"]["summary"]} if rr.get("rl") else {}))
        tm["seconds"] = round(_time.time() - t1, 2)
        log(f"{code} {rk} {typ:<15} {len(res)} choice(s) in {tm['seconds']:.2f}s")
    meta["seconds"] = round(_time.time() - t0, 2)
    try:
        cur, prev = record_history(mod, rk, meta)
        meta["version"] = dict(version=cur["version"], at=cur["at"], changes=cur["changes"])
        meta["baseline"] = prev and dict(version=prev["version"], at=prev["at"], results=prev["results"].get(rk))
    except (OSError, ValueError) as e:                 # history is a convenience: a run never fails on it
        log(f"history not recorded: {e}")
    with open(os.path.join(folder, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(_jsonable(meta), fh, indent=1)
    return meta


def _old_type(folder, typ):
    f = os.path.join(folder, "meta.json")
    if not os.path.exists(f): return None
    return json.load(open(f, encoding="utf-8")).get("types", {}).get(typ)


# ================================================================ version history (history/<CODE>.json, versioned in git)
HISTORY = os.path.join(HERE, "history")
BRIEF = ("trades", "wins", "pts", "net_inr", "pf", "max_dd_inr", "t_stat")


def _flat(d, pre=""):
    out = {}
    for k, v in (d.items() if isinstance(d, dict) else []):
        if isinstance(v, dict): out.update(_flat(v, f"{pre}{k}."))
        else: out[f"{pre}{k}"] = v
    return out


def _code_hash(mod):
    """sha1[:12] of the code a strategy's results come from: core.py, its strategy file and its family modules."""
    h = hashlib.sha1()
    files = [os.path.join(HERE, "core.py"), mod.PATH]
    d = os.path.join(STRATDIR)
    for name in ("rainbow", "c2c", "foundation_zone", "learner"):
        if name in open(mod.PATH, encoding="utf-8").read(): files.append(os.path.join(d, f"{name}.py"))
    for f in files: h.update(open(f, "rb").read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]


def record_history(mod, rk, meta):
    """history/<CODE>.json: a new version whenever the strategy's definition (SPEC without name, description and backtests)
    or the code its results come from changes; each version keeps the headline numbers of every run made on it. Returns
    (current version, previous version or None) so a run is read against the strategy's previous version."""
    spec = mod.SPEC
    definition = {k: v for k, v in spec.items() if k not in ("name", "description", "backtests")}
    definition["position"] = position_of(spec)
    code = _code_hash(mod)
    key = hashlib.sha1(json.dumps([definition, code], sort_keys=True, default=str).encode()).hexdigest()[:12]
    os.makedirs(HISTORY, exist_ok=True)
    path = os.path.join(HISTORY, f"{spec['code']}.json")
    hist = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else dict(code=spec["code"], versions=[])
    vs = hist["versions"]
    if not vs or vs[-1]["key"] != key:
        changes = []
        if vs:
            a, b = _flat(vs[-1]["definition"]), _flat(json.loads(json.dumps(definition, default=str)))
            changes = [f"{k}: {a.get(k)!r} -> {b.get(k)!r}" for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)]
            if not changes: changes = ["code changed (core.py, the strategy file or its family module)"]
        vs.append(dict(version=len(vs) + 1, at=meta["at"], key=key, code=code, definition=json.loads(json.dumps(definition, default=str)),
                       changes=changes, results={}))
    cur = vs[-1]
    cur["results"][rk] = {t: {ch: {k: v.get(k) for k in BRIEF} for ch, v in tm.get("choices", {}).items()}
                          for t, tm in meta["types"].items() if tm.get("status") == "ok"}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh: json.dump(hist, fh, indent=1)
    os.replace(tmp, path)
    return cur, (vs[-2] if len(vs) > 1 else None)


def history(code):
    path = os.path.join(HISTORY, f"{code}.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else dict(code=code, versions=[])


def list_runs(code):
    out = []
    for f in glob.glob(os.path.join(RESULTS, code, "*", "meta.json")):
        try: out.append(json.load(open(f, encoding="utf-8")))
        except ValueError: pass
    return sorted(out, key=lambda m: m.get("at") or "", reverse=True)


def custom_backtest(spec, what, frm=None, to=None, tf=None, underlying=None, square_off="keep", label=None):
    """A backtest entry from a period request (preset / all / custom dates) and optional overrides."""
    if what in PRESETS: bt = dict(kind="preset", preset=what, label=label or what)
    elif what == "all": bt = dict(kind="all", label=label or "All data")
    elif what == "custom":
        if not (frm and to and frm <= to): raise ValueError("custom needs from <= to")
        bt = dict(kind="named", **{"from": frm, "to": to}, label=label or f"{frm} to {to}")
    else: raise ValueError(f"what must be one of {PRESETS + ('all', 'custom')}")
    if tf: bt["timeframe"] = tf
    if underlying: bt["underlying"] = underlying
    if square_off != "keep": bt["square_off"] = square_off
    return bt


# ================================================================ charts (computed on request)
def _chart_bars(b, i0, i1):
    return [[int(b.t[i]), float(b.o[i]), float(b.h[i]), float(b.l[i]), float(b.c[i]), float(b.v[i])] for i in range(i0, i1 + 1)]


_FZC = {}                     # (code, run, type) -> (bars, F): the FZ gate of a stored run, for its chart's zone layer


def _fz_layers(b, F, i0, i1):
    """FZ layers of b[i0..i1] (v1 lab.fz_chart): Z = the as-of zone card per bar, ZONES = the bands to draw (every band born
    by then holding a close of the range, every band a card row names, the 3 nearest the first close that are not too old;
    rooms retired before the range are not drawn unless a card row names them)."""
    fz = F["mod"]
    t, c, card, zs = b.t, b.c, F["out"]["card"], F["out"]["zones"]
    byid = {z["id"]: z for z in zs}
    zs = [z for z in zs if z.get("retired_bar") is None or z["retired_bar"] > i0]
    code = {x: k for k, x in enumerate(fz.READS)}
    iv = lambda x: None if x is None else int(round(x))
    Z = [[int(t[i]), d["zone_id"], d["visit_n"], d["this_bars"], iv(d["this_vol"]), d["first_bars"], iv(d["first_vol"]),
          code[d["read"]], d["left_id"], d["out_run"], int(bool(d["vol_na"])), d["gap_pts"], d["session_bar"],
          d["wick_depth"], d["in_id"], int(bool(d["first_vol_na"]))] for i in range(i0, i1 + 1) for d in (card[i],)]
    lo, hi = float(c[i0:i1 + 1].min()), float(c[i0:i1 + 1].max())
    keep = {}
    for z in zs:
        if z["birth_bar"] > i1 or z["hi"] + fz.EPS < lo or z["lo"] - fz.EPS > hi: continue
        a = max(i0, z["birth_bar"])
        if a <= i1 and np.any((c[a:i1 + 1] >= z["lo"] - fz.EPS) & (c[a:i1 + 1] <= z["hi"] + fz.EPS)): keep[z["id"]] = z
    age, sess = F["cfg"]["zone_max_age_sessions"], F["sess"]

    def fresh(z):
        if age is None: return True
        ends = [V["end"] for V in z["visits"] if V["start"] < i0]
        last = z["birth_bar"] if not ends else (i0 if ends[-1] is None or ends[-1] >= i0 else ends[-1])
        return sess[i0] - sess[last] <= age
    near = sorted((z for z in zs if z["birth_bar"] <= i0 and fresh(z)), key=lambda z: abs(z["mid"] - float(c[i0])))[:3]
    for z in near: keep.setdefault(z["id"], z)
    for row in Z:
        for zid in (row[1], row[8], row[14]):
            if zid is not None and zid in byid: keep.setdefault(zid, byid[zid])
    ZONES = [[z["id"], z["kind"], z["lo"], z["hi"], ts(z["born_ts"])] for z in sorted(keep.values(), key=lambda z: z["birth_bar"])]
    return dict(Z=Z, ZONES=ZONES, Z_COLS=list(F["Z_COLS"]), READS=list(fz.READS))


def _trend_avwap(b, sg, i0, i1):
    """The engine's trend AVWAP over b[i0..i1], one segment per anchor: anchored at the first confirmed swing, then at
    every trend flip on the swing the flip makes the anchor (the last swing high after a bearish flip, the last swing low
    after a bullish one); the engine reads it from the bar after the anchor is set. It qualifies the protected level and
    decides whether a CHoCH flips the trend."""
    if not len(sg.sc): return []
    ch = [(int(sg.sc[0]) + 1, int(sg.sb[0]))]
    for j in range(len(sg.qi)):
        if sg.qflip[j]:
            s_ = int(sg.qhi[j] if sg.qd[j] == -1 else sg.qlo[j])
            ch.append((int(sg.qi[j]) + 1, int(sg.sb[s_])))
    out = []
    for n, (a, anc) in enumerate(ch):
        z = ch[n + 1][0] - 1 if n + 1 < len(ch) else len(b) - 1
        lo, hi = max(a, i0), min(z, i1)
        if lo > hi: continue
        out.append(dict(anchor=tstr(b.t[anc]), pts=[[int(b.t[k]), round(sg.av(anc, k), 2)] for k in range(lo, hi + 1)]))
    return out


def _overlays(b, sg, i0, i1, pair=True):
    """The engine's layers over b[i0..i1]: candidate swing levels, swings, CHoCH / BOS, protected level, SETUPs, the AVWAP
    pair (live from the CHoCH, and back to its anchor), and a strategy's own lines (the rainbow ribbon)."""
    t = b.t
    rng = range(i0, i1 + 1)
    out = dict(
        cand=[[int(t[i]), None if np.isnan(sg.candh[i]) else float(sg.candh[i]), None if np.isnan(sg.candl[i]) else float(sg.candl[i])] for i in rng],
        swings=[["H" if sg.sk[k] == 1 else "L", int(t[sg.sb[k]]), float(sg.sp[k]), int(t[sg.sc[k]])]
                for k in range(len(sg.sk)) if i0 <= sg.sc[k] <= i1],
        events=[[int(t[sg.ei[k]]), "BOS" if sg.ek[k] == 0 else "CHoCH", "up" if sg.ed[k] == 1 else "down"]
                for k in range(len(sg.ei)) if i0 <= sg.ei[k] <= i1],
        flips=[int(t[sg.qi[j]]) for j in range(len(sg.qi)) if sg.qflip[j] and i0 <= sg.qi[j] <= i1],
        prot=[[int(t[i]), float(sg.prot[i])] for i in rng if not np.isnan(sg.prot[i])],
        setups=[[int(t[k]), "up" if dd == 1 else "down"] for k, dd in zip(sg.ui, sg.ud) if i0 <= k <= i1])
    P = []
    if pair:
        for j in range(len(sg.qi)):
            ci, end = int(sg.qi[j]), int(sg.qend[j])
            if end < i0 or ci > i1: continue
            for side, s_ in (("H", int(sg.qhi[j])), ("L", int(sg.qlo[j]))):
                if s_ < 0: continue
                a = int(sg.sb[s_])
                live = [[int(t[k]), round(sg.av(a, k), 2)] for k in range(max(ci, i0), min(end, i1) + 1)]
                back = [[int(t[k]), round(sg.av(a, k), 2)] for k in range(max(a, i0), min(ci, i1) + 1)] if ci >= i0 else []
                P.append(dict(side=side, anchor=tstr(t[a]), p=float(sg.sp[s_]), live=live, back=back))
    out["pair"] = P
    out["tav"] = _trend_avwap(b, sg, i0, i1)
    # the SETUP trigger: the CHoCH candle's high (bullish) / low (bearish), from the CHoCH to its SETUP or the next CHoCH
    setup_of = {int(c_): int(k) for k, c_ in zip(sg.ui, sg.uch)}
    trig = []
    for j in range(len(sg.qi)):
        ci = int(sg.qi[j])
        if sg.qhi[j] < 0 or sg.qlo[j] < 0: continue          # no AVWAP pair -> no SETUP possible from this CHoCH
        stop = setup_of.get(ci, int(sg.qend[j]))
        if stop < i0 or ci > i1: continue
        up = sg.qd[j] == 1
        trig.append(dict(dir="up" if up else "down", p=float(b.h[ci] if up else b.l[ci]),
                         a=int(t[max(ci, i0)]), z=int(t[min(stop, i1)]), hit=ci in setup_of))
    out["trig"] = trig
    if sg.lines is not None:
        out["lines"] = [[[int(t[i]), round(float(ln[i]), 2)] for i in rng if not np.isnan(ln[i])] for ln in sg.lines]
    return out


def chart(code, run, typ, choice, day, inst=None, to=None):
    """Sessions day .. to (default: day) of a stored run: the signal candles (futures or index) with the engine's layers, the
    FZ zones for FZ strategies, and this choice's trades; with `inst`, that option contract's own candles (from the session
    before) with its trades and, for standalone options, the engine on its candles."""
    mods = load_strategies(); mod = mods[code]
    folder = os.path.join(RESULTS, code, run)
    meta = json.load(open(os.path.join(folder, "meta.json"), encoding="utf-8"))
    body = json.load(open(os.path.join(folder, typ, f"{choice}.json"), encoding="utf-8"))
    tm = meta["types"][typ]
    ctx = context(mod, typ, meta["timeframe"], meta["underlying"], meta["square_off"], tm["date_from"], meta["date_to"], run)
    cols = {k: i for i, k in enumerate(body["cols"])}
    d0, d1 = dnum(day), dnum(to or day)
    trades = body["trades"]
    zones = None
    if inst:
        mine = [r for r in trades if r[cols["instrument"]] == inst]
        if not mine: raise ValueError("no trades on that instrument in this run")
        r0 = mine[0]
        s = OptionChain(meta["timeframe"]).get(r0[cols["expiry"]], r0[cols["strike"]], r0[cols["opt_type"]])
        if typ == "OPT_NATIVE":
            ob, _ = window(s, ctx["date_from"], ctx["date_to"], ctx["warmup"])
            sg = strategy_signals(dict(ctx, underlying="FUT"), ob); b = ob
        else:
            b, sg = s, None
        i1 = int(np.searchsorted(b.day, d1, "right")) - 1
        di = int(np.searchsorted(b.day, d0)); i0 = di
        if 0 < di < len(b): i0 = int(np.searchsorted(b.day, b.day[di - 1]))       # from the session before
        sel = [r for r in mine if d0 <= dnum(r[cols["entry_time"]]) <= d1]
        if sel: i1 = max(i1, int(np.searchsorted(b.t, max(ts(r[cols["exit_time"]]) for r in sel), "right")) - 1)
        marks = sel
    else:
        b, s0 = signal_bars(ctx)
        sg = strategy_signals(ctx, b)
        i0 = int(np.searchsorted(b.day, d0)); i1 = int(np.searchsorted(b.day, d1, "right")) - 1
        lo, hi = (int(b.t[i0]), int(b.t[i1])) if 0 <= i0 <= i1 < len(b) else (0, -1)
        marks = [r for r in trades if ts(r[cols["entry_time"]]) <= hi and ts(r[cols["exit_time"]]) >= lo]
        if hasattr(mod, "gate") and i1 >= i0:                 # FZ: the zone card and bands of this range
            key = (code, run, typ)
            if key not in _FZC:
                _FZC.clear()
                _, F = mod.gate(ctx, b, s0, sg)
                fzm = sys.modules.get("lib_fz")
                _FZC[key] = dict(F, mod=fzm, Z_COLS=family("foundation_zone").Z_COLS)
            zones = _fz_layers(b, _FZC[key], i0, i1)
    if not (0 <= i0 <= i1 < len(b)): raise ValueError(f"no candles from {day}" + (f" to {to}" if to else ""))
    out = dict(day=day, to=to or day, inst=inst, candles=_chart_bars(b, i0, i1), cols=body["cols"], trades=marks,
               sessions=int(len(np.unique(b.day[i0:i1 + 1]))))
    if typ == "OPT_NATIVE" and not inst:
        out["reference"] = True                       # standalone signals come from the option panes; this row is context only
    elif sg is not None: out.update(_overlays(b, sg, i0, i1, pair=out["sessions"] <= 30))
    if zones: out["fz"] = zones
    if inst and hasattr(mod, "option_lines"):         # a strategy's own lines on an option's chart (e.g. its SMA filter)
        k = np.searchsorted(s.t, b.t)                 # computed on the contract's whole series, as the filter reads it
        out["olines"] = [dict(name=nm_, pts=[[int(b.t[i]), round(float(v[k[i]]), 2)] for i in range(i0, i1 + 1)
                                             if k[i] < len(s) and s.t[k[i]] == b.t[i] and not np.isnan(v[k[i]])])
                         for nm_, v in mod.option_lines(s)]
    return _jsonable(out)


# ================================================================ explorer (any day, any instrument; computed on request)
def explorer_meta():
    mods = load_strategies(); ss = sessions()
    return dict(strategies=[dict(code=c, name=m.SPEC["name"], timeframe=m.SPEC["timeframe"], description=m.SPEC["description"],
                                 entry_rule=m.SPEC["rules"].get("entry_rule"), managed=position_of(m.SPEC)["exit"] == "position",
                                 square_off=position_of(m.SPEC)["square_off"])
                            for c, m in mods.items()],
                first=dstr(ss[0]), last=dstr(ss[-1]), tfs=list(TF_MIN))


def explorer_instruments(date, tf="minute"):
    """What can be shown on `date`: the futures contract, the index, and the option contracts with candles that day
    (the next three expiries and the month's expiry; strikes per right)."""
    d = dnum(date)
    if d not in set(sessions().tolist()): raise ValueError(f"{date} is not a session in the data")
    ct, con, exp, _ = fut_contracts()
    j = int(np.searchsorted(ct, d * DAY))
    fut = dict(contract=str(con[j]) if j < len(ct) and ct[j] // DAY == d else "NIFTY FUT",
               expiry=(str(exp[j]) or None) if j < len(ct) and ct[j] // DAY == d else None)
    ch = OptionChain("minute" if tf in ("minute", "3minute") else "5minute")
    exps = [e for e in ch.calendar if dnum(e) >= d][:3]
    mo = ch.expiry_for(d, 0, "MONTHLY")
    if mo and mo not in exps: exps.append(mo)
    opts = []
    for e in exps:
        strikes = {}
        for right in ("CE", "PE"):
            if e == ch.kite_exp:
                folder = os.path.join(ch.kite, ch.base)
                ks = sorted({int(f[len(ch.pre):-6]) for f in os.listdir(folder) if f.startswith(ch.pre) and f.endswith(right + ".csv")}) \
                    if os.path.isdir(folder) else []
                ks = [k for k in ks if (s := ch.get(e, k, right)) is not None and np.any(s.day == d)]
            else:
                tab, idx = ch._local_right(e, right)
                ks = sorted(k for k, (a, b_) in idx.items() if np.any(tab["t"][a:b_] // DAY == d))
            strikes[right] = ks
        if strikes["CE"] or strikes["PE"]: opts.append(dict(expiry=e, monthly=e == mo, strikes=strikes))
    sp = series("spot", "minute"); k = int(np.searchsorted(sp.day, d))
    return dict(date=date, futures=fut, index_open=float(sp.o[k]) if k < len(sp) and sp.day[k] == d else None, options=opts)


def option_milestones(src, expiry, strike, right, tf, step, liq_pct):
    """When an option contract was listed (its first candle), the previous expiry (the first candle on or after it), the
    first candle it was ATM (index within half a strike step) and ITM (CE: index above the strike, PE: below), from the
    index candle at that time; its first liquid session (daily volume >= liq_pct % of its busiest session); and its last
    candle. Times as int seconds, None where it never happened in the data. Hindsight by design (the busiest session):
    this is for reading a chart, never for a trading decision."""
    out = dict(listing=int(src.t[0]), expiry=int(src.t[-1]))
    ch = OptionChain(tf)
    prev = [e for e in ch.calendar if e < expiry]
    pe = dnum(prev[-1]) if prev else None
    k = int(np.searchsorted(src.day, pe)) if pe is not None else len(src)
    out["prev_expiry"] = int(src.t[k]) if k < len(src) else None
    sp = series("spot", tf)
    j = np.searchsorted(sp.t, src.t, "right") - 1
    ok = (j >= 0) & (sp.day[np.maximum(j, 0)] == src.day)
    spot = np.where(ok, sp.c[np.maximum(j, 0)], np.nan)
    atm = np.nonzero(np.abs(spot - strike) <= step / 2)[0]
    itm = np.nonzero(spot > strike if right == "CE" else spot < strike)[0]
    out["atm"] = int(src.t[atm[0]]) if len(atm) else None
    out["itm"] = int(src.t[itm[0]]) if len(itm) else None
    days, idx = np.unique(src.day, return_index=True)
    vol = np.add.reduceat(src.v, idx) if len(idx) else np.array([])
    liq = np.nonzero(vol >= vol.max() * liq_pct / 100)[0] if len(vol) and vol.max() > 0 else []
    out["liquid"] = int(src.t[idx[liq[0]]]) if len(liq) else None
    return out


def explorer_chart(date, inst, code, tf="minute", expiry=None, strike=None, right=None, days_before=1, holding="own",
                   start="days", end="date", liq_pct=10):
    """One instrument's candles around `date` with the engine's layers and the strategy's trades computed on those candles
    (a visualization, not a backtest: nothing stored). FUT = the near-month futures, INDEX = the index (equal-weight
    AVWAP), OPT = one option contract, the strategy applied to its own chart. The engine warms up on the strategy's
    warm-up sessions before the start; the chart starts `days_before` sessions before the date, or (options, `start`) at the
    contract's first candle ('listing'), the previous expiry ('prev_expiry'), its first ATM / ITM candle ('atm' / 'itm':
    from the index at that candle, ATM = within half a strike step) or its first liquid session ('liquid': daily volume at
    least `liq_pct` % of its busiest session); it ends at the date or (`end` = 'expiry') at the contract's last candle."""
    if tf not in TF_MIN: raise ValueError(f"tf must be one of {tuple(TF_MIN)}")
    if inst not in ("FUT", "INDEX", "OPT"): raise ValueError("inst is FUT, INDEX or OPT")
    days_before = max(0, min(int(days_before), 30))
    mod = load_strategies()[code]; spec = mod.SPEC
    ss = sessions(); d = dnum(date)
    k = int(np.searchsorted(ss, d))
    if k >= len(ss) or ss[k] != d: raise ValueError(f"{date} is not a session in the data")
    show, last, M, note = int(ss[max(0, k - days_before)]), d, None, ""
    if inst == "OPT":
        if not (expiry and strike and right in ("CE", "PE")): raise ValueError("an option needs expiry, strike and right")
        src = OptionChain(tf).get(expiry, int(strike), right)
        if src is None: raise ValueError(f"no candles for {expiry} {strike} {right}")
        name = OptionChain.name(expiry, int(strike), right)
        M = option_milestones(src, expiry, int(strike), right, tf, spec["options"]["strike_step"], float(liq_pct))
        if start != "days":
            if start not in M or start == "expiry": raise ValueError("start is days, listing, prev_expiry, atm, itm or liquid")
            if M[start] is None: note = f"never {start.replace('_', ' ')} in its data: shown from its first candle; "
            show = (M[start] or M["listing"]) // DAY
        if end == "expiry": last = int(src.day[-1])
        if show > last: raise ValueError(f"the chosen start ({dstr(show)}) is after the end ({dstr(last)}): pick a later date or end at expiry")
    else:
        src = series("spot" if inst == "INDEX" else "fut", tf); name = None
    ks = int(np.searchsorted(ss, show))
    first = int(ss[max(0, ks - spec["warmup_days"])])
    typ = "OPT_NATIVE" if inst == "OPT" else "FUT"
    sq = position_of(spec)["square_off"] if holding == "own" else (None if holding in ("none", "positional", "") else holding)
    ctx = context(mod, typ, tf, "INDEX" if inst == "INDEX" else "FUT", sq, dstr(show), dstr(last))
    a, z = int(np.searchsorted(src.day, first)), int(np.searchsorted(src.day, last, "right"))
    b = src.slice(a, z)
    if not len(b) or not np.any((b.day >= show) & (b.day <= last)): raise ValueError("no candles in that range")
    sg = strategy_signals(ctx, b)
    i0 = int(np.searchsorted(b.day, show)); i1 = len(b) - 1
    P = ctx["position"]; pmode = P["exit"] == "position"
    ct, con, exps, clast = fut_contracts()
    lock = StrikeLock(P["lock"] == "strike")
    trades, skipped = [], []
    leg_filter = getattr(mod, "leg_filter", None) if inst == "OPT" else None
    for x in sg.trades():
        if x["entry"] < i0: continue
        te = int(b.t[x["entry"]]); lng = x["dir"] == "up"
        if inst == "FUT":
            j = int(np.searchsorted(ct, te)); ok = j < len(ct) and ct[j] == te
            iname, e_ = (str(con[j]), str(exps[j]) or None) if ok else ("NIFTY FUT", None)
        else:
            iname, e_ = (name or "NIFTY index"), (expiry if inst == "OPT" else None)
        rec = dict(dir=x["dir"], signal="BULLISH" if lng else "BEARISH", position="LONG" if lng else "SHORT",
                   opt_type=right or inst, kind="OPT" if inst == "OPT" else "FUT", instrument=iname, strike=strike, expiry=e_,
                   choch_time=int(b.t[x["choch"]]), entry_time=te, exit_time=int(b.t[x["exit"]]), exit_reason=x["exit_reason"],
                   open=x["open"], sl=x["sl"], entry_px=float(b.c[x["entry"]]), exit_px=x["exit_px"], und_entry=None, und_exit=None)
        why = leg_filter(ctx, rec, src) if leg_filter else None      # e.g. Strategy 32's SMA filter on the whole contract
        if why:
            skipped.append(dict(entry_time=tstr(te), position=rec["position"], why=why, filtered=True)); continue
        e = square_off_at(sq, te)
        if e and te >= e:
            skipped.append(dict(entry_time=tstr(te), position=rec["position"], why="entry at or after the square-off time")); continue
        u = lock.held(iname, te)
        if u:
            skipped.append(dict(entry_time=tstr(te), position=rec["position"], why=f"strike locked: open until {tstr(u)}")); continue
        cap = int(b.t[-1])
        if inst == "FUT" and e_ and iname in clast: cap = min(cap, clast[iname])
        if pmode: parts = managed_with_reversals(P, rec, b, cap, e_)
        else:
            eod_cut(sq, rec, b); parts = tranches(P, rec, b)
        lock.hold(iname, max(q["exit_time"] for q in parts), any(q["open"] for q in parts))
        for tr in parts:
            excursion(b, tr, tr["position"] == "LONG")
            tr["label"] = tr["position"] + (f" · {tr['tranche']}" if tr.get("tranche") else "")
            trades.append(price_trade(ctx, tr))
    out = dict(meta=dict(date=date, first_shown=dstr(show), inst=inst, instrument=name or (trades[0]["instrument"] if trades else inst),
                         expiry=expiry, strike=strike, right=right, tf=tf, code=code, strategy=spec["name"], position=P,
                         rules=spec["rules"], lot_size=spec["lot_size"], slippage_pts=ctx["slippage_pts"], warmup_from=dstr(first),
                         note="visualization only: the strategy's signals() on this instrument's own candles, priced with its "
                              "position rules; FZ gates, the learner and c2c's put rule are not applied here (their trades are "
                              "the Foundation engine's)" if getattr(mod, "gate", None) or getattr(mod, "run", None) else
                              "visualization only: the strategy's signals() on this instrument's own candles, priced with its position rules"),
               candles=_chart_bars(b, i0, i1), cols=list(TRADE_COLS), trades=trade_rows(trades), skipped=skipped,
               net=round(sum(x["net"] for x in trades), 2))
    out.update(_overlays(b, sg, i0, i1, pair=len(np.unique(b.day[i0:i1 + 1])) <= 30))
    out["meta"]["note"] = note + out["meta"]["note"]
    out["meta"]["range"] = [dstr(show), dstr(last)]
    if M is not None:
        lbl = dict(listing="listed", prev_expiry="prev expiry", atm="first ATM", itm="first ITM", liquid="liquid", expiry="expiry")
        out["milestones"] = [dict(key=k_, label=lbl[k_], ts=v, time=tstr(v) if v is not None else None) for k_, v in M.items() if k_ in lbl]
        sp = series("spot", tf)
        j = np.searchsorted(sp.t, b.t[i0:i1 + 1], "right") - 1
        okj = (j >= 0) & (sp.day[np.maximum(j, 0)] == b.day[i0:i1 + 1])
        out["spot"] = [[int(t_), float(sp.c[jj])] for t_, jj, o_ in zip(b.t[i0:i1 + 1], j, okj) if o_]
        out["strike"] = int(strike)
        if hasattr(mod, "option_lines"):              # the strategy's own lines (Strategy 32: SMA 200 from the contract's first candle)
            out["olines"] = [dict(name=nm_, pts=[[int(b.t[i]), round(float(v[a + i]), 2)] for i in range(i0, i1 + 1)
                                                 if not np.isnan(v[a + i])]) for nm_, v in mod.option_lines(src)]
    elif hasattr(mod, "TYPES") and "FUT" not in mod.TYPES:
        out["meta"]["note"] += f" · {spec['code']} does not trade this instrument: " + str(getattr(mod, "REFUSED_WHY", ""))
    return _jsonable(out)

def explorer_expiries(tf="minute"):
    """Every option expiry the data holds (newest first): its date, weekly / monthly, and whether it has full-chain data."""
    ch = OptionChain("minute" if tf in ("minute", "3minute") else "5minute")
    months = set(ch.monthly)
    out = []
    for e in reversed(ch.calendar):
        base = os.path.join(ch.root, e[:4], e)
        has = e == ch.kite_exp or os.path.isdir(base)
        if not has: continue
        full = e == ch.kite_exp or (os.path.exists(os.path.join(base, "manifest.json"))
                                    and "full_chain" in json.load(open(os.path.join(base, "manifest.json"), encoding="utf-8")))
        out.append(dict(expiry=e, monthly=e in months, full_chain=bool(full)))
    return out


def explorer_strikes(expiry, tf="minute", date=None):
    """One expiry's contracts: strikes with candles per right, the first / last session of the contracts, and the strike
    nearest the index on `date` (clamped into the contracts' life) as the suggested one."""
    ch = OptionChain("minute" if tf in ("minute", "3minute") else "5minute")
    strikes, lives, first, last = {}, {}, None, None
    for right in ("CE", "PE"):
        if expiry == ch.kite_exp:
            folder = os.path.join(ch.kite, ch.base)
            ks = sorted({int(f[len(ch.pre):-6]) for f in os.listdir(folder) if f.startswith(ch.pre) and f.endswith(right + ".csv")}) if os.path.isdir(folder) else []
            spans = []
            for k_ in ks:
                b_ = ch.get(expiry, k_, right)
                if b_ is not None: spans.append((k_, int(b_.day[0]), int(b_.day[-1])))
        else:
            tab, idx = ch._local_right(expiry, right)
            spans = [(k_, int(tab["t"][a] // DAY), int(tab["t"][b_ - 1] // DAY)) for k_, (a, b_) in sorted(idx.items())]
        strikes[right] = [k_ for k_, _, _ in spans]
        lives[right] = {str(k_): [dstr(f_), dstr(l_)] for k_, f_, l_ in spans}      # each strike trades over its own dates
        for _, f_, l_ in spans:
            first = f_ if first is None else min(first, f_); last = l_ if last is None else max(last, l_)
    if first is None: raise ValueError(f"no option candles for {expiry}")
    d = dnum(date) if date else last
    d = min(max(d, first), last)
    sp = series("spot", "minute")
    k = int(np.searchsorted(sp.day, d, "right")) - 1
    spot = float(sp.c[k]) if k >= 0 else None
    ds = dstr(d)
    def near(right):
        # the strike nearest the index among those trading on the date (else among all of them)
        ks = strikes[right]
        alive = [k_ for k_ in ks if lives[right][str(k_)][0] <= ds <= lives[right][str(k_)][1]] or ks
        return min(alive, key=lambda x: abs(x - spot)) if alive and spot is not None else (alive[0] if alive else None)
    return dict(expiry=expiry, first=dstr(first), last=dstr(last), date=ds, index_close=spot,
                strikes=strikes, lives=lives, atm=dict(CE=near("CE"), PE=near("PE")))
