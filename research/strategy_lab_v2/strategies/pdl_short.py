"""An option sold when it closes below its own previous-session low; managed by its own structure (family module for ST90).

Built 2026-10-24 at the user's word: "if an option crosses below the previous day's low, sell; if CHoCH upside, exit if in
loss, else trail". The build choices (the request fixes none of them; all in SPEC["pdl"]):

  instrument  each session, the CE and the PE at the index's 09:15 open rounded to the strike step (the day-open ATM), on
              the nearest weekly expiry at least `expiry_min_days` out. Each leg is its own machine; both can be short at
              once; one position per leg. Prices: the download store's 1-minute option candles (store_reader.py, read-only).
  level       the leg's own low of the session before (the same contract). No candles of it that session: no trade.
  entry       a 1-minute CLOSE below that low (a wick is not a cross); SELL at the next minute's open. After an exit the leg
              needs a fresh cross: a close at or above the level first, then a close below it again.
  structure   the Foundation engine (the strategy's `rules`) on the leg's own 1-minute candles, warmed up on the
              `warmup_days` sessions before. A bullish CHoCH is an event on the candle that makes it (its close).
  exit        at each bullish CHoCH of the leg after the entry:
                in loss (that candle's close above the sale price)  -> buy back at that close ("choch_loss");
                in profit                                            -> keep it and TRAIL: the stop goes to the top of the
                bounce so far (the highest high since the leg's latest confirmed swing low, the CHoCH candle included);
                a later candle whose high reaches it buys back there ("trail_stop"; at the open when it opens above).
              While trailing, every new confirmed swing high below the stop and above the close lowers the stop to it;
              a later bullish CHoCH applies the same rule again (in loss: out; in profit: the stop to the new bounce top,
              never raised). No stop before the first CHoCH (the request has none); flat at the square-off ("eod",
              that minute's open).
"""
import numpy as np
import core
import store_reader

ENTRY_RULES = ("pdl_short_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT", "INDEX")
OWN_COVERAGE = True
REFUSED_WHY = "Strategy 90 sells the day-open ATM options on their own candles; only the Options (via futures) type runs"
DAY = core.DAY


def _expiry(exps, day, min_days):
    d = core.dnum(day)
    for e in exps:
        if core.dnum(e) - d >= min_days: return e
    return None


_SER = {}


def _bars(exp, strike, right, d_from, d_to):
    """core.Bars of one contract over sessions d_from..d_to (1-minute), from the store; None when it has no candles."""
    key = (exp, strike, right, d_from, d_to)
    if key not in _SER:
        c = store_reader.option_candles(exp, strike, right, d_from, d_to, "minute")
        while len(_SER) > 200: del _SER[next(iter(_SER))]
        if not c: _SER[key] = None
        else:
            a = np.array([x[:6] for x in c], dtype=np.float64)
            _SER[key] = core.Bars(a[:, 0].astype(np.int64), a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])
    return _SER[key]


def _legs(ctx, d):
    """[(right, name, expiry, strike, Bars, first candle of session d, the previous-session low)] of session d, or a reason."""
    spec = ctx["spec"]; S = spec["pdl"]; step = spec["options"]["strike_step"]
    sp = core.series("spot", "minute"); ss = core.sessions()
    i = int(np.searchsorted(sp.day, d))
    if i >= len(sp) or sp.day[i] != d: return "no index candles"
    exps = sorted(e["expiry"] for e in store_reader.expiries())
    day = core.dstr(d); exp = _expiry(exps, day, S["expiry_min_days"])
    if not exp: return "no option expiry in the store"
    k = int(round(float(sp.o[i]) / step) * step)
    k_ = int(np.searchsorted(ss, d)); d_from = core.dstr(int(ss[max(0, k_ - ctx["warmup"])]))
    out = []
    for right in ("CE", "PE"):
        name = f"NIFTY {core.D.date.fromisoformat(exp):%d%b%y} {k} {right}".upper()
        ob = _bars(exp, k, right, d_from, day)
        if ob is None: out.append((right, name, exp, k, None, -1, None)); continue
        o_day = int(np.searchsorted(ob.day, d))
        if o_day >= len(ob) or ob.day[o_day] != d: out.append((right, name, exp, k, ob, -1, None)); continue
        if o_day == 0: out.append((right, name, exp, k, ob, o_day, None)); continue
        j0 = int(np.searchsorted(ob.day, ob.day[o_day - 1]))
        out.append((right, name, exp, k, ob, o_day, float(ob.l[j0:o_day].min())))
    return out


