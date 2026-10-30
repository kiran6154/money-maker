"""The user's four Pine rules as lab strategies on NIFTY near-month futures (family module for ST135 - ST138).

Built 2026-10-26 at the user's word ("create those 4 as strategies here with our backtesting project"), after the Pine
scripts and the combined-book check (STRATEGY_ANALYSIS_TODO S142, tools/combo_book.py - the same rules, the same numbers).
Data: the download store's near-month futures and the index, 1-minute (jilly._store_bars, to 2026-10-23). A decision at a
bar's close fills at the next bar's open. 1 lot of 65; 0.5 pt slippage a side + futures charges by date (jilly._price).
SPEC["pine"]["rule"] picks the rule:

  ibs     (ST135) at the 15:19 bar (opens 15:19, closes 15:20): IBS = (close - session low) / (session high - session low),
          the session from the day's first bar. IBS > `long_above` (0.7): long; < `short_below` (0.3): short. In at the 15:20
          open, out at the next session's 09:16 open. BUILD: not on the contract's expiry day (it does not exist overnight)
          and not when a weekday holiday follows (the script's "tomorrow is holiday" box).
  basis   (ST136) at the 15:19 bar: premium = (futures close - index close) / index close; deviation = premium - `carry` %
          x days to the contract's expiry / 365; z = the deviation against the previous `lookback` (60) sessions' (mean,
          population std). z > `z` (2.0): short; z < -`z`: long. In at the 15:20 open, out at the next session's 15:20 open.
          Not on the expiry day.
  cpr     (ST137) today's CPR from the previous session's high / low / last close (pivot, BC = (H + L) / 2, TC = 2P - BC),
          yesterday's from the session before. A narrow day: width below the mean of the previous `wlen` (20) CPR widths,
          and today's CPR entirely above (long side) or below (short side) yesterday's; the 09:15 open beyond today's CPR the
          same way. Then the first close beyond the `orb` (15) minute opening range that way (by 15:19): in at the next open.
          BUILD (the Pine rule gives no exit): stop at the far side of the opening range (a touch exits at the next open),
          else out at the 15:20 open.
  emab    (ST138) 5-minute bars (09:15-aligned): EMA `ema` (50) of the closes, continuous; band = EMA +/- `mult` (3.0) x the
          mean |close - EMA| of the last `dlen` (20) bars. A close crossing above the upper band: long; below the lower: short
          (when flat). Out at the next bar's open after a close back through the EMA. Positional (held overnight); BUILD: out
          at the contract's last close before a roll.
"""
import datetime as Dt
import numpy as np
import core

ENTRY_RULES = ("pine_rules_v1",)
TYPES = ("FUT",)
UNDERLYINGS = ("FUT",)
OWN_COVERAGE = True
REFUSED_WHY = "the four Pine rules trade the near-month future; only the Futures type runs"
DAY = core.DAY
_J = core.family("jilly")
_D = {}


def _data():
    if "d" in _D: return _D["d"]
    f = _J._store_bars("fut"); sp = _J._store_bars("index")
    MIN = (f.t % DAY) // 60
    cut = np.concatenate([[0], np.nonzero(np.diff(f.day))[0] + 1, [len(f.t)]])
    SES = [(int(a), int(z)) for a, z in zip(cut[:-1], cut[1:])]
    DSTR = [core.dstr(int(f.day[a])) for a, z in SES]
    _D["d"] = (f, sp, MIN, SES, DSTR)
    return _D["d"]


def _at(MIN, a, z, m):
    w = np.nonzero(MIN[a:z] == m)[0]
    return a + int(w[0]) if len(w) else None


def _gap(d1, d2):
    a, b = Dt.date.fromisoformat(d1), Dt.date.fromisoformat(d2); x = a + Dt.timedelta(days=1)
    while x < b:
        if x.weekday() < 5: return True
        x += Dt.timedelta(days=1)
    return False


def _t(f, name, side, ei, xi, xpx, why, label, sl=None):
    return dict(name=name, side=side, ei=ei, xi=xi, entry_px=float(f.o[ei]), exit_px=float(xpx), why=why, label=label, sl=sl)


