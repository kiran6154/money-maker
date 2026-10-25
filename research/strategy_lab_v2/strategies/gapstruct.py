"""Gap days read with market structure: does the price FOLLOW the gap or REVERSE it? (family module for ST125 - ST128).

Built 2026-10-26 at the user's word: "identify if it's gap days and whether price follows or reverses using CHoCH or BOS and
backtest" (after Strategy 124, the gap-and-go -> Williams chain). Research only.

  gap day    |09:15 open - the previous session's 15:15 close| >= `gap_min` % of that close (0.2%: the small-gap boundary of
             Strategy 124's spec). NIFTY spot, 1-minute bars from the store (jilly._store_bars("index")).
  structure  the Foundation engine (core.foundation, Strategy 1's rules: touch) on the index at `minutes` (1 or 5), over the day
             and the `warm` sessions before it. The day's FIRST CHoCH or BOS confirmed on a candle after the 09:15 candle and
             before `last_entry` classifies the day: a break the gap's way = "follow", the other way = "reverse".
  trade      one a day, in the break's direction (`take`: both / follow / reverse): the 150-point ITM weekly option (CE up, PE
             down; ATM = round(spot at the break candle's close / 50) x 50; the nearest weekly on or after the day), bought at
             the open of the first minute after the break candle closes.
  exits      `exit` "premium" (Strategy 124's): on the option's 1-minute closes, stop 70% of entry, once above 105% a trail at
             80% of the highest close, filled at the next open. `exit` "structure": the next CHoCH against the trade on the
             same index candles - sold at the first minute after that candle closes; no other stop. Both flat at 15:15.
  costs      `slip_pct` of the premium a side + option charges by date (jilly._charges); lot 65.
"""
import datetime as Dt
import numpy as np
import core
import store_reader

ENTRY_RULES = ("gap_structure_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT", "INDEX")
OWN_COVERAGE = True
REFUSED_WHY = "the gap-structure strategies buy options from the index's structure; only the Options type runs"
DAY = core.DAY
_J = core.family("jilly")
_X = core.family("jilly_ext")
HM = lambda s: core.hhmm_sec(s)
_SIG = {}


def signals_of(X):
    """[(day, side, decision time (the minute the option is bought), kind, follow/reverse, gap %, exit decision time or None)]."""
    key = (X["minutes"], X["warm"], X["gap_min"], X["last_entry"], X["exit"], str(sorted(X["rules"].items())))
    if key in _SIG: return _SIG[key]
    sp = _J._store_bars("index"); t = sp.t
    cut = np.concatenate([[0], np.nonzero(np.diff(sp.day))[0] + 1, [len(t)]])
    S = [(int(a), int(z)) for a, z in zip(cut[:-1], cut[1:])]
    mn = X["minutes"]; out = []
    for n in range(1, len(S)):
        a, z = S[n]; pa, pz = S[n - 1]
        if t[a] % DAY != HM("09:15"): continue
        p15 = np.nonzero(t[pa:pz] % DAY == HM("15:15"))[0]
        if not len(p15): continue
        pc = float(sp.c[pa + p15[0]]); gap = float(sp.o[a]) - pc; gp = gap / pc * 100
        if abs(gp) < X["gap_min"]: continue
        g = 1 if gap > 0 else -1
        a0 = S[max(0, n - X["warm"])][0]
        B, first = _X._bars(sp, a0, z, mn)
        eng = core.foundation(B, X["rules"])
        q0 = int(np.searchsorted(B.t, int(t[a])))                   # the day's first candle (09:15)
        d0 = int(t[a]) - int(t[a]) % DAY; last = d0 + HM(X["last_entry"]); flat = d0 + HM("15:15")
        ev = sorted((int(eng.ei[j]), int(eng.ek[j]), int(eng.ed[j])) for j in range(len(eng.ei)))
        hit = next(((i, k, d) for i, k, d in ev if i > q0 and int(B.t[i]) + mn * 60 <= last), None)
        if hit is None: continue
        i, k, d = hit
        te = int(B.t[i]) + mn * 60                                    # the break candle has closed: buy at this minute
        if te >= flat: continue
        xt = None
        if X["exit"] == "structure":
            q = next((q for q, kk, dd in ev if q > i and kk == 1 and dd == -d and int(B.t[q]) + mn * 60 < flat), None)
            xt = int(B.t[q]) + mn * 60 if q is not None else None
        ii = int(first[i]) + mn - 1                                  # the break candle's last 1-minute bar (its close = spot)
        out.append((core.dstr(int(sp.day[a])), d, te, "BOS" if k == 0 else "CHoCH", "follow" if d == g else "reverse", round(gp, 3), xt, float(sp.c[ii])))
    _SIG[key] = out
    return out