def run(ctx):
    spec = ctx["spec"]; S = spec["pdl"]; sq = ctx["square_off"]; lots = ctx["position"]["lots"]
    ss = core.sessions(); days = ss[(ss >= core.dnum(ctx["date_from"])) & (ss <= core.dnum(ctx["date_to"]))]
    trs, skipped = [], []
    for d in days:
        d = int(d); legs = _legs(ctx, d)
        if isinstance(legs, str): continue
        for right, name, exp, k, ob, o_day, pdl in legs:
            base = dict(dir="down", signal="BEARISH", strike=k, expiry=exp)
            skip = lambda t_, why: skipped.append(dict(base, position="SHORT", opt_type=right, instrument=name, entry_time=t_, why=why))
            if ob is None or o_day < 0: skip(core.dstr(d), "no candles for that contract on that day in the store"); continue
            if pdl is None: skip(core.dstr(d), "the option has no candles in the session before: no previous low"); continue
            oe = core.foundation(ob, spec["rules"])
            t, o, h, l, c = ob.t, ob.o, ob.h, ob.l, ob.c; n = len(ob)
            cut = core.square_off_at(sq, int(t[o_day]))
            ch_up = set(int(oe.ei[j]) for j in range(len(oe.ei)) if oe.ek[j] == 1 and oe.ed[j] == 1)
            sw_hi = {}                                                    # confirmed at candle -> swing high price
            sw_lo = {}                                                    # confirmed at candle -> swing low's candle
            for j in range(len(oe.sk)):
                if oe.sk[j] == 1: sw_hi.setdefault(int(oe.sc[j]), []).append(float(oe.sp[j]))
                else: sw_lo[int(oe.sc[j])] = int(oe.sb[j])
            i, armed = o_day, True
            while i < n and ob.day[i] == d and (not cut or t[i] < cut):
                if c[i] >= pdl: armed = True; i += 1; continue
                if not armed: i += 1; continue
                e_i = i + 1
                if e_i >= n or ob.day[e_i] != d or (cut and t[e_i] >= cut): break
                e_px = float(o[e_i]); stop, moves, x_i, x_px, why = None, 0, None, None, None
                last_lo = max((sw_lo[q] for q in sw_lo if q <= e_i), default=e_i)        # the latest confirmed swing low's candle
                for m in range(e_i + 1, n):
                    if ob.day[m] != d or (cut and t[m] >= cut): x_i, x_px, why = m, float(o[m]), "eod"; break
                    if m in sw_lo: last_lo = max(last_lo, sw_lo[m])
                    if stop is not None and h[m] >= stop:
                        x_i, x_px, why = m, max(float(o[m]), stop), "trail_stop"; break
                    if m in ch_up:
                        if c[m] > e_px: x_i, x_px, why = m, float(c[m]), "choch_loss"; break
                        top = float(h[max(last_lo, e_i):m + 1].max())
                        stop = top if stop is None else min(stop, top); moves += 1
                    elif stop is not None and m in sw_hi:
                        for v in sw_hi[m]:
                            if c[m] < v < stop: stop = v; moves += 1
                if x_i is None:
                    x_i = max(q for q in range(e_i, n) if ob.day[q] == d and (not cut or t[q] < cut)); x_px, why = float(c[x_i]), "eod"
                rec = dict(base, position="SHORT", opt_type=right, kind="OPT", instrument=name, entry_time=int(t[e_i]), entry_px=e_px,
                           exit_time=int(t[x_i]), exit_px=x_px, exit_reason=why, open=False, sl=stop, sl_last=stop, sl_moves=moves,
                           choch_time=int(t[i]), und_entry=e_px, und_exit=x_px, stale=False, lots=lots, tranche="",
                           label=f"SHORT {right}", prev_low=round(pdl, 2), cross_time=core.tstr(t[i]))
                core.excursion(ob, rec, False)
                trs.append(core.price_trade(ctx, rec))
                i, armed = x_i + 1, False
    trs.sort(key=lambda r: r["entry_time"])
    return {ch: dict(trades=trs, skipped=skipped, signals=[]) for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL")}


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """The lab's main chart: the day-open ATM leg's own 1-minute candles (the leg with a trade that day, else the CE) with
    the engine's layers on them, the previous-session low as a line, and that leg's trades."""
    spec = ctx["spec"]; C = {k: i for i, k in enumerate(body["cols"])}
    ss = core.sessions(); days = ss[(ss >= core.dnum(day)) & (ss <= core.dnum(to))]
    candles, rows, ov, lines, legs_out = [], [], None, [], []
    LISTS = ("cand", "swings", "events", "flips", "prot", "setups", "pair", "tav", "trig")
    for d in days:
        d = int(d); legs = _legs(ctx, d)
        if isinstance(legs, str): legs_out.append(dict(day=core.dstr(d), why=legs)); continue
        mine = [r for r in body["trades"] if core.dnum(str(r[C["entry_time"]])[:10]) == d]
        want = mine[0][C["opt_type"]] if mine else "CE"
        leg = next((x for x in legs if x[0] == want and x[4] is not None and x[5] >= 0), None) or next((x for x in legs if x[4] is not None and x[5] >= 0), None)
        if leg is None: legs_out.append(dict(day=core.dstr(d), why="no candles for the day-open ATM options in the store")); continue
        right, name, exp, k, ob, o_day, pdl = leg
        eng = core.foundation(ob, spec["rules"]); i0, i1 = o_day, int(np.searchsorted(ob.day, d, "right")) - 1
        candles += core._chart_bars(ob, i0, i1)
        o_ = core._overlays(ob, eng, i0, i1, pair=True)
        if ov is None: ov = {k2: list(o_.get(k2) or []) for k2 in LISTS}
        else:
            for k2 in LISTS: ov[k2] += list(o_.get(k2) or [])
        if pdl is not None: lines.append([[int(ob.t[q]), round(pdl, 2)] for q in range(i0, i1 + 1)])
        rows += [list(r) for r in mine if r[C["instrument"]] == name]
        legs_out.append(dict(day=core.dstr(d), instrument=name, strike=k, expiry=exp, prev_low=pdl))
    if not candles: raise ValueError(f"no day-open ATM option candles from {day}" + (f": {legs_out[0].get('why')}" if legs_out else ""))
    out = dict(day=day, to=to, inst=None, candles=candles, cols=body["cols"], trades=rows, own=True, sessions=len([g for g in legs_out if g.get("strike")]),
               derived=dict(what="the day-open ATM option's own candles (the leg with a trade that day, else the CE); the line is its previous-session low", legs=legs_out))
    out.update(ov or {}); out["lines"] = lines
    return out
