"""Jilly's ORB + Noise Band as a CONFIRMATION, then market structure for the trades (family module for ST114 - ST118).

Built 2026-10-25 at the user's word: "extend the strategy: apply CHoCH / BOS plain for entry and exits, and after the base
strategy's confirmation apply Strategy 1 or 2 or 3", then "even check reversals in CHoCH / BOS, not just in the direction of
Jilly ORB + noise band".

  confirmation  Strategy 111's signal (jilly.py, the paper spec with the sigma filter) on the near-month future: its side and
                its signal minute. Its own entry and exits are NOT traded - it only arms the day. No signal: no trades.
  structure     the Foundation engine (core.foundation) on the future's candles of the day and the `warm` sessions before it,
                with `rules` (Strategy 1's: touch; Strategy 2's on 5-minute candles; Strategy 3's: a CHoCH needs a close).
  mode "plain"  (ST114 / ST115) every CHoCH or BOS after the signal minute is an entry in its direction, at the next candle's
                open; out at the next CHoCH against it (the next candle's open), or at the stop - BUILD: the last confirmed
                swing beyond the entry (Strategy 1's "previous swing"), touched -> filled at the stop, or the open when it
                opens through it - or flat at `flatten`. One position at a time; after an exit the next event can enter.
  mode "setup"  (ST116 - ST118) the engine's SETUP trades (Strategy 1 / 2 / 3: the AVWAP-pair setup after a CHoCH; its stop
                and its next-CHoCH exit) whose entry candle is after the signal minute; cut at `flatten`; one at a time.
  sides         "jilly": only trades in the confirmation's direction; "both": reversals too (the user's second request).
  instruments   the future (FUT), and an ATM weekly option bought on the same entries and exits (CE for a long, PE for a
                short; ATM = round(spot at the entry minute / 50) x 50; the nearest weekly on or after today; bought at the
                entry minute's open, sold at the exit minute's open - the first option candle at or after each). Costs and
                data as jilly.py (the store to 2026-10-23; options from 2020-02).
"""
import datetime as Dt
import numpy as np
import core
import store_reader

