"""Alien Algorithms' "Institutional Imbalance Framework" (family module for ST131 - ST134), rebuilt from its public docs
(https://docs.alienalgorithms.com/Institutional-Imbalance-Framework-TradingView/ - signals, somm, cvmi, settings).

The indicator is closed-source. The docs give its defaults and describe its rules in words; every rule they leave open
is a key of SPEC["iif"] (PARAMS below, with the docs' words beside each), fixed before the first run (S131).

  LTF gaps      a 3-candle Fair Value Gap on the chart's candles, all three in one session: bullish when low[j] > high[j-2]
                (zone high[j-2] .. low[j]), bearish the mirror; known at the close of j. A bullish gap fills from its top
                down as price trades into it (fill = how far the lowest low since has reached, 0 - 1); bearish the mirror.
  HTF blocks    the chart's candles grouped into `htf_mult` x candles inside each session (5-minute -> 15-minute; a
                higher-timeframe candle counts only after its last chart candle closed). A run of `min_gaps` consecutive
                bullish HTF gaps ("consecutive gap structure") makes a bullish OrderBlock from the low of the run's first
                origin candle to the high of its last displacement candle; it must be at least `min_width_atr` x HTF
                ATR(14) wide and contain at least one same-direction chart gap formed inside the run ("Require Internal
                FVGs"). Overlap Skip: a block overlapping, or nearer than `min_sep_atr` x chart ATR(14) to, an active
                block of its side is not created. At most `max_active` per side (the oldest retires). Retired after
                `lookback` chart candles.
  mitigation    the block's fill % = the filled width of its internal gaps / their total width. Mitigated (retired) when
                every internal gap is filled and a candle closes beyond the block's far edge (bullish: above its top).
  break level   bullish: bottom - `max_hunt` x width (the docs: deeper than the hunt cap counts as a breakdown); a close
                beyond it breaks and retires the block ("Break", close mode).
  Sweep         bullish: a close below the bottom (not beyond the break level), then `reclaim` consecutive closes back
                inside the block -> long at that close. A low beyond the break level, a close above the top, or the
                block retiring cancels the sweep; a new close below restarts the count. One sweep per block.
                `osc_filter`: CVMI at <= osc_low (bullish) / >= osc_high at the signal.
  Exhaust       bullish: fill >= `min_fill` while CVMI <= osc_low arms it; "Osc Exit" - fires on the first close with
                CVMI back above osc_low while the block is still active. One per block.
  Break trade   the broken bullish block is read the other way: short at the breaking close (bearish blocks: long).
  CVMI          an APPROXIMATION (the vendor's formula is not published): the sum over every open chart gap of
                +/- its width in % of price x (1 - fill), mapped to 0 - 100 by the "ADN": an EMA(`osc_period`) centre,
                an EMA of the absolute deviation as the envelope, 100 / (1 + exp(-sharpness x z)). Spatial mode (the
                default: no volume).

Trades (one position at a time, both sides): entry at the signal candle's close (not on the session's first candle, not at
or after the square-off). Stop: the block's break level (Break trades: the block's far edge). Target: the near edge of the
nearest open chart gap (fill <= `rebal_fill`, the Matrix's Filled 20%) at least `min_rr` x risk beyond the entry - the
docs' "untested Active cluster" - else `rr_fallback` x risk. A touch exits at the level, at the open when the candle opens
beyond it; the stop is checked first. Flat at the square-off.
"""
import numpy as np
import core

ENTRY_RULES = ("iif_v1",)
SIGNALS = ("sweep", "exhaust", "break")

