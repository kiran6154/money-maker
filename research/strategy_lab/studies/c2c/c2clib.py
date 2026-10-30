"""Shared machinery for the C2C research phases 5, 8-16 (ledger EXP-007 onward). Development years only: the index is loaded
to 2023-12-31 (phase3_dev.load) and options come only from expiries fetched by `tools/breeze_options.py --research` to
completion (phase4_9.research_ok).

- candidates(ctx, defn): every swing that confirms in its regime (not on the flip candle) - the signal before the band and
  day filters, with the features phases 10-14, 21, 22 read; signals(...) applies a band (points or daily-ATR multiple) and
  the day filter to them. R-A / R-B as in phase3_dev.
- ctrl_excess(ctx, cands, key): each candidate's directional NIFTY move over a horizon minus the same-year same-time-of-day
  mean of every candle (the EXP-002 control).
- option(ctx, e, k, right, i_entry): the option series and entry (exact-time candle only).
- walk(ctx, ser, j0, P0, x, X): one long option position under an exit spec X (stop, trail, targets, NIFTY target, flips,
  ladder, time, end of day, decay-aware, edge exhaustion) - the baseline is X = BASE.
- book(ctx, cands, pick, X): one position at a time, net rupees per 65-unit lot after today's charges + slippage.
"""
import bisect, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import engine, lab  # noqa: E402
import phase3_dev as P3  # noqa: E402
import phase4_9 as P4  # noqa: E402

LOT = 65
BASE = dict(stop_pct=5, trail_pts=5, target_pts=None, target_pct=None, und_target=None, flip=True, ladder=True,
            time_min=None, eod=False, next_close=False, decay=False, exhaust=None, fill="close", slip=0.5)


class Ctx:
    def __init__(self):
        b = self.b = P3.load()
        self.t = b["t"]; self.o, self.h, self.l, self.c = (np.array(b[k]) for k in "ohlc")
        n = self.n = len(self.t); self.day = [x[:10] for x in self.t]
        self.last_of = np.zeros(n, dtype=int); s = 0
        for i in range(n):
            if i == n - 1 or self.day[i + 1] != self.day[i]: self.last_of[s:i + 1] = i; s = i + 1
        self.first_of = {}
        for i in range(n): self.first_of.setdefault(self.day[i], i)
        self.chain = lab.OptionChain(dict(lab.type_rows(lab.load_strategies()[0][1])[1], timeframe="5minute"))
        self.cs = json.load(open(lab.CHARGECFG, encoding="utf-8"))["ZERODHA_NFO_OPT"]
        h, l, c = self.h, self.l, self.c
        tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1)))); tr[0] = h[0] - l[0]
        self.atr5 = np.zeros(n); a = tr[0]
        for i in range(n): a = tr[:i + 1].mean() if i < 14 else (a * 13 + tr[i]) / 14; self.atr5[i] = a
        days = self.days = sorted(self.first_of); self.di = {d: j for j, d in enumerate(days)}
        idx = {d: (self.first_of[d], self.last_of[self.first_of[d]]) for d in days}
        self.dO = np.array([self.o[idx[d][0]] for d in days]); self.dC = np.array([c[idx[d][1]] for d in days])
        self.dH = np.array([h[idx[d][0]:idx[d][1] + 1].max() for d in days]); self.dL = np.array([l[idx[d][0]:idx[d][1] + 1].min() for d in days])
        dtr = np.maximum(self.dH - self.dL, np.maximum(abs(self.dH - np.roll(self.dC, 1)), abs(self.dL - np.roll(self.dC, 1)))); dtr[0] = self.dH[0] - self.dL[0]
        self.dtr = dtr
        self.atr20 = np.array([dtr[max(0, j - 20):j].mean() if j else dtr[0] for j in range(len(days))])   # the 20 sessions BEFORE day j
        self._exp, self._runs, self._ctl = {}, {}, {}

    def expiry(self, d, kind, md):
        if (d, kind, md) not in self._exp: self._exp[(d, kind, md)] = self.chain.expiry_for(d, md, kind)
        return self._exp[(d, kind, md)]

    def unit_cost(self, buy, sell, slip=0.5):
        return lab.trade_charges(self.cs, buy, sell, LOT)["total"] / LOT + 2 * slip


