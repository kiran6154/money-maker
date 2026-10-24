"""ORR_V1's signals traded by SELLING options at the day's extreme (family module for ST85).

Derived from Strategy 83 (strategies/orr.py) at the user's request: "do it directly on options: the day's high or low will be
shorted, so that if price goes back to that place we are at a minimal loss; enter one, and if we get a signal on the other
side enter that as well and manage it; not more than one trade per side at a time".

  signals   ORR_V1's sweep / reclaim of the 09:15 candle's low (a LONG signal) or high (a SHORT signal), on the NIFTY index
            1-minute candles, on sessions whose 09:15 body is 60 - 90% of its range (SPEC["orr_opt"]["body_rule"]; false:
            every session, the 09:15 candle only sets the range). SPEC["orr_opt"]["align"]: true keeps
            ORR_V1's rule (only the 09:15 body's side); false lets both sides signal.
  trade     a LONG signal SELLS a PE, a SHORT signal SELLS a CE, at the open of the entry minute (the minute after the
            reclaim, as ORR_V1). The strike is the day's extreme so far: the PE at the day's low rounded DOWN to the strike
            step, the CE at the day's high rounded UP - if the index comes back to that level the option is only at the
            money. Nearest weekly expiry at least `expiry_min_days` out.
  exit      the index CLOSES beyond the strike (below the PE's, above the CE's): out at that minute's option close; else
            `target_pct` of the premium earned (when set); else flat at `cutoff` (that minute's option open).
  occupancy one position per side at a time (a PE and a CE can be open together); after an exit that side needs a fresh
            sweep and reclaim.
Option prices: the download store's 1-minute option candles (store_reader.py, read-only; September 2024 on).
"""
import numpy as np
import core
import store_reader

ENTRY_RULES = ("orr_opt_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT", "INDEX")
OWN_COVERAGE = True
REFUSED_WHY = "Strategy 85 sells options from the index's signals; only the Options (via futures) type runs"
_O = core.family("orr")


def _expiry(exps, day, min_days):
    d = core.dnum(day)
    for e in exps:
        if core.dnum(e) - d >= min_days: return e
    return None


_SER = {}


def _series(exp, strike, right, day):
    """{minute time: (open, high, low, close)} of one option contract on one day, from the store."""
    key = (exp, strike, right, day)
    if key not in _SER:
        c = store_reader.option_candles(exp, strike, right, day, day, "minute")
        while len(_SER) > 400: del _SER[next(iter(_SER))]
        _SER[key] = {int(x[0]): (x[1], x[2], x[3], x[4]) for x in c}
    return _SER[key]