PARAMS = {
    "htf_mult": 3,            # "Auto HTF On, x 3"
    "min_gaps": 2,            # "consecutive gap structure" - no count in the docs
    "min_width_atr": 0.6,     # "Min Width x ATR 0.6" (HTF ATR(14))
    "min_sep_atr": 0.3,       # "Min Separation 0.3" (chart ATR)
    "max_active": 3,          # "Max Active OBs 3"
    "lookback": 2000,         # "OB Lookback 2000 bars"
    "max_hunt": 0.33,         # "Max Hunt x Width 0.33"
    "reclaim": 4,             # "Reclaim Closes 4"
    "osc_filter": False,      # "Oscillator Filter Off"
    "min_fill": 85.0,         # "Min Fill % 85"
    "osc_low": 25.0, "osc_high": 75.0,   # "Osc Low / High 25 / 75"
    "osc_period": 200, "sharpness": 1.5, # "Period 200", "Sharpness 1.5"
    "pool": 500,              # "Max Pool 500"
    "rebal_fill": 0.2,        # "Active % / Filled % 80 / 20"
    "rebal_lookback": 1000,   # "Lookback 1000"
    "min_rr": 1.0, "rr_fallback": 2.0,   # not in the docs: the target rule
}


def _ema(x, n):
    out = np.empty(len(x)); a = 2.0 / (n + 1); m = x[0] if len(x) else 0.0
    for i in range(len(x)):
        m = m + a * (x[i] - m); out[i] = m
    return out


def _gaps(h, l, day):
    """Chart gaps: (bar j, dir, bottom, top)."""
    j = np.arange(2, len(h))
    same = (day[j] == day[j - 2])
    bu = np.nonzero(same & (l[j] > h[j - 2]))[0] + 2
    be = np.nonzero(same & (h[j] < l[j - 2]))[0] + 2
    g = [(int(k), 1, float(h[k - 2]), float(l[k])) for k in bu] + [(int(k), -1, float(h[k]), float(l[k - 2])) for k in be]
    g.sort()
    return g


def _htf(b, mult, bar_sec):
    """HTF candles inside each session: (last chart bar, h, l, c, day) arrays."""
    tod = b.t % core.DAY; size = mult * bar_sec
    key = b.day * 1000 + (tod - tod.min()) // size
    ends = np.nonzero(np.r_[key[1:] != key[:-1], True])[0]
    starts = np.r_[0, ends[:-1] + 1]
    H = np.array([b.h[s:e + 1].max() for s, e in zip(starts, ends)])
    L = np.array([b.l[s:e + 1].min() for s, e in zip(starts, ends)])
    C = b.c[ends]; D = b.day[ends]
    return starts, ends, H, L, C, D


def _htf_runs(starts, ends, H, L, C, D, X):
    """HTF gap runs -> block candidates (known at chart bar, dir, bottom, top, first chart bar of the run)."""
    at = core._atr(H, L, C, 14); n = len(H); out = []; run = {1: 0, -1: 0}
    for k in range(2, n):
        if D[k] != D[k - 2]: run = {1: 0, -1: 0}; continue
        for d in (1, -1):
            gap = L[k] > H[k - 2] if d > 0 else H[k] < L[k - 2]
            run[d] = run[d] + 1 if gap else 0
            if run[d] == int(X["min_gaps"]):
                s = k - run[d] + 1                       # first gap's third candle; origin candle s-2
                if d > 0: bot, top = float(L[s - 2]), float(H[k - 1])
                else: bot, top = float(L[k - 1]), float(H[s - 2])
                if top - bot >= float(X["min_width_atr"]) * at[k] and top > bot:
                    out.append((int(ends[k]), d, bot, top, int(starts[s - 2])))
    return out


