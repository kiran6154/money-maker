"""Structure + Order Block + previous-day range on the option premium (family module for ST82).

From the user's document "NIFTY Options Strategy: Structure + Order Block + Previous Day Range" (v1.0, 2026-10-24).
Signals on the NIFTY index 5-minute candles; the trade is the ATM option of the nearest open weekly expiry, priced on
its own 5-minute candles. Pieces, each a function:

  structure      pivots of SPEC["ob"]["pivot"] bars each side (confirmed that many bars later); a close beyond the latest
                 unbroken swing high / low is a BOS when the structure already points that way (or is neutral), a CHoCH
                 when it pointed the other way. Each swing level is broken once. Closed bars only.
  order_blocks   on a bar that closes above the highest high of the `lookback` bars before it: the most recent up
                 candle among those bars + this one with a body of at least `impulse_atr` x ATR(14) is the impulse; the
                 last down candle before it is the bullish Order Block (its low - high). It is created only if no bar
                 after the impulse has traded back into it. Bearish: the mirror. A zone stays fresh until price trades back into
                 it; the first touch uses it up (whether or not it is traded).
  entries        Long: the latest structure break is a bullish CHoCH, a fresh bullish OB created after it, and a bar
                 trades into the OB (low <= OB high) and closes up and above the OB low -> buy the ATM CE at that bar's
                 close, if the CE's close is at or above that same CE's previous-session low. Short: the mirror on a
                 bearish CHoCH, if the ATM PE's close is below that PE's previous-session low. Between `start` and
                 `last_entry`; one position at a time; one entry per CHoCH.
  exits          on the option's own 5-minute candles after the entry: stop, target, `time_exit_min` minutes, flat at
                 `flatten`. SPEC["ob"]["short_as"]: "buy_pe" (the document's section 1: shorts buy the PE; its exits
                 then are the long ones: stop entry x (1 - stop_pct), target entry x (1 + stop_pct x rr)) or "sell_pe"
                 (the document's exit table: the PE is sold, stop entry x (1 + stop_pct), target entry x 0.5).
"""
import numpy as np
import core

ENTRY_RULES = ("ob_retest_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT",)
OWN_COVERAGE = True
REFUSED_WHY = "the strategy trades the ATM CE / PE from the index's signals; only the Options (via futures) type runs"


def structure(b, p):
    """Per bar: ev (0 none, 1 BOS, 2 CHoCH), evd (+1 / -1), and the swings [(kind, pivot bar, price, confirm bar)]."""
    h, l, c, n = b.h, b.l, b.c, len(b)
    ev = np.zeros(n, np.int8); evd = np.zeros(n, np.int8); swings = []
    sh = sl = np.nan; sh_used = sl_used = True; tr = 0
    for i in range(n):
        q = i - p
        if q - p >= 0:
            w = slice(q - p, q + p + 1)
            if (h[w] < h[q]).sum() == 2 * p: sh, sh_used = float(h[q]), False; swings.append(("H", q, sh, i))
            if (l[w] > l[q]).sum() == 2 * p: sl, sl_used = float(l[q]), False; swings.append(("L", q, sl, i))
        if not sh_used and c[i] > sh:
            ev[i], evd[i] = (1 if tr >= 0 else 2), 1; tr = 1; sh_used = True
        elif not sl_used and c[i] < sl:
            ev[i], evd[i] = (1 if tr <= 0 else 2), -1; tr = -1; sl_used = True
    return ev, evd, swings


def order_blocks(b, O):
    """[(created bar, dir +1 / -1, ob bar, low, high)] in creation order."""
    o, h, l, c, n = b.o, b.h, b.l, b.c, len(b); L = int(O["lookback"]); at = core.atr(b, 14); out = []
    body = np.abs(c - o)
    for i in range(L, n):
        for d in (1, -1):
            brk = c[i] > h[i - L:i].max() if d > 0 else c[i] < l[i - L:i].min()
            if not brk: continue
            imp = None
            for k in range(i, i - L - 1, -1):                    # the impulse: the latest strong candle that way
                if (c[k] > o[k] if d > 0 else c[k] < o[k]) and body[k] >= O["impulse_atr"] * at[k]: imp = k; break
            if imp is None: continue
            ob = None
            for k in range(imp - 1, max(imp - 30, 0) - 1, -1):      # the last opposite candle before it
                if (c[k] < o[k] if d > 0 else c[k] > o[k]): ob = k; break
            if ob is None: continue
            lo_, hi_ = float(l[ob]), float(h[ob])
            seen = (l[imp + 1:i + 1] <= hi_).any() if d > 0 else (h[imp + 1:i + 1] >= lo_).any()   # after the impulse
            if seen: continue                                     # already revisited: no zone
            if out and out[-1][2] == ob and out[-1][1] == d: continue
            out.append((i, d, ob, lo_, hi_))
    return out