# ---------------------------------------------------------------- candidates
def _runs(ctx, defn):
    """[(engine result, window bars, global offset, keep_day or None)] for a regime definition."""
    if defn in ctx._runs: return ctx._runs[defn]
    b, out = ctx.b, []
    if defn == "R-A":
        days = sorted({x[:10] for x in b["t"]}); idx = {}
        for i, x in enumerate(b["t"]): idx.setdefault(x[:10], [i, i])[1] = i
        for k, d in enumerate(days):
            if d < P3.START: continue
            a = idx[days[max(0, k - P3.MEMORY)]][0]; z = idx[d][1]
            w = {q: b[q][a:z + 1] for q in "tohlcv"}
            out.append((engine.run(w, P3.P), w, a, d))
    else:
        out.append((P3.level_break_engine().run(b, P3.P), b, 0, None))
    ctx._runs[defn] = out
    return out


def candidates(ctx, defn):
    """Every in-regime swing confirmation (not on the flip candle), with features; plus the flip times per direction."""
    cands, flips = [], {"up": [], "down": []}
    for r, w, off, keep in _runs(ctx, defn):
        t = w["t"]; n = len(t)
        fl = {e["i"]: e for e in r["chs"] if e["flip"]}
        for k, e in fl.items():
            if not keep or t[k][:10] == keep: flips[e["dir"]].append(t[k])
        reg, cur = [None] * n, (0, None, None)
        for i in range(n):
            e = fl.get(i)
            if e: cur = (-1, i, e["hi"]["bar"]) if e["dir"] == "down" else (1, i, e["lo"]["bar"])
            reg[i] = cur
        sw = sorted(r["sw"], key=lambda s: s["conf"])
        prev = {}
        for s in sw:
            i = s["conf"]; gi = i + off
            p_same = prev.get(s["k"]); p_opp = prev.get("L" if s["k"] == "H" else "H"); prev[s["k"]] = s
            if i + 1 >= n or t[i] < P3.START or (keep and t[i][:10] != keep): continue
            want = -1 if s["k"] == "H" else 1
            rg, fi, anchor = reg[i]
            if rg != want or fi == i: continue
            av = r["av"](anchor, i); d = t[i][:10]; j = ctx.di[d]
            e = fl[fi]
            cands.append(dict(i=gi, dir=want, time=t[i], defn=defn, swing=s["p"], av=av, dist_av=s["p"] - av,
                              day_ok=(ctx.c[gi] > ctx.dO[j] * (1 - 0.006)) if want < 0 else (ctx.c[gi] < ctx.dO[j] * (1 + 0.006)),
                              atr20=float(ctx.atr20[j]), atr5=float(ctx.atr5[gi]), bars_since_flip=i - fi,
                              break_size=abs(w["c"][fi] - e["lvl"]),
                              leg=abs(s["p"] - p_opp["p"]) if p_opp else None,
                              lh_hl=((p_same["p"] - s["p"]) if want < 0 else (s["p"] - p_same["p"])) if p_same else None))
    for k in flips: flips[k] = sorted(set(flips[k]))
    cands.sort(key=lambda x: (x["i"], x["dir"]))
    return cands, flips


def signals(cands, band=50, band_atr=None, day_filter=True):
    out = []
    for x in cands:
        w = band_atr * x["atr20"] if band_atr is not None else band
        if abs(x["dist_av"]) < w and (x["day_ok"] or not day_filter): out.append(x)
    return out


