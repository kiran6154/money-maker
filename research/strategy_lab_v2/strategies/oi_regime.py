"""NIFTY regime strategy from CE / PE open interest and price structure (family module for ST81).

Four separate pieces, each a function that can be run and checked on its own:

  oi_series(bars, spec)      the OPEN INTEREST inputs, per bar of `bars`: the CE and the PE OI change (dOI) of the 3 strikes
                             around the at-the-money strike (ATM from the index close of that bar, +/- one strike step) on
                             the nearest weekly expiry (the expiry day itself included), each strike compared with ITSELF one
                             bar before (so the ATM moving does not jump the series), and the same strikes' premium change.
                             Also the session's cumulative dOI (the two lines drawn). Source: the option files' open_interest
                             column (5-minute files, or the 1-minute files for 1-minute bars; a 15-minute bar reads the
                             last 5 minutes inside it).
  structure(bars, spec)      swing highs / lows (a pivot: higher / lower than `pivot` bars each side, confirmed `pivot` bars
                             later); BOS up = a close above the last swing high while the trend is up, BOS down = a close
                             below the last swing low while the trend is down; CHoCH up = a close above the last swing high
                             while the trend is down, CHoCH down = a close below the last swing low while the trend is up.
                             Each swing level is broken once. The trend is what the last BOS / CHoCH says.
  regime(bars, spec, oi, st) what a bar says, first match:
                               CHoCH      a CHoCH on this bar
                               BOS down   trend down AND CE short buildup dominant: over the last `n` bars CE dOI > 0, the
                                          CE premium fell, and CE dOI > PE dOI
                               BOS up     trend up AND PE short buildup dominant (the mirror)
                               Sideways   CE dOI > 0 AND PE dOI > 0 over the last `n` bars (both sides written) AND the
                                          high - low range of those `n` bars is at most `tight_pts` points (no ATR anywhere)
                                          AND no BOS / CHoCH inside those bars (price is not breaking structure)
                             Every window is the last `n` bars of the SAME session (never reaching into the day before),
                             and a regime needs a full window with OI on every bar.
                             The regime is a STATE: it becomes what the bars say only when that is seen on `confirm` bars
                             in a row, and holds until another regime is confirmed; a CHoCH clears it (none), a BOS ends
                             Sideways, every session starts with none. Lengths are in minutes (`window_min`, `pivot_min`,
                             `max_min`) so that 1-, 5- and 15-minute candles read the same span of time.
                               none       otherwise: no trade
  signals_of(...)            entries, only when flat, only on a fresh signal, none after `last_entry`:
                               Sideways   SELL when the close is in the top `edge` share of the n-bar range, BUY in the bottom
                                          share (fresh: the previous bar was not in that zone)
                               BOS down   SELL on a bounce: the previous bar closed up and this one closes down. No buys.
                               BOS up     BUY on a dip: the previous bar closed down and this one closes up. No sells.
                             exits, first of: stop `stop_pts`, target `target_pts` (stop checked first in a candle), a CHoCH
                             (any direction) at that bar's close, `max_bars` bars held (that bar's close), the square-off.
One position at a time. Every number is in SPEC["oi_regime"].
"""
import os
import numpy as np
import pandas as pd
import core