def signals_of(b, spec):
    """[(bar, +1 long / -1 short, ob)] - the entry bars before the option filter, one per CHoCH."""
    O = spec["ob"]; ev, evd, _ = structure(b, int(O["pivot"])); obs = order_blocks(b, O)
    o, h, l, c, t = b.o, b.h, b.l, b.c, b.t
    start, last = core.hhmm_sec(O["start"]), core.hhmm_sec(O["last_entry"])
    out, fresh, k = [], [], 0; cur = 0; used = True; ch_i = -10**9   # cur: +1 / -1 the latest break was a bullish / bearish CHoCH
    for i in range(len(b)):
        while k < len(obs) and obs[k][0] <= i: fresh.append([*obs[k], False]); k += 1   # zones created up to this bar
        if ev[i]:
            cur = int(evd[i]) if ev[i] == 2 else 0; used = False; ch_i = i
        hit = None
        for z in fresh:
            if z[5] or z[0] >= i: continue                       # used, or created on this bar
            cb, d, ob, lo_, hi_, _ = z
            if (l[i] <= hi_) if d > 0 else (h[i] >= lo_):         # price trades into the zone: it is used up
                z[5] = True
                if hit is None and cur == d and not used and cb >= ch_i - int(O["lookback"]) and \
                   ((c[i] > o[i] and c[i] > lo_) if d > 0 else (c[i] < o[i] and c[i] < hi_)): hit = (d, z)
        fresh = [z for z in fresh if not z[5]]
        if hit and start <= t[i] % core.DAY < last:
            out.append((i, hit[0], hit[1])); used = True
    return out, ev, evd, obs


