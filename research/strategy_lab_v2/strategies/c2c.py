"""CHoCH to CHoCH put retest (entry_rule c2c_v1): the family module behind ST25-ST28 (v1 c2c.py).

Buy a NIFTY put when the 5-minute structure has flipped bearish and a fresh swing high confirms near the VWAP anchored at
the peak before the break; hold until the structure flips back up, a premium stop / trail, or the decision ladder.

Entry - all on the same closed signal candle i (every number in SPEC["c2c"]):
  regime bearish (the engine's trend after a flip down) · a swing high confirms at i · anchored VWAP - band_pts < swing
  high < VWAP + band_pts · close > the session's first open x (1 - day_drop_pct %) · window PCR < pcr.entry_max (PCR books;
  NA = not met) · i is not the flip bar. The put: strike from the index close at i (options.strike_default), nearest expiry
  of options.expiry_types at least expiry_min_days out, full-chain data only; entered at the open of its first candle at or
  after the next signal candle, the same session. One position at a time.
Exits on the put's own candles from the entry candle: stop stop_pct % below entry, then trail_pts behind the peak
  (stop_fill "close": a close at or below it, peak = highest close; "touch": the low, at the stop / the open below it / a
  session's first candle at its close, peak = highest high) · the regime flips bullish ('choch') · once per session at
  ladder.time: up > profit_pct %, down > loss_pct %, or window PCR > pcr.exit_above · 'expiry' / 'open' at the end.
Window PCR: sum PE OI / sum CE OI over strikes within window_pts of the index ATM, the traded expiry, each strike counted
  when both rights have an OI print at or before the candle that session; NA below min_strikes.
Options (via futures) type only, 5-minute candles.
"""
import bisect, glob, json, os
import numpy as np
import pandas as pd
import core

