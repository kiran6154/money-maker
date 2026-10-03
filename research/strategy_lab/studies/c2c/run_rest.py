"""C2C research, remaining phases on development data (ledger EXP-007 .. EXP-017). User, 2026-09-30: run all remaining
phases. Index 2021-2023, options only from research-fetched expiries (2021, most of 2022 when first run). Nothing after
2023-12-31 is loaded. Every section is one experiment; nothing here selects a winner - EXP-017 (walk-forward) is the only
section that selects, and it selects on the earlier year and reports the next year untouched.

Outcome measures used throughout:
  sig    the signal's directional NIFTY move to the close (and at 60 min) minus the same-year same-time-of-day control
  eod    each signal's own ITM1 monthly (>= 15 days) option bought at the next candle's open and sold at the session's
         last candle (no lock: every signal counted once), net rupees per 65-lot
  book   the baseline position rules (c2clib.BASE) as a one-position-at-a-time book, net rupees per lot
Counts of cells tested are reported with every table so chance winners can be discounted.

    python studies/c2c/run_rest.py        # writes studies/c2c/run_rest.json
"""
import json, math, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import c2clib as L  # noqa: E402
import phase4_9 as P4  # noqa: E402
import lab  # noqa: E402

OUT = os.path.dirname(os.path.abspath(__file__))
EOD = dict(L.BASE, stop_pct=0, trail_pts=0, flip=False, ladder=False, eod=True)
R = {}


def per_signal(ctx, x, flips, X, pick=("ITM1", "M15"), cache={}):
    key = (x["defn"], x["i"], x["dir"], json.dumps(X, sort_keys=True), pick)
    if key not in cache:
        tr, _ = L.book(ctx, [x], flips, X, pick)
        cache[key] = tr[0]["net"] if tr else None
    return cache[key]


def quint(ctx, sigs, flips, feat, name):
    """Quintiles of a feature: sig excess (eod), and eod option net per signal."""
    v = [(feat(x), x) for x in sigs]; v = [(f, x) for f, x in v if f is not None and np.isfinite(f)]
    if len(v) < 50: return None
    arr = np.array([f for f, _ in v]); edges = np.quantile(arr, [0.2, 0.4, 0.6, 0.8]); q = np.searchsorted(edges, arr, side="right")
    cells = []
    for k in range(5):
        xs = [x for (f, x), qq in zip(v, q) if qq == k]
        if not xs: continue                                                  # tied values leave a quintile empty
        ex = [L.ctrl_excess(ctx, x, "eod")[1] for x in xs]
        on = [per_signal(ctx, x, flips, EOD) for x in xs]
        cells.append(dict(lo=round(float(arr[q == k].min()), 3), hi=round(float(arr[q == k].max()), 3),
                          sig=L.summarize(ex), eod=L.summarize(on)))
    return cells


