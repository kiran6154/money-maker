"""Weekly short options against a 10% CAGR fair-value line, hedged with monthly longs (family module for ST91).

Built 2026-10-24 at the user's word. The rule as given:
  fair value   NIFTY = 2000 on 2000-01-01 growing at `cagr` a year: F(t) = 2000 x (1 + cagr) ^ (years since 2000-01-01).
  when         the session before the current weekly expiry, at `entry_time` (09:30): the index (the candle's open) against F.
  above F      SELL 1 lot each of two PUTs of the NEXT weekly expiry: the strikes (multiples of `strike_round`) whose premium
               then is nearest `short_premiums` (150 and 450); BUY `long_lots` (3) lots of a monthly PUT whose premium is
               nearest `long_premium` (200), on the first monthly expiry at least `monthly_min_days` (18) days out.
  below F      the mirror with CALLs.
  then         every `steps` (hourly from 09:30, and 15:25) the position is marked at its legs' prices; it is closed at the
               first step where: the P&L is up `target_pct` (3%) or down `stop_pct` (6%) of the position's base; or the
               session two sessions ahead is the sold options' expiry ("the next next day"); or the bought options have
               under `long_exit_days` (15) days to expiry. One position at a time.
Build choices (not in the request):
  the P&L base is `short_option_margin` per short lot plus the long legs' premium paid (pnl.base "margin_plus_debit");
  prices are the candle at the step minute (its open; the last candle before it when that minute is missing); fills are
  those prices, slippage and charges per leg as the lab's other option strategies; strikes come from the download store
  (near-settlement strikes only in some weeks: a target premium with no strike within `premium_tolerance` of it is a
  skipped entry, listed with the reason); the index is the lab's spot series; lot size `lot_size`.
Each leg is one trade row (entry and exit shared; `tranche` = the position's number); the strategy chart is the index with
the fair-value line and the legs placed at the index's price.
"""
import datetime as D
import numpy as np
import core
import store_reader

ENTRY_RULES = ("cagr_hedge_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT", "INDEX")
OWN_COVERAGE = True
REFUSED_WHY = "Strategy 91 trades weekly and monthly options against the fair-value line; only the Options (via futures) type runs"
DAY = core.DAY
T0 = D.date(2000, 1, 1)


def fair(day, S):
    """F on a date (ISO string or date): 2000 x (1 + cagr) ^ years since 2000-01-01 (365.25-day years)."""
    d = D.date.fromisoformat(day) if isinstance(day, str) else day
    return S["base_price"] * (1 + S["cagr"]) ** ((d - T0).days / 365.25)


_K = {}


def _strikes(exp, day):
    key = (exp, day)
    if key not in _K:
        try: _K[key] = store_reader.strikes(exp, day)
        except ValueError: _K[key] = None
    return _K[key]


_SER = {}


def _series(exp, k, right, d0, d1):
    """{minute: (o, h, l, c)} of one contract over d0..d1 from the store (cached)."""
    key = (exp, k, right, d0, d1)
    if key not in _SER:
        while len(_SER) > 300: del _SER[next(iter(_SER))]
        c = store_reader.option_candles(exp, k, right, d0, d1, "minute")
        _SER[key] = {int(x[0]): (float(x[1]), float(x[2]), float(x[3]), float(x[4])) for x in c}
    return _SER[key]


def _px(ser, t):
    """The price at minute t: that candle's open, else the last candle before it (its close); None when there is none."""
    if t in ser: return ser[t][0]
    prev = [m for m in ser if m < t and m > t - 3 * DAY]
    return ser[max(prev)][3] if prev else None


