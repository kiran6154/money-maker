"""CHoCH to CHoCH put retest (entry_rule c2c_v1): buy a NIFTY put when the 5-minute structure has flipped bearish and a fresh
swing high confirms near the VWAP anchored at the peak before the break; hold until the structure flips back up, a premium
stop / trail, or the 15:15 decision ladder. Source: the user's "Nifty CHoCH to CHoCH in Plain English" spec (2026-09-29).

What is the engine's and what is this module's
  engine.run() supplies the swings, the CHoCH events and the AVWAP function. The regime is the engine's own trend: bearish
  from a CHoCH that flips it down (a close through the protected level and the anchored VWAP) until one flips it up; a CHoCH
  that breaks the protected level without flipping the trend changes nothing here. The anchored VWAP is the engine's AVWAP
  from the swing high the flip re-anchors at (e["hi"]: the peak of the rally before the break) - equal-weighted on the index
  (no volume), volume-weighted on futures.

Entry - every rule true on the same closed signal candle i (the file's `c2c` block holds every number):
  1. regime bearish at i                                 5. close[i] > first open of the session x (1 - day_drop_pct %)
  2. a swing high confirms at i                          6. window PCR at i < pcr.entry_max (PCR books only; NA = not met)
  3-4. anchored VWAP - band_pts < swing high < VWAP + band_pts   7. i is not the bar of the bearish flip itself
  The put: strike from the index close at i (options.strike_default, ITM1 = one strike above ATM for a put), the nearest
  expiry of options.expiry_types at least options.expiry_min_days out. Entered at the open of the put's first candle at or
  after the next signal candle, the same session only. One position at a time: a signal while one is open is skipped.

Exits, candle by candle on the put's own candles from the entry candle (the file's `c2c` block):
  stop    stop_pct % below the entry premium; once the premium has gained, trail_pts behind the peak premium (whichever is
          higher; never lowered). stop_fill "close": a finished candle closing at or below the stop exits at that close,
          and the peak is the highest close. "touch": the low touching it exits at the stop (at the open when the candle
          opens below it; on a session's first candle at its close - the lab's no-fill-on-the-opening-print rule), and the
          peak is the highest high; a stop raised on a candle applies from the next one.
  choch   the regime flips bullish: exit at the close of the put's candle at that time (at the open of its next candle when
          it has none then)
  ladder  once per session, on the put's first candle labelled at or after ladder.time: exit at its close if the premium
          is up more than profit_pct %, down more than loss_pct %, or (PCR books) the window PCR is above pcr.exit_above
  Checked in that order on each candle. Still open at the contract's last candle on or after its expiry date: 'expiry';
  at the backtest's end: open (valued at the last close).

Window PCR (pcr block): sum of PE open interest / sum of CE open interest over the strikes within window_pts of the ATM
of the index at that candle, the traded expiry, each strike counted only when both rights have an OI print at or before
the candle that session; NA when fewer than min_strikes qualify. The local option files hold a strike window, not the
full chain, so this is a stand-in for the exchange PCR (STRATEGY_ANALYSIS_TODO S52).

No hindsight strikes: a contract is priced only when its expiry has full-chain data (a manifest with full_chain, or the
Kite chain expiry) - the lab's option_coverage rule applied per trade instead of per backtest, so a window can span expiries
with and without it; signals on an uncovered expiry are skipped with the reason.

v1 scope: the Options (via futures) type, 5-minute candles, long puts on bearish structure only. The Futures and
Options (standalone) types are refused with a reason.
"""
import bisect, csv, glob, hashlib, json, os
import engine
import lab

RULES = ("c2c_v1",)
MODULES = ("c2c.py",)
TYPE_WHY = "c2c v1 buys puts: only the Options (via futures) type runs"
TF_WHY = "c2c v1 runs on 5-minute candles (the option and OI files are 5-minute)"
TIMEFRAME = "5minute"
STOP_FILLS = ("close", "touch")
KEYS = {"band_pts", "day_drop_pct", "pcr", "stop_pct", "trail_pts", "stop_fill", "ladder", "max_open"}
PCR_KEYS = {"entry_max", "exit_above", "window_pts", "min_strikes"}
LADDER_KEYS = {"time", "profit_pct", "loss_pct"}