ENTRY_RULES = ("c2c_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
TIMEFRAMES = ("5minute",)
OWN_COVERAGE = True          # full-chain data is checked per trade (a window may span covered and uncovered expiries)
REFUSED_WHY = "c2c v1 buys puts: only the Options (via futures) type runs"
TF_WHY = "c2c v1 runs on 5-minute candles (the option and OI files are 5-minute)"
DAY = core.DAY

_FULL = {}
def full_chain(e):
    """True when expiry e has full-chain option data (5-minute manifest with full_chain, or the Kite expiry)."""
    if e is None: return False
    o = core.DATA["options"]
    if e == o["kite_expiry"]: return True
    if e not in _FULL:
        f = os.path.join(o["weekly_dir"], "nifty_options", e[:4], e, "manifest.json")
        _FULL[e] = os.path.exists(f) and "full_chain" in json.load(open(f, encoding="utf-8"))
    return _FULL[e]


class OI:
    """Open interest by (expiry, right, strike) -> (times, oi), 5-minute files, cached as numpy under cache/oi/."""
    _local, _kite = {}, {}

    def _load_local(self, e, right):
        key = (e, right)
        if key not in self._local:
            o = core.DATA["options"]
            base = os.path.join(o["weekly_dir"], "nifty_options", e[:4], e)
            files = [os.path.join(base, f"NIFTY_{e}_{right}_5minute.csv")] + sorted(glob.glob(os.path.join(base, ".chunks", "options", right, "*", "*.csv")))
            files = [f for f in files if os.path.exists(f)]
            idx, tab = {}, None
            if files:
                os.makedirs(os.path.join(core.CACHE, "oi"), exist_ok=True)
                npz = os.path.join(core.CACHE, "oi", f"{e}_{right}.{core._sig(files)}.npz")
                if os.path.exists(npz):
                    z = np.load(npz); tab = {k: z[k] for k in z.files}
                else:
                    parts = []
                    for f in files:
                        df = pd.read_csv(f, float_precision="round_trip", dtype={"datetime": str},
                                         usecols=lambda c: c in ("datetime", "strike_price", "open_interest"))
                        if "open_interest" not in df: continue
                        df = df[df["open_interest"].notna()]
                        parts.append(pd.DataFrame(dict(strike=df["strike_price"].astype(np.float64).astype(np.int64).values,
                                                       t=pd.to_datetime(df["datetime"], format="%Y-%m-%d %H:%M:%S").values.astype("datetime64[s]").astype(np.int64),
                                                       oi=df["open_interest"].astype(np.float64).values)))
                    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(dict(strike=[], t=[], oi=[]))
                    df = df.drop_duplicates(["strike", "t"], keep="last").sort_values(["strike", "t"], kind="mergesort")
                    tab = dict(strike=df["strike"].values.astype(np.int64), t=df["t"].values.astype(np.int64), oi=df["oi"].values.astype(np.float64))
                    np.savez(npz, **tab)
                if len(tab["strike"]):
                    ks, st = np.unique(tab["strike"], return_index=True)
                    en = list(st[1:]) + [len(tab["strike"])]
                    idx = {int(k): (tab["t"][a:b], tab["oi"][a:b]) for k, a, b in zip(ks, st, en)}
            self._local[key] = idx
        return self._local[key]

    def series(self, e, right, k):
        o = core.DATA["options"]
        if e != o["kite_expiry"]: return self._load_local(e, right).get(k)
        key = (right, k)
        if key not in self._kite:
            p = os.path.join(o["kite_dir"], "5minute", f"{o['kite_prefix']}{k}{right}.csv")
            s = None
            if os.path.exists(p) and os.path.getsize(p) > 100:
                df = pd.read_csv(p, float_precision="round_trip", dtype={"datetime": str})
                if "oi" in df:
                    df = df[df["oi"].notna()]
                    if len(df): s = (pd.to_datetime(df["datetime"], format="%Y-%m-%d %H:%M:%S").values.astype("datetime64[s]").astype(np.int64),
                                     df["oi"].astype(np.float64).values)
            self._kite[key] = s
        return self._kite[key]

    def at(self, e, right, k, when):
        """OI of the last print at or before `when` the same session, else None."""
        s = self.series(e, right, k)
        if s is None or not len(s[0]): return None
        j = int(np.searchsorted(s[0], when, "right")) - 1
        return float(s[1][j]) if j >= 0 and s[0][j] // DAY == when // DAY else None

    def pcr(self, e, when, spot, P, step):
        atm = round(spot / step) * step
        w = int(P["window_pts"] // step)
        pe = ce = 0.0; n = 0
        for k in range(atm - w * step, atm + w * step + 1, step):
            a, b = self.at(e, "PE", k, when), self.at(e, "CE", k, when)
            if a is None or b is None: continue
            pe += a; ce += b; n += 1
        return (round(pe / ce, 4) if n >= P["min_strikes"] and ce > 0 else None), n


def hold(os_, k0, e, cfg, ups, after, pcr_at, iend):
    """Walk one long put from its entry candle k0 (entered at its open, price e) to iend. Returns (exit index, exit price,
    reason, still open, final stop, peak)."""
    close_mode = cfg["stop_fill"] == "close"
    L, P = cfg["ladder"], cfg["pcr"]
    lt = core.hhmm_sec(L["time"])
    stop0 = stop = e * (1 - cfg["stop_pct"] / 100)
    peak, laddered = e, set()
    t, o_, h_, l_, c_, day = os_.t, os_.o, os_.h, os_.l, os_.c, os_.day
    if (t[k0] % DAY) // 60 > lt // 60: laddered.add(int(day[k0]))     # entered after the ladder: from the next session
    u = bisect.bisect_right(ups, after)
    for k in range(k0, iend + 1):
        T, o, h, l, c = int(t[k]), float(o_[k]), float(h_[k]), float(l_[k]), float(c_[k])
        first = k > 0 and day[k - 1] != day[k]
        why = "trail_stop" if stop > stop0 else "stop_loss"
        if close_mode:
            if c <= stop: return k, c, why, False, stop, peak
        else:
            gap = k > k0 and o <= stop
            if gap or l <= stop: return k, (c if first and k > k0 else (o if gap else stop)), why, False, stop, peak
        if u < len(ups) and ups[u] <= T:
            return k, (c if ups[u] == T else o), "choch", False, stop, peak
        if (T % DAY) // 60 >= lt // 60 and int(day[k]) not in laddered:
            laddered.add(int(day[k]))
            pnl = (c - e) / e * 100
            if pnl > L["profit_pct"]: return k, c, "ladder_profit", False, stop, peak
            if pnl < -L["loss_pct"]: return k, c, "ladder_loss", False, stop, peak
            if P is not None:
                x = pcr_at(T)
                if x is not None and x > P["exit_above"]: return k, c, "ladder_pcr", False, stop, peak
        peak = max(peak, c if close_mode else h)
        if peak > e: stop = max(stop, peak - cfg["trail_pts"])
    return iend, float(c_[iend]), "open", True, stop, peak


def signals(bars, spec):
    """The engine (no stop rule) on these candles: its structure feeds the entry; its own SETUP trades are not used."""
    return core.foundation(bars, dict(spec["rules"], sl_rule="none"))


def run(ctx):
    """{choice: dict(trades, skipped, signals)} for one c2c window (v1 c2c.run_variant)."""
    spec = ctx["spec"]; cfg = spec["c2c"]; P = cfg["pcr"]; opt = spec["options"]
    if ctx["tf"] not in TIMEFRAMES: raise ValueError(TF_WHY)
    fut, s0 = core.signal_bars(ctx)
    r = core.strategy_signals(ctx, fut)
    t, o, c = fut.t, fut.o, fut.c
    n = len(t)
    spot = core.series("spot", ctx["tf"]); atr = core.atr(spot, opt["atr_period"])
    chain, oi, step = core.OptionChain(ctx["tf"]), OI(), opt["strike_step"]
    # regime per bar from the engine's trend flips: (-1 / 0 / 1, flip bar, anchor bar)
    reg_v = np.zeros(n, np.int8); reg_f = np.full(n, -1, np.int64); reg_a = np.full(n, -1, np.int64)
    flips = {int(r.qi[j]): j for j in range(len(r.qi)) if r.qflip[j]}
    cur = (0, -1, -1)
    for i in range(n):
        j = flips.get(i)
        if j is not None:
            cur = (-1, i, int(r.sb[r.qhi[j]])) if r.qd[j] == -1 else (1, i, int(r.sb[r.qlo[j]]))
        reg_v[i], reg_f[i], reg_a[i] = cur
    ups = sorted(int(t[r.qi[j]]) for j in range(len(r.qi)) if r.qflip[j] and r.qd[j] == 1)
    day_open = {}
    for i in range(n): day_open.setdefault(int(fut.day[i]), float(o[i]))
    cap_all = core.dnum(ctx["date_to"]) * DAY + DAY - 1
    lots = ctx["position"]["lots"]
    pcr_memo = {}

    def pcr_of(e, when):
        if (e, when) not in pcr_memo:
            sp, _ = spot.at(when)
            pcr_memo[(e, when)] = oi.pcr(e, when, sp, P, step) if sp is not None else (None, 0)
        return pcr_memo[(e, when)]

    highs = [q for q in range(len(r.sk)) if r.sk[q] == 1]          # swing highs, in confirmation order
    out = {}
    for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL"):
        ekind, sc = core.split_choice(ch)
        trs, skipped, free_at = [], [], -1
        for q in highs:
            i = int(r.sc[q])
            if i < s0: continue
            rg, fi, anchor = int(reg_v[i]), int(reg_f[i]), int(reg_a[i])
            if rg != -1 or fi == i: continue
            av = r.av(anchor, i)
            if not (av - cfg["band_pts"] < float(r.sp[q]) < av + cfg["band_pts"]): continue
            if not float(c[i]) > day_open[int(fut.day[i])] * (1 - cfg["day_drop_pct"] / 100): continue
            base = dict(dir="down", signal="BEARISH", position="LONG", opt_type="PE", choch_time=int(t[fi]), signal_time=int(t[i]))
            if i + 1 >= n:
                skipped.append(dict(base, entry_time=int(t[i]), why="no next candle in the window")); continue
            ti = int(t[i + 1])
            si = spot.find(int(t[i]))
            if si < 0:
                skipped.append(dict(base, entry_time=ti, why="no spot candle")); continue
            k = core.pick_strike(sc, "PE", float(spot.c[si]), float(atr[si]), step)
            exp = chain.expiry_for(ti // DAY, opt["expiry_min_days"], ekind)
            nm = chain.name(exp, k, "PE") if exp else f"{int(k)} PE"
            base.update(instrument=nm, strike=k, expiry=exp)
            if not full_chain(exp):
                skipped.append(dict(base, entry_time=ti, why=f"no full-chain data for {nm}")); continue
            if P is not None:
                x, used = pcr_of(exp, int(t[i]))
                if x is None:
                    skipped.append(dict(base, entry_time=ti, why=f"PCR NA ({used} strikes with OI within {P['window_pts']:g} pts)")); continue
                if not x < P["entry_max"]: continue
                base["pcr"] = x
            os_ = chain.get(exp, k, "PE")
            if os_ is None:
                skipped.append(dict(base, entry_time=ti, why=f"no data for {nm}")); continue
            k0 = int(np.searchsorted(os_.t, ti))
            if k0 >= len(os_) or os_.day[k0] != ti // DAY:
                skipped.append(dict(base, entry_time=ti, why=f"{nm} has no candle at or after {core.tstr(ti)[11:16]} that session")); continue
            if os_.t[k0] <= free_at:
                skipped.append(dict(base, entry_time=int(os_.t[k0]), why=f"strike locked (one position at a time): open until {core.tstr(free_at)}")); continue
            iend = int(np.searchsorted(os_.t, min(cap_all, core.dnum(exp) * DAY + DAY - 1), "right")) - 1
            e = float(os_.o[k0])
            kx, px, why, still, stop, peak = hold(os_, k0, e, cfg, ups, int(t[i]), lambda T: pcr_of(exp, T)[0], iend)
            if still and os_.day[kx] >= core.dnum(exp): why, still = "expiry", False
            free_at = int(os_.t[kx])
            jx = max(int(np.searchsorted(t, free_at, "right")) - 1, 0)
            rec = dict(base, kind="OPT", entry_time=int(os_.t[k0]), entry_px=e, exit_time=free_at, exit_px=round(px, 2),
                       exit_reason=why, open=still, sl=round(stop, 2), und_entry=float(o[i + 1]), und_exit=float(c[jx]), stale=False,
                       lots=lots, tranche="", peak=round(peak, 2), label="LONG PE")
            core.excursion(os_, rec, True)
            trs.append(core.price_trade(ctx, rec))
        signals_ = []
        for j in range(len(r.qi)):
            if r.qi[j] < s0: continue
            T = int(t[r.qi[j]]); hi, lo = int(r.qhi[j]), int(r.qlo[j])
            signals_.append(dict(time=T, dir="up" if r.qd[j] == 1 else "down", flipped=bool(r.qflip[j]), lvl=float(r.qlvl[j]),
                                 av=float(r.qav[j]), hi=(int(t[r.sb[hi]]), float(r.sp[hi])) if hi >= 0 else None,
                                 lo=(int(t[r.sb[lo]]), float(r.sp[lo])) if lo >= 0 else None,
                                 setup=next((x["entry_time"] for x in trs if x["choch_time"] == T), None)))
        out[ch] = dict(trades=trs, skipped=skipped, signals=signals_)
    return out
