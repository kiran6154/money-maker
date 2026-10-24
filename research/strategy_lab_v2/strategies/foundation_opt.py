"""Strategy 1's Foundation rules applied directly to an option's own 1-minute candles (family module for ST94).

Built 2026-10-25 at the user's word: "extend Foundation 1, apply it on options directly; see how many of the buys are
losses when taken inside the previous day's range". The build choices (all in SPEC["fopt"]):

  instrument  each session, the day-open ATM CE and PE (the index's 09:15 open rounded to the strike step), nearest weekly
              expiry at least `expiry_min_days` out; each leg its own chart. Prices: the download store (store_reader.py).
  structure   the Foundation engine with the strategy's `rules` (Strategy 1's: touch, stop at the previous swing, exit at
              the stop or the next CHoCH) on the leg's candles, warmed up on the `warmup_days` sessions before; only SETUPs
              whose entry candle is in the session are trades, one trade a leg at a time, flat at the square-off.
  sides       "long": the bullish SETUPs (buy the option); "both": the bearish ones sell it too.
  fills       the entry at the SETUP candle's close, the exit at the engine's price (the stop level, or the CHoCH candle's
              close), the square-off at that candle's close - as the straddle family's leg_structure.
  range tag   each trade carries the same contract's previous-session high and low and where the entry premium sits:
              "inside" (between them), "above" the high or "below" the low (`pd_range`); no candles the session before:
              "no_prev". The tag is recorded, never acted on - the question is how the buys inside the range fare.
"""
import numpy as np
import core

ENTRY_RULES = ("foundation_opt_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT", "INDEX")
OWN_COVERAGE = True
REFUSED_WHY = "Strategy 94 reads the Foundation rules on the day-open ATM options' own candles; only the Options (via futures) type runs"
_P = core.family("pdl_short")


def _legs(ctx, d):
    """pdl_short's legs of session d with the previous-session HIGH added: [(right, name, exp, k, Bars, o_day, pdl, pdh)]."""
    legs = _P._legs(dict(ctx, spec=dict(ctx["spec"], pdl=ctx["spec"]["fopt"])), d)
    if isinstance(legs, str): return legs
    out = []
    for right, name, exp, k, ob, o_day, pdl in legs:
        pdh = None
        if ob is not None and o_day > 0:
            j0 = int(np.searchsorted(ob.day, ob.day[o_day - 1])); pdh = float(ob.h[j0:o_day].max())
        out.append((right, name, exp, k, ob, o_day, pdl, pdh))
    return out