def _price(ctx, rec, slip):
    lot = ctx["lot_size"] * rec.setdefault("lots", 1)
    buy, sell = rec["entry_px"] * (1 + slip), rec["exit_px"] * (1 - slip)
    rec.update(pts=sell - buy, gross=(sell - buy) * lot, chg=_J._charges(core.tstr(rec["entry_time"])[:10], "OPT", buy, sell, lot))
    rec["net"] = rec["gross"] - rec["chg"]["total"]
    return rec


def run(ctx):
    spec = ctx["spec"]; X = spec["gapstruct"]; lots = ctx["position"]["lots"]
    d0, d1 = ctx["date_from"], ctx["date_to"]
    SIG = signals_of(X)
    exps = sorted(e["expiry"] for e in store_reader.expiries())
    res = {}
    for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL"):
        trs, skipped = [], []
        for day, side, te, kind, fr, gp, xt, spot in SIG:
            if not (d0 <= day <= d1) or (X["take"] != "both" and X["take"] != fr): continue
            atm = int(round(spot / 50) * 50); right = "CE" if side > 0 else "PE"
            k = atm - X["itm"] if right == "CE" else atm + X["itm"]
            ex = next((e for e in exps if e >= day), None)
            base = dict(dir="up" if side > 0 else "down", signal="BULLISH" if side > 0 else "BEARISH", choch_time=te - 60, strike=k, expiry=ex or "",
                        und_entry=spot, stale=False, lots=lots, tranche="", sl=None, open=False, position="LONG", opt_type=right)
            if not ex: continue
            oc = store_reader.option_candles(ex, k, right, day, day, "minute")
            if not oc:
                skipped.append(dict(base, instrument="", entry_time=te, why="no candles for the ITM contract in the store")); continue
            ot = np.array([x[0] for x in oc], dtype=np.int64); O_, C_ = np.array([x[1] for x in oc]), np.array([x[4] for x in oc])
            ie = int(np.searchsorted(ot, te))
            if ie >= len(ot) or ot[ie] - te > 300:
                skipped.append(dict(base, instrument="", entry_time=te, why="no option candle at the entry minute")); continue
            e = float(O_[ie]); flat = te - te % DAY + HM("15:15")
            xq, xp, xw = len(ot) - 1, float(C_[-1]), "eod"
            if X["exit"] == "structure":
                q = int(np.searchsorted(ot, xt if xt is not None else flat))
                if q < len(ot) and ot[q] < flat and xt is not None: xq, xp, xw = q, float(O_[q]), "next_choch"
                else:
                    q = int(np.searchsorted(ot, flat))
                    if q < len(ot): xq, xp = q, float(O_[q])
            else:
                hi, armed = e, False
                for m in range(ie, len(ot)):
                    if ot[m] >= flat: xq, xp, xw = m, float(O_[m]), "eod"; break
                    cl = float(C_[m]); hi = max(hi, cl)
                    if cl > X["arm"] * e: armed = True
                    hit = "stop_loss" if cl <= X["stop"] * e else ("trail_stop" if armed and cl <= X["trail"] * hi else None)
                    if hit:
                        xq, xp, xw = (m + 1, float(O_[m + 1]), hit) if m + 1 < len(ot) else (m, cl, hit); break
            name = f"NIFTY {Dt.date.fromisoformat(ex):%d%b%y} {k} {right}".upper()
            rec = dict(base, kind="OPT", instrument=name, entry_time=int(ot[ie]), entry_px=e, exit_time=int(ot[xq]), exit_px=xp, exit_reason=xw,
                       und_exit=None, label=f"gap {gp:+.2f}% · {kind} {'up' if side > 0 else 'down'} · {fr} · BUY {right}", gap_pct=gp, fr=fr, ev=kind)
            trs.append(_price(ctx, rec, X["slip_pct"] / 100))
        trs.sort(key=lambda x: x["entry_time"])
        res[ch] = dict(trades=trs, skipped=skipped, signals=[])
    return res


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])
