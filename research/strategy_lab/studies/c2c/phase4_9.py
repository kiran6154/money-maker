"""C2C research, phases 4-9 on development years (ledger EXP-004): Question B - does the NIFTY move after a CHoCH retest
signal pay for the option?

For every signal of phase3_dev.py (R-A and R-B, bearish -> long PE, bullish -> long CE; 2021-2023 only, nothing later is
loaded) and every option in a fixed grid - strike ATM / ITM1 / ITM2 / OTM1 / OTM2 from the index close of the signal candle,
expiry = nearest weekly, the weekly after it, nearest monthly >= 15 days - the option is bought at the open of its candle at
the entry time (the next candle; only an exact-time candle, never a stale print; entries on the 09:15 print are excluded)
and valued at the close of its candle at 15, 30, 60, 120, 240 minutes and the session's close (exact candle, else the last
print that session, flagged stale).

Per option and horizon: premium, intrinsic / extrinsic, DTE (calendar days to 15:30 on expiry), Black-Scholes implied vol
(r = 6.5 %, no dividend; the entry candle's open against the index open), delta / gamma / theta / vega, the NIFTY move, the
actual option change, the Greek decomposition (delta, gamma, theta, vega, residual), costs (the lab's Zerodha option charges
for one 65-unit lot, per unit, + 0.5 pt slippage per side - current schedule applied to every year: a sensitivity, not
history), and the required NIFTY move: the favourable move x with |delta| x + gamma x^2 / 2 = expected extrinsic decay over
the horizon + costs, where expected decay = extrinsic x (1 - (T1/T0)^alpha), alpha = 0.5 (D1).
Decay (D6): the realised extrinsic change of the same trades, per DTE bucket, and alpha fitted per bucket from
ln(E1/E0) = alpha ln(T1/T0) - it also absorbs IV changes, so it is an upper-bound calibration, reported as such.

    python studies/c2c/phase4_9.py      # writes studies/c2c/phase4_9.json and studies/c2c/option_trades.csv
Nothing here writes to the lab's results, database or strategy files.
"""
import bisect, csv, datetime as D, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab  # noqa: E402
import phase3_dev as P3  # noqa: E402

R_RATE, ALPHA0, LOT, SLIP = 0.065, 0.5, 65, 0.5
H_MIN = (15, 30, 60, 120, 240)
CHOICES = ("ATM", "ITM1", "ITM2", "OTM1", "OTM2")
EXPIRIES = (("W0", "WEEKLY", 0), ("W1", "WEEKLY", 7), ("M15", "MONTHLY", 15))
DTE_BUCKETS = ((0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, 20), (20, 30), (30, 60))
OUT = os.path.dirname(os.path.abspath(__file__))
N = lambda x: 0.5 * (1 + math.erf(x / math.sqrt(2)))
n_ = lambda x: math.exp(-x * x / 2) / math.sqrt(2 * math.pi)


def bs(S, K, T, sig, right):
    if T <= 0 or sig <= 0: return max(S - K, 0) if right == "CE" else max(K - S, 0)
    d1 = (math.log(S / K) + (R_RATE + sig * sig / 2) * T) / (sig * math.sqrt(T)); d2 = d1 - sig * math.sqrt(T)
    if right == "CE": return S * N(d1) - K * math.exp(-R_RATE * T) * N(d2)
    return K * math.exp(-R_RATE * T) * N(-d2) - S * N(-d1)


def iv(price, S, K, T, right):
    lo, hi = 1e-4, 3.0
    if T <= 0 or price <= bs(S, K, T, lo, right) + 1e-6 or price >= bs(S, K, T, hi, right): return None
    for _ in range(80):
        m = (lo + hi) / 2
        if bs(S, K, T, m, right) > price: hi = m
        else: lo = m
    return (lo + hi) / 2


def greeks(S, K, T, sig, right):
    d1 = (math.log(S / K) + (R_RATE + sig * sig / 2) * T) / (sig * math.sqrt(T)); d2 = d1 - sig * math.sqrt(T)
    delta = N(d1) if right == "CE" else N(d1) - 1
    gamma = n_(d1) / (S * sig * math.sqrt(T))
    vega = S * n_(d1) * math.sqrt(T) / 100                                   # per 1 vol point
    th = -S * n_(d1) * sig / (2 * math.sqrt(T))
    th += (-R_RATE * K * math.exp(-R_RATE * T) * N(d2)) if right == "CE" else (R_RATE * K * math.exp(-R_RATE * T) * N(-d2))
    return delta, gamma, th / 365, vega                                      # theta per calendar day