def scan(b, X):
    """Bar-by-bar engine: returns (events [(bar, kind, dir, block)], cvmi array, gap pool snapshots for targets)."""
    o, h, l, c, day, n = b.o, b.h, b.l, b.c, b.day, len(b)
    bar_sec = int(np.median(np.diff(b.t[:200]))) if n > 2 else 60
    starts, ends, H, L, C, D = _htf(b, int(X["htf_mult"]), bar_sec)
    cands = _htf_runs(starts, ends, H, L, C, D, X); ci = 0
    gaps = _gaps(h, l, day); gi = 0
    catr = core._atr(h, l, c, 14)
    press, _ = _pool(b, gaps, X, ())
    all_g = gaps
    blocks = []; active = []; events = []
    hunt, rec, mf = float(X["max_hunt"]), int(X["reclaim"]), float(X["min_fill"])
    lo_o, hi_o = float(X["osc_low"]), float(X["osc_high"])
    cen = _ema(press, int(X["osc_period"])); dev = _ema(np.abs(press - cen), int(X["osc_period"]))
    z = np.where(dev > 0, (press - cen) / np.where(dev > 0, dev, 1), 0.0)
    osc = 100.0 / (1.0 + np.exp(-float(X["sharpness"]) * z))

    gix = np.array([g[0] for g in all_g], np.int64)
    for i in range(n):
        while ci < len(cands) and cands[ci][0] == i:
            k, d, bo, to, first = cands[ci]; ci += 1
            same = [B for B in active if B["dir"] == d]
            sep = float(X["min_sep_atr"]) * catr[i]
            if any(not (to + sep < B["bot"] or bo - sep > B["top"]) for B in same): continue
            lo_j, hi_j = int(np.searchsorted(gix, first + 2, "left")), int(np.searchsorted(gix, i, "right"))
            inner = [g for g in all_g[lo_j:hi_j] if g[1] == d and g[2] < to and g[3] > bo]
            if not inner: continue
            B = dict(dir=d, bot=bo, top=to, born=i, w=to - bo,
                     brk=bo - hunt * (to - bo) if d > 0 else to + hunt * (to - bo),
                     ib=np.array([max(g[2], bo) for g in inner]), it=np.array([min(g[3], to) for g in inner]),
                     ext=None, swept=False, cnt=0, sweep_done=False, armed=False, exh_done=False)
            B["ext"] = B["it"].copy() if d > 0 else B["ib"].copy()
            if len(same) >= int(X["max_active"]): active.remove(same[0])
            active.append(B); blocks.append(B)
        for B in list(active):
            if i <= B["born"]: continue
            d, bo, to = B["dir"], B["bot"], B["top"]
            if d > 0: B["ext"] = np.minimum(B["ext"], l[i]); f = np.clip((B["it"] - B["ext"]), 0, None)
            else: B["ext"] = np.maximum(B["ext"], h[i]); f = np.clip((B["ext"] - B["ib"]), 0, None)
            tw = (B["it"] - B["ib"]); fill = 100.0 * float(np.minimum(f, tw).sum() / tw.sum())
            B["fill"] = fill
            if i - B["born"] > int(X["lookback"]): active.remove(B); continue
            if (c[i] < B["brk"]) if d > 0 else (c[i] > B["brk"]):
                events.append((i, "break", -d, B)); active.remove(B); continue
            if fill >= 99.999 and ((c[i] > to) if d > 0 else (c[i] < bo)):
                active.remove(B); continue
            # sweep
            if not B["sweep_done"]:
                beyond = (c[i] < bo) if d > 0 else (c[i] > to)
                inside = bo <= c[i] <= to
                too_deep = (l[i] < B["brk"]) if d > 0 else (h[i] > B["brk"])
                if too_deep: B["swept"], B["cnt"] = False, 0
                elif beyond: B["swept"], B["cnt"] = True, 0
                elif B["swept"] and inside:
                    B["cnt"] += 1
                    if B["cnt"] >= rec:
                        ok = (not X["osc_filter"]) or ((osc[i] <= lo_o) if d > 0 else (osc[i] >= hi_o))
                        if ok: events.append((i, "sweep", d, B))
                        B["sweep_done"] = True
                elif B["swept"]: B["swept"], B["cnt"] = False, 0
            # exhaust (Osc Exit)
            if not B["exh_done"]:
                ext_now = (osc[i] <= lo_o) if d > 0 else (osc[i] >= hi_o)
                if fill >= mf and ext_now: B["armed"] = True
                elif B["armed"] and not ext_now:
                    events.append((i, "exhaust", d, B)); B["exh_done"] = True
    _, snaps = _pool(b, gaps, X, {e[0] for e in events})
    return events, osc, snaps


