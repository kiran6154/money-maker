"""Day-open ATM straddle strategies (family module for ST57 / ST58): the Foundation engine read on the straddle's candles.

The instrument: on each session, the strike nearest the index's first candle (no look-ahead) for which both the CE and the
PE have candles that day, on the nearest weekly expiry at least options.expiry_min_days out (the one expiring that day when
the next is not in the data). Its candles = CE + PE per candle: open = the two opens, close = the two closes, high / low =
the highest / lowest of that open and close (the legs' own highs come at different moments), volume = both. Candles of a
timeframe above 1 minute are built from the 1-minute ones (09:15-aligned), with high / low from the 1-minute values.

The engine runs once per session on that session's own pair: the pair's candles of the `warmup_days` sessions before it
(the same strike, so the chart does not jump when the ATM strike changes overnight) warm the structure up, and only
SETUPs whose entry candle is in the session are trades. Strategy 3's rules, stop and exit, all on the straddle's chart:
stop at the previous swing of the combined premium, exit at the stop or the next CHoCH, flat by the square-off.

SPEC["straddle"]["mode"]:
  both         a bullish SETUP buys the CE and the PE; a bearish SETUP sells both. Each leg is one position (1 lot each).
  rising_leg   bullish SETUPs only: buy the one leg that is going up - the leg with the larger change of its close over
               the last `lookback` candles up to the entry candle - and leave it when the straddle trade ends (its stop
               or the next CHoCH on the straddle chart: the sell side), or at the square-off.
A leg's fill is its own candle close at the straddle trade's entry and exit candles (also when the exit is the stop: the
stop is a level of the combined premium, which no single leg trades at).
"""
import numpy as np
import core

ENTRY_RULES = ("straddle_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT",)
OWN_COVERAGE = True
REFUSED_WHY = "the straddle strategies trade the day-open ATM CE / PE; only the Options (via futures) type runs"
DAY = core.DAY


def pair_of(chain, sp, spec, d):
    """(expiry, strike, CE series, PE series, the index's open) of session d, or a reason string."""
    o = spec["options"]; step = o["strike_step"]
    i = int(np.searchsorted(sp.day, d))
    if i >= len(sp) or sp.day[i] != d: return "no index candles"
    exp = chain.expiry_for(d, o.get("expiry_min_days", 1), "WEEKLY") or chain.expiry_for(d, 0, "WEEKLY")
    if not exp: return "no option expiry on or after this day in the data"
    if not chain.full_chain(exp): return f"no full-chain data for expiry {exp}"
    k0 = int(round(float(sp.o[i]) / step) * step)
    for n in range(0, 3):                                   # the ATM, else one or two strikes away; further is not a straddle at the money
        for k in ((k0,) if n == 0 else (k0 + n * step, k0 - n * step)):
            ce, pe = chain.get(exp, k, "CE"), chain.get(exp, k, "PE")
            if ce is not None and pe is not None and np.any(ce.day == d) and np.any(pe.day == d):
                return exp, int(k), ce, pe, float(sp.o[i])
    return f"no CE + PE pair within 2 strikes of {k0} with candles"


