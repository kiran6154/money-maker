"""C2C research on development years (ledger EXP-005, EXP-006). Nothing after 2023-12-31 is loaded.

EXP-005 (phase 12, baseline exits): the frozen Strategy 25 position rules on real option candles - ITM1 of the nearest
monthly >= 15 days, one position at a time per book, entry at the open of the option's candle after the signal (no 09:15
print), then c2c.hold: premium stop 5 %, trail 5 pts behind the peak premium once it has gained, the opposite flip exits,
the 15:15 ladder (profit > 40 %, loss > 2 %; no PCR rule - no full-chain OI before 2026), positional. Stops on the close and
by touch. Books: bearish -> long PE (the baseline) and bullish -> long CE (the mirror), under R-A and R-B. Options only from
expiries fetched by `tools/breeze_options.py --research` to completion; a signal on another expiry is skipped and counted.
Costs: today's Zerodha option charges for one 65-unit lot + 0.5 pt slippage a side; P&L in rupees per lot of 65.

EXP-006 (phase 7, flat markets): for every signal (index only, 2021-2023), one regime feature at a time, computed from
data before the signal: 20-session return, 20-session ATR, 20-session realised vol, ADX(14) of daily candles, 20-session
slope / ATR, distance from the 20-session mean / ATR, distance from the anchored VWAP / ATR(5-min), 5- over 20-session range
(compression), the previous session's range, today's range so far, today's return so far / daily ATR. Per quintile of each
feature (quintile edges from the development signals themselves - in-sample, descriptive): the mean and median NIFTY move to
the close in the signal's direction, the mean favourable excursion, and the share of signals whose move to the close reached
12 pts - roughly what EXP-004 found a monthly option needs to cover carry and costs. The question is whether a feature marks
signals that cannot move enough, not which quintile earns most.

    python studies/c2c/phase7_12.py
"""
import bisect, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab, c2c  # noqa: E402
import phase3_dev as P3  # noqa: E402
import phase4_9 as P4  # noqa: E402

LOT, SLIP, NEED = 65, 0.5, 12.0
CFG = dict(band_pts=50, day_drop_pct=0.6, pcr=None, stop_pct=5, trail_pts=5, stop_fill="close",
           ladder=dict(time="15:15", profit_pct=40, loss_pct=2), max_open=1)
OUT = os.path.dirname(os.path.abspath(__file__))


def book_stats(trs):
    if not trs: return dict(trades=0)
    net = np.array([x["net"] for x in trs]); eq = np.cumsum(net)
    dd = float((eq - np.maximum.accumulate(eq)).min())
    streak = lambda cond: max((len(s) for s in "".join("1" if cond(v) else "0" for v in net).split("0")), default=0)
    wins, loss = net[net > 0], net[net <= 0]
    hold = np.array([x["hold_min"] for x in trs])
    reasons = {}
    for x in trs: reasons[x["why"]] = reasons.get(x["why"], 0) + 1
    by_year = {}
    for x in trs: by_year.setdefault(x["entry_time"][:4], []).append(x["net"])
    return dict(trades=len(trs), win=round(float((net > 0).mean() * 100), 1), avg=round(float(net.mean()), 1),
                median=round(float(np.median(net)), 1), gross_profit=round(float(wins.sum()), 0), gross_loss=round(float(loss.sum()), 0),
                net=round(float(net.sum()), 0), pf=round(float(wins.sum() / -loss.sum()), 2) if loss.sum() < 0 else None,
                max_dd=round(dd, 0), worst=round(float(net.min()), 0), best=round(float(net.max()), 0),
                t=round(float(net.mean() / (net.std(ddof=1) / math.sqrt(len(net)))), 2) if len(net) > 2 else None,
                hold_min_avg=round(float(hold.mean()), 0), hold_min_median=round(float(np.median(hold)), 0),
                premium_avg=round(float(np.mean([x["premium"] for x in trs])), 1), dte_avg=round(float(np.mean([x["dte"] for x in trs])), 1),
                max_consec_loss=streak(lambda v: v <= 0), max_consec_win=streak(lambda v: v > 0), exits=reasons,
                years={y: dict(trades=len(v), net=round(sum(v), 0), win=round(100 * sum(1 for q in v if q > 0) / len(v), 1))
                       for y, v in sorted(by_year.items())})


