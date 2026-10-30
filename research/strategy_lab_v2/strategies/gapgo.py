"""NIFTY gap-and-go -> Williams chain (OptionsBuyer.in's description, research only) - family module for ST124.

Built 2026-10-26 from the user's pasted spec. Index = the NIFTY spot (the download store, 1-minute); options = the store's 1-minute
weekly options. Every rule is the spec's; BUILD marks a choice it leaves open.

1. Gap-and-go (10% opening-range breakout)
   OR      the highest / lowest 1-minute CLOSE from 09:15 to 09:45 (31 bars); W = OR high - OR low.
   bands   up = ORH + `band` x W, down = ORL - `band` x W (band 0.10).
   gap     the 09:15 price (BUILD: the 09:15 candle's open) against the previous session's 15:15 close (the 15:15 candle's
           close). Gap up: only the upside break counts; gap down: only the downside break (a zero gap: no direction, the day
           is "no_break" - BUILD).
   checks  1-minute closes from 09:46 to 12:00 (`gng_end`).
   stands down  "opposite_first": the opposite band breaks first; "filled": at the break, the index has already touched the
           previous 15:15 close earlier in the day (BUILD: a 1-minute high / low through it on a bar before the break);
           "no_break": nothing by 12:00.
   entry   the next 1-minute bar: buy the 150-point in-the-money weekly option (CE on an upside break, PE downside).
2. Williams (back-up) - only after "opposite_first" or "filled", and only when |gap| < 0.2% or >= 0.5% of the previous close
   R       the previous session's highest minus lowest 1-minute close; levels = today's open +/- `wk` x R (0.5).
   trigger the first 1-minute close beyond either level, from the hand-over minute (the stand-down minute) to 14:29.
   entry   the next 1-minute bar, the 150-point ITM weekly option of that side.
3. Exits (both bots, on the option premium, checked on 1-minute closes, filled at the next bar's open)
   stop 70% of the entry premium; trail: once a close has been above 105% of entry, out when a close is at or below 80% of the
   highest close since entry (BUILD: "its highest point" read on closes, as the checks); flat at 15:15. One position a day.
Strike: ATM = round(spot at the signal minute's close / 50) x 50; CE strike ATM - 150, PE ATM + 150. Expiry: the nearest weekly
on or after today (BUILD: the same-day contract on expiry day). Costs: `slip_pct` of the premium a side (0.1%; the spec's stress
test adds 0.2%) plus option charges by date (jilly.py's schedule); lot 65.
"""
import datetime as Dt
import numpy as np
import core
import store_reader

ENTRY_RULES = ("gapgo_williams_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT", "INDEX")
OWN_COVERAGE = True
REFUSED_WHY = "the gap-and-go / Williams chain buys options from the index's levels; only the Options type runs"
DAY = core.DAY
_J = core.family("jilly")
HM = lambda s: core.hhmm_sec(s)


def _price(ctx, rec, slip):
    lot = ctx["lot_size"] * rec.setdefault("lots", 1)
    buy, sell = rec["entry_px"] * (1 + slip), rec["exit_px"] * (1 - slip)
    rec.update(pts=sell - buy, gross=(sell - buy) * lot, chg=_J._charges(core.tstr(rec["entry_time"])[:10], "OPT", buy, sell, lot))
    rec["net"] = rec["gross"] - rec["chg"]["total"]
    return rec