def run(ctx):
    """{choice: dict(trades, skipped, signals)}: the ATM option of each signal, priced on its own candles."""
    spec = ctx["spec"]; O = spec["ob"]; step = spec["options"]["strike_step"]
    sp = core.series("spot", "5minute"); chain = core.OptionChain("5minute")
    d_from, d_to = core.dnum(ctx["date_from"]), core.dnum(ctx["date_to"])
    ss = core.sessions(); k0 = int(np.searchsorted(ss, d_from)); first = int(ss[max(0, k0 - 3)])
    a, z = int(np.searchsorted(sp.day, first)), int(np.searchsorted(sp.day, d_to, "right"))
    b = sp.slice(a, z); sigs, ev, evd, obs = signals_of(b, spec)
    lots = ctx["position"]["lots"]; flat = core.hhmm_sec(O["flatten"]); tex = int(O["time_exit_min"]) * 60
    trs, skipped, free = [], [], -1
    for i, d, z_ in sigs:
        te = int(b.t[i]); day = te // core.DAY
        if day < d_from: continue
        if te <= free: skipped.append(dict(signal="BULLISH" if d > 0 else "BEARISH", position="", opt_type="", instrument="", entry_time=te, why="one position at a time")); continue
        right = "CE" if d > 0 else "PE"; k = int(round(float(b.c[i]) / step) * step)
        exp = chain.expiry_for(day, 0, "WEEKLY")
        s = chain.get(exp, k, right) if exp else None
        base = dict(dir="up" if d > 0 else "down", signal="BULLISH" if d > 0 else "BEARISH", strike=k, expiry=exp, choch_time=te)
        if s is None: skipped.append(dict(base, position="", opt_type=right, instrument=f"{k} {right}", entry_time=te, why="no candles for the ATM contract")); continue
        j = int(np.searchsorted(s.t, te))
        if j >= len(s) or s.t[j] != te: skipped.append(dict(base, position="", opt_type=right, instrument=chain.name(exp, k, right), entry_time=te, why="no option candle at the signal")); continue
        dd = int(np.searchsorted(s.day, day))
        if dd == 0: skipped.append(dict(base, position="", opt_type=right, instrument=chain.name(exp, k, right), entry_time=te, why="no previous session for this contract")); continue
        p0 = int(np.searchsorted(s.day, s.day[dd - 1])); plow = float(s.l[p0:dd].min()); e = float(s.c[j])
        ok = e >= plow if d > 0 else e < plow
        if not ok and O.get("prev_day_filter", True):
            skipped.append(dict(base, position="", opt_type=right, instrument=chain.name(exp, k, right), entry_time=te, filtered=True,
                                why=f"previous-day filter: {right} close {e:.2f} {'below' if d > 0 else 'not below'} its previous low {plow:.2f}")); continue
        sell = d < 0 and O["short_as"] == "sell_pe"
        stop = e * (1 + O["stop_pct"]) if sell else e * (1 - O["stop_pct"])
        tgt = e * O["sell_target"] if sell else e * (1 + O["stop_pct"] * O["rr"])
        end_t = min(te + tex, te - te % core.DAY + flat)
        x, px, why = None, None, None
        for m in range(j + 1, len(s)):
            if s.t[m] > end_t or s.day[m] != day: break
            if (s.h[m] >= stop) if sell else (s.l[m] <= stop): x, px, why = m, (max(s.o[m], stop) if sell else min(s.o[m], stop)), "stop_loss"; break
            if (s.l[m] <= tgt) if sell else (s.h[m] >= tgt): x, px, why = m, (min(s.o[m], tgt) if sell else max(s.o[m], tgt)), "target 1"; break
            x = m
        if x is None: skipped.append(dict(base, position="", opt_type=right, instrument=chain.name(exp, k, right), entry_time=te, why="no option candle after the entry")); continue
        if why is None: px, why = float(s.c[x]), ("eod" if s.t[x] >= te - te % core.DAY + flat - 300 else "time")
        free = int(s.t[x]); ui = lambda t_: float(b.c[max(0, int(np.searchsorted(b.t, t_, "right")) - 1)])
        rec = dict(base, position="SHORT" if sell else "LONG", opt_type=right, kind="OPT", instrument=chain.name(exp, k, right),
                   entry_time=te, entry_px=e, exit_time=int(s.t[x]), exit_px=float(px), exit_reason=why, open=False, sl=round(stop, 2),
                   und_entry=float(b.c[i]), und_exit=ui(int(s.t[x])), stale=False, lots=lots, tranche="", label=f"{'SHORT' if sell else 'LONG'} {right}",
                   prev_low=round(plow, 2), ob=f"{z_[3]:.1f}-{z_[4]:.1f}")
        core.excursion(s, rec, not sell)
        trs.append(core.price_trade(ctx, rec))
    sg = [dict(time=int(b.t[i]), dir="up" if evd[i] > 0 else "down", flipped=bool(ev[i] == 2), lvl=float(b.c[i]), av=None, hi=None, lo=None, setup=None)
          for i in range(len(b)) if ev[i] and core.dnum(core.dstr(int(b.day[i]))) >= d_from]
    return {ch: dict(trades=trs, skipped=skipped, signals=sg) for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL")}


def signals(bars, spec):
    """The futures structure, for the reference chart only; the trades come from run()."""
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """The index candles with this strategy's swings, BOS / CHoCH and Order Blocks, and its trades placed on the index."""
    spec = ctx["spec"]; O = spec["ob"]; sp = core.series("spot", "5minute")
    d0, d1 = core.dnum(day), core.dnum(to); ss = core.sessions(); k0 = int(np.searchsorted(ss, d0))
    a, z = int(np.searchsorted(sp.day, int(ss[max(0, k0 - 3)]))), int(np.searchsorted(sp.day, d1, "right"))
    b = sp.slice(a, z); i0 = int(np.searchsorted(b.day, d0)); i1 = len(b) - 1
    if i0 > i1: raise ValueError(f"no index candles from {day}")
    ev, evd, swings = structure(b, int(O["pivot"])); obs = order_blocks(b, O)
    T = lambda i: int(b.t[i]); C = {k: i for i, k in enumerate(body["cols"])}
    rows = []
    for r in body["trades"]:
        if not (d0 <= core.dnum(r[C["entry_time"]][:10]) <= d1): continue
        r = list(r); r[C["entry_px"]], r[C["exit_px"]], r[C["sl"]] = r[C["und_entry"]], r[C["und_exit"]], None; rows.append(r)
    trig = []
    for cb, d, ob, lo_, hi_ in obs:
        if cb < i0 - 40 or cb > i1: continue
        end = next((m for m in range(cb + 1, i1 + 1) if ((b.l[m] <= hi_) if d > 0 else (b.h[m] >= lo_))), i1)
        if end < i0: continue
        for p_ in (lo_, hi_): trig.append(dict(dir="up" if d > 0 else "down", p=round(p_, 2), a=T(max(ob, i0)), z=T(end), hit=end < i1))
    return dict(day=day, to=to, inst=None, candles=core._chart_bars(b, i0, i1), cols=body["cols"], trades=rows, own=True,
                sessions=int(len(np.unique(b.day[i0:i1 + 1]))),
                swings=[[k_, T(q), round(p_, 2), T(cf)] for k_, q, p_, cf in swings if i0 <= cf <= i1],
                events=[[T(i), "BOS" if ev[i] == 1 else "CHoCH", "up" if evd[i] > 0 else "down"] for i in range(i0, i1 + 1) if ev[i]],
                trig=trig)