ENTRY_RULES = ("jilly_ext_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
OWN_COVERAGE = True
REFUSED_WHY = "the Jilly extensions read the near-month future; Futures and Options (via futures) run"
DAY = core.DAY
_J = core.family("jilly")
BASE = dict(filter=True, band_k=1.25, sigma_lb=20, rank_lb=250, rank_min=120, rank_cut=0.2, or_keys=15, atr_n=9, atr_buf=0.3,
            ck_first=30, ck_last=285, ck_step=15, flatten="15:20", opt_from="2020-02-01", stop_atr=10, target_r=1, opt_stop="orm", target_r_opt=2)


def _bars(f, a, z, minutes):
    """core.Bars of f[a:z] at `minutes` (09:15-aligned), and per candle the index of its first 1-minute bar."""
    if minutes == 1:
        return core.Bars(f.t[a:z], f.o[a:z], f.h[a:z], f.l[a:z], f.c[a:z], f.v[a:z]), np.arange(a, z)
    t = f.t[a:z]; tod = t % DAY; b = t - tod + (555 + ((tod // 60 - 555) // minutes) * minutes) * 60
    cut = np.concatenate([[0], np.nonzero(np.diff(b))[0] + 1, [len(t)]]); q0, q1 = cut[:-1], cut[1:] - 1
    B = core.Bars(b[q0], f.o[a:z][q0], np.maximum.reduceat(f.h[a:z], q0), np.minimum.reduceat(f.l[a:z], q0), f.c[a:z][q1], np.add.reduceat(f.v[a:z], q0))
    return B, a + q0


def trades_of(X):
    """[(day, side, entry 1-minute index, exit 1-minute index, exit price, why, stop, label, fill, option entry index, option
    exit index)] over every confirmed day. The option is traded only on minutes AFTER the futures decision is known: bought
    at the open of the first minute after the candle that triggered the entry, sold at the open of the first minute after
    the candle that touched the stop or made the exit CHoCH (the flatten: its own open)."""
    f, keyv, E = _J.engine(BASE)
    flat_key = (core.hhmm_sec(BASE["flatten"]) - 555 * 60) // 60 + 1
    out = []
    for n, r in enumerate(E):
        if r["signal"] is None: continue
        a0 = E[max(0, n - X["warm"])]["a"]; a, z = r["a"], r["z"]
        B, first = _bars(f, a0, z, X["minutes"])
        eng = core.foundation(B, X["rules"])
        sig_t = int(f.t[r["i"]])                                     # the confirmation: the signal candle's minute
        mins = X["minutes"] * 60
        after = lambda i: int(B.t[i]) + mins - 60 > sig_t          # a candle that closes after the signal candle closed
        flat_t = int(f.t[a]) - int(f.t[a]) % DAY + core.hhmm_sec(BASE["flatten"])
        first_today = int(np.searchsorted(B.t, int(f.t[a])))
        ok_side = lambda s: X["sides"] == "both" or s == r["signal"]
        busy = -1
        mn = X["minutes"]; zz = z - 1
        after_c = lambda q: min(int(first[q]) + mn, zz)              # the first minute after candle q
        if X["mode"] == "plain":
            ev = [(int(eng.ei[j]), int(eng.ek[j]), int(eng.ed[j])) for j in range(len(eng.ei))]
            for i, k, d in ev:
                if i < first_today or i <= busy or not after(i) or not ok_side(d): continue
                e = i + 1
                if e >= len(B) or int(B.t[e]) >= flat_t: continue
                fill = float(B.o[e])
                m = np.nonzero((eng.sk == -d) & (eng.sc <= i) & ((eng.sp < fill) if d > 0 else (eng.sp > fill)))[0]
                stop = float(eng.sp[m[-1]]) if len(m) else None
                xi, why, xp = None, None, None
                nxt = [q for q, kk, dd in ev if q > i and kk == 1 and dd == -d]
                for q in range(e, len(B)):
                    if int(B.t[q]) >= flat_t: xi, why, xp = q, "eod", float(B.o[q]); break
                    if stop is not None and ((B.l[q] <= stop) if d > 0 else (B.h[q] >= stop)):
                        xi, why, xp = q, "stop_loss", (min(float(B.o[q]), stop) if d > 0 else max(float(B.o[q]), stop)); break
                    if nxt and q == nxt[0]:
                        if q + 1 < len(B): xi, why, xp = q + 1, "next_choch", float(B.o[q + 1])
                        else: xi, why, xp = q, "next_choch", float(B.c[q])
                        break
                if xi is None: xi, why, xp = len(B) - 1, "eod", float(B.c[-1])
                oxi = after_c(xi) if why == "stop_loss" else int(first[xi])   # a stop touched inside candle xi: the minute after it
                out.append((r["day"], d, int(first[e]), int(first[xi]), xp, why, stop, f"{'BOS' if k == 0 else 'CHoCH'} {'up' if d > 0 else 'down'}", fill,
                            int(first[e]), oxi))
                busy = xi
        else:
            for x in eng.trades():
                e = x["entry"]; d = 1 if x["dir"] == "up" else -1
                if e < first_today or e <= busy or not after(e) or not ok_side(d): continue
                if int(B.t[e]) >= flat_t: continue
                xi, why, xp = x["exit"], x["exit_reason"], x["exit_px"]
                if int(B.t[xi]) > flat_t or x["open"]:
                    q = int(np.searchsorted(B.t, flat_t))
                    if q < len(B) and q >= e: xi, why, xp = q, "eod", float(B.o[q])
                    else: xi, why, xp = len(B) - 1, "eod", float(B.c[-1])
                fill = float(B.c[e])                                  # the engine's SETUP fills at its entry candle's close
                oxi = int(first[xi]) if why == "eod" else after_c(xi)   # the engine's stop / CHoCH exit is known at candle xi's end
                out.append((r["day"], d, int(first[e]) + mn - 1, int(first[xi]), float(xp), why, x["sl"], f"SETUP {'up' if d > 0 else 'down'}", fill,
                            after_c(e), oxi))
                busy = xi
    return f, out


def run(ctx):
    spec = ctx["spec"]; X = spec["jext"]; typ = ctx["type"]; lots = ctx["position"]["lots"]
    f, T = trades_of(X)
    d0, d1 = ctx["date_from"], ctx["date_to"]
    if typ != "FUT": d0 = max(d0, BASE["opt_from"])
    sp = _J._store_bars("index")
    exps = sorted(e["expiry"] for e in store_reader.expiries()) if typ != "FUT" else []
    res = {}
    for ch in core.choice_keys(spec, typ):
        trs, skipped = [], []
        for day, d, ei, xi, xp, why, stop, lab, fill, oei, oxi in T:
            if not (d0 <= day <= d1): continue
            pos = "LONG" if d > 0 else "SHORT"
            base = dict(dir="up" if d > 0 else "down", signal="BULLISH" if d > 0 else "BEARISH", choch_time=int(f.t[ei]), und_entry=fill, und_exit=xp,
                        stale=False, lots=lots, tranche="", sl=stop, open=False, exit_reason=why)
            if typ == "FUT":
                rec = dict(base, position=pos, opt_type="FUT", kind="FUT", instrument=f"NIFTY FUT {f.extra['expiry'][ei]}", strike=0, expiry=str(f.extra["expiry"][ei]),
                           entry_time=int(f.t[ei]), entry_px=fill, exit_time=int(f.t[xi]), exit_px=xp, label=f"{pos} FUT · {lab}")
                trs.append(_J._price(ctx, rec, "FUT")); continue
            si = int(np.searchsorted(sp.t, f.t[oei]))
            if si >= len(sp) or abs(int(sp.t[si]) - int(f.t[oei])) > 120: continue
            atm = int(round(float(sp.o[si]) / 50) * 50); right = "CE" if d > 0 else "PE"
            ex = next((e for e in exps if e >= day), None)
            if not ex: continue
            oc = store_reader.option_candles(ex, atm, right, day, day, "minute")
            ot = np.array([x[0] for x in oc], dtype=np.int64)
            ie = int(np.searchsorted(ot, int(f.t[oei]))) if len(ot) else 0
            if ie >= len(ot) or ot[ie] - int(f.t[oei]) > 300:
                skipped.append(dict(base, position="LONG", opt_type=right, instrument="", entry_time=int(f.t[ei]), why="no option candle at the entry minute")); continue
            ix = int(np.searchsorted(ot, int(f.t[oxi])))
            opx = float(oc[ix][1]) if ix < len(ot) else float(oc[-1][4])
            name = f"NIFTY {Dt.date.fromisoformat(ex):%d%b%y} {atm} {right}".upper()
            rec = dict(base, position="LONG", opt_type=right, kind="OPT", instrument=name, strike=atm, expiry=ex, entry_time=int(ot[ie]), entry_px=float(oc[ie][1]),
                       exit_time=int(ot[ix]) if ix < len(ot) else int(ot[-1]), exit_px=opx, label=f"LONG {right} · {lab}")
            trs.append(_J._price(ctx, rec, "OPT"))
        trs.sort(key=lambda x: x["entry_time"])
        res[ch] = dict(trades=trs, skipped=skipped, signals=[])
    return res


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """Strategy 111's chart (the future with the band, the opening range and VWAP) with these trades on it."""
    return _J.chart_main(dict(ctx, spec=dict(ctx["spec"], jilly=BASE)), body, day, to)