ENTRY_RULES = ("oi_regime_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
REFUSED_WHY = "the regime is read on the NIFTY price with the CE / PE open interest of the whole ATM area; options on their own chart are not part of it"
CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache", "oi")
LABELS = ("none", "Sideways", "BOS up", "BOS down", "CHoCH")


# ---------------------------------------------------------------- 1. open interest
_EXP = {}


def _expiry_frame(exp, src="5minute"):
    """(times, strikes, OI matrix, close matrix) per right of one expiry's option files (`src`: 5minute or 1minute);
    nan = no candle."""
    if (exp, src) in _EXP: return _EXP[(exp, src)]
    os.makedirs(CACHE, exist_ok=True); f = os.path.join(CACHE, f"{exp}.npz" if src == "5minute" else f"{exp}_{src}.npz")
    if os.path.exists(f):
        z = np.load(f); out = {r: (z[f"{r}_t"], z[f"{r}_k"], z[f"{r}_oi"], z[f"{r}_c"]) for r in ("CE", "PE") if f"{r}_t" in z}
    else:
        folder = core.OptionChain("5minute" if src == "5minute" else "minute")._dir.get(exp); out, save = {}, {}
        for r in ("CE", "PE"):
            p = folder and os.path.join(folder, f"NIFTY_{exp}_{r}_{src}.csv")
            if not p or not os.path.exists(p): continue
            df = pd.read_csv(p, usecols=["datetime", "strike_price", "close", "open_interest"])
            df["t"] = (pd.to_datetime(df["datetime"]).astype("int64") // 10**9).astype("int64")
            oi = df.pivot_table(index="t", columns="strike_price", values="open_interest", aggfunc="last")
            cl = df.pivot_table(index="t", columns="strike_price", values="close", aggfunc="last").reindex(index=oi.index, columns=oi.columns)
            oi = oi.where(oi > 0)                                 # 0 = not reported yet
            out[r] = (oi.index.values.astype(np.int64), oi.columns.values.astype(np.int64), oi.values.astype(float), cl.values.astype(float))
            save.update({f"{r}_t": out[r][0], f"{r}_k": out[r][1], f"{r}_oi": out[r][2], f"{r}_c": out[r][3]})
        if save: np.savez_compressed(f, **save)
    while len(_EXP) > 40: del _EXP[next(iter(_EXP))]
    _EXP[(exp, src)] = out
    return out


def _bar_t(bars):
    """The bar's own times in the lab's clock (core.ts of 'YYYY-MM-DD HH:MM'), as the option files' times are read."""
    return bars.t


def oi_series(bars, spec):
    """Per bar: dict(ce_doi, pe_doi, ce_dprem, pe_dprem, ce_cum, pe_cum, ok) - the 3-strike sums described above."""
    O = spec["oi_regime"]; step = spec["options"]["strike_step"]; tfm = core.TF_MIN[spec_tf(bars)]
    src, sm = ("1minute", 1) if tfm < 5 else ("5minute", 5)           # 1-minute bars read the 1-minute option files
    sp = core.series("spot", "minute" if sm == 1 else "5minute")
    n = len(bars); out = {k: np.zeros(n) for k in ("ce_doi", "pe_doi", "ce_dprem", "pe_dprem", "ce_cum", "pe_cum")}; ok = np.zeros(n, bool)
    chain = core.OptionChain("5minute" if sm == 5 else "minute"); cal = np.array([core.dnum(e) for e in chain.calendar], dtype=np.int64)
    last_read = bars.t + (tfm - sm) * 60                          # the last source candle inside each bar
    j = np.searchsorted(sp.t, last_read, "right") - 1
    exp_of = {}                                                   # session -> its expiry's frames (or None)
    for i in range(n):
        d = int(bars.day[i])
        if j[i] < 0 or sp.day[j[i]] != d: continue
        if d not in exp_of:
            k = int(np.searchsorted(cal, d + O["expiry_min_days"])); F = None
            for kk in range(k, min(k + 3, len(cal))):             # the nearest expiry with files (a missing week: the next)
                F = _expiry_frame(chain.calendar[kk], src) or None
                if F: break
            exp_of[d] = F
        F = exp_of[d]
        if not F: continue
        atm = int(round(float(sp.c[j[i]]) / step) * step)
        good = True
        for r in ("CE", "PE"):
            if r not in F: good = False; break
            t_, ks, oi, cl = F[r]
            a = int(np.searchsorted(t_, last_read[i], "right")) - 1; b = int(np.searchsorted(t_, last_read[i] - tfm * 60, "right")) - 1
            if a < 0 or t_[a] // core.DAY != d or b < 0: good = False; break
            doi = dp = 0.0; seen = 0
            for s_ in (atm - step, atm, atm + step):
                m = int(np.searchsorted(ks, s_))
                if m >= len(ks) or ks[m] != s_: continue
                if np.isfinite(oi[a, m]) and np.isfinite(oi[b, m]): doi += oi[a, m] - oi[b, m]; seen += 1
                if np.isfinite(cl[a, m]) and np.isfinite(cl[b, m]): dp += cl[a, m] - cl[b, m]
            if not seen: good = False; break
            out[f"{r.lower()}_doi"][i], out[f"{r.lower()}_dprem"][i] = doi, dp
        ok[i] = good
        if not good: out["ce_doi"][i] = out["pe_doi"][i] = out["ce_dprem"][i] = out["pe_dprem"][i] = 0.0
    for r in ("ce", "pe"):                                        # the session's cumulative dOI (the lines drawn)
        c = out[f"{r}_doi"]; cum = np.zeros(n)
        for i in range(n): cum[i] = c[i] + (cum[i - 1] if i and bars.day[i] == bars.day[i - 1] else 0.0)
        out[f"{r}_cum"] = cum
    out["ok"] = ok
    return out


def spec_tf(bars):
    """The timeframe name of `bars` from its spacing."""
    d = np.diff(bars.t[: min(len(bars), 400)]); d = d[(d > 0) & (d < 3600)]
    m = int(np.median(d) // 60) if len(d) else 5
    return {1: "minute", 3: "3minute", 5: "5minute", 15: "15minute", 30: "30minute", 60: "60minute"}.get(m, "5minute")


def bars_of(spec, key, tfm, least=1):
    """A SPEC["oi_regime"] length given in minutes, as bars of this timeframe (at least `least`)."""
    return max(least, int(round(spec["oi_regime"][key] / tfm)))


# ---------------------------------------------------------------- 2. structure
def structure(bars, spec):
    """Per bar: trend (1 / -1 / 0 after the bar), event (0 none, 1 BOS, 2 CHoCH), event dir, last SH / SL; plus the swings."""
    p = bars_of(spec, "pivot_min", core.TF_MIN[spec_tf(bars)]); h, l, c, n = bars.h, bars.l, bars.c, len(bars)
    trend = np.zeros(n, np.int8); ev = np.zeros(n, np.int8); evd = np.zeros(n, np.int8); sh_l = np.full(n, np.nan); sl_l = np.full(n, np.nan)
    swings = []                                                   # (kind 'H'/'L', pivot bar, price, confirm bar)
    sh = sl = np.nan; sh_used = sl_used = True; tr = 0
    for i in range(n):
        q = i - p                                                 # a pivot confirmed now
        if q - p >= 0:
            w = slice(q - p, q + p + 1)
            if h[q] == h[w].max() and (h[w] < h[q]).sum() == 2 * p: sh, sh_used = float(h[q]), False; swings.append(("H", q, sh, i))
            if l[q] == l[w].min() and (l[w] > l[q]).sum() == 2 * p: sl, sl_used = float(l[q]), False; swings.append(("L", q, sl, i))
        if not sh_used and c[i] > sh:
            ev[i], evd[i] = (1 if tr >= 0 else 2), 1; tr = 1; sh_used = True
        elif not sl_used and c[i] < sl:
            ev[i], evd[i] = (1 if tr <= 0 else 2), -1; tr = -1; sl_used = True
        trend[i] = tr; sh_l[i] = sh; sl_l[i] = sl
    return dict(trend=trend, ev=ev, evd=evd, sh=sh_l, sl=sl_l, swings=swings)


# ---------------------------------------------------------------- 3. regime
def regime(bars, spec, oi, st):
    """Per bar a code into LABELS (0 none, 1 Sideways, 2 BOS up, 3 BOS down, 4 CHoCH)."""
    O = spec["oi_regime"]; N = bars_of(spec, "window_min", core.TF_MIN[spec_tf(bars)], 2); n = len(bars); day = bars.day
    first = np.zeros(n, np.int64)                                 # each bar's session start: windows never reach into yesterday
    for i in range(1, n): first[i] = first[i - 1] if day[i] == day[i - 1] else i
    w0 = np.maximum(np.arange(n) - N + 1, first)                 # the window: the last N bars of this session (fewer early on)
    def roll(x):
        cs = np.concatenate([[0.0], np.cumsum(x)]); return cs[np.arange(n) + 1] - cs[w0]
    ce, pe, cep, pep = roll(oi["ce_doi"]), roll(oi["pe_doi"]), roll(oi["ce_dprem"]), roll(oi["pe_dprem"])
    okN = (roll(oi["ok"].astype(float)) >= N) & (np.arange(n) - w0 + 1 >= N)   # a full window with OI on every bar
    brk = roll((st["ev"] > 0).astype(float))                    # BOS / CHoCH inside the window
    hi = np.array([bars.h[w0[i]:i + 1].max() for i in range(n)]); lo = np.array([bars.l[w0[i]:i + 1].min() for i in range(n)])
    raw = np.zeros(n, np.int8)                                    # what this bar alone says
    for i in range(n):
        if st["ev"][i] == 2: raw[i] = 4; continue
        if not okN[i]: continue
        ce_sb, pe_sb = ce[i] > 0 and cep[i] < 0, pe[i] > 0 and pep[i] < 0
        if st["trend"][i] == -1 and ce_sb and ce[i] > pe[i]: raw[i] = 3
        elif st["trend"][i] == 1 and pe_sb and pe[i] > ce[i]: raw[i] = 2
        elif ce[i] > 0 and pe[i] > 0 and hi[i] - lo[i] <= O["tight_pts"] and brk[i] == 0: raw[i] = 1
    # the regime is a STATE: it changes only when another regime is seen on `confirm` bars in a row; a CHoCH clears it,
    # a BOS ends Sideways, a new session starts with none
    out = np.zeros(n, np.int8); state = run = 0; cand = 0; K = int(O["confirm"])
    for i in range(n):
        if i and day[i] != day[i - 1]: state = run = cand = 0
        if raw[i] == 4: out[i] = 4; state = run = cand = 0; continue
        if state == 1 and st["ev"][i] == 1: state = 0
        if raw[i] and raw[i] != state:
            run = run + 1 if raw[i] == cand else 1; cand = raw[i]
            if run >= K: state, run = cand, 0
        else: run, cand = 0, 0
        out[i] = state
    return out, hi, lo


# ---------------------------------------------------------------- 4. entries and exits
def signals_of(bars, spec, rg, hi, lo, st):
    """The trades (the lab's trade dicts) from the regime, one at a time."""
    O = spec["oi_regime"]; sq = spec["position"]["square_off"]; o, h, l, c, t = bars.o, bars.h, bars.l, bars.c, bars.t; n = len(bars)
    max_bars = bars_of(spec, "max_min", core.TF_MIN[spec_tf(bars)])
    last_entry = core.hhmm_sec(O["last_entry"]); edge = float(O["edge"])
    up, dn = c > o, c < o
    def want(i):
        """+1 buy, -1 sell, 0 nothing at bar i (the fresh-signal rule included)."""
        g = rg[i]; rngi = hi[i] - lo[i]
        if g == 1 and rngi > 0:
            top = lambda k: rg[k] == 1 and c[k] >= hi[k] - edge * (hi[k] - lo[k])
            bot = lambda k: rg[k] == 1 and c[k] <= lo[k] + edge * (hi[k] - lo[k])
            if top(i) and not (i and top(i - 1)): return -1
            if bot(i) and not (i and bot(i - 1)): return 1
        if g == 3 and i and up[i - 1] and dn[i]: return -1
        if g == 2 and i and dn[i - 1] and up[i]: return 1
        return 0
    trades, free = [], -1
    for i in range(n):
        if i <= free or t[i] % core.DAY >= last_entry: continue
        s = want(i)
        if not s: continue
        cut = core.square_off_at(sq, int(t[i]))
        if cut and t[i] >= cut: continue
        last = (int(np.searchsorted(t, cut, "right")) - 1) if cut else n - 1
        if last <= i: continue
        e = float(c[i]); stop, tgt = e - s * O["stop_pts"], e + s * O["target_pts"]
        x, px, why = min(last, i + max_bars), None, None
        for k in range(i + 1, min(last, i + max_bars) + 1):
            if (l[k] <= stop) if s > 0 else (h[k] >= stop): x, px, why = k, (min(o[k], stop) if s > 0 else max(o[k], stop)), "stop_loss"; break
            if (h[k] >= tgt) if s > 0 else (l[k] <= tgt): x, px, why = k, (max(o[k], tgt) if s > 0 else min(o[k], tgt)), "target 1"; break
            if st["ev"][k] == 2: x, px, why = k, float(c[k]), "choch"; break
        if why is None: px, why = float(c[x]), ("eod" if x == last and cut else "max_bars")
        trades.append(dict(entry=i, exit=x, exit_px=float(px), dir="up" if s > 0 else "down", choch=i, sl=float(stop),
                           pts=s * (float(px) - e), open=False, exit_reason=why, regime=LABELS[rg[i]]))
        free = x
    return trades


def compute(bars, spec):
    oi = oi_series(bars, spec); st = structure(bars, spec); rg, hi, lo = regime(bars, spec, oi, st)
    return oi, st, rg, hi, lo, signals_of(bars, spec, rg, hi, lo, st)


def signals(bars, spec):
    """The lab's entry point: the trades as a Signals (the Foundation engine is run only to carry them)."""
    *_, trades = compute(bars, spec)
    return core.foundation(bars, spec["rules"]).with_trades(trades)


# ---------------------------------------------------------------- the chart
def chart_main(ctx, body, day, to):
    """The price candles with this strategy's own swings, BOS / CHoCH, regime labels and trades, and the two OI lines."""
    spec = ctx["spec"]; b, _ = core.signal_bars(ctx)
    d0, d1 = core.dnum(day), core.dnum(to)
    i0 = int(np.searchsorted(b.day, d0)); i1 = int(np.searchsorted(b.day, d1, "right")) - 1
    if not (0 <= i0 <= i1 < len(b)): raise ValueError(f"no candles from {day}")
    k0 = max(0, int(np.searchsorted(b.day, b.day[max(0, i0 - 1)])) - 400)   # enough bars before for the structure and the n-bar sums
    w = b.slice(k0, i1 + 1); a, z = i0 - k0, i1 - k0
    oi, st, rg, hi, lo, _ = compute(w, spec)
    C = {k: i for i, k in enumerate(body["cols"])}; lo_t, hi_t = int(w.t[a]), int(w.t[z])
    rows = [r for r in body["trades"] if core.ts(r[C["entry_time"]]) <= hi_t and core.ts(r[C["exit_time"]]) >= lo_t]
    T = lambda i: int(w.t[i])
    marks, prev = [], None
    for i in range(a, z + 1):
        if rg[i] != prev: marks.append([T(i), LABELS[rg[i]]]); prev = rg[i]
    last = rows[-1] if rows else None
    status = "flat at the last candle"
    if last and core.ts(last[C["exit_time"]]) >= hi_t: status = f"{last[C['position']]} since {last[C['entry_time']][11:16]} at {last[C['entry_px']]}"
    return dict(day=day, to=to, inst=None, candles=core._chart_bars(w, a, z), cols=body["cols"], trades=rows, own=True,
                sessions=int(len(np.unique(w.day[a:z + 1]))),
                swings=[[k_, T(q), round(p_, 2), T(cf)] for k_, q, p_, cf in st["swings"] if a <= cf <= z],
                events=[[T(i), "BOS" if st["ev"][i] == 1 else "CHoCH", "up" if st["evd"][i] == 1 else "down"] for i in range(a, z + 1) if st["ev"][i]],
                regimes=marks, status=status,
                oi=dict(ce=[[T(i), round(float(oi["ce_cum"][i]))] for i in range(a, z + 1) if oi["ok"][i]],
                        pe=[[T(i), round(float(oi["pe_cum"][i]))] for i in range(a, z + 1) if oi["ok"][i]]),
                prot=[[T(i), round(float(st["sh"][i] if st["trend"][i] == -1 else st["sl"][i]), 2)] for i in range(a, z + 1)
                      if st["trend"][i] and np.isfinite(st["sh"][i] if st["trend"][i] == -1 else st["sl"][i])])