def trades_ibs(P):
    f, sp, MIN, SES, DSTR = _data(); E = f.extra["expiry"]; out = []
    for s in range(len(SES) - 1):
        a, z = SES[s]; d = DSTR[s]
        i = _at(MIN, a, z, 919)
        if i is None or i + 1 >= z or E[i] == d: continue
        a2, z2 = SES[s + 1]
        if _gap(d, DSTR[s + 1]) or E[a2] != E[i]: continue
        hi, lo = f.h[a:i + 1].max(), f.l[a:i + 1].min()
        if hi <= lo: continue
        v = (f.c[i] - lo) / (hi - lo)
        side = 1 if v > P["long_above"] else -1 if v < P["short_below"] else 0
        if not side: continue
        x = _at(MIN, a2, z2, 556); x = x if x is not None else min(a2 + 1, z2 - 1)
        out.append(_t(f, "IBS", side, i + 1, x, f.o[x], "next_0916", f"IBS {v:.2f} · {'LONG' if side > 0 else 'SHORT'} overnight"))
    return out


def basis_series(P):
    """{session: (deviation, z or None, dte, fair futures at 15:19)} for every session with a 15:19 bar and an index close."""
    key = ("basis", P["carry"], P["lookback"])
    if key in _D: return _D[key]
    f, sp, MIN, SES, DSTR = _data(); E = f.extra["expiry"]; out, devs = {}, []
    for s in range(len(SES)):
        a, z = SES[s]; d = DSTR[s]
        i = _at(MIN, a, z, 919)
        if i is None: continue
        j = int(np.searchsorted(sp.t, f.t[i]))
        if j >= len(sp.t) or sp.t[j] != f.t[i]: continue
        spot = float(sp.c[j]); dte = (Dt.date.fromisoformat(E[i]) - Dt.date.fromisoformat(d)).days
        dev = (f.c[i] - spot) / spot - P["carry"] / 100 * dte / 365
        zz = None
        if len(devs) >= P["lookback"]:
            w = np.array(devs[-P["lookback"]:]); sd = w.std()
            zz = (dev - w.mean()) / sd if sd > 0 else None
        devs.append(dev)
        out[s] = (dev, zz, dte, i)
    _D[key] = out
    return out


def trades_basis(P):
    f, sp, MIN, SES, DSTR = _data(); E = f.extra["expiry"]; out = []
    for s, (dev, zz, dte, i) in basis_series(P).items():
        a, z = SES[s]; d = DSTR[s]
        if zz is None or abs(zz) <= P["z"] or i + 1 >= z or E[i] == d or s + 1 >= len(SES): continue
        a2, z2 = SES[s + 1]
        if E[a2] != E[i]: continue
        x = _at(MIN, a2, z2, 920); x = x if x is not None else z2 - 1
        side = -1 if zz > P["z"] else 1
        out.append(_t(f, "Basis z", side, i + 1, x, f.o[x], "next_1520", f"basis z {zz:+.2f} (dev {dev * 100:+.3f}%, {dte} days) · {'LONG' if side > 0 else 'SHORT'} overnight"))
    return out


def _cp(h, l, c):
    p = (h + l + c) / 3; bc = (h + l) / 2; tc = 2 * p - bc
    return max(tc, bc), min(tc, bc)


def cpr_days(P):
    """{session: dict(top, bot, ytop, ybot, narrow, dir, orh, orl)} - every session's CPR and the narrow-day test."""
    key = ("cpr", P["wlen"], P["orb"])
    if key in _D: return _D[key]
    f, sp, MIN, SES, DSTR = _data()
    HLC = [(f.h[a:z].max(), f.l[a:z].min(), f.c[z - 1]) for a, z in SES]
    W = [abs(x[0] - x[1]) for x in (_cp(*v) for v in HLC)]
    out = {}
    for s in range(P["wlen"] + 2, len(SES)):
        a, z = SES[s]
        if MIN[a] != 555: continue
        top, bot = _cp(*HLC[s - 1]); yt, yb = _cp(*HLC[s - 2])
        avg = float(np.mean(W[s - 1 - P["wlen"]:s - 1]))
        hi_, lo_ = bot > yt, top < yb
        narrow = (top - bot) < avg and (hi_ or lo_)
        dr = (1 if hi_ and f.o[a] > top else -1 if lo_ and f.o[a] < bot else 0) if narrow else 0
        m = (MIN[a:z] >= 555) & (MIN[a:z] < 555 + P["orb"])
        out[s] = dict(top=top, bot=bot, ytop=yt, ybot=yb, narrow=narrow, dir=dr, avg=avg,
                      orh=float(f.h[a:z][m].max()) if m.any() else None, orl=float(f.l[a:z][m].min()) if m.any() else None)
    _D[key] = out
    return out


