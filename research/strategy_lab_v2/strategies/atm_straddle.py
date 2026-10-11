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
  managed_short  a short straddle managed leg by leg on the SETUPs of the straddle chart (no stop, no CHoCH exit):
               bearish SETUP -> be short both legs: sell every leg not held (both when flat; the one bought back earlier);
               bullish SETUP -> buy back the leg that is going up (the larger change of its close over `lookback`
               candles), when it is held; the other leg stays short;
               the square-off closes what is left.
  both_sides   nothing is bought back. A bearish SETUP sells the CE and the PE; a bullish SETUP buys the one leg that is
               going up (rising_leg's definition) while any short stays open. Every leg has a target of `target_pts` on its
               own premium (touched on its own 1-minute candles: filled at the target, or at the open when the candle
               gaps through it); an entry's legs still open leave at that straddle trade's own exit (the stop at the
               previous swing of the combined premium, or the next CHoCH), or at the square-off. One entry a side at a time.
               With `exit: "target_only"` the straddle trade's stop and CHoCH exit are not used: a leg leaves at its
               target, or at the square-off.
               With `real: "long"` the short straddle is imaginary (a signal on the chart, never an order): only the
               bullish SETUP's leg is bought.
  leg_structure  the straddle chart only says WHEN and WHICH option; the trades come from the option's own chart.
               A bullish SETUP on the straddle chart ("the long scenario") arms the leg that is going up (rising_leg's
               definition). From the next candle the Foundation engine's SETUPs on THAT OPTION'S OWN candles (the same
               rules, warmed up on the option's own candles of the warm-up sessions) are traded: stop at the option's
               previous swing, exit at the stop or the option's next CHoCH, flat by the square-off. One trade a leg at a time.
               `window`: "day" = armed until the close; "scenario" = armed only until that straddle trade's own exit.
               `sides`: "long" = only the option's bullish SETUPs (buy it); "both" = its bearish SETUPs sell it too.
               `arm` (optional): "both" = a bearish SETUP on the straddle chart arms the leg that is going up as well
               (default: only the bullish one does).
               `entry` (optional): "signal" = no SETUP of the option is waited for: the leg is BOUGHT at the straddle
               signal's own candle (its close). The option's own structure then manages it: stop at its latest
               confirmed swing low below the entry, `trail`, exit at its next bearish CHoCH, flat by the square-off.
               With `stop: {rule: "prev_choch", buffer_pct}` (entry "signal" only) the first stop is the low of the
               option's latest CHoCH candle at or before the entry, less buffer_pct percent of that low - instead of
               the latest swing low. With `stop: {rule: "fixed", pts}` it is the entry premium less pts points.
               With `two_lots: {target_pts, trail_after_pts}` (entry "signal" only) the entry is two lots of
               `position.lots` each: lot T1 leaves at entry + target_pts (the first stop until then, never moved);
               lot TRAIL keeps the first stop until the option has traded at entry + trail_after_pts, then its stop
               goes to the level of the latest bullish BOS since the entry and follows every later one. Both leave at
               the stop, the option's next bearish CHoCH, or the square-off.
               `trail` (optional): the stop follows the option's own BOS in the trade's direction, from the candle
               after it, and never moves back. "bos_level" = to the level that BOS broke (the swing high for a long);
               "bos_swing" = to the latest confirmed swing low (long) / high (short) at that BOS.
SPEC["straddle"]["gap_restart"] (optional, any mode's charts that it is applied to: the straddle chart, and the option's own
chart in leg_structure): on a session whose first candle OPENS above the previous session's high or below its low (that
chart's own candles), the structure starts again: the engine runs from the session's first candle only, with no memory of
the earlier sessions.
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


def gap_start(b, d):
    """The candle of b at which session d starts again after a gap (its first candle, when that candle opens outside
    the previous session's high - low range on this chart), else 0 (no gap, or no session before it)."""
    i = int(np.searchsorted(b.day, d))
    if i == 0 or i >= len(b): return 0
    j = int(np.searchsorted(b.day, b.day[i - 1]))
    return i if (b.o[i] > b.h[j:i].max() or b.o[i] < b.l[j:i].min()) else 0


def cut_bars(b, i):
    return b if i == 0 else core.Bars(b.t[i:], b.o[i:], b.h[i:], b.l[i:], b.c[i:], b.v[i:])


def signals(bars, spec):
    """The futures structure, for the reference chart only (no trade comes from it)."""
    return core.foundation(bars, spec["rules"])


def run(ctx):
    """{choice: dict(trades, skipped, signals)}: one engine run per session on that session's ATM pair."""
    spec, S = ctx["spec"], ctx["spec"]["straddle"]
    if S["mode"] not in ("both", "rising_leg", "managed_short", "both_sides", "leg_structure"): raise ValueError("straddle.mode is 'both', 'rising_leg', 'managed_short', 'both_sides' or 'leg_structure'")
    chain = core.OptionChain("minute"); sp = core.series("spot", "minute")
    minutes = core.TF_MIN[ctx["tf"]]; sq = ctx["square_off"]; lots = ctx["position"]["lots"]
    ss = core.sessions(); days = ss[(ss >= core.dnum(ctx["date_from"])) & (ss <= core.dnum(ctx["date_to"]))]
    trs, skipped, sigs, gaps = [], [], [], []
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
        if S.get("gap_restart"):
            g = gap_start(b, d)
            if g: b, ia, ib = cut_bars(b, g), ia[g:], ib[g:]; gaps.append(core.dstr(d))
        eng = core.foundation(b, spec["rules"])
        i_day = int(np.searchsorted(b.day, d)); free_at = -1
        for j in range(len(eng.qi)):
            if eng.qi[j] >= i_day:
                sigs.append(dict(time=int(b.t[eng.qi[j]]), dir="up" if eng.qd[j] == 1 else "down", flipped=bool(eng.qflip[j]),
                                 lvl=float(eng.qlvl[j]), av=float(eng.qav[j]), hi=None, lo=None, setup=None))
        if S["mode"] == "leg_structure":
            if minutes != 1: raise ValueError("straddle.mode 'leg_structure' reads the option's own 1-minute candles: run it on the 1-minute timeframe")
            _leg_structure(ctx, S, eng, b, i_day, d, d_from, k, exp, chain, (("CE", ce, ia), ("PE", pe, ib)), trs, skipped); continue
        if S["mode"] == "both_sides":
            _both_sides(ctx, S, eng, b, i_day, k, exp, chain, (("CE", ce, ia), ("PE", pe, ib)), trs, skipped); continue
        if S["mode"] == "managed_short":
            _managed(ctx, S, eng, b, i_day, d, k, exp, chain, (("CE", ce, ia), ("PE", pe, ib)), trs, skipped); continue
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


def _managed(ctx, S, eng, b, i_day, d, k, exp, chain, legs, trs, skipped):
    """One session of the managed short straddle: every SETUP of the session in candle order (see the module text)."""
    sq, lots, n = ctx["square_off"], ctx["position"]["lots"], S["lookback"]
    cut = core.square_off_at(sq, int(b.t[i_day])); held = {}          # right -> (entry candle, the SETUP that opened it)
    kc = (int(np.searchsorted(b.t, cut, "right")) - 1) if cut else len(b) - 1

    def close(right, kx, why, still=False):
        ke, x = held.pop(right); os_, ix = next((o_, i_) for r_, o_, i_ in legs if r_ == right)
        rec = dict(dir="down", signal="BEARISH", strike=k, expiry=exp, choch_time=int(b.t[x["choch"]]), position="SHORT", opt_type=right,
                   kind="OPT", instrument=chain.name(exp, k, right), entry_time=int(os_.t[ix[ke]]), entry_px=float(os_.c[ix[ke]]),
                   exit_time=int(os_.t[ix[kx]]), exit_px=float(os_.c[ix[kx]]), exit_reason=why, open=bool(still), sl=None,
                   und_entry=float(b.c[ke]), und_exit=float(b.c[kx]), stale=False, lots=lots, tranche="", label=f"SHORT {right}")
        core.excursion(os_, rec, False)
        trs.append(core.price_trade(ctx, rec))

    for x in eng.trades():
        ke = x["entry"]
        if ke < i_day: continue
        te = int(b.t[ke]); up = x["dir"] == "up"
        base = dict(dir=x["dir"], signal="BULLISH" if up else "BEARISH", strike=k, expiry=exp, choch_time=int(b.t[x["choch"]]))
        if cut and (te >= cut or ke >= kc):
            if not up: skipped.append(dict(base, position="SHORT", opt_type="", instrument=f"{k} straddle", entry_time=te, why="entry at or after the square-off time"))
            continue
        if not up:
            for right, _, _ in legs:
                if right not in held: held[right] = (ke, x)
            continue
        k0 = max(ke - n, 0); ce, ia = legs[0][1], legs[0][2]; pe, ib = legs[1][1], legs[1][2]
        rising = "CE" if float(ce.c[ia[ke]] - ce.c[ia[k0]]) >= float(pe.c[ib[ke]] - pe.c[ib[k0]]) else "PE"
        if rising in held and held[rising][0] < ke: close(rising, ke, "buy_signal")
    for right in list(held):
        if held[right][0] < kc or not cut: close(right, kc, "eod" if cut else "open", still=not cut)
        else: held.pop(right)


def _both_sides(ctx, S, eng, b, i_day, k, exp, chain, legs, trs, skipped):
    """One session of the both-sides book: short straddle on a bearish SETUP, the rising leg bought on a bullish one, each
    leg with its own target, the rest out at the straddle trade's own exit (see the module text)."""
    sq, lots, n, tgt = ctx["square_off"], ctx["position"]["lots"], S["lookback"], float(S["target_pts"])
    free = {"up": -1, "down": -1}                                    # per side: the time its last entry's legs are all closed
    for x in eng.trades():
        ke = x["entry"]
        if ke < i_day: continue
        te = int(b.t[ke]); up = x["dir"] == "up"; pos = "LONG" if up else "SHORT"
        cut = core.square_off_at(sq, te)
        base = dict(dir=x["dir"], signal="BULLISH" if up else "BEARISH", strike=k, expiry=exp, choch_time=int(b.t[x["choch"]]))
        if S.get("real") == "long" and not up: continue                 # the short straddle is imaginary
        if cut and te >= cut:
            skipped.append(dict(base, position=pos, opt_type="", instrument=f"{k} straddle", entry_time=te, why="entry at or after the square-off time")); continue
        if te <= free[x["dir"]]:
            skipped.append(dict(base, position=pos, opt_type="", instrument=f"{k} straddle", entry_time=te, why=f"one {pos.lower()} entry at a time: open until {core.tstr(free[x['dir']])}")); continue
        kx, why, still = x["exit"], x["exit_reason"], x["open"]
        if S.get("exit") == "target_only": kx, why, still = len(b) - 1, "open", True      # no stop, no CHoCH exit
        if cut and (b.t[kx] > cut or still):
            kc = int(np.searchsorted(b.t, cut, "right")) - 1
            if kc >= ke: kx, why, still = kc, "eod", False
        if up:
            k0 = max(ke - n, 0); (_, ce, ia), (_, pe, ib) = legs
            mine = [legs[0]] if float(ce.c[ia[ke]] - ce.c[ia[k0]]) >= float(pe.c[ib[ke]] - pe.c[ib[k0]]) else [legs[1]]
        else: mine = list(legs)
        last = te
        for right, os_, ix in mine:
            e = float(os_.c[ix[ke]]); lvl = e + tgt if up else e - tgt
            j0, j1 = int(ix[ke]) + 1, int(ix[kx])                       # the leg's own candles after the entry, before the exit candle
            hit = np.nonzero(os_.h[j0:j1] >= lvl)[0] if up else np.nonzero(os_.l[j0:j1] <= lvl)[0]
            if len(hit):
                j = j0 + int(hit[0]); o_ = float(os_.o[j])
                xpx = o_ if (o_ >= lvl if up else o_ <= lvl) else lvl
                kk = int(np.searchsorted(b.t, os_.t[j], "right")) - 1
                xt, xwhy, xopen, ux = int(os_.t[j]), "target 1", False, float(b.c[kk])
            else: xt, xpx, xwhy, xopen, ux = int(os_.t[ix[kx]]), float(os_.c[ix[kx]]), why, bool(still), float(b.c[kx])
            rec = dict(base, position=pos, opt_type=right, kind="OPT", instrument=chain.name(exp, k, right), entry_time=int(os_.t[ix[ke]]),
                       entry_px=e, exit_time=xt, exit_px=xpx, exit_reason=xwhy, open=xopen, sl=None, target=round(lvl, 2),
                       und_entry=float(b.c[ke]), und_exit=ux, stale=False, lots=lots, tranche="", label=f"{pos} {right}")
            core.excursion(os_, rec, up)
            trs.append(core.price_trade(ctx, rec)); last = max(last, xt)
        free[x["dir"]] = last


def _leg_structure(ctx, S, eng, b, i_day, d, d_from, k, exp, chain, legs, trs, skipped):
    """One session: the straddle chart's bullish SETUPs arm the rising leg; the armed option's own Foundation SETUPs trade."""
    spec, sq, lots, n = ctx["spec"], ctx["square_off"], ctx["position"]["lots"], S["lookback"]
    (_, ce, ia), (_, pe, ib) = legs
    arms = {"CE": [], "PE": []}                                       # per leg: (armed after this time, until this time)
    for x in eng.trades():
        ke = x["entry"]
        if ke < i_day or (x["dir"] != "up" and S.get("arm") != "both"): continue
        right = "CE" if float(ce.c[ia[ke]] - ce.c[ia[max(ke - n, 0)]]) >= float(pe.c[ib[ke]] - pe.c[ib[max(ke - n, 0)]]) else "PE"
        until = int(b.t[x["exit"]]) if S["window"] == "scenario" and not x["open"] else int(b.t[-1]) + DAY
        arms[right].append((int(b.t[ke]), until, x["dir"]))
    for right, os_, _ in legs:
        if not arms[right]: continue
        a0, a1 = int(np.searchsorted(os_.day, d_from)), int(np.searchsorted(os_.day, d, "right"))
        ob = core.Bars(os_.t[a0:a1], os_.o[a0:a1], os_.h[a0:a1], os_.l[a0:a1], os_.c[a0:a1], os_.v[a0:a1])
        if S.get("gap_restart"): ob = cut_bars(ob, gap_start(ob, d))
        oe = core.foundation(ob, spec["rules"]); o_day = int(np.searchsorted(ob.day, d)); free_at = -1
        if S.get("entry") == "signal":
            _at_signal(ctx, S, oe, ob, os_, b, arms[right], right, k, exp, chain.name(exp, k, right), trs, skipped); continue
        for x in oe.trades():
            ke = x["entry"]
            if ke < o_day: continue
            te = int(ob.t[ke]); up = x["dir"] == "up"
            if not up and S["sides"] != "both": continue
            arm = next((a_ for a_ in arms[right] if a_[0] < te <= a_[1]), None)
            if arm is None: continue                                  # the straddle chart has not called this leg (yet / any more)
            pos = "LONG" if up else "SHORT"; cut = core.square_off_at(sq, te)
            base = dict(dir=x["dir"], signal="BULLISH" if up else "BEARISH", strike=k, expiry=exp, choch_time=int(ob.t[x["choch"]]),
                        armed_at=core.tstr(arm[0]))
            name = chain.name(exp, k, right)
            if cut and te >= cut:
                skipped.append(dict(base, position=pos, opt_type=right, instrument=name, entry_time=te, why="entry at or after the square-off time")); continue
            if te <= free_at:
                skipped.append(dict(base, position=pos, opt_type=right, instrument=name, entry_time=te, why=f"one trade a leg at a time: open until {core.tstr(free_at)}")); continue
            kx, why, still, xpx = x["exit"], x["exit_reason"], x["open"], x["exit_px"]
            if cut and (ob.t[kx] > cut or still):
                kc = int(np.searchsorted(ob.t, cut, "right")) - 1
                if kc >= ke: kx, why, still, xpx = kc, "eod", False, float(ob.c[kc])
            sl_last, moves = x["sl"], 0
            if S.get("trail") and x["sl"] is not None:
                kx, why, still, xpx, sl_last, moves = _trail(S["trail"], oe, ob, ke, kx, why, still, xpx, x["sl"], up)
            free_at = int(ob.t[kx])
            u = lambda t_: float(b.c[max(int(np.searchsorted(b.t, t_, "right")) - 1, 0)])       # the straddle's close then (for its chart)
            rec = dict(base, position=pos, opt_type=right, kind="OPT", instrument=name, entry_time=te, entry_px=float(ob.c[ke]),
                       exit_time=int(ob.t[kx]), exit_px=float(xpx), exit_reason=why, open=bool(still), sl=x["sl"],
                       **({"sl_last": round(float(sl_last), 2), "sl_moves": moves} if S.get("trail") else {}), und_entry=u(te), und_exit=u(int(ob.t[kx])), stale=False, lots=lots, tranche="", label=f"{pos} {right}")
            core.excursion(os_, rec, up)
            trs.append(core.price_trade(ctx, rec))


def _at_signal(ctx, S, oe, ob, os_, b, arms, right, k, exp, name, trs, skipped):
    """One leg of one session, bought at the straddle signals' own candles (see `entry` in the module text)."""
    sq, lots = ctx["square_off"], ctx["position"]["lots"]; free_at = -1
    for t_arm, _, sdir in arms:
        ke = int(np.searchsorted(ob.t, t_arm))
        if ke >= len(ob) or ob.t[ke] != t_arm: continue
        e = float(ob.c[ke]); cut = core.square_off_at(sq, t_arm)
        base = dict(dir="up", signal="BULLISH" if sdir == "up" else "BEARISH", strike=k, expiry=exp, choch_time=t_arm, straddle_signal=sdir)
        skip = lambda why: skipped.append(dict(base, position="LONG", opt_type=right, instrument=name, entry_time=t_arm, why=why))
        if cut and t_arm >= cut: skip("entry at or after the square-off time"); continue
        if t_arm <= free_at: skip(f"one trade a leg at a time: open until {core.tstr(free_at)}"); continue
        if (S.get("stop") or {}).get("rule") == "fixed":
            sl = round(e - float(S["stop"]["pts"]), 2)
            if sl <= 0: skip(f"the premium is not above the {S['stop']['pts']} point stop"); continue
        elif (S.get("stop") or {}).get("rule") == "prev_choch":
            m = np.nonzero((oe.ek == 1) & (oe.ei <= ke))[0]                   # the option's CHoCH candles so far
            if not len(m): skip("the option has no CHoCH before the entry: no stop"); continue
            sl = round(float(ob.l[int(oe.ei[m[-1]])]) * (1 - float(S["stop"]["buffer_pct"]) / 100), 2)
            if sl >= e: skip("the previous CHoCH's low less the buffer is not below the entry: no stop"); continue
        else:
            m = np.nonzero((oe.sk == -1) & (oe.sc <= ke) & (oe.sp < e))[0]  # the option's confirmed swing lows below the entry
            if not len(m): skip("the option has no confirmed swing low below the entry: no stop"); continue
            sl = float(oe.sp[m[-1]])
        nx = np.nonzero((oe.ek == 1) & (oe.ed == -1) & (oe.ei > ke))[0]      # the option's next bearish CHoCH
        if len(nx): kx = int(oe.ei[nx[0]]); why, still = "next_choch", False
        else: kx, why, still = len(ob) - 1, "open", True
        if cut and (ob.t[kx] > cut or still):
            kc = int(np.searchsorted(ob.t, cut, "right")) - 1
            if kc >= ke: kx, why, still = kc, "eod", False
        u = lambda t_: float(b.c[max(int(np.searchsorted(b.t, t_, "right")) - 1, 0)])
        two = S.get("two_lots")
        plans = ([("T1", dict(target=e + float(two["target_pts"]))), ("TRAIL", dict(mode=S.get("trail") or "none", unlock=e + float(two["trail_after_pts"])))]
                 if two else [("", dict(mode=S.get("trail") or "none"))])
        for tranche, kw in plans:
            kx2, why2, still2, xpx, sl_last, moves = _walk(oe, ob, ke, kx, why, still, float(ob.c[kx]), sl, **kw)
            free_at = max(free_at, int(ob.t[kx2]))
            rec = dict(base, position="LONG", opt_type=right, kind="OPT", instrument=name, entry_time=t_arm, entry_px=e, exit_time=int(ob.t[kx2]),
                       exit_px=float(xpx), exit_reason=why2, open=bool(still2), sl=sl, sl_last=round(float(sl_last), 2), sl_moves=moves,
                       und_entry=u(t_arm), und_exit=u(int(ob.t[kx2])), stale=False, lots=lots, tranche=tranche,
                       label=f"LONG {right}" + (f" {tranche}" if tranche else ""))
            core.excursion(os_, rec, True)
            trs.append(core.price_trade(ctx, rec))


def _walk(oe, ob, ke, kx, why, still, xpx, sl, mode="none", unlock=None, target=None):
    """A long re-walked candle by candle from the entry to its structure exit (candle kx). Each candle: the stop first
    (filled at the stop, or the open when it opens below); then the target (filled at the target, or the open when it opens
    above); then the stop may move for the next candle: to the level of the latest bullish BOS since the entry - held
    back until the option has traded at `unlock` when that is given. Returns (exit candle, reason, open, exit price, the
    last stop, how many times it moved)."""
    ev = {}
    for j in range(len(oe.ei)):
        i = int(oe.ei[j])
        if mode == "none" or oe.ek[j] != 0 or oe.ed[j] != 1 or i <= ke or i > kx: continue
        m = np.nonzero((oe.sk == 1) & (oe.sc < i))[0] if mode == "bos_level" else np.nonzero((oe.sk == -1) & (oe.sc <= i))[0]
        if len(m): ev[i] = float(oe.sp[m[-1]])
    moves, want, free = 0, None, unlock is None
    for i in range(ke + 1, kx + 1):
        o_, h_, l_ = float(ob.o[i]), float(ob.h[i]), float(ob.l[i])
        if l_ <= sl: return i, ("trail_stop" if moves else "stop_loss"), False, min(o_, sl), sl, moves
        if target is not None and h_ >= target: return i, "target 1", False, max(o_, target), sl, moves
        if not free and h_ >= unlock: free = True
        if i in ev: want = ev[i] if want is None else max(want, ev[i])
        if free and want is not None and want > sl: sl = want; moves += 1
    return kx, why, still, xpx, sl, moves


def _trail(mode, oe, ob, ke, kx, why, still, xpx, sl, up):
    """The trade re-walked candle by candle with the stop following the BOS in its direction (see `trail` in the module
    text). Returns (exit candle, reason, open, exit price, the last stop, how many times it moved)."""
    sg = 1 if up else -1
    ev = {}                                                          # candle -> the stop a BOS at that candle asks for
    for j in range(len(oe.ei)):
        i = int(oe.ei[j])
        if mode == "none" or oe.ek[j] != 0 or oe.ed[j] != sg or i <= ke or i > kx: continue
        kind = sg if mode == "bos_level" else -sg                    # the swing broken, or the swing behind the move
        m = np.nonzero((oe.sk == kind) & (oe.sc < i if mode == "bos_level" else oe.sc <= i))[0]
        if len(m): ev[i] = float(oe.sp[m[-1]])
    moves = 0
    for i in range(ke + 1, kx + 1):
        o_, h_, l_ = float(ob.o[i]), float(ob.h[i]), float(ob.l[i])
        if (l_ <= sl) if up else (h_ >= sl):
            px = (min(o_, sl) if up else max(o_, sl))
            return i, ("trail_stop" if moves else "stop_loss"), False, px, sl, moves
        if i in ev and ((ev[i] > sl) if up else (ev[i] < sl)): sl = ev[i]; moves += 1
    return kx, why, still, xpx, sl, moves


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
        g = gap_start(b, d) if spec["straddle"].get("gap_restart") else 0
        if g: b, ia, ib = cut_bars(b, g), ia[g:], ib[g:]
        eng = core.foundation(b, spec["rules"]); i0 = int(np.searchsorted(b.day, d)); i1 = len(b) - 1
        if i0 > i1: continue
        candles += core._chart_bars(b, i0, i1)
        o_ = core._overlays(b, eng, i0, i1, pair=True)
        if ov is None: ov = {k2: list(o_.get(k2) or []) for k2 in LISTS}
        else:
            for k2 in LISTS: ov[k2] += list(o_.get(k2) or [])
        legs.append(dict(day=core.dstr(d), strike=k, expiry=exp, index_open=idx_open, gap_restart=bool(g)))
        if spec["straddle"]["mode"] in ("managed_short", "both_sides", "leg_structure"):   # each leg leaves on its own: one row a leg
            for r0 in body["trades"]:
                if core.dnum(str(r0[C["entry_time"]])[:10]) != d: continue
                r = list(r0); r[C["entry_px"]] = r0[C["und_entry"]]; r[C["exit_px"]] = r0[C["und_exit"]]; r[C["sl"]] = None            # a stop on the option's own chart is not a level of this one
                rows.append(r)
            continue
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