def signals_of(G):
    """[(day, bot, side, signal bar index, why_gng, gap, gap_pct)] - at most one per day."""
    sp = _J._store_bars("index"); t, o, h, l, c = sp.t, sp.o, sp.h, sp.l, sp.c
    tod = t % DAY
    cut = np.concatenate([[0], np.nonzero(np.diff(sp.day))[0] + 1, [len(t)]])
    S = [(int(a), int(z)) for a, z in zip(cut[:-1], cut[1:])]
    out, prev = [], None                                   # prev: (15:15 close, highest close, lowest close)
    for a, z in S:
        day = core.dstr(int(sp.day[a]))
        p15 = np.nonzero(tod[a:z] == HM("15:15"))[0]
        cur = (float(c[a + p15[0]]) if len(p15) else None, float(c[a:z].max()), float(c[a:z].min()))
        P = prev; prev = cur if cur[0] is not None else prev
        if P is None or tod[a] != HM("09:15"): continue
        pc, phc, plc = P
        orm = (tod[a:z] >= HM("09:15")) & (tod[a:z] <= HM("09:45"))
        if orm.sum() < 25: continue
        ORH, ORL = float(c[a:z][orm].max()), float(c[a:z][orm].min()); W = ORH - ORL
        up, dn = ORH + G["band"] * W, ORL - G["band"] * W
        O = float(o[a]); gap = O - pc; gpct = abs(gap) / pc * 100; d = 1 if gap > 0 else -1 if gap < 0 else 0
        why, i_sig, hand = "no_break", None, None
        for i in range(a, z):
            if tod[i] < HM("09:46"): continue
            if tod[i] > HM(G["gng_end"]): break
            bu, bd = c[i] > up, c[i] < dn
            if not (bu or bd): continue
            s = 1 if bu else -1
            if d == 0: why = "no_direction"; break
            if s != d: why, hand = "opposite_first", i; break
            touched = bool((l[a:i] <= pc).any()) if d > 0 else bool((h[a:i] >= pc).any())   # the gap already closed
            if touched: why, hand = "filled", i; break
            why, i_sig = "go", i; break
        if why == "go":
            out.append((day, "gap-and-go", d, i_sig, why, gap, gpct)); continue
        if why in ("opposite_first", "filled") and (gpct < 0.2 or gpct >= 0.5) and G.get("williams", True):
            R = phc - plc; wu, wd = O + G["wk"] * R, O - G["wk"] * R
            for i in range(hand, z):
                if tod[i] > HM(G["wk_end"]): break
                if c[i] > wu: out.append((day, "williams", 1, i, why, gap, gpct)); break
                if c[i] < wd: out.append((day, "williams", -1, i, why, gap, gpct)); break
    return sp, out


def run(ctx):
    spec = ctx["spec"]; G = spec["gapgo"]; lots = ctx["position"]["lots"]
    d0, d1 = ctx["date_from"], ctx["date_to"]
    sp, SIG = signals_of(G)
    exps = sorted(e["expiry"] for e in store_reader.expiries())
    res = {}
    for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL"):
        trs, skipped = [], []
        for day, bot, side, i, why, gap, gpct in SIG:
            if not (d0 <= day <= d1) or (G.get("bots", "both") != "both" and G["bots"] != bot): continue
            atm = int(round(float(sp.c[i]) / 50) * 50); right = "CE" if side > 0 else "PE"
            k = atm - G["itm"] if right == "CE" else atm + G["itm"]
            ex = next((e for e in exps if e >= day), None)
            base = dict(dir="up" if side > 0 else "down", signal="BULLISH" if side > 0 else "BEARISH", choch_time=int(sp.t[i]), strike=k, expiry=ex or "",
                        und_entry=float(sp.c[i]), stale=False, lots=lots, tranche="", sl=None, open=False)
            if not ex: continue
            oc = store_reader.option_candles(ex, k, right, day, day, "minute")
            if not oc:
                skipped.append(dict(base, position="LONG", opt_type=right, instrument="", entry_time=int(sp.t[i]), why="no candles for the ITM contract in the store")); continue
            ot = np.array([x[0] for x in oc], dtype=np.int64); O_, C_ = np.array([x[1] for x in oc]), np.array([x[4] for x in oc])
            te = int(sp.t[i]) + 60; ie = int(np.searchsorted(ot, te))
            if ie >= len(ot) or ot[ie] - te > 300:
                skipped.append(dict(base, position="LONG", opt_type=right, instrument="", entry_time=te, why="no option candle at the entry minute")); continue
            e = float(O_[ie]); hi, armed = e, False; flat = int(sp.t[i]) - int(sp.t[i]) % DAY + HM(G["flatten"])
            xq, xp, xw = len(ot) - 1, float(C_[-1]), "eod"
            for m in range(ie, len(ot)):
                if ot[m] >= flat: xq, xp, xw = m, float(O_[m]), "eod"; break
                cl = float(C_[m]); hi = max(hi, cl)
                if cl > G["arm"] * e: armed = True
                hit = "stop_loss" if cl <= G["stop"] * e else ("trail_stop" if armed and cl <= G["trail"] * hi else None)
                if hit:
                    xq, xp, xw = (m + 1, float(O_[m + 1]), hit) if m + 1 < len(ot) else (m, cl, hit); break
            name = f"NIFTY {Dt.date.fromisoformat(ex):%d%b%y} {k} {right}".upper()
            rec = dict(base, position="LONG", opt_type=right, kind="OPT", instrument=name, entry_time=int(ot[ie]), entry_px=e, exit_time=int(ot[xq]),
                       exit_px=xp, exit_reason=xw, und_exit=None, label=f"{bot} · BUY {right} · {why}", gap=round(gap, 2), gap_pct=round(gpct, 3))
            trs.append(_price(ctx, rec, G["slip_pct"] / 100))
        trs.sort(key=lambda x: x["entry_time"])
        res[ch] = dict(trades=trs, skipped=skipped, signals=[])
    return res


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])