def main():
    ctx = L.Ctx()
    C = {d: L.candidates(ctx, d) for d in ("R-A", "R-B")}
    S = {d: L.signals(C[d][0]) for d in C}
    sides = (("bearish", -1), ("bullish", 1))

    # ---------------- EXP-007: phases 5 + 9, expected move and decay-aware entry filters
    # expected move = mean directional move to the close of the EARLIER signals (same definition, side, entry hour)
    carry = {}
    e7 = {}
    for d in C:
        for side, dv in sides:
            xs = [x for x in S[d] if x["dir"] == dv]
            hist, rows = {}, []
            for x in xs:
                mv, _ = L.ctrl_excess(ctx, x, "eod"); hr = ctx.t[min(x["i"] + 1, ctx.n - 1)][11:13]
                h = hist.get(hr, [])
                rows.append((x, float(np.mean(h)) if len(h) >= 20 else None, mv))
                if mv is not None: hist.setdefault(hr, []).append(mv)
            cells = {}
            for nm, f in (("M1 none", lambda m, x: True), ("M2 >= 5 pts", lambda m, x: m is not None and m >= 5),
                          ("M2 >= 10 pts", lambda m, x: m is not None and m >= 10), ("M3 >= 0.05 ATR", lambda m, x: m is not None and m >= 0.05 * x["atr20"]),
                          ("M4/M5/E2-E6 >= required (>= 9 pts)", lambda m, x: m is not None and m >= 9)):
                take = [x for x, m, _ in rows if f(m, x)]
                cells[nm] = dict(taken=len(take), sig=L.summarize([L.ctrl_excess(ctx, x, "eod")[1] for x in take]),
                                 eod=L.summarize([per_signal(ctx, x, C[d][1], EOD) for x in take]))
            exp = [m for _, m, _ in rows if m is not None]
            e7[f"{d} {side}"] = dict(expected_move_dist=L.summarize(exp), cells=cells)
    R["EXP-007"] = e7
    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)   # partial results survive a crash

    # ---------------- EXP-008: phases 8 + 9, strike x expiry under the baseline book and the eod exit
    e8 = {}
    for d in C:
        for side, dv in sides:
            xs = [x for x in S[d] if x["dir"] == dv]
            for ek in ("W0", "W1", "M15"):
                for ch in ("ATM", "ITM1", "ITM2", "OTM1", "OTM2"):
                    tr, _ = L.book(ctx, xs, C[d][1], L.BASE, (ch, ek))
                    on = [per_signal(ctx, x, C[d][1], EOD, (ch, ek)) for x in xs]
                    e8[f"{d} {side} {ek} {ch}"] = dict(book=L.stats(tr), eod=L.summarize(on))
    R["EXP-008"] = dict(cells=len(e8), grid=e8)
    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)   # partial results survive a crash

    # ---------------- EXP-009: phase 10, CHoCH quality, one feature at a time
    feats = {
        "break_size": lambda x: x["break_size"], "break_atr5": lambda x: x["break_size"] / x["atr5"],
        "dist_av_abs": lambda x: abs(x["dist_av"]), "dist_av_atr5": lambda x: abs(x["dist_av"]) / x["atr5"],
        "bars_since_flip": lambda x: x["bars_since_flip"], "leg_atr5": lambda x: x["leg"] / x["atr5"] if x["leg"] else None,
        "lh_hl": lambda x: x["lh_hl"], "dist_day_open": lambda x: x["dir"] * (ctx.c[x["i"]] - ctx.dO[ctx.di[ctx.day[x["i"]]]]),
        "dist_prev_high": lambda x: ctx.c[x["i"]] - ctx.dH[ctx.di[ctx.day[x["i"]]] - 1],
        "dist_prev_low": lambda x: ctx.c[x["i"]] - ctx.dL[ctx.di[ctx.day[x["i"]]] - 1],
        "day_range_so_far": lambda x: float(ctx.h[ctx.first_of[ctx.day[x["i"]]]:x["i"] + 1].max() - ctx.l[ctx.first_of[ctx.day[x["i"]]]:x["i"] + 1].min()),
        "vol_before_atr5": lambda x: x["atr5"],
    }
    e9 = {}
    for d in C:
        for side, dv in sides:
            xs = [x for x in S[d] if x["dir"] == dv]
            for fn, f in feats.items(): e9[f"{d} {side} {fn}"] = quint(ctx, xs, C[d][1], f, fn)
    R["EXP-009"] = dict(cells=len(e9) * 5, table=e9)
    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)   # partial results survive a crash

    # ---------------- EXP-010: phase 11 (+27), entry band
    e10 = {}
    bands = [("pts", b_) for b_ in (20, 25, 35, 40, 45, 50, 55, 60, 75, 100)] + [("atr", a) for a in (0.25, 0.5, 0.75, 1.0)]
    for d in C:
        for side, dv in sides:
            for kind, bw in bands:
                xs = [x for x in (L.signals(C[d][0], band=bw) if kind == "pts" else L.signals(C[d][0], band_atr=bw)) if x["dir"] == dv]
                tr, _ = L.book(ctx, xs, C[d][1], L.BASE)
                e10[f"{d} {side} {kind} {bw}"] = dict(n=len(xs), sig=L.summarize([L.ctrl_excess(ctx, x, "eod")[1] for x in xs]),
                                                      sig60=L.summarize([L.ctrl_excess(ctx, x, "60")[1] for x in xs]),
                                                      eod=L.summarize([per_signal(ctx, x, C[d][1], EOD) for x in xs]), book=L.stats(tr))
    R["EXP-010"] = dict(cells=len(e10), table=e10)
    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)   # partial results survive a crash

    # ---------------- EXP-011: phases 12 + 16, exits with the entry frozen; holding period
    # decay-aware inputs (in-sample, development): the control's expected carry to the close per DTE bucket x hour, and the
    # mean remaining directional move to the close of the development signals per hour
    import phase4_9 as _p4
    V = dict(
        X1_current=L.BASE,
        **{f"X2_target_{p}pts": dict(L.BASE, trail_pts=0, target_pts=p) for p in (10, 20, 40)},
        **{f"X3_target_{p}pct": dict(L.BASE, trail_pts=0, target_pct=p) for p in (10, 20, 40)},
        **{f"X4_nifty_{p}pts": dict(L.BASE, trail_pts=0, und_target=p) for p in (25, 50, 100)},
        X5_choch_only=dict(L.BASE, stop_pct=0, trail_pts=0, ladder=False),
        **{f"X6_trail_{p}pts": dict(L.BASE, trail_pts=p) for p in (10, 20, 40)},
        **{f"X7_time_{m}min": dict(L.BASE, stop_pct=0, trail_pts=0, flip=False, ladder=False, time_min=m) for m in (15, 30, 60, 120, 240)},
        X7_eod=EOD, X7_next_close=dict(EOD, eod=False, next_close=True),
        X9_exhaust_40pts=dict(L.BASE, trail_pts=0, exhaust=40),
    )
    e11 = {}
    for d in C:
        for side, dv in sides:
            xs = [x for x in S[d] if x["dir"] == dv]
            for nm, X in V.items():
                tr, _ = L.book(ctx, xs, C[d][1], X)
                e11[f"{d} {side} {nm}"] = L.stats(tr)
    R["EXP-011"] = dict(cells=len(e11), note="X8 decay-aware exit: the development signals' mean remaining move to the close is <= 0 at every hour (EXP-004/006), so the rule 'exit when expected remaining gain < expected carry' exits at the first check - it is the X7 30-minute exit; not run separately.", table=e11)
    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)   # partial results survive a crash

    # ---------------- EXP-012: phases 13 + 17 + 18, IV level and percentile at entry
    ivday = {}
    for dd in ctx.days:
        i = next((j for j in range(ctx.first_of[dd], ctx.last_of[ctx.first_of[dd]] + 1) if ctx.t[j][11:16] == "10:15"), None)
        if i is None: continue
        e = ctx.expiry(dd, "MONTHLY", 15); vs = []
        for right in ("CE", "PE"):
            k = int(lab.pick_strike("ATM", right, ctx.c[i - 1], 0, 50)); op = L.option(ctx, e, k, right, i)
            if op:
                s_, j0 = op; v = P4.iv(s_.o[j0], ctx.o[i], k, P4.years_to(e, ctx.t[i]), right)
                if v: vs.append(v)
        if vs: ivday[dd] = float(np.mean(vs))
    days_iv = sorted(ivday)
    def entry_iv(x):
        e = ctx.expiry(ctx.day[x["i"]], "MONTHLY", 15); right = "PE" if x["dir"] < 0 else "CE"
        k = int(lab.pick_strike("ITM1", right, ctx.c[x["i"]], 0, 50)); op = L.option(ctx, e, k, right, x["i"] + 1)
        if not op: return None
        s_, j0 = op
        return P4.iv(s_.o[j0], ctx.o[x["i"] + 1], k, P4.years_to(e, ctx.t[x["i"] + 1]), right)
    def prev_day_ivpct(x):
        dd = ctx.day[x["i"]]; prev = [z for z in days_iv if z < dd]
        if len(prev) < 21: return None
        hist = [ivday[z] for z in prev[-61:-1]]; last = ivday[prev[-1]]
        return sum(1 for z in hist if z <= last) / len(hist) * 100
    e12 = {}
    for d in C:
        for side, dv in sides:
            xs = [x for x in S[d] if x["dir"] == dv]
            e12[f"{d} {side} entry_iv"] = quint(ctx, xs, C[d][1], entry_iv, "entry_iv")
            e12[f"{d} {side} iv_pct_prev_day"] = quint(ctx, xs, C[d][1], prev_day_ivpct, "iv_pct")
    R["EXP-012"] = dict(days_with_iv=len(ivday), table=e12)
    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)   # partial results survive a crash

    # ---------------- EXP-013: phases 14 + 20, higher-timeframe regime (A ignore / B same direction only)
    def htf_label(x, minutes):
        """+1 / -1 / 0: the last COMPLETED higher-timeframe candle's close vs its EMA20, and the EMA's slope."""
        i = x["i"]; t_sig = ctx.t[i]
        if minutes == "day":
            j = ctx.di[ctx.day[i]]
            if j < 25: return None
            closes = ctx.dC[:j]
        else:
            k = minutes // 5
            s0 = ctx.first_of[ctx.day[i]]
            # completed buckets of `minutes` aligned to 09:15, over the previous 10 sessions and today up to the signal close
            j0 = ctx.first_of[ctx.days[max(0, ctx.di[ctx.day[i]] - 10)]]
            closes = []
            for dd in ctx.days[max(0, ctx.di[ctx.day[i]] - 10): ctx.di[ctx.day[i]] + 1]:
                a = ctx.first_of[dd]; z = ctx.last_of[a] if dd != ctx.day[i] else i
                m = a
                while m + k - 1 <= z: closes.append(ctx.c[m + k - 1]); m += k
            closes = np.array(closes)
        if len(closes) < 22: return None
        ema = closes[0]; em = []
        for v in closes: ema = ema + (v - ema) * 2 / 21; em.append(ema)
        up = closes[-1] > em[-1] and em[-1] > em[-2]; dn = closes[-1] < em[-1] and em[-1] < em[-2]
        return 1 if up else -1 if dn else 0
    e13 = {}
    for d in C:
        for side, dv in sides:
            xs = [x for x in S[d] if x["dir"] == dv]
            for tf in (15, 30, 60, "day"):
                lab_ = {id(x): htf_label(x, tf) for x in xs}
                for nm, keep in (("A ignore", lambda z: True), ("B same direction", lambda z: z == dv),
                                 ("against", lambda z: z == -dv), ("neutral", lambda z: z == 0)):
                    ys = [x for x in xs if lab_[id(x)] is not None and keep(lab_[id(x)])]
                    tr, _ = L.book(ctx, ys, C[d][1], L.BASE)
                    e13[f"{d} {side} {tf} {nm}"] = dict(n=len(ys), sig=L.summarize([L.ctrl_excess(ctx, x, "eod")[1] for x in ys]),
                                                         eod=L.summarize([per_signal(ctx, x, C[d][1], EOD) for x in ys]), book=L.stats(tr))
    R["EXP-013"] = dict(cells=len(e13), note="C (counter-trend needs a larger expected move) and D (HTF for strike choice) not run: there is no expected-move signal to scale (EXP-007) and no strike with an edge to choose (EXP-008).", table=e13)
    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)   # partial results survive a crash

    # ---------------- EXP-014: phase 21, volatility regime (realised vol tertiles of the previous 20 sessions)
    def rvol(x):
        j = ctx.di[ctx.day[x["i"]]]
        if j < 21: return None
        r_ = np.diff(np.log(ctx.dC[j - 21:j])); return float(r_.std() * math.sqrt(252))
    e14 = {}
    for d in C:
        for side, dv in sides:
            xs = [x for x in S[d] if x["dir"] == dv]
            e14[f"{d} {side} rvol20"] = quint(ctx, xs, C[d][1], rvol, "rvol20")
    R["EXP-014"] = e14
    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)   # partial results survive a crash

    # ---------------- EXP-015: phase 22, gaps, previous day, expiry week / day (calendar known before entry)
    def gap(x):
        j = ctx.di[ctx.day[x["i"]]]; return (ctx.dO[j] - ctx.dC[j - 1]) / ctx.atr20[j] if j else None
    def prev_trend(x):
        j = ctx.di[ctx.day[x["i"]]]; return x["dir"] * (ctx.dC[j - 1] - ctx.dO[j - 1]) / ctx.atr20[j] if j else None
    def prev_range(x):
        j = ctx.di[ctx.day[x["i"]]]; return (ctx.dH[j - 1] - ctx.dL[j - 1]) / ctx.atr20[j] if j else None
    e15 = {}
    for d in C:
        for side, dv in sides:
            xs = [x for x in S[d] if x["dir"] == dv]
            e15[f"{d} {side} gap_atr"] = quint(ctx, xs, C[d][1], gap, "gap")
            e15[f"{d} {side} prev_day_trend_with_signal"] = quint(ctx, xs, C[d][1], prev_trend, "prev_trend")
            e15[f"{d} {side} prev_range_atr"] = quint(ctx, xs, C[d][1], prev_range, "prev_range")
            for nm, keep in (("weekly expiry day", lambda x: ctx.expiry(ctx.day[x["i"]], "WEEKLY", 0) == ctx.day[x["i"]]),
                             ("weekly expiry week (<= 2 days)", lambda x: (np.datetime64(ctx.expiry(ctx.day[x["i"]], "WEEKLY", 0)) - np.datetime64(ctx.day[x["i"]])).astype(int) <= 2),
                             ("monthly expiry week", lambda x: (np.datetime64(ctx.expiry(ctx.day[x["i"]], "MONTHLY", 0)) - np.datetime64(ctx.day[x["i"]])).astype(int) <= 6)):
                ys = [x for x in xs if ctx.expiry(ctx.day[x["i"]], "WEEKLY", 0) and keep(x)]
                zs = [x for x in xs if ctx.expiry(ctx.day[x["i"]], "WEEKLY", 0) and not keep(x)]
                e15[f"{d} {side} {nm}"] = dict(yes=dict(n=len(ys), sig=L.summarize([L.ctrl_excess(ctx, x, "eod")[1] for x in ys]),
                                                        eod=L.summarize([per_signal(ctx, x, C[d][1], EOD) for x in ys])),
                                               no=dict(n=len(zs), sig=L.summarize([L.ctrl_excess(ctx, x, "eod")[1] for x in zs]),
                                                       eod=L.summarize([per_signal(ctx, x, C[d][1], EOD) for x in zs])))
    R["EXP-015"] = dict(note="no scheduled-event calendar in the data: events not analysed", table=e15)
    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)   # partial results survive a crash

    # ---------------- EXP-016: phases 16/23/24/27, execution and parameter robustness of the baseline book
    e16 = {}
    for d in C:
        xs = [x for x in S[d] if x["dir"] == -1]
        for nm, kw, X in (("entry next open (baseline)", {}, L.BASE), ("entry next candle close", dict(entry_at="close"), L.BASE),
                          ("+1 candle delay", dict(entry_delay=1), L.BASE), ("+2 candle delay", dict(entry_delay=2), L.BASE),
                          ("slippage 1 pt", {}, dict(L.BASE, slip=1.0)), ("slippage 2 pts", {}, dict(L.BASE, slip=2.0)),
                          ("stops by touch", {}, dict(L.BASE, fill="touch"))):
            tr, _ = L.book(ctx, xs, C[d][1], X, **kw); e16[f"{d} bearish {nm}"] = L.stats(tr)
        for s_ in (4, 4.5, 5.5, 6):
            tr, _ = L.book(ctx, xs, C[d][1], dict(L.BASE, stop_pct=s_)); e16[f"{d} bearish stop {s_}%"] = L.stats(tr)
        for tp in (4, 4.5, 5.5, 6):
            tr, _ = L.book(ctx, xs, C[d][1], dict(L.BASE, trail_pts=tp)); e16[f"{d} bearish trail {tp} pts"] = L.stats(tr)
    R["EXP-016"] = e16
    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)   # partial results survive a crash

    # ---------------- EXP-017: phases 15 + 29, walk-forward selection (the only selecting section)
    e17 = {}
    for d in C:
        for side, dv in sides:
            # signal level: choose the band with the best 2021 excess to the close, apply it to 2022, then 2021-22 -> 2023
            for train, test in ((("2021",), "2022"), (("2021", "2022"), "2023")):
                best, bestv = None, -1e9
                for bw in (20, 25, 35, 50, 75, 100):
                    xs = [x for x in L.signals(C[d][0], band=bw) if x["dir"] == dv and x["time"][:4] in train]
                    s = L.summarize([L.ctrl_excess(ctx, x, "eod")[1] for x in xs])
                    if s.get("mean") is not None and s["mean"] > bestv: best, bestv = bw, s["mean"]
                ts = [x for x in L.signals(C[d][0], band=best) if x["dir"] == dv and x["time"][:4] == test]
                e17[f"{d} {side} band {'+'.join(train)} -> {test}"] = dict(chosen=best, train_mean=round(bestv, 2),
                                                                       test=L.summarize([L.ctrl_excess(ctx, x, "eod")[1] for x in ts]))
            # option level: choose the exit variant with the best 2021 book net, apply it to 2022
            xs = [x for x in S[d] if x["dir"] == dv]
            best, bestv = None, -1e18
            for nm, X in V.items():
                tr, _ = L.book(ctx, [x for x in xs if x["time"][:4] == "2021"], C[d][1], X)
                nv = L.stats(tr).get("net", -1e18)
                if nv is not None and nv > bestv: best, bestv = nm, nv
            tr, _ = L.book(ctx, [x for x in xs if x["time"][:4] == "2022"], C[d][1], V[best])
            e17[f"{d} {side} exit 2021 -> 2022"] = dict(chosen=best, train_net=bestv, test=L.stats(tr))
    R["EXP-017"] = e17

    json.dump(R, open(os.path.join(OUT, "run_rest.json"), "w"), indent=1, default=float)
    print("wrote run_rest.json")


if __name__ == "__main__":
    main()