# ---------------------------------------------------------------- the time-of-day control (Question A)
def fwd_all(ctx):
    """For every candle e as an entry (at its open): NIFTY move (up-positive) at 15/30/60/120/240 min and to the close."""
    if "fwd" in ctx._ctl: return ctx._ctl["fwd"]
    n, o, c = ctx.n, ctx.o, ctx.c
    E = np.arange(n); L = ctx.last_of
    out = {}
    for hm in (15, 30, 60, 120, 240):
        out[str(hm)] = c[np.minimum(E + hm // 5 - 1, L)] - o
    out["eod"] = c[L] - o
    ctx._ctl["fwd"] = out
    buckets = {}
    for e in range(1, n):
        if ctx.day[e] == ctx.day[e - 1] and ctx.t[e] >= P3.START: buckets.setdefault((ctx.t[e][:4], ctx.t[e][11:16]), []).append(e)
    ctx._ctl["means"] = {k: {bk: float(v[idx].mean()) for bk, idx in buckets.items()} for k, v in out.items()}
    ctx._ctl["buckets"] = buckets
    return out


def ctrl_excess(ctx, x, key):
    """The candidate's directional move over `key` from the next candle's open, minus the same-year same-time mean."""
    F = fwd_all(ctx); e = x["i"] + 1
    if e >= ctx.n or ctx.day[e] != ctx.day[x["i"]]: return None, None
    mv = x["dir"] * F[key][e]
    m = ctx._ctl["means"][key].get((ctx.t[e][:4], ctx.t[e][11:16]))
    return float(mv), (None if m is None else float(mv - x["dir"] * m))


def summarize(vals):
    v = np.array([q for q in vals if q is not None], float)
    if len(v) < 3: return dict(n=len(v))
    return dict(n=len(v), mean=round(float(v.mean()), 2), t=round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2),
                hit=round(float((v > 0).mean() * 100), 1))


# ---------------------------------------------------------------- options
def option(ctx, e, k, right, i_entry):
    if not e or not P4.research_ok(e): return None
    ser = ctx.chain.get(e, k, right)
    j0 = ser.ix.get(ctx.t[i_entry]) if ser else None
    return (ser, j0) if j0 is not None else None


def walk(ctx, ser, j0, P0, x, X, flips, carry=None, exp_rem=None):
    """(exit index, exit price, reason) for a long option entered at the open of ser candle j0, after signal x."""
    close_mode = X["fill"] == "close"
    stop0 = stop = P0 * (1 - X["stop_pct"] / 100) if X["stop_pct"] else -1e9
    peak, laddered = P0, set()
    t0 = ser.t[j0]
    if t0[11:16] > "15:15": laddered.add(t0[:10])
    opp = flips["up" if x["dir"] < 0 else "down"]; u = bisect.bisect_right(opp, x["time"])
    tgt = P0 + X["target_pts"] if X["target_pts"] else (P0 * (1 + X["target_pct"] / 100) if X["target_pct"] else None)
    ie = x["i"] + 1; S0 = ctx.o[ie]; end_day = t0[:10]
    t_lim = None
    if X["time_min"]:
        t_lim = ctx.t[min(ie + X["time_min"] // 5 - 1, ctx.last_of[ie])]
    nxt_close = None
    if X["next_close"]:
        j = ctx.last_of[ie] + 1
        nxt_close = ctx.t[ctx.last_of[j]] if j < ctx.n else None
    iend = bisect.bisect_right(ser.t, f"{min(ser.t[-1][:10], '2023-12-31')} 23:59:59") - 1
    for k in range(j0, iend + 1):
        T, o_, h_, l_, c_ = ser.t[k], ser.o[k], ser.h[k], ser.l[k], ser.c[k]
        first = k > 0 and ser.t[k - 1][:10] != T[:10]
        if X["stop_pct"] or X["trail_pts"]:
            why = "trail_stop" if stop > stop0 else "stop_loss"
            if close_mode:
                if c_ <= stop: return k, c_, why
            else:
                gap = k > j0 and o_ <= stop
                if gap or l_ <= stop: return k, (c_ if first and k > j0 else (o_ if gap else stop)), why
        if tgt is not None:
            if close_mode:
                if c_ >= tgt: return k, c_, "target"
            elif h_ >= tgt: return k, (o_ if k > j0 and o_ >= tgt else tgt), "target"
        gi = bisect.bisect_right(ctx.t, T) - 1                                 # the index candle of this time
        if X["und_target"] and gi >= 0 and x["dir"] * (ctx.c[gi] - S0) >= X["und_target"]: return k, c_, "nifty_target"
        if X["exhaust"] and gi >= 0 and x["dir"] * (ctx.c[gi] - S0) >= X["exhaust"]: return k, c_, "exhaustion"
        if X["flip"] and u < len(opp) and opp[u] <= T: return k, (c_ if opp[u] == T else o_), "choch"
        if X["ladder"] and T[11:16] >= "15:15" and T[:10] not in laddered:
            laddered.add(T[:10]); pnl = (c_ - P0) / P0 * 100
            if pnl > 40: return k, c_, "ladder_profit"
            if pnl < -2: return k, c_, "ladder_loss"
        if t_lim and T >= t_lim: return k, c_, "time"
        if X["eod"] and (T[:10] > end_day or T[11:16] >= "15:25" or (k + 1 <= iend and ser.t[k + 1][:10] != T[:10])): return k, c_, "eod"
        if nxt_close and T >= nxt_close: return k, c_, "next_close"
        if X["decay"] and carry is not None and T[14:16] in ("15", "45") and T > t0:
            dte = P4.years_to(ser.t[-1][:10], T) * 365
            cm = carry.get((P4.bucket(dte), T[11:13], "eod"))
            em = exp_rem.get(T[11:13]) if exp_rem else None
            if cm is not None and em is not None and X["decay_delta"] * em < -cm: return k, c_, "decay_exit"
        peak = max(peak, c_ if close_mode else h_)
        if X["trail_pts"] and peak > P0: stop = max(stop, peak - X["trail_pts"])
    return iend, ser.c[iend], "open"


def book(ctx, sigs, flips, X, pick=("ITM1", "M15"), carry=None, exp_rem=None, entry_delay=0, entry_at="open"):
    """One position at a time. pick = (strike choice, expiry key). Returns list of trades (net rupees per lot)."""
    kinds = {"W0": ("WEEKLY", 0), "W1": ("WEEKLY", 7), "M15": ("MONTHLY", 15)}
    trs, free_at, skipped = [], "", {}
    for x in sigs:
        i = x["i"]; ie = i + 1 + entry_delay
        if ie >= ctx.n or ctx.day[ie] != ctx.day[i]: skipped["opening print / session end"] = skipped.get("opening print / session end", 0) + 1; continue
        right = "PE" if x["dir"] < 0 else "CE"
        e = ctx.expiry(ctx.day[i], *kinds[pick[1]])
        k = int(lab.pick_strike(pick[0], right, ctx.c[i], 0, 50))
        op = option(ctx, e, k, right, ie)
        if not op: skipped["no option data"] = skipped.get("no option data", 0) + 1; continue
        ser, j0 = op
        if entry_at == "close":                                               # signal close -> the entry candle's close
            P0 = ser.c[j0]; j0 = j0 + 1 if j0 + 1 < len(ser.t) and ser.t[j0 + 1][:10] == ser.t[j0][:10] else None
            if j0 is None: continue
        else:
            P0 = ser.o[j0]
        if ser.t[j0] <= free_at: skipped["position open"] = skipped.get("position open", 0) + 1; continue
        xx = dict(x, i=ie - 1)                                                # entry-relative index for the walk
        kx, px, why = walk(ctx, ser, j0, P0, xx, X, flips, carry, exp_rem)
        free_at = ser.t[kx]
        slip = X["slip"]
        net = (px - slip - (P0 + slip)) * LOT - lab.trade_charges(ctx.cs, P0 + slip, px - slip, LOT)["total"]
        trs.append(dict(entry_time=ser.t[j0], exit_time=ser.t[kx], P0=P0, px=px, why=why, net=round(net, 1), dir=x["dir"],
                        hold=int((np.datetime64(ser.t[kx]) - np.datetime64(ser.t[j0])).astype("timedelta64[m]").astype(int)),
                        dte=P4.years_to(e, ser.t[j0]) * 365))
    return trs, skipped


def stats(trs):
    if not trs: return dict(trades=0)
    net = np.array([x["net"] for x in trs]); eq = np.cumsum(net)
    wins, loss = net[net > 0], net[net <= 0]
    why = {}
    for x in trs: why[x["why"]] = why.get(x["why"], 0) + 1
    yr = {}
    for x in trs: yr.setdefault(x["entry_time"][:4], []).append(x["net"])
    return dict(trades=len(trs), win=round(float((net > 0).mean() * 100), 1), avg=round(float(net.mean()), 1),
                median=round(float(np.median(net)), 1), net=round(float(net.sum()), 0),
                pf=round(float(wins.sum() / -loss.sum()), 2) if loss.sum() < 0 else None,
                max_dd=round(float((eq - np.maximum.accumulate(eq)).min()), 0),
                t=round(float(net.mean() / (net.std(ddof=1) / math.sqrt(len(net)))), 2) if len(net) > 2 else None,
                hold_median=float(np.median([x["hold"] for x in trs])), exits=why,
                years={y: round(sum(v), 0) for y, v in sorted(yr.items())})