def c2c_rule(st):
    return str(st.get("entry_rule") or "") in RULES


def code_hash():
    h = hashlib.sha1()
    for f in MODULES: h.update(open(os.path.join(lab.HERE, f), "rb").read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def config_of(spec):
    """The strategy file's `c2c` block, validated. Every key is required: there are no defaults in code (+ optional notes)."""
    c = spec.get("c2c")
    if not isinstance(c, dict): raise ValueError("entry_rule c2c_v1 needs a 'c2c' block")
    if not KEYS <= set(c) <= KEYS | {"notes"}: raise ValueError(f"keys are {sorted(KEYS)} (+ optional notes; got {sorted(c)})")
    pos = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    for k in ("band_pts", "day_drop_pct", "stop_pct", "trail_pts"):
        if not pos(c[k]): raise ValueError(f"{k} must be > 0")
    if c["stop_fill"] not in STOP_FILLS: raise ValueError(f"stop_fill must be one of {STOP_FILLS}")
    if c["max_open"] != 1: raise ValueError("max_open: v1 holds one position at a time (1)")
    L = c["ladder"]
    if not isinstance(L, dict) or set(L) != LADDER_KEYS: raise ValueError(f"ladder keys are {sorted(LADDER_KEYS)}")
    if not (isinstance(L["time"], str) and len(L["time"]) == 5 and "09:15" < L["time"] < "15:30"): raise ValueError('ladder.time is "HH:MM" inside the session')
    if not (pos(L["profit_pct"]) and pos(L["loss_pct"])): raise ValueError("ladder profit_pct / loss_pct must be > 0")
    P = c["pcr"]
    if P is not None:
        if not isinstance(P, dict) or set(P) != PCR_KEYS: raise ValueError(f"pcr is null (rules off) or has keys {sorted(PCR_KEYS)}")
        if not all(pos(P[k]) for k in ("entry_max", "exit_above", "window_pts")): raise ValueError("pcr thresholds and window_pts must be > 0")
        if not (isinstance(P["min_strikes"], int) and P["min_strikes"] >= 1): raise ValueError("pcr.min_strikes: a whole number >= 1")
    if spec["timeframe"] != TIMEFRAME: raise ValueError(TF_WHY)
    if spec["options"]["strike_choices"] != [spec["options"]["strike_default"]]:
        raise ValueError("options.strike_choices is the one strike the rule trades (= strike_default)")
    return c


# ---------------------------------------------------------------- option data
def full_chain(st, e, _memo={}):
    """True when expiry e has full-chain option data (the lab's option_coverage test for one expiry)."""
    if e is None: return False
    if e == st["option_expiry"]: return True
    if e not in _memo:
        f = os.path.join(st["weekly_dir"], "nifty_options", e[:4], e, "manifest.json")
        _memo[e] = os.path.exists(f) and "full_chain" in json.load(open(f, encoding="utf-8"))
    return _memo[e]


class OI:
    """Open interest by (expiry, right, strike) -> (sorted times, oi), 5-minute files; loaded on first use."""

    def __init__(self, st):
        self.st, self.local, self.kite = st, {}, {}

    def _local(self, e, right):
        key = (e, right)
        if key not in self.local:
            base = os.path.join(self.st["weekly_dir"], "nifty_options", e[:4], e)
            by = {}
            files = [os.path.join(base, f"NIFTY_{e}_{right}_5minute.csv")] + sorted(glob.glob(os.path.join(base, ".chunks", "options", right, "*", "*.csv")))
            for f in files:
                if not os.path.exists(f): continue
                with open(f) as fh:
                    for r in csv.DictReader(fh):
                        v = r.get("open_interest")
                        if v not in (None, ""): by.setdefault(int(float(r["strike_price"])), {})[r["datetime"]] = float(v)
            self.local[key] = {k: (sorted(d), [d[x] for x in sorted(d)]) for k, d in by.items()}
        return self.local[key]

    def series(self, e, right, k):
        if e != self.st["option_expiry"]: return self._local(e, right).get(k)
        key = (right, k)
        if key not in self.kite:
            p = os.path.join(self.st["option_dir"], "5minute", f"{self.st['option_prefix']}{k}{right}.csv")
            s = None
            if os.path.exists(p) and os.path.getsize(p) > 100:
                with open(p) as fh: rows = [r for r in csv.DictReader(fh) if r.get("oi") not in (None, "")]
                if rows: s = ([r["datetime"] for r in rows], [float(r["oi"]) for r in rows])
            self.kite[key] = s
        return self.kite[key]

    def at(self, e, right, k, when):
        """OI of the last print at or before `when` the same session, else None."""
        s = self.series(e, right, k)
        if not s: return None
        j = bisect.bisect_right(s[0], when) - 1
        return s[1][j] if j >= 0 and s[0][j][:10] == when[:10] else None

    def pcr(self, e, when, spot, P, step):
        """(PCR, strikes used) over the strikes within P.window_pts of the ATM; (None, n) below P.min_strikes."""
        atm = round(spot / step) * step
        w = int(P["window_pts"] // step)
        pe = ce = 0.0; n = 0
        for k in range(atm - w * step, atm + w * step + 1, step):
            a, b = self.at(e, "PE", k, when), self.at(e, "CE", k, when)
            if a is None or b is None: continue
            pe += a; ce += b; n += 1
        return (round(pe / ce, 4) if n >= P["min_strikes"] and ce > 0 else None), n


# ---------------------------------------------------------------- the rule
def regimes(r, n):
    """Per signal bar: (regime -1 / 0 / 1, index of the flip that set it, its anchor bar) from the engine's trend flips."""
    out, cur = [(0, None, None)] * n, (0, None, None)
    flips = {e["i"]: e for e in r["chs"] if e["flip"]}
    for i in range(n):
        e = flips.get(i)
        if e: cur = (-1, i, e["hi"]["bar"]) if e["dir"] == "down" else (1, i, e["lo"]["bar"])
        out[i] = cur
    return out


def hold(os_, k0, e, cfg, ups, after, pcr_at, iend):
    """Walk one long put from its entry candle k0 (entered at its open, price e) to iend (see the module doc); `after` is
    the signal candle's time (bullish flips after it exit). Returns (exit index, exit price, reason, open, final stop, peak)."""
    close_mode = cfg["stop_fill"] == "close"
    L, P = cfg["ladder"], cfg["pcr"]
    stop0 = stop = e * (1 - cfg["stop_pct"] / 100)
    peak, laddered = e, set()
    if os_.t[k0][11:16] > L["time"]: laddered.add(os_.t[k0][:10])  # entered after the ladder: it applies from the next session
    u = bisect.bisect_right(ups, after)
    for k in range(k0, iend + 1):
        T, o, h, l, c = os_.t[k], os_.o[k], os_.h[k], os_.l[k], os_.c[k]
        first = k > 0 and os_.t[k - 1][:10] != T[:10]
        why = "trail_stop" if stop > stop0 else "stop_loss"
        if close_mode:
            if c <= stop: return k, c, why, False, stop, peak
        else:
            gap = k > k0 and o <= stop
            if gap or l <= stop: return k, (c if first and k > k0 else (o if gap else stop)), why, False, stop, peak
        if u < len(ups) and ups[u] <= T:
            return k, (c if ups[u] == T else o), "choch", False, stop, peak
        if T[11:16] >= L["time"] and T[:10] not in laddered:
            laddered.add(T[:10])
            pnl = (c - e) / e * 100
            if pnl > L["profit_pct"]: return k, c, "ladder_profit", False, stop, peak
            if pnl < -L["loss_pct"]: return k, c, "ladder_loss", False, stop, peak
            if P is not None:
                x = pcr_at(T)
                if x is not None and x > P["exit_above"]: return k, c, "ladder_pcr", False, stop, peak
        peak = max(peak, c if close_mode else h)
        if peak > e: stop = max(stop, peak - cfg["trail_pts"])
    return iend, os_.c[iend], "open", True, stop, peak


def run_variant(st, cs):
    """Lab-shaped result for a c2c row: {choice: dict(trades, skipped, signals, charts, c2c)}."""
    keys = lab.choice_keys(st)
    if st["variant"] != "OPT_FUT_SIGNAL":
        return {ch: dict(trades=[], skipped=[dict(why=TYPE_WHY)], signals=[], charts=[]) for ch in keys}
    cfg = json.loads(st["c2c_json"])
    P = cfg["pcr"]
    index_sig = st.get("underlying") == "INDEX"
    fut, s0 = engine.load(st.get("signal_file") or st["data_file"], st["date_from"], st["date_to"], st["warmup_days"])
    p = dict(break_mode=st["break_mode"], choch_mode=st.get("choch_mode") or st["break_mode"],
             avwap_weight="equal" if index_sig else st["avwap_weight"], sl_rule="none")
    r = engine.run(fut, p)
    t, o, c = fut["t"], fut["o"], fut["c"]
    n = len(t)
    spot = lab.Series.get(st["spot_file"]); atr = lab.atr_series(spot, st["atr_period"])
    chain, oi, step = lab.OptionChain(st), OI(st), st["strike_step"]
    reg = regimes(r, n)
    ups = sorted(t[e["i"]] for e in r["chs"] if e["flip"] and e["dir"] == "up")
    day_open = {}
    for i in range(n): day_open.setdefault(t[i][:10], o[i])
    cap_all = f"{st['date_to']} 23:59:59"
    pcr_memo = {}

    def pcr_of(e, when):
        if (e, when) not in pcr_memo:
            sp, _ = spot.at(when)
            pcr_memo[(e, when)] = oi.pcr(e, when, sp, P, step) if sp is not None else (None, 0)
        return pcr_memo[(e, when)]

    out = {}
    for ch in keys:
        ekind, sc = lab.split_choice(ch)
        funnel = dict(sh_confirmed=0, bearish=0, not_flip_bar=0, in_band=0, above_day_floor=0, pcr_na=0, pcr_ok=0,
                      priced=0, taken=0, locked=0)
        pcr_seen, trs, skipped, fmarks, omarks, free_at = [], [], [], [], {}, ""
        for s in sorted((s for s in r["sw"] if s["k"] == "H"), key=lambda s: s["conf"]):
            i = s["conf"]
            if i < s0: continue
            funnel["sh_confirmed"] += 1
            rg, fi, anchor = reg[i]
            if rg != -1: continue
            funnel["bearish"] += 1
            if fi == i: continue
            funnel["not_flip_bar"] += 1
            av = r["av"](anchor, i)
            if not (av - cfg["band_pts"] < s["p"] < av + cfg["band_pts"]): continue
            funnel["in_band"] += 1
            if not c[i] > day_open[t[i][:10]] * (1 - cfg["day_drop_pct"] / 100): continue
            funnel["above_day_floor"] += 1
            base = dict(dir="down", signal="BEARISH", position="LONG", opt_type="PE", choch_time=t[fi], signal_time=t[i])
            if i + 1 >= n:
                skipped.append(dict(base, entry_time=t[i], why="no next candle in the window")); continue
            ti = t[i + 1]
            si = spot.ix.get(t[i])
            if si is None:
                skipped.append(dict(base, entry_time=ti, why="no spot candle")); continue
            k = lab.pick_strike(sc, "PE", spot.c[si], atr[si], step)
            exp = chain.expiry_for(ti[:10], st["expiry_min_days"], ekind)
            nm = chain.name(exp, k, "PE") if exp else f"{int(k)} PE"
            base.update(instrument=nm, strike=k, expiry=exp)
            if not full_chain(st, exp):
                skipped.append(dict(base, entry_time=ti, why=f"no full-chain data for {nm}")); continue
            if P is not None:
                x, used = pcr_of(exp, t[i])
                if x is None:
                    funnel["pcr_na"] += 1
                    skipped.append(dict(base, entry_time=ti, why=f"PCR NA ({used} strikes with OI within {P['window_pts']:g} pts)")); continue
                pcr_seen.append(x)
                if not x < P["entry_max"]: continue
                base["pcr"] = x
            funnel["pcr_ok"] += 1
            os_ = chain.get(exp, k, "PE")
            if os_ is None:
                skipped.append(dict(base, entry_time=ti, why=f"no data for {nm}")); continue
            k0 = bisect.bisect_left(os_.t, ti)
            if k0 >= len(os_.t) or os_.t[k0][:10] != ti[:10]:
                skipped.append(dict(base, entry_time=ti, why=f"{nm} has no candle at or after {ti[11:16]} that session")); continue
            funnel["priced"] += 1
            if os_.t[k0] <= free_at:
                funnel["locked"] += 1
                skipped.append(dict(base, entry_time=os_.t[k0], why=f"strike locked (one position at a time): open until {free_at}")); continue
            iend = bisect.bisect_right(os_.t, min(cap_all, f"{exp} 23:59:59")) - 1
            e = os_.o[k0]
            kx, px, why, still, stop, peak = hold(os_, k0, e, cfg, ups, t[i], lambda T: pcr_of(exp, T)[0], iend)
            if still and os_.t[kx][:10] >= exp: why, still = "expiry", False
            funnel["taken"] += 1
            free_at = os_.t[kx]
            jx = max(bisect.bisect_right(t, os_.t[kx]) - 1, 0)
            rec = dict(base, kind="OPT", entry_time=os_.t[k0], entry_px=e, exit_time=os_.t[kx], exit_px=round(px, 2),
                       exit_reason=why, open=still, sl=round(stop, 2), und_entry=o[i + 1], und_exit=c[jx], stale=False,
                       lots=lab.position_cfg(st)["lots"], tranche="", peak=round(peak, 2))
            lab.excursion(os_.t, os_.h, os_.l, rec, True)
            trs.append(lab.price_trade(st, cs, rec))
            lbl = "LONG PE"
            fmarks.append([lab.ts(t[i + 1]), o[i + 1], lab.ts(t[jx]), c[jx], "down", round(rec["pts"], 2), still, None, why, lbl, "down"])
            omarks.setdefault((nm, rec["entry_time"][:10]), (os_, []))[1].append(
                [lab.ts(rec["entry_time"]), e, lab.ts(rec["exit_time"]), rec["exit_px"], "up", round(rec["pts"], 2), still,
                 rec["sl"], why, lbl, "down"])
        # signals and charts, as lab.run_variant draws them
        signals = [dict(time=t[e["i"]], dir=e["dir"], flipped=e["flip"], lvl=e["lvl"], av=e["av"],
                        hi=(t[e["hi"]["bar"]], e["hi"]["p"]) if e["hi"] else None,
                        lo=(t[e["lo"]["bar"]], e["lo"]["p"]) if e["lo"] else None,
                        setup=next((x["entry_time"] for x in trs if x["choch_time"] == t[e["i"]]), None))
                   for e in r["chs"] if e["i"] >= s0]
        charts, day_span = [], {}
        for i in range(s0, n): day_span.setdefault(t[i][:10], [i, i])[1] = i
        for d, (i0, i1) in day_span.items():
            lo, hi = lab.ts(t[i0]), lab.ts(t[i1])
            mk = [m for m in fmarks if m[0] <= hi and m[2] >= lo]
            inday = [m for m in fmarks if lo <= m[0] <= hi]
            charts.append(dict(lab.chart(fut, r, i0, i1, mk), day=d, kind="signal",
                               label=f"{d} · {'index' if index_sig else 'futures'}"
                                     + (f" · {len(inday)} trades · {sum(m[5] for m in inday):+.1f} pts" if inday else "")))
        for (nm, d), (os_, mk) in sorted(omarks.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            i0 = lab.prev_session_start(os_.t, bisect.bisect_left(os_.t, f"{d} 00:00:00"))
            i1 = max(bisect.bisect_right(os_.t, f"{d} 23:59:59") - 1,
                     max(bisect.bisect_right(os_.t, x["exit_time"]) - 1 for x in trs if x["instrument"] == nm and x["entry_time"][:10] == d))
            charts.append(dict(lab.option_chart(os_, i0, i1, mk), day=d, kind="option",
                               label=f"{d} · {nm} · {len(mk)} trade{'s' * (len(mk) > 1)} · {sum(m[5] for m in mk):+.1f} pts"))
        ps = sorted(pcr_seen)
        q = lambda f: ps[min(len(ps) - 1, int(f * len(ps)))] if ps else None
        why_n = {}
        for x in trs: why_n[x["exit_reason"]] = why_n.get(x["exit_reason"], 0) + 1
        payload = dict(config=cfg, funnel=funnel, exits=why_n,
                       pcr_at_candidates=dict(n=len(ps), min=q(0), p25=q(.25), median=q(.5), p75=q(.75), max=ps[-1] if ps else None))
        out[ch] = dict(trades=trs, skipped=skipped, signals=signals, charts=charts, c2c=payload)
    return out