def years_to(expiry, t):
    return max((D.datetime.fromisoformat(expiry + " 15:30:00") - D.datetime.fromisoformat(t)).total_seconds(), 0) / (365 * 86400)


_RC = {}
def research_ok(e):
    """Only expiries fetched by tools/breeze_options.py --research to completion (research_chain.json complete): strikes from
    decision-time spot. The older five-strikes-around-settlement files are never used - a trade priced only when its strike
    happens to be in them is priced only when NIFTY ended near it (hindsight)."""
    if e not in _RC:
        f = os.path.join(lab.DATA["options"]["weekly_dir"], "nifty_options", e[:4], e, "research_chain.json")
        _RC[e] = os.path.exists(f) and bool(json.load(open(f, encoding="utf-8")).get("complete"))
    return _RC[e]


def bucket(dte):
    return next((f"{a}-{b}" for a, b in DTE_BUCKETS if a <= dte < b), "60+")


def main():
    b = P3.load()
    t, o, c = b["t"], b["o"], b["c"]; n = len(t)
    day = [x[:10] for x in t]
    last_of = [0] * n; s = 0
    for i in range(n):
        if i == n - 1 or day[i + 1] != day[i]:
            for j in range(s, i + 1): last_of[j] = i
            s = i + 1
    row = dict(lab.type_rows(lab.load_strategies()[0][1])[1], timeframe="5minute")
    chain = lab.OptionChain(row)
    cs = dict(lab.connect().execute("select * from charge_schedule where code='ZERODHA_NFO_OPT'").fetchone())
    unit_cost = lambda buy, sell: lab.trade_charges(cs, buy, sell, LOT)["total"] / LOT + 2 * SLIP
    exp_cache, trades, cover = {}, [], {}
    for defname, fn in (("R-A", P3.run_ra), ("R-B", P3.run_rb)):
        sig, _ = fn(b)
        for x in sig:
            i = x["i"]
            if i + 1 >= n or day[i + 1] != day[i]: continue                 # no entry on the 09:15 print
            te, S0, right = t[i + 1], o[i + 1], ("PE" if x["dir"] < 0 else "CE")
            for ek, kind, md in EXPIRIES:
                key = (day[i], kind, md)
                if key not in exp_cache: exp_cache[key] = chain.expiry_for(day[i], md, kind)
                e = exp_cache[key]
                for ch in CHOICES:
                    k = int(lab.pick_strike(ch, right, c[i], 0, 50))
                    cv = cover.setdefault((defname, ek, ch), [0, 0]); cv[0] += 1
                    ser = chain.get(e, k, right) if e and research_ok(e) else None
                    j0 = ser.ix.get(te) if ser else None
                    if j0 is None: continue                                   # no exact-time candle at entry
                    cv[1] += 1
                    P0 = ser.o[j0]; T0 = years_to(e, te)
                    intr0 = max(S0 - k, 0) if right == "CE" else max(k - S0, 0)
                    sg0 = iv(P0, S0, k, T0, right)
                    rec = dict(defn=defname, dir=x["dir"], signal_time=x["time"], entry_time=te, right=right, expiry_kind=ek,
                               expiry=e, choice=ch, strike=k, spot=S0, premium=P0, intrinsic=round(intr0, 2),
                               extrinsic=round(P0 - intr0, 2), dte=round(T0 * 365, 3), dte_bucket=bucket(T0 * 365),
                               iv=round(sg0, 4) if sg0 else None)
                    if sg0:
                        dl, gm, th, vg = greeks(S0, k, T0, sg0, right)
                        rec.update(delta=round(dl, 4), gamma=round(gm, 6), theta_day=round(th, 3), vega=round(vg, 3))
                    for hm in H_MIN + ("eod",):
                        ix = last_of[i + 1] if hm == "eod" else min(i + hm // 5, last_of[i + 1])
                        tx, S1 = t[ix], c[ix]
                        jx = ser.ix.get(tx); stale = jx is None
                        if stale:
                            jj = bisect.bisect_right(ser.t, tx) - 1
                            if jj < j0 or ser.t[jj][:10] != tx[:10]: continue
                            jx = jj
                        P1 = ser.c[jx]; T1 = years_to(e, tx)
                        intr1 = max(S1 - k, 0) if right == "CE" else max(k - S1, 0)
                        cost = unit_cost(P0, P1)
                        h = dict(move=round(x["dir"] * (S1 - S0), 2), opt=round(P1 - P0, 2), net=round(P1 - P0 - cost, 2),
                                 ext1=round(P1 - intr1, 2), cost=round(cost, 2), stale=stale, t1=round(T1 * 365, 3))
                        if sg0:
                            sg1 = iv(P1, S1, k, T1, right) if T1 > 0 else None
                            dS, dt_d = S1 - S0, (T0 - T1) * 365
                            h.update(p_delta=round(dl * dS, 2), p_gamma=round(0.5 * gm * dS * dS, 2), p_theta=round(th * dt_d, 2))
                            if sg1: h.update(p_vega=round(vg * (sg1 - sg0) * 100, 2), iv1=round(sg1, 4))
                            h["p_resid"] = round(h["opt"] - h["p_delta"] - h["p_gamma"] - h["p_theta"] - h.get("p_vega", 0), 2)
                            decay = max(rec["extrinsic"], 0) * (1 - (T1 / T0) ** ALPHA0) if T0 > 0 else 0
                            need = decay + cost; ad = abs(dl)
                            xreq = (-ad + math.sqrt(ad * ad + 2 * gm * need)) / gm if gm > 0 else need / max(ad, 1e-9)
                            h.update(exp_decay=round(decay, 2), req_move=round(xreq, 2), enough=h["move"] >= xreq)
                        rec[str(hm)] = h
                    trades.append(rec)
    # ---- summaries
    def agg(rs, hk):
        hs = [r[hk] for r in rs if hk in r]
        if not hs: return None
        f = lambda k: np.array([q[k] for q in hs if k in q], float)
        out = dict(n=len(hs), stale=int(sum(q["stale"] for q in hs)))
        for k in ("move", "opt", "net", "cost", "exp_decay", "req_move", "p_delta", "p_gamma", "p_theta", "p_vega", "p_resid"):
            v = f(k)
            if len(v): out[k] = round(float(v.mean()), 2)
        v = f("net"); out["net_median"] = round(float(np.median(v)), 2); out["win"] = round(float((v > 0).mean() * 100), 1)
        out["t_net"] = round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2) if len(v) > 2 and v.std() > 0 else None
        en = [q["enough"] for q in hs if "enough" in q]
        if en: out["pct_move_enough"] = round(100 * sum(en) / len(en), 1)
        return out

    res = dict(r=R_RATE, alpha0=ALPHA0, lot=LOT, slip=SLIP, coverage={f"{a} {b_} {c_}": v for (a, b_, c_), v in cover.items()},
               grid={}, decay={})
    for defname in ("R-A", "R-B"):
        for side in ("bearish", "bullish"):
            dv = -1 if side == "bearish" else 1
            for ek, _, _ in EXPIRIES:
                for ch in CHOICES:
                    rs = [r for r in trades if r["defn"] == defname and r["dir"] == dv and r["expiry_kind"] == ek and r["choice"] == ch]
                    if not rs: continue
                    g = res["grid"].setdefault(f"{defname} {side} {ek} {ch}", dict(
                        n=len(rs), premium=round(float(np.mean([r["premium"] for r in rs])), 2),
                        extrinsic=round(float(np.mean([r["extrinsic"] for r in rs])), 2), dte=round(float(np.mean([r["dte"] for r in rs])), 2),
                        iv=round(float(np.nanmean([r["iv"] or np.nan for r in rs])), 4),
                        delta=round(float(np.nanmean([r.get("delta", np.nan) for r in rs])), 3),
                        theta_day=round(float(np.nanmean([r.get("theta_day", np.nan) for r in rs])), 2)))
                    for hk in [str(h) for h in H_MIN] + ["eod"]: g[hk] = agg(rs, hk)
    # D6: realised extrinsic decay vs the sqrt model, per DTE bucket (every trade, 60 min and to the close)
    for hk in ("60", "eod"):
        for bk in sorted({r["dte_bucket"] for r in trades}):
            rs = [r for r in trades if r["dte_bucket"] == bk and hk in r and r["extrinsic"] > 0.5 and r[hk]["ext1"] > 0.05]
            if len(rs) < 20: continue
            e0 = np.array([r["extrinsic"] for r in rs]); e1 = np.array([r[hk]["ext1"] for r in rs])
            T0 = np.array([r["dte"] for r in rs]); T1 = np.array([r[hk]["t1"] for r in rs])
            ok = (T1 > 0) & (T1 < T0)
            lr, lt = np.log(e1[ok] / e0[ok]), np.log(T1[ok] / T0[ok])
            res["decay"][f"{hk} {bk}"] = dict(n=int(ok.sum()), ext0=round(float(e0.mean()), 2),
                                              actual_change=round(float((e1 - e0).mean()), 2),
                                              sqrt_model_change=round(float((e0 * ((T1 / np.maximum(T0, 1e-9)) ** ALPHA0 - 1)).mean()), 2),
                                              alpha_fit=round(float((lt * lr).sum() / (lt * lt).sum()), 2) if ok.sum() > 5 else None)
    # D6 control: the same extrinsic change from ATM entries every 30 minutes of every session (both rights), no signal -
    # separates a market-wide intraday pattern from anything the signals select
    ctl = {}
    for i in range(1, n - 1):
        if day[i] != day[i - 1] or t[i][14:16] not in ("15", "45") or day[i + 1] != day[i]: continue
        for ek, kind, md in EXPIRIES:
            key = (day[i], kind, md)
            if key not in exp_cache: exp_cache[key] = chain.expiry_for(day[i], md, kind)
            e = exp_cache[key]
            if not e or not research_ok(e): continue
            for right in ("CE", "PE"):
                k = int(lab.pick_strike("ATM", right, c[i - 1], 0, 50))
                ser = chain.get(e, k, right); j0 = ser.ix.get(t[i]) if ser else None
                if j0 is None: continue
                S0, P0, T0 = o[i], ser.o[j0], years_to(e, t[i])
                e0 = P0 - (max(S0 - k, 0) if right == "CE" else max(k - S0, 0))
                for hk, ix in (("60", min(i + 11, last_of[i])), ("eod", last_of[i])):
                    jx = ser.ix.get(t[ix])
                    if jx is None or e0 <= 0.5: continue
                    e1 = ser.c[jx] - (max(c[ix] - k, 0) if right == "CE" else max(k - c[ix], 0))
                    ctl.setdefault(f"{hk} {bucket(T0 * 365)}", []).append((e0, e1, t[i][11:16]))
    for key, v in sorted(ctl.items()):
        a = np.array([(x[0], x[1]) for x in v])
        res["decay"].setdefault(key, {})["control"] = dict(n=len(v), ext0=round(float(a[:, 0].mean()), 2),
                                                             actual_change=round(float((a[:, 1] - a[:, 0]).mean()), 2))
    tod = {}
    for key, v in ctl.items():
        if not key.startswith("eod"): continue
        for e0, e1, hm in v: tod.setdefault(hm[:2], []).append(e1 - e0)
    res["decay_to_close_by_entry_hour"] = {h: dict(n=len(v), change=round(float(np.mean(v)), 2)) for h, v in sorted(tod.items())}
    json.dump(res, open(os.path.join(OUT, "phase4_9.json"), "w"), indent=1)
    flat = []
    for r in trades:
        base = {k: v for k, v in r.items() if not isinstance(v, dict)}
        for hk in [str(h) for h in H_MIN] + ["eod"]:
            if hk in r: flat.append(dict(base, horizon=hk, **r[hk]))
    cols = sorted({k for f in flat for k in f}, key=lambda k: list(flat[0]).index(k) if k in flat[0] else 999)
    with open(os.path.join(OUT, "option_trades.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(flat)
    print(f"{len(trades)} option entries priced; coverage (priced / asked) " +
          ", ".join(f"{k}: {v[1]}/{v[0]}" for k, v in list(res["coverage"].items())[:6]))


if __name__ == "__main__":
    main()