def trades_cpr(P):
    f, sp, MIN, SES, DSTR = _data(); out = []
    for s, r in cpr_days(P).items():
        if not r["dir"] or r["orh"] is None: continue
        a, z = SES[s]; dr = r["dir"]
        for i in range(a, z - 1):
            if MIN[i] < 555 + P["orb"]: continue
            if MIN[i + 1] >= 920: break
            if (dr > 0 and f.c[i] > r["orh"]) or (dr < 0 and f.c[i] < r["orl"]):
                stop = r["orl"] if dr > 0 else r["orh"]
                xi, why, xp = z - 1, "eod", f.c[z - 1]
                for m in range(i + 1, z):
                    if MIN[m] >= 920: xi, why, xp = m, "eod", f.o[m]; break
                    if (f.l[m] <= stop) if dr > 0 else (f.h[m] >= stop):
                        if m + 1 < z: xi, xp = m + 1, f.o[m + 1]
                        else: xi, xp = m, f.c[m]
                        why = "stop_loss"; break
                out.append(_t(f, "CPR+ORB", dr, i + 1, xi, xp, why, f"narrow CPR {'above' if dr > 0 else 'below'} · OR break · {'LONG' if dr > 0 else 'SHORT'}", sl=stop))
                break
    return out


def ema_bars(P):
    """5-minute bars (09:15-aligned) of the whole series with EMA and bands: (first 1-min index, last 1-min index, close,
    ema, upper, lower)."""
    key = ("ema", P["ema"], P["mult"], P["dlen"])
    if key in _D: return _D[key]
    f, sp, MIN, SES, DSTR = _data()
    b5 = f.day * 1000 + (MIN - 555) // 5
    cb = np.concatenate([[0], np.nonzero(np.diff(b5))[0] + 1, [len(f.t)]]); q0, q1 = cb[:-1], cb[1:] - 1
    c5 = f.c[q1]; N = len(c5); k = 2 / (P["ema"] + 1)
    ema = np.empty(N); ema[0] = c5[0]
    for x in range(1, N): ema[x] = c5[x] * k + ema[x - 1] * (1 - k)
    dist = np.abs(c5 - ema); cs = np.cumsum(np.insert(dist, 0, 0)); ad = np.full(N, np.nan); ad[P["dlen"] - 1:] = (cs[P["dlen"]:] - cs[:-P["dlen"]]) / P["dlen"]
    _D[key] = (q0, q1, c5, ema, ema + P["mult"] * ad, ema - P["mult"] * ad)
    return _D[key]


def trades_emab(P):
    f, sp, MIN, SES, DSTR = _data(); E = f.extra["expiry"]
    q0, q1, c5, ema, up, lo = ema_bars(P); N = len(c5)
    if P.get("slope") or P.get("be"): return _trades_emab_x(P)
    out, pos, e, econ = [], 0, None, None
    lab = lambda s: f"EMA band break · {'LONG' if s > 0 else 'SHORT'}"
    for x in range(max(P["ema"], P["dlen"]) + 1, N - 1):
        nxt = q0[x + 1]
        if pos and E[nxt] != econ:
            out.append(_t(f, "EMA bands", pos, e, q1[x], f.c[q1[x]], "roll", lab(pos))); pos = 0
        if pos == 1 and c5[x - 1] >= ema[x - 1] and c5[x] < ema[x]: out.append(_t(f, "EMA bands", 1, e, nxt, f.o[nxt], "ema_cross", lab(1))); pos = 0
        elif pos == -1 and c5[x - 1] <= ema[x - 1] and c5[x] > ema[x]: out.append(_t(f, "EMA bands", -1, e, nxt, f.o[nxt], "ema_cross", lab(-1))); pos = 0
        if not pos and np.isfinite(up[x - 1]):
            if c5[x - 1] <= up[x - 1] and c5[x] > up[x]: pos, e, econ = 1, nxt, E[nxt]
            elif c5[x - 1] >= lo[x - 1] and c5[x] < lo[x]: pos, e, econ = -1, nxt, E[nxt]
    return out