def exp005(b):
    t, o, c = b["t"], b["o"], b["c"]; n = len(t); day = [x[:10] for x in t]
    chain = lab.OptionChain(dict(lab.type_rows(lab.load_strategies()[0][1])[1], timeframe="5minute"))
    cs = __import__("json").load(open(lab.CHARGECFG, encoding="utf-8"))["ZERODHA_NFO_OPT"]
    out = {}
    for defname, fn in (("R-A", P3.run_ra), ("R-B", P3.run_rb)):
        sig, fl = fn(b)
        ups = sorted(x for x, d in fl if d == "up"); downs = sorted(x for x, d in fl if d == "down")
        for side, dv, right, opp in (("bearish", -1, "PE", ups), ("bullish", 1, "CE", downs)):
            for fill in ("close", "touch"):
                cfg = dict(CFG, stop_fill=fill)
                trs, skipped, free_at = [], {}, ""
                for x in sorted((s for s in sig if s["dir"] == dv), key=lambda s: s["i"]):
                    i = x["i"]
                    if i + 1 >= n or day[i + 1] != day[i]: skipped["opening print"] = skipped.get("opening print", 0) + 1; continue
                    e = chain.expiry_for(day[i], 15, "MONTHLY")
                    if not e or not P4.research_ok(e): skipped["no research data"] = skipped.get("no research data", 0) + 1; continue
                    k = int(lab.pick_strike("ITM1", right, c[i], 0, 50))
                    ser = chain.get(e, k, right); j0 = ser.ix.get(t[i + 1]) if ser else None
                    if j0 is None: skipped["no option candle at entry"] = skipped.get("no option candle at entry", 0) + 1; continue
                    if ser.t[j0] <= free_at: skipped["position open"] = skipped.get("position open", 0) + 1; continue
                    iend = bisect.bisect_right(ser.t, f"{min(e, '2023-12-31')} 23:59:59") - 1
                    P0 = ser.o[j0]
                    kx, px, why, still, _, _ = c2c.hold(ser, j0, P0, cfg, opp, t[i], lambda T: None, iend)
                    if still and ser.t[kx][:10] >= e: why, still = "expiry", False
                    free_at = ser.t[kx]
                    chg = lab.trade_charges(cs, P0 + SLIP, px - SLIP, LOT)["total"]
                    net = (px - SLIP - (P0 + SLIP)) * LOT - chg
                    hm = (np.datetime64(ser.t[kx]) - np.datetime64(ser.t[j0])).astype("timedelta64[m]").astype(int)
                    trs.append(dict(entry_time=ser.t[j0], exit_time=ser.t[kx], premium=P0, exit_px=px, why=why, open=still,
                                    net=round(net, 1), hold_min=int(hm), dte=P4.years_to(e, ser.t[j0]) * 365))
                out[f"{defname} {side} {fill}"] = dict(stats=book_stats(trs), skipped=skipped)
    return out