def run(ctx):
    spec = ctx["spec"]; S = spec["fopt"]; sq = ctx["square_off"]; lots = ctx["position"]["lots"]
    ss = core.sessions(); days = ss[(ss >= core.dnum(ctx["date_from"])) & (ss <= core.dnum(ctx["date_to"]))]
    trs, skipped = [], []
    for d in days:
        d = int(d); legs = _legs(ctx, d)
        if isinstance(legs, str): continue
        for right, name, exp, k, ob, o_day, pdl, pdh in legs:
            if ob is None or o_day < 0: skipped.append(dict(signal="", position="", opt_type=right, instrument=name, strike=k, expiry=exp, entry_time=core.dstr(d), why="no candles for that contract on that day in the store")); continue
            oe = core.foundation(ob, spec["rules"]); free_at = -1
            for x in oe.trades():
                ke = x["entry"]
                if ke < o_day or ob.day[ke] != d: continue
                up = x["dir"] == "up"
                if not up and S["sides"] != "both": continue
                te = int(ob.t[ke]); pos = "LONG" if up else "SHORT"; cut = core.square_off_at(sq, te)
                base = dict(dir=x["dir"], signal="BULLISH" if up else "BEARISH", strike=k, expiry=exp, choch_time=int(ob.t[x["choch"]]))
                if cut and te >= cut: skipped.append(dict(base, position=pos, opt_type=right, instrument=name, entry_time=te, why="entry at or after the square-off time")); continue
                if te <= free_at: skipped.append(dict(base, position=pos, opt_type=right, instrument=name, entry_time=te, why=f"one trade a leg at a time: open until {core.tstr(free_at)}")); continue
                kx, why, still, xpx = x["exit"], x["exit_reason"], x["open"], x["exit_px"]
                if cut and (ob.t[kx] > cut or still):
                    kc = int(np.searchsorted(ob.t, cut, "right")) - 1
                    if kc >= ke: kx, why, still, xpx = kc, "eod", False, float(ob.c[kc])
                free_at = int(ob.t[kx]); e = float(ob.c[ke])
                tag = "no_prev" if pdl is None else "inside" if pdl <= e <= pdh else "above" if e > pdh else "below"
                rec = dict(base, position=pos, opt_type=right, kind="OPT", instrument=name, entry_time=te, entry_px=e, exit_time=int(ob.t[kx]),
                           exit_px=float(xpx), exit_reason=why, open=bool(still), sl=x["sl"], und_entry=e, und_exit=float(xpx), stale=False,
                           lots=lots, tranche="", label=f"{pos} {right} · {tag}", pd_range=tag, prev_high=pdh, prev_low=pdl)
                core.excursion(ob, rec, up)
                trs.append(core.price_trade(ctx, rec))
    trs.sort(key=lambda r: r["entry_time"])
    return {ch: dict(trades=trs, skipped=skipped, signals=[]) for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL")}


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """The leg's own 1-minute candles (the leg with a trade that day, else the CE) with the engine's layers, the
    previous-session high and low as lines, and that leg's trades."""
    spec = ctx["spec"]; C = {k: i for i, k in enumerate(body["cols"])}
    ss = core.sessions(); days = ss[(ss >= core.dnum(day)) & (ss <= core.dnum(to))]
    candles, rows, ov, lines, legs_out = [], [], None, [[], []], []
    LISTS = ("cand", "swings", "events", "flips", "prot", "setups", "pair", "tav", "trig")
    for d in days:
        d = int(d); legs = _legs(ctx, d)
        if isinstance(legs, str): legs_out.append(dict(day=core.dstr(d), why=legs)); continue
        mine = [r for r in body["trades"] if core.dnum(str(r[C["entry_time"]])[:10]) == d]
        want = mine[0][C["opt_type"]] if mine else "CE"
        leg = next((x for x in legs if x[0] == want and x[4] is not None and x[5] >= 0), None) or next((x for x in legs if x[4] is not None and x[5] >= 0), None)
        if leg is None: legs_out.append(dict(day=core.dstr(d), why="no candles for the day-open ATM options in the store")); continue
        right, name, exp, k, ob, o_day, pdl, pdh = leg
        eng = core.foundation(ob, spec["rules"]); i0, i1 = o_day, int(np.searchsorted(ob.day, d, "right")) - 1
        candles += core._chart_bars(ob, i0, i1)
        o_ = core._overlays(ob, eng, i0, i1, pair=True)
        if ov is None: ov = {k2: list(o_.get(k2) or []) for k2 in LISTS}
        else:
            for k2 in LISTS: ov[k2] += list(o_.get(k2) or [])
        if pdl is not None:
            lines[0] += [[int(ob.t[q]), round(pdh, 2)] for q in range(i0, i1 + 1)]
            lines[1] += [[int(ob.t[q]), round(pdl, 2)] for q in range(i0, i1 + 1)]
        rows += [list(r) for r in mine if r[C["instrument"]] == name]
        legs_out.append(dict(day=core.dstr(d), instrument=name, strike=k, expiry=exp, prev_high=pdh, prev_low=pdl))
    if not candles: raise ValueError(f"no day-open ATM option candles from {day}" + (f": {legs_out[0].get('why')}" if legs_out else ""))
    out = dict(day=day, to=to, inst=None, candles=candles, cols=body["cols"], trades=rows, own=True, sessions=len([g for g in legs_out if g.get("strike")]),
               derived=dict(what="the day-open ATM option's own candles (the leg with a trade that day, else the CE); the lines are its previous-session high and low", legs=legs_out))
    out.update(ov or {}); out["lines"] = [l for l in lines if l]
    return out