def _pick(exp, right, day, t, target, S):
    """(strike, premium) of the contract of `exp` whose premium at minute t on `day` is nearest `target`, among strikes that are
    multiples of S['strike_round'] alive on `day`; None when none is within S['premium_tolerance'] of the target."""
    meta = _strikes(exp, day)
    if not meta: return None
    best = None
    for k in meta["strikes"].get(right, []):
        k = int(k)
        if k % S["strike_round"]: continue
        life = (meta.get("lives") or {}).get(right, {}).get(str(k)) or (meta.get("lives") or {}).get(right, {}).get(k)
        if life and (day < life[0] or day > life[1]): continue
        p = _px(_series(exp, k, right, day, day), t)
        if p is None: continue
        if best is None or abs(p - target) < abs(best[1] - target): best = (k, p)
    if best is None or abs(best[1] - target) > S["premium_tolerance"]: return None
    return best


def run(ctx):
    spec = ctx["spec"]; S = spec["cagr"]; lots = ctx["position"]["lots"]; lot = spec["lot_size"]
    sp = core.series("spot", "minute"); ss = core.sessions()
    d0, d1 = core.dnum(ctx["date_from"]), core.dnum(ctx["date_to"])
    exps = sorted(e["expiry"] for e in store_reader.expiries())
    monthly = sorted(e["expiry"] for e in store_reader.expiries() if e.get("monthly"))
    trs, skipped = [], []
    steps = [core.hhmm_sec(x) for x in S["steps"]]
    entry_t = core.hhmm_sec(S["entry_time"])
    busy_until = -1; n_pos = 0
    for d in ss[(ss >= d0) & (ss <= d1)]:
        d = int(d); day = core.dstr(d)
        if d <= busy_until: continue
        cur = next((e for e in exps if e >= day), None)
        if not cur: continue
        k_ = int(np.searchsorted(ss, core.dnum(cur)))
        if k_ == 0 or k_ >= len(ss) or int(ss[k_ - 1]) != d: continue    # not the session before the current weekly expiry
        if int(ss[k_]) != core.dnum(cur): continue                         # the expiry is not a session in the lab's data
        nxt = next((e for e in exps if e > cur), None)
        mon = next((e for e in monthly if (D.date.fromisoformat(e) - D.date.fromisoformat(day)).days >= S["monthly_min_days"]), None)
        i = int(np.searchsorted(sp.t, d * DAY + entry_t))
        if i >= len(sp) or sp.day[i] != d: continue
        idx = float(sp.o[i]); F = fair(day, S); above = idx > F
        right = "PE" if above else "CE"
        base = dict(dir="up" if above else "down", signal="BULLISH" if above else "BEARISH", fair=round(F, 1), index=idx)
        skip = lambda why: skipped.append(dict(base, position="", opt_type=right, instrument="", strike=0, expiry=nxt or "", entry_time=int(sp.t[i]), why=why))
        if not nxt: skip("no next weekly expiry in the store"); continue
        if not mon: skip(f"no monthly expiry at least {S['monthly_min_days']} days out in the store"); continue
        t = int(sp.t[i])
        legs = []
        for prem in S["short_premiums"]:
            got = _pick(nxt, right, day, t, prem, S)
            if got is None: skip(f"no {nxt} {right} strike (multiple of {S['strike_round']}) with premium within {S['premium_tolerance']} of {prem} at {S['entry_time']}"); break
            legs.append(("SHORT", nxt, got[0], got[1], 1))
        else:
            got = _pick(mon, right, day, t, S["long_premium"], S)
            if got is None: skip(f"no {mon} {right} strike (multiple of {S['strike_round']}) with premium within {S['premium_tolerance']} of {S['long_premium']} at {S['entry_time']}")
            else: legs.append(("LONG", mon, got[0], got[1], S["long_lots"]))
        if len(legs) != len(S["short_premiums"]) + 1: continue
        debit = sum(p * lot * n for pos, e, k, p, n in legs if pos == "LONG")
        base_amt = S["margin_per_short_lot"] * sum(n for pos, e, k, p, n in legs if pos == "SHORT") + debit
        # ---- walk the steps
        far = core.dstr(min(core.dnum(nxt), core.dnum(mon)))
        sers = [_series(e, k, right, day, far) for pos, e, k, p, n in legs]
        x_t, x_why, x_px = None, None, None
        for dd in ss[ss >= d]:
            dd = int(dd); dday = core.dstr(dd)
            j = int(np.searchsorted(ss, dd))
            ahead2 = core.dstr(int(ss[j + 2])) if j + 2 < len(ss) else None
            days_long = (D.date.fromisoformat(mon) - D.date.fromisoformat(dday)).days
            for st in steps:
                tt = dd * DAY + st
                if dd == d and st <= entry_t: continue
                pxs = [_px(s_, tt) for s_ in sers]
                if any(p is None for p in pxs): continue
                pnl = sum(((p0 - p) if pos == "SHORT" else (p - p0)) * lot * n for (pos, e, k, p0, n), p in zip(legs, pxs))
                pct = 100 * pnl / base_amt
                if pct >= S["target_pct"]: x_t, x_why, x_px = tt, "target", pxs; break
                if pct <= -S["stop_pct"]: x_t, x_why, x_px = tt, "stop_loss", pxs; break
                if ahead2 == nxt or nxt <= dday: x_t, x_why, x_px = tt, "short_expiry_near", pxs; break
                if days_long < S["long_exit_days"]: x_t, x_why, x_px = tt, "long_expiry_near", pxs; break
                if dd > d1 and dd == int(ss[ss >= d][-1]): pass
            if x_t is not None: break
        if x_t is None:
            # no step closed it (the data ends): close at the last step with prices
            last = None
            for dd in ss[ss >= d]:
                for st in steps:
                    tt = int(dd) * DAY + st; pxs = [_px(s_, tt) for s_ in sers]
                    if all(p is not None for p in pxs): last = (tt, pxs)
            if last is None: skip("no option prices after the entry"); continue
            x_t, x_why, x_px = last[0], "data_end", last[1]
        n_pos += 1
        xi = max(int(np.searchsorted(sp.t, x_t, "right")) - 1, 0)
        for (pos, e, k, p0, n), p1 in zip(legs, x_px):
            name = f"NIFTY {D.date.fromisoformat(e):%d%b%y} {k} {right}".upper()
            rec = dict(base, position=pos, opt_type=right, kind="OPT", instrument=name, strike=k, expiry=e, entry_time=t, entry_px=p0,
                       exit_time=int(x_t), exit_px=p1, exit_reason=x_why, open=False, sl=None, choch_time=t, und_entry=idx, und_exit=float(sp.c[xi]),
                       stale=False, lots=lots * n, tranche=f"P{n_pos}", label=f"{pos} {right} {e[5:]} {k}")
            trs.append(core.price_trade(ctx, rec))
        busy_until = int(x_t // DAY)
    trs.sort(key=lambda r: (r["entry_time"], r["position"]))
    return {ch: dict(trades=trs, skipped=skipped, signals=[]) for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL")}


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """The index's 1-minute candles of day..to with the fair-value line; the legs placed at the index's price."""
    spec = ctx["spec"]; S = spec["cagr"]; sp = core.series("spot", "minute")
    a, z = int(np.searchsorted(sp.day, core.dnum(day))), int(np.searchsorted(sp.day, core.dnum(to), "right"))
    if a >= z: raise ValueError(f"no index candles on {day}")
    candles = core._chart_bars(sp, a, z - 1)
    line = [[int(sp.t[q]), round(fair(core.dstr(int(sp.day[q])), S), 1)] for q in range(a, z)]
    C = {k: i for i, k in enumerate(body["cols"])}
    rows = []
    for r in body["trades"]:
        e_d, x_d = core.dnum(str(r[C["entry_time"]])[:10]), core.dnum(str(r[C["exit_time"]])[:10])
        if x_d < core.dnum(day) or e_d > core.dnum(to): continue
        r = list(r); r[C["entry_px"]], r[C["exit_px"]] = r[C["und_entry"]], r[C["und_exit"]]; rows.append(r)
    return dict(day=day, to=to, inst=None, candles=candles, cols=body["cols"], trades=rows, own=True, lines=[line],
                derived=dict(what=f"the NIFTY index with the fair-value line (2000 on 2000-01-01 at {100 * S['cagr']:.0f}% a year; {fair(day, S):,.0f} on {day})"))