def combined(ce, pe, d_from, d_to, minutes):
    """(Bars of CE + PE over sessions d_from..d_to at `minutes`, per candle the index of its last 1-minute candle in ce, in pe)."""
    a0, a1 = int(np.searchsorted(ce.day, d_from)), int(np.searchsorted(ce.day, d_to, "right"))
    b0, b1 = int(np.searchsorted(pe.day, d_from)), int(np.searchsorted(pe.day, d_to, "right"))
    t, ia, ib = np.intersect1d(ce.t[a0:a1], pe.t[b0:b1], return_indices=True)
    if not len(t): return None
    ia += a0; ib += b0
    op, cl, v = ce.o[ia] + pe.o[ib], ce.c[ia] + pe.c[ib], ce.v[ia] + pe.v[ib]
    tod = t % DAY; bucket = t - tod + (555 + ((tod // 60 - 555) // minutes) * minutes) * 60
    cuts = np.concatenate([[0], np.nonzero(np.diff(bucket))[0] + 1, [len(t)]])
    q0, q1 = cuts[:-1], cuts[1:] - 1
    hi = np.array([max(op[a:b + 1].max(), cl[a:b + 1].max()) for a, b in zip(q0, q1)])
    lo = np.array([min(op[a:b + 1].min(), cl[a:b + 1].min()) for a, b in zip(q0, q1)])
    vol = np.add.reduceat(v, q0)
    return core.Bars(bucket[q0], op[q0], hi, lo, cl[q1], vol), ia[q1], ib[q1]


def signals(bars, spec):
    """The futures structure, for the reference chart only (no trade comes from it)."""
    return core.foundation(bars, spec["rules"])


def run(ctx):
    """{choice: dict(trades, skipped, signals)}: one engine run per session on that session's ATM pair."""
    spec, S = ctx["spec"], ctx["spec"]["straddle"]
    if S["mode"] not in ("both", "rising_leg"): raise ValueError("straddle.mode is 'both' or 'rising_leg'")
    chain = core.OptionChain("minute"); sp = core.series("spot", "minute")
    minutes = core.TF_MIN[ctx["tf"]]; sq = ctx["square_off"]; lots = ctx["position"]["lots"]
    ss = core.sessions(); days = ss[(ss >= core.dnum(ctx["date_from"])) & (ss <= core.dnum(ctx["date_to"]))]
    trs, skipped, sigs = [], [], []
    for d in days:
        d = int(d); got = pair_of(chain, sp, spec, d)
        if isinstance(got, str):                               # days before the option data are not listed one by one
            if got.startswith("no CE + PE"): skipped.append(dict(signal="", position="", opt_type="", instrument="", entry_time=core.dstr(d), why=got))
            continue
        exp, k, ce, pe, _ = got
        k_ = int(np.searchsorted(ss, d)); d_from = int(ss[max(0, k_ - ctx["warmup"])])
        got = combined(ce, pe, d_from, d, minutes)
        if got is None: continue
        b, ia, ib = got
        eng = core.foundation(b, spec["rules"])
        i_day = int(np.searchsorted(b.day, d)); free_at = -1
        for j in range(len(eng.qi)):
            if eng.qi[j] >= i_day:
                sigs.append(dict(time=int(b.t[eng.qi[j]]), dir="up" if eng.qd[j] == 1 else "down", flipped=bool(eng.qflip[j]),
                                 lvl=float(eng.qlvl[j]), av=float(eng.qav[j]), hi=None, lo=None, setup=None))
        for x in eng.trades():
            ke = x["entry"]
            if ke < i_day: continue
            te = int(b.t[ke]); up = x["dir"] == "up"
            if S["mode"] == "rising_leg" and not up: continue
            cut = core.square_off_at(sq, te)
            base = dict(dir=x["dir"], signal="BULLISH" if up else "BEARISH", strike=k, expiry=exp, choch_time=int(b.t[x["choch"]]))
            if cut and te >= cut:
                skipped.append(dict(base, position="LONG" if up else "SHORT", opt_type="", instrument=f"{k} straddle", entry_time=te, why="entry at or after the square-off time")); continue
            if te <= free_at:
                skipped.append(dict(base, position="LONG" if up else "SHORT", opt_type="", instrument=f"{k} straddle", entry_time=te, why=f"one straddle trade at a time: open until {core.tstr(free_at)}")); continue
            kx, why, still = x["exit"], x["exit_reason"], x["open"]
            if cut and (b.t[kx] > cut or still):                      # intraday: flat at the last candle opening at or before the square-off
                kc = int(np.searchsorted(b.t, cut, "right")) - 1
                if kc >= ke and (b.t[kx] > cut or still): kx, why, still = kc, "eod", False
            free_at = int(b.t[kx])
            if S["mode"] == "rising_leg":
                n = S["lookback"]; k0 = max(ke - n, 0)
                dce = float(ce.c[ia[ke]] - ce.c[ia[k0]]); dpe = float(pe.c[ib[ke]] - pe.c[ib[k0]])
                legs = [("CE", ce, ia)] if dce >= dpe else [("PE", pe, ib)]
                extra = dict(leg_move=round(max(dce, dpe), 2), other_move=round(min(dce, dpe), 2))
            else:
                legs, extra = [("CE", ce, ia), ("PE", pe, ib)], {}
            for right, os_, ix in legs:
                rec = dict(base, **extra, position="LONG" if up else "SHORT", opt_type=right, kind="OPT", instrument=chain.name(exp, k, right),
                           entry_time=int(os_.t[ix[ke]]), entry_px=float(os_.c[ix[ke]]), exit_time=int(os_.t[ix[kx]]), exit_px=float(os_.c[ix[kx]]),
                           exit_reason=why, open=bool(still), sl=None, und_entry=float(b.c[ke]), und_exit=float(b.c[kx]), stale=False,
                           lots=lots, tranche="", label=f"{'LONG' if up else 'SHORT'} {right}")
                core.excursion(os_, rec, up)
                trs.append(core.price_trade(ctx, rec))
    trs.sort(key=lambda r: (r["entry_time"], r["opt_type"]))
    return {ch: dict(trades=trs, skipped=skipped, signals=sigs) for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL")}


def chart_main(ctx, body, day, to):
    """The lab's main chart for these strategies: the derived straddle candles of sessions day..to (each session its own
    day-open ATM pair) with the engine's layers computed on them, and one marker row per straddle trade placed on the
    combined premium (entry / exit = the combined close at those candles; points and rupees = the legs' own, summed)."""
    spec = ctx["spec"]; chain = core.OptionChain("minute"); sp = core.series("spot", "minute")
    minutes = core.TF_MIN[ctx["tf"]]; ss = core.sessions()
    days = ss[(ss >= core.dnum(day)) & (ss <= core.dnum(to))]
    C = {k: i for i, k in enumerate(body["cols"])}
    by = {}                                                       # (entry time, position) -> the stored leg rows
    for r in body["trades"]: by.setdefault((core.ts(r[C["entry_time"]]), r[C["position"]]), []).append(r)
    candles, rows, legs, ov = [], [], [], None
    LISTS = ("cand", "swings", "events", "flips", "prot", "setups", "pair", "tav", "trig")
    for d in days:
        d = int(d); got = pair_of(chain, sp, spec, d)
        if isinstance(got, str): legs.append(dict(day=core.dstr(d), why=got)); continue
        exp, k, ce, pe, idx_open = got
        k_ = int(np.searchsorted(ss, d)); d_from = int(ss[max(0, k_ - ctx["warmup"])])
        got = combined(ce, pe, d_from, d, minutes)
        if got is None: legs.append(dict(day=core.dstr(d), why="the CE and the PE share no candle")); continue
        b, ia, ib = got
        eng = core.foundation(b, spec["rules"]); i0 = int(np.searchsorted(b.day, d)); i1 = len(b) - 1
        if i0 > i1: continue
        candles += core._chart_bars(b, i0, i1)
        o_ = core._overlays(b, eng, i0, i1, pair=True)
        if ov is None: ov = {k2: list(o_.get(k2) or []) for k2 in LISTS}
        else:
            for k2 in LISTS: ov[k2] += list(o_.get(k2) or [])
        legs.append(dict(day=core.dstr(d), strike=k, expiry=exp, index_open=idx_open))
        for x in eng.trades():
            if x["entry"] < i0: continue
            te = int(os_t(ce, ia, x["entry"])); pos = "LONG" if x["dir"] == "up" else "SHORT"
            mine = by.get((te, pos))
            if not mine: continue                                 # a SETUP the strategy did not take (square-off, lock, mode)
            r = list(mine[0]); rights = "+".join(m[C["opt_type"]] for m in mine)
            r[C["instrument"]] = f"{k} {rights} (straddle chart)"; r[C["opt_type"]] = rights
            r[C["entry_px"]] = mine[0][C["und_entry"]]; r[C["exit_px"]] = mine[0][C["und_exit"]]; r[C["sl"]] = x["sl"]
            for f in ("pts", "gross", "charges", "net"): r[C[f]] = round(sum(m[C[f]] for m in mine), 2)
            r[C["label"]] = f"{pos} {rights}"
            rows.append(r)
    if not candles: raise ValueError(f"no day-open ATM straddle candles from {day}" + (f" to {to}" if to != day else "") + (f": {legs[0].get('why')}" if legs else ""))
    out = dict(day=day, to=to, inst=None, candles=candles, cols=body["cols"], trades=rows, own=True,
               sessions=len([g for g in legs if g.get("strike")]),
               derived=dict(what="CE + PE of the strike nearest the index at each day's open", legs=legs))
    out.update(ov or {})
    return out


def os_t(os_, ix, k):
    """The time a leg's trade at combined candle k is recorded at (its own last 1-minute candle in that candle)."""
    return os_.t[ix[k]]