def exp006(b):
    t, o, h, l, c = b["t"], *(np.array(b[k]) for k in "ohlc"); n = len(t); day = [x[:10] for x in t]
    # daily candles
    D = {}
    for i in range(n): D.setdefault(day[i], []).append(i)
    days = sorted(D)
    dO = np.array([o[D[d][0]] for d in days]); dH = np.array([h[D[d]].max() for d in days])
    dL = np.array([l[D[d]].min() for d in days]); dC = np.array([c[D[d][-1]] for d in days])
    tr = np.maximum(dH - dL, np.maximum(abs(dH - np.roll(dC, 1)), abs(dL - np.roll(dC, 1)))); tr[0] = dH[0] - dL[0]
    up, dn = dH - np.roll(dH, 1), np.roll(dL, 1) - dL
    pdm = np.where((up > dn) & (up > 0), up, 0.0); ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    def wilder(x, k=14):
        r = np.zeros_like(x); r[k] = x[1:k + 1].sum()
        for j in range(k + 1, len(x)): r[j] = r[j - 1] - r[j - 1] / k + x[j]
        return r
    atr14, p14, n14 = wilder(tr), wilder(pdm), wilder(ndm)
    with np.errstate(divide="ignore", invalid="ignore"):
        pdi, ndi = 100 * p14 / atr14, 100 * n14 / atr14; dx = 100 * abs(pdi - ndi) / (pdi + ndi)
    adx = np.zeros(len(days)); adx[27] = np.nanmean(dx[14:28])
    for j in range(28, len(days)): adx[j] = (adx[j - 1] * 13 + dx[j]) / 14
    di = {d: j for j, d in enumerate(days)}
    # 5-minute ATR(14) at each bar
    tr5 = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1)))); a5 = np.zeros(n); a = tr5[0]
    for i in range(n): a = tr5[:i + 1].mean() if i < 14 else (a * 13 + tr5[i]) / 14; a5[i] = a
    last_of = {d: D[d][-1] for d in days}
    rows = []
    for defname, fn in (("R-A", P3.run_ra), ("R-B", P3.run_rb)):
        sig, _ = fn(b)
        for x in sig:
            i = x["i"]; d = day[i]; j = di[d]
            if j < 30 or i + 1 >= n or day[i + 1] != d: continue
            p = slice(j - 20, j)                                      # the 20 sessions before today
            atr20 = float(tr[p].mean())
            ret = np.diff(np.log(dC[j - 21:j]))
            y = dC[p]; slope = np.polyfit(np.arange(20), y, 1)[0]
            s0 = D[d][0]
            e0 = o[i + 1]; L = last_of[d]; dv = x["dir"]
            move = dv * (c[L] - e0)
            mfe = (h[i + 1:L + 1].max() - e0) if dv > 0 else (e0 - l[i + 1:L + 1].min())
            rows.append(dict(defn=defname, dir=dv, move=move, mfe=mfe, f=dict(
                ret20=dC[j - 1] / dC[j - 21] - 1, atr20=atr20, rvol20=float(ret.std() * math.sqrt(252)), adx14=float(adx[j - 1]),
                slope20_atr=slope / atr20, dist_ma20_atr=(c[i] - y.mean()) / atr20, dist_avwap_atr5=x["dist_av"] / a5[i],
                compression=(dH[j - 5:j].max() - dL[j - 5:j].min()) / (dH[p].max() - dL[p].min()),
                prev_range=float(dH[j - 1] - dL[j - 1]), day_range=float(h[s0:i + 1].max() - l[s0:i + 1].min()),
                day_ret_atr=(c[i] - o[s0]) / atr20)))
    out = {}
    for defname in ("R-A", "R-B"):
        for side, dv in (("bearish", -1), ("bullish", 1)):
            rs = [r for r in rows if r["defn"] == defname and r["dir"] == dv]
            for feat in rs[0]["f"]:
                v = np.array([r["f"][feat] for r in rs]); edges = np.quantile(v, [0.2, 0.4, 0.6, 0.8])
                q = np.searchsorted(edges, v, side="right")
                cells = []
                for k in range(5):
                    m = np.array([r["move"] for r, qq in zip(rs, q) if qq == k]); f_ = np.array([r["mfe"] for r, qq in zip(rs, q) if qq == k])
                    cells.append(dict(n=len(m), lo=round(float(v[q == k].min()), 4), hi=round(float(v[q == k].max()), 4),
                                      move=round(float(m.mean()), 1), median=round(float(np.median(m)), 1), mfe=round(float(f_.mean()), 1),
                                      reach=round(float((m >= NEED).mean() * 100), 1),
                                      t=round(float(m.mean() / (m.std(ddof=1) / math.sqrt(len(m)))), 2)))
                out[f"{defname} {side} {feat}"] = cells
    return out


def main():
    b = P3.load()
    res = dict(need_pts=NEED, exp005=exp005(b), exp006=exp006(b))
    json.dump(res, open(os.path.join(OUT, "phase7_12.json"), "w"), indent=1)
    print("wrote phase7_12.json")


if __name__ == "__main__":
    main()