def _pool(b, gaps, X, want):
    """The open-gap pool bar by bar ("Max Pool"): the CVMI pressure per bar and, for the bars in `want`, the open gaps."""
    h, l, c, n = b.h, b.l, b.c, len(b); P = int(X["pool"]); gi = 0
    gb = np.zeros(P); gt = np.ones(P); gd = np.zeros(P); gj = np.zeros(P, np.int64); ext = np.zeros(P)
    live = np.zeros(P, bool); slot = 0; press = np.zeros(n); snaps = {}
    for i in range(n):
        while gi < len(gaps) and gaps[gi][0] == i:
            j, d, bo, to = gaps[gi]; gi += 1
            gb[slot], gt[slot], gd[slot], gj[slot], live[slot] = bo, to, d, j, True
            ext[slot] = to if d > 0 else bo
            slot = (slot + 1) % P
        m = live & (gj < i)
        up = m & (gd > 0); dn = m & (gd < 0)
        ext[up] = np.minimum(ext[up], l[i]); ext[dn] = np.maximum(ext[dn], h[i])
        w = gt - gb; fill = np.zeros(P)
        fill[up] = np.clip((gt[up] - ext[up]) / w[up], 0, 1); fill[dn] = np.clip((ext[dn] - gb[dn]) / w[dn], 0, 1)
        live &= ~(m & (fill >= 1.0))
        press[i] = float(np.sum(gd[live] * w[live] / c[i] * 100.0 * (1.0 - fill[live])))
        if i in want: snaps[i] = (gb[live].copy(), gt[live].copy(), fill[live].copy(), gj[live].copy())
    return press, snaps


def _target(snaps, i, d, e, risk, X):
    gb, gt, fill, gj = snaps[i]
    ok = (fill <= float(X["rebal_fill"])) & (gj >= i - int(X["rebal_lookback"]))
    need = float(X["min_rr"]) * risk
    if d > 0:
        lv = gb[ok & (gb >= e + need)]
        if len(lv): return float(lv.min())
        return e + float(X["rr_fallback"]) * risk
    lv = gt[ok & (gt <= e - need)]
    if len(lv): return float(lv.max())
    return e - float(X["rr_fallback"]) * risk


def signals(bars, spec):
    X = dict(PARAMS, **(spec.get("iif") or {})); kind = X.get("signal")
    if kind not in SIGNALS: raise ValueError(f"{spec['code']}: iif.signal must be one of {SIGNALS}")
    sq = spec["position"]["square_off"]
    o, h, l, c, day, t, n = bars.o, bars.h, bars.l, bars.c, bars.day, bars.t, len(bars)
    events, osc, snaps = scan(bars, X)
    trades, free = [], -1
    for i, k, d, B in events:
        if k != kind or i <= free or i + 1 >= n: continue
        if i == 0 or day[i] != day[i - 1]: continue                  # not the session's first candle
        cut = core.square_off_at(sq, int(t[i]))
        if cut and t[i] >= cut: continue
        e = float(c[i])
        if kind == "break": sl = B["top"] if d < 0 else B["bot"]
        else: sl = B["brk"]
        risk = (e - sl) * d
        if risk <= 0: continue
        tg = _target(snaps, i, d, e, risk, X)
        last = (int(np.searchsorted(t, cut, "right")) - 1) if cut else n - 1
        if last <= i: continue
        x, px, why, still = last, float(c[last]), ("eod" if cut else "open"), not cut
        for j in range(i + 1, last + 1):
            if (l[j] <= sl) if d > 0 else (h[j] >= sl):
                x, px, why, still = j, (min(o[j], sl) if d > 0 else max(o[j], sl)), "stop_loss", False; break
            if (h[j] >= tg) if d > 0 else (l[j] <= tg):
                x, px, why, still = j, (max(o[j], tg) if d > 0 else min(o[j], tg)), "target 1", False; break
        trades.append(dict(entry=i, exit=x, exit_px=float(px), dir="up" if d > 0 else "down", choch=i, sl=float(sl),
                           pts=(float(px) - e) * d, open=still, exit_reason=why))
        free = x
    sg = core.foundation(bars, spec["rules"]).with_trades(trades, [])
    sg.line_names = []; sg.line_colors = []
    return sg