def _trades_emab_x(P):
    """The EMA bands with the S146 corrections (opt-in; Strategy 146): `slope` "with" = enter only when the EMA moved the
    trade's way over the last 12 bars (1 hour), "band" = and by at most 0.15% of price; `be` = once a 5-minute close is
    be x the mean distance beyond the entry, the stop moves to the entry (touched on a later bar's high / low, filled at the
    entry, or the open when it opens through it). Exits as Strategy 138 otherwise."""
    f, sp, MIN, SES, DSTR = _data(); E = f.extra["expiry"]
    q0, q1, c5, ema, up, lo = ema_bars(P); N = len(c5); ad = (up - ema) / P["mult"]
    h5 = np.maximum.reduceat(f.h, q0); l5 = np.minimum.reduceat(f.l, q0); o5 = f.o[q0]
    out, pos = [], 0
    lab = lambda s, x="": f"EMA band break · {'LONG' if s > 0 else 'SHORT'}{x}"
    for x in range(max(P["ema"], P["dlen"]) + 13, N - 1):
        nxt = q0[x + 1]
        if pos:
            if x >= e and st is not None and ((l5[x] <= st) if pos > 0 else (h5[x] >= st)):
                px = min(o5[x], st) if pos > 0 else max(o5[x], st)
                out.append(_t(f, "EMA bands", pos, q0[e], q0[x], px, "breakeven", lab(pos, " · slope ok"), sl=st)); pos = 0
            if pos and P.get("be") and not moved and pos * (c5[x] - entry) >= P["be"] * ad[e - 1]:
                st, moved = entry, True
            if pos and E[nxt] != econ: out.append(_t(f, "EMA bands", pos, q0[e], q1[x], f.c[q1[x]], "roll", lab(pos, " · slope ok"), sl=st)); pos = 0
            if pos == 1 and c5[x - 1] >= ema[x - 1] and c5[x] < ema[x]: out.append(_t(f, "EMA bands", 1, q0[e], nxt, f.o[nxt], "ema_cross", lab(1, " · slope ok"), sl=st)); pos = 0
            elif pos == -1 and c5[x - 1] <= ema[x - 1] and c5[x] > ema[x]: out.append(_t(f, "EMA bands", -1, q0[e], nxt, f.o[nxt], "ema_cross", lab(-1, " · slope ok"), sl=st)); pos = 0
            if pos: continue
        if not np.isfinite(up[x - 1]): continue
        s = 1 if (c5[x - 1] <= up[x - 1] and c5[x] > up[x]) else -1 if (c5[x - 1] >= lo[x - 1] and c5[x] < lo[x]) else 0
        if not s: continue
        if P.get("slope"):
            sl = s * (ema[x] - ema[x - 12]) / ema[x] * 100
            if sl <= 0 or (P["slope"] == "band" and sl > 0.15): continue
        pos, e, econ, entry, moved, st = s, x + 1, E[nxt], float(o5[x + 1]), False, None
    return out


RULES = dict(ibs=trades_ibs, basis=trades_basis, cpr=trades_cpr, emab=trades_emab)