def run(ctx):
    spec = ctx["spec"]; X = spec["orr"]; Y = spec["orr_opt"]; step = spec["options"]["strike_step"]
    sp = core.series("spot", "minute")
    d0, d1 = core.dnum(ctx["date_from"]), core.dnum(ctx["date_to"])
    a, z = int(np.searchsorted(sp.day, d0)), int(np.searchsorted(sp.day, d1, "right"))
    b = sp.slice(a, z); o, h, l, c, t = b.o, b.h, b.l, b.c, b.t
    exps = sorted(e["expiry"] for e in store_reader.expiries())
    lots = ctx["position"]["lots"]; trs, skipped = [], []
    for day_n, s0, s1 in _O.sessions_of(b):
        day = core.dstr(day_n)
        if not _O.complete(b, s0, s1): continue
        O_, H_, L_, C_ = (_O.paise(v[s0]) for v in (o, h, l, c)); rng, body = H_ - L_, abs(C_ - O_)
        if rng <= 0: continue
        if Y.get("body_rule", True) and (C_ == O_ or not (body * 100 >= rng * round(X["body_min"] * 100) and body * 100 < rng * round(X["body_max"] * 100))): continue
        if Y["align"] and C_ == O_: continue                 # a doji has no side to align to
        exp = _expiry(exps, day, Y["expiry_min_days"])
        if not exp: skipped.append(dict(signal="", position="", opt_type="", instrument="", entry_time=day, why="no option expiry in the store")); continue
        oh, ol = float(h[s0]), float(l[s0]); cut = t[s0] - t[s0] % core.DAY + core.hhmm_sec(X["cutoff"])
        sides = [1 if C_ > O_ else -1] if Y["align"] else [1, -1]
        for side in sides:                                # each side is its own machine: one position at a time
            i, swept = s0 + 1, False
            while i < s1 and t[i] < cut:
                if X.get("sweep") == "close": sweep = c[i] < ol if side > 0 else c[i] > oh     # a close beyond, not a wick
                else: sweep = l[i] < ol if side > 0 else h[i] > oh
                reclaim = c[i] > ol if side > 0 else c[i] < oh
                if sweep: swept = True
                if not (swept and reclaim): i += 1; continue
                e_i = i + 1
                if e_i >= s1 or t[e_i] != t[i] + 60 or t[e_i] >= cut: break
                right = "PE" if side > 0 else "CE"
                lo_, hi_ = float(l[s0:i + 1].min()), float(h[s0:i + 1].max())
                k = int(np.floor(lo_ / step) * step) if side > 0 else int(np.ceil(hi_ / step) * step)
                base = dict(dir="up" if side > 0 else "down", signal="BULLISH" if side > 0 else "BEARISH", strike=k, expiry=exp, choch_time=int(t[i]))
                ser = _series(exp, k, right, day); name = f"NIFTY {core.D.date.fromisoformat(exp):%d%b%y} {k} {right}".upper()
                if int(t[e_i]) not in ser:
                    skipped.append(dict(base, position="SHORT", opt_type=right, instrument=name, entry_time=int(t[e_i]), why="no option candle at the entry minute"))
                    i = e_i; swept = False; continue
                e_px = ser[int(t[e_i])][0]; tgt = e_px * (1 - Y["target_pct"] / 100) if Y.get("target_pct") else None
                x_i, x_px, why = None, None, None
                for m in range(e_i, s1):
                    q = ser.get(int(t[m]))
                    if t[m] >= cut:
                        x_i, why = m, "eod"; x_px = q[0] if q else None; break
                    if q is None: continue
                    if (c[m] < k) if side > 0 else (c[m] > k):          # the index back through the strike
                        x_i, x_px, why = m, q[3], "stop_loss"; break
                    if tgt is not None and q[2] <= tgt: x_i, x_px, why = m, max(tgt, 0.05), "target 1"; break
                if x_i is None or x_px is None:
                    last = max((m for m in range(e_i, s1) if int(t[m]) in ser and t[m] <= cut), default=e_i)
                    x_i, x_px, why = last, ser.get(int(t[last]), (e_px,) * 4)[3], "eod"
                rec = dict(base, position="SHORT", opt_type=right, kind="OPT", instrument=name, entry_time=int(t[e_i]), entry_px=float(e_px),
                           exit_time=int(t[x_i]), exit_px=float(x_px), exit_reason=why, open=False, sl=float(k), und_entry=float(o[e_i]),
                           und_exit=float(c[x_i]), stale=False, lots=lots, tranche="", label=f"SHORT {right}",
                           sweep_reclaim=core.tstr(t[i]), day_extreme=round(lo_ if side > 0 else hi_, 2))
                trs.append(core.price_trade(ctx, rec))
                i, swept = x_i + 1, False
    trs.sort(key=lambda r: r["entry_time"])
    return {ch: dict(trades=trs, skipped=skipped, signals=[]) for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL")}


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """The index 1-minute candles with the opening range and the option trades placed on the index (entry / exit there)."""
    out = _O.chart_main(ctx, body, day, to)
    C = {k: i for i, k in enumerate(body["cols"])}
    rows = []
    for r in out["trades"]:
        r = list(r); r[C["entry_px"]], r[C["exit_px"]] = r[C["und_entry"]], r[C["und_exit"]]; rows.append(r)
    out["trades"] = rows
    return out