def run(ctx):
    spec = ctx["spec"]; P = spec["pine"]; f = _data()[0]; E = f.extra["expiry"]
    d0, d1 = ctx["date_from"], ctx["date_to"]
    trs = []
    for x in RULES[P["rule"]](P):
        if not (d0 <= core.tstr(int(f.t[x["ei"]]))[:10] <= d1): continue
        side = x["side"]; pos = "LONG" if side > 0 else "SHORT"
        rec = dict(dir="up" if side > 0 else "down", signal="BULLISH" if side > 0 else "BEARISH", choch_time=int(f.t[x["ei"] - 1]),
                   und_entry=x["entry_px"], und_exit=x["exit_px"], stale=False, lots=ctx["position"]["lots"], tranche="", sl=x["sl"], open=False,
                   position=pos, opt_type="FUT", kind="FUT", instrument=f"NIFTY FUT {E[x['ei']]}", strike=0, expiry=str(E[x["ei"]]),
                   entry_time=int(f.t[x["ei"]]), entry_px=x["entry_px"], exit_time=int(f.t[x["xi"]]), exit_px=x["exit_px"], exit_reason=x["why"],
                   label=x["label"])
        trs.append(_J._price(ctx, rec, "FUT"))
    trs.sort(key=lambda r: r["entry_time"])
    return {"-": dict(trades=trs, skipped=[], signals=[])}


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """The near-month future of the sessions with the rule's own lines (1-minute candles; the EMA bands on 5-minute ones)
    and the trades entered in the range."""
    P = ctx["spec"]["pine"]; f, sp, MIN, SES, DSTR = _data()
    idx = [s for s, d in enumerate(DSTR) if day <= d <= to]
    if not idx: raise ValueError(f"no futures candles from {day}")
    C = {k: i for i, k in enumerate(body["cols"])}
    trades = [x for x in body["trades"] if day <= str(x[C["entry_time"]])[:10] <= to]
    candles, names, colors, lines = [], [], [], []
    def L(n, col): names.append(n); colors.append(col); lines.append([]); return lines[-1]
    if P["rule"] == "emab":
        q0, q1, c5, ema, up, lo = ema_bars(P)
        a, z = SES[idx[0]][0], SES[idx[-1]][1]
        k0, k1 = int(np.searchsorted(q0, a)), int(np.searchsorted(q0, z))
        le, lu, ll = L("EMA", "#f5a524"), L("upper band", "#12a594"), L("lower band", "#12a594")
        for k in range(k0, k1):
            i0, i1 = int(q0[k]), int(q1[k]); tt = int(f.t[i0])
            candles.append([tt, float(f.o[i0]), float(f.h[i0:i1 + 1].max()), float(f.l[i0:i1 + 1].min()), float(f.c[i1]), float(f.v[i0:i1 + 1].sum())])
            le.append([tt, round(float(ema[k]), 2)])
            if np.isfinite(up[k]): lu.append([tt, round(float(up[k]), 2)]); ll.append([tt, round(float(lo[k]), 2)])
        what = "5-minute near-month future: EMA and the distance bands"
    else:
        if P["rule"] == "ibs": lh, ll_, l7, l3 = L("session high", "#8e4ec6"), L("session low", "#8e4ec6"), L(f"IBS {P['long_above']}", "#30a46c"), L(f"IBS {P['short_below']}", "#e5484d")
        if P["rule"] == "basis": lf = L("fair futures (index + carry)", "#2962ff"); B = basis_series(P)
        if P["rule"] == "cpr": lt, lb, oh, ol = L("CPR top", "#2962ff"), L("CPR bottom", "#2962ff"), L("OR high", "#8e4ec6"), L("OR low", "#8e4ec6"); R = cpr_days(P)
        for s in idx:
            a, z = SES[s]
            candles += core._chart_bars(f, a, z - 1)
            first = True
            if P["rule"] == "ibs":
                hi = lo = None
                for i in range(a, z):
                    hi = f.h[i] if hi is None else max(hi, f.h[i]); lo = f.l[i] if lo is None else min(lo, f.l[i]); tt = int(f.t[i])
                    v = None if first else 1
                    for ln, val in ((lh, hi), (ll_, lo), (l7, lo + P["long_above"] * (hi - lo)), (l3, lo + P["short_below"] * (hi - lo))):
                        ln.append([tt, None if v is None else round(float(val), 2)])
                    first = False
            elif P["rule"] == "basis":
                sidx = np.searchsorted(sp.t, f.t[a:z]); E = f.extra["expiry"]
                dte = (Dt.date.fromisoformat(E[a]) - Dt.date.fromisoformat(DSTR[s])).days
                for n, i in enumerate(range(a, z)):
                    j = int(sidx[n]); tt = int(f.t[i])
                    if j < len(sp.t) and sp.t[j] == f.t[i]:
                        lf.append([tt, None if first else round(float(sp.c[j]) * (1 + P["carry"] / 100 * dte / 365), 2)]); first = False
            elif P["rule"] == "cpr" and s in R:
                r = R[s]
                for i in range(a, z):
                    tt = int(f.t[i])
                    lt.append([tt, None if first else round(r["top"], 2)]); lb.append([tt, None if first else round(r["bot"], 2)])
                    if MIN[i] >= 555 + P["orb"] and r["orh"] is not None:
                        oh.append([tt, None if MIN[i] == 555 + P["orb"] else r["orh"]]); ol.append([tt, None if MIN[i] == 555 + P["orb"] else r["orl"]])
                    first = False
        what = {"ibs": "the session high / low and the IBS 0.7 / 0.3 levels (the signal reads the 15:19 close)",
                "basis": "the fair futures price = index x (1 + carry x days to expiry / 365); the signal is the 15:19 premium's z-score",
                "cpr": "today's CPR (from the previous session) and the opening range after it closes"}[P["rule"]]
    keep = [k for k in range(len(lines)) if lines[k]]
    return dict(day=day, to=to, inst=None, candles=candles, cols=body["cols"], trades=trades, own=True, lines=[lines[k] for k in keep],
                line_names=[names[k] for k in keep], line_colors=[colors[k] for k in keep], sessions=len(idx), derived=dict(what=what))
