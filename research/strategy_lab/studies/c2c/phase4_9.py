"""C2C research, phases 4-9 on development years (ledger EXP-004): Question B - does the NIFTY move after a CHoCH retest
signal pay for the option?

Signals: phase3_dev.py's R-A and R-B (bearish -> long PE, bullish -> long CE), 2021-2023 only; nothing later is loaded.
Option grid per signal: strike ATM / ITM1 / ITM2 / OTM1 / OTM2 from the index close of the signal candle; expiry = nearest
weekly (W0), the weekly after it (W1), nearest monthly >= 15 days (M15). Only expiries fetched by
`tools/breeze_options.py --research` to completion are priced (strikes from decision-time spot; the older
five-strikes-around-settlement files are never used - that would price a trade only when NIFTY ended near its strike).
Bought at the open of the option's candle at the entry time (the next candle; an exact-time candle only; no entry on the
09:15 print); valued at the close of its candle at 15, 30, 60, 120, 240 minutes and the session's close (exact candle, else
the last print that session, flagged stale).

Price change split exactly (Black-Scholes, r = 6.5 %, no dividend, calendar time to 15:30 on expiry, IV implied from the
traded price against the index):
  time = BS(S0, T1, iv0) - BS(S0, T0, iv0)      spot and IV held
  spot = BS(S1, T1, iv0) - BS(S0, T1, iv0)      the NIFTY move at the entry IV
  vol  = P1 - BS(S1, T1, iv0)                   the IV change (and anything BS misses)
(An earlier version measured decay as the change of extrinsic value against spot intrinsic; that mixes in the moneyness
change - an ATM option's extrinsic falls ~|move|/2 whichever way NIFTY moves - and was withdrawn, ledger EXP-004.)

D6 empirical decay: a control with no signal - ATM CE and PE bought at every :15 and :45 candle of every session of the
same expiries - split the same way; its mean time + vol per (DTE bucket, entry hour, horizon) is the expected carry. The
required NIFTY move of a trade: the favourable move x with |delta| x + gamma x^2 / 2 = -expected carry + costs (costs = the
lab's Zerodha option charges for one 65-unit lot, per unit, + 0.5 pt slippage per side; today's schedule for every year - a
sensitivity, not history). The carry is ATM's, applied to every strike of the grid (an approximation, reported beside the
trades' own time + vol). All of it is in-sample on the development years.

    python studies/c2c/phase4_9.py      # writes studies/c2c/phase4_9.json and studies/c2c/option_trades.csv
Nothing here writes to the lab's results, database or strategy files.
"""
import bisect, csv, datetime as D, json, math, os, sys
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lab  # noqa: E402
import phase3_dev as P3  # noqa: E402

R_RATE, LOT, SLIP = 0.065, 65, 0.5
H_MIN = (15, 30, 60, 120, 240)
HKEYS = [str(h) for h in H_MIN] + ["eod"]
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
    vega = S * n_(d1) * math.sqrt(T) / 100
    th = -S * n_(d1) * sig / (2 * math.sqrt(T))
    th += (-R_RATE * K * math.exp(-R_RATE * T) * N(d2)) if right == "CE" else (R_RATE * K * math.exp(-R_RATE * T) * N(-d2))
    return delta, gamma, th / 365, vega


def years_to(expiry, t):
    return max((D.datetime.fromisoformat(expiry + " 15:30:00") - D.datetime.fromisoformat(t)).total_seconds(), 0) / (365 * 86400)


def bucket(dte):
    return next((f"{a}-{b}" for a, b in DTE_BUCKETS if a <= dte < b), "60+")


_RC = {}
def research_ok(e):
    if e not in _RC:
        f = os.path.join(lab.DATA["options"]["weekly_dir"], "nifty_options", e[:4], e, "research_chain.json")
        _RC[e] = os.path.exists(f) and bool(json.load(open(f, encoding="utf-8")).get("complete"))
    return _RC[e]


def main():
    b = P3.load()
    t, o, c = b["t"], b["o"], b["c"]; n = len(t)
    day = [x[:10] for x in t]
    last_of = [0] * n; s = 0
    for i in range(n):
        if i == n - 1 or day[i + 1] != day[i]:
            for j in range(s, i + 1): last_of[j] = i
            s = i + 1
    chain = lab.OptionChain(dict(lab.type_rows(lab.load_strategies()[0][1])[1], timeframe="5minute"))
    cs = json.load(open(lab.CHARGECFG, encoding="utf-8"))["ZERODHA_NFO_OPT"]   # the file, not the db (a lab run may hold its lock)
    unit_cost = lambda buy, sell: lab.trade_charges(cs, buy, sell, LOT)["total"] / LOT + 2 * SLIP
    exp_cache = {}

    def expiry(d, kind, md):
        if (d, kind, md) not in exp_cache: exp_cache[(d, kind, md)] = chain.expiry_for(d, md, kind)
        return exp_cache[(d, kind, md)]

    def value(e, k, right, i_entry, sign):
        """Entry at the open of candle i_entry (exact-time option candle), valued at each horizon. None if not priceable."""
        if not e or not research_ok(e): return None
        ser = chain.get(e, k, right)
        te = t[i_entry]; j0 = ser.ix.get(te) if ser else None
        if j0 is None: return None
        S0, P0, T0 = o[i_entry], ser.o[j0], years_to(e, te)
        sg0 = iv(P0, S0, k, T0, right)
        rec = dict(entry_time=te, spot=S0, premium=P0, strike=k, right=right, expiry=e,
                   intrinsic=round(max(S0 - k, 0) if right == "CE" else max(k - S0, 0), 2), dte=round(T0 * 365, 3),
                   dte_bucket=bucket(T0 * 365), hour=te[11:13], iv=round(sg0, 4) if sg0 else None)
        rec["extrinsic"] = round(P0 - rec["intrinsic"], 2)
        if sg0:
            dl, gm, th, vg = greeks(S0, k, T0, sg0, right)
            rec.update(delta=round(dl, 4), gamma=round(gm, 6), theta_day=round(th, 3), vega=round(vg, 3))
        for hk in HKEYS:
            ix = last_of[i_entry] if hk == "eod" else min(i_entry + int(hk) // 5 - 1, last_of[i_entry])
            tx, S1 = t[ix], c[ix]
            jx = ser.ix.get(tx); stale = jx is None
            if stale:
                jj = bisect.bisect_right(ser.t, tx) - 1
                if jj < j0 or ser.t[jj][:10] != tx[:10]: continue
                jx = jj
            P1, T1 = ser.c[jx], years_to(e, tx)
            cost = unit_cost(P0, P1)
            h = dict(move=round(sign * (S1 - S0), 2), opt=round(P1 - P0, 2), net=round(P1 - P0 - cost, 2), cost=round(cost, 2),
                     stale=stale)
            if sg0:
                a0 = bs(S0, k, T0, sg0, right); a1 = bs(S0, k, T1, sg0, right); a2 = bs(S1, k, T1, sg0, right)
                h.update(c_time=round(a1 - a0, 2), c_spot=round(a2 - a1, 2), c_vol=round(P1 - a2 - (P0 - a0), 2))
                sg1 = iv(P1, S1, k, T1, right) if T1 > 0 else None
                if sg1: h["iv_chg"] = round((sg1 - sg0) * 100, 2)
            rec[hk] = h
        return rec

    # ---- D6 control: ATM CE and PE at every :15 / :45 candle, no signal
    control = []
    for i in range(1, n):
        if day[i] != day[i - 1] or t[i][14:16] not in ("15", "45"): continue
        for ek, kind, md in EXPIRIES:
            e = expiry(day[i], kind, md)
            for right in ("CE", "PE"):
                r = value(e, int(lab.pick_strike("ATM", right, c[i - 1], 0, 50)), right, i, 1 if right == "CE" else -1)
                if r: control.append(dict(r, expiry_kind=ek))
    carry = {}
    for r in control:
        for hk in HKEYS:
            if hk in r and "c_time" in r[hk]:
                carry.setdefault((r["dte_bucket"], r["hour"], hk), []).append(r[hk]["c_time"] + r[hk]["c_vol"])
    carry_mean = {k: float(np.mean(v)) for k, v in carry.items() if len(v) >= 10}

    # ---- signals
    trades, cover = [], {}
    for defname, fn in (("R-A", P3.run_ra), ("R-B", P3.run_rb)):
        sig, _ = fn(b)
        for x in sig:
            i = x["i"]
            if i + 1 >= n or day[i + 1] != day[i]: continue                 # no entry on the 09:15 print
            right = "PE" if x["dir"] < 0 else "CE"
            for ek, kind, md in EXPIRIES:
                e = expiry(day[i], kind, md)
                for ch in CHOICES:
                    k = int(lab.pick_strike(ch, right, c[i], 0, 50))
                    cv = cover.setdefault(f"{defname} {ek} {ch}", [0, 0]); cv[0] += 1
                    r = value(e, k, right, i + 1, x["dir"])
                    if not r: continue
                    cv[1] += 1
                    r.update(defn=defname, dir=x["dir"], signal_time=x["time"], expiry_kind=ek, choice=ch)
                    if "delta" in r:
                        ad, gm = abs(r["delta"]), r["gamma"]
                        for hk in HKEYS:
                            if hk not in r: continue
                            cm = carry_mean.get((r["dte_bucket"], r["hour"], hk))
                            if cm is None: continue
                            need = max(-cm, 0) + r[hk]["cost"]
                            xreq = (-ad + math.sqrt(ad * ad + 2 * gm * need)) / gm if gm > 0 else need / max(ad, 1e-9)
                            r[hk].update(exp_carry=round(cm, 2), req_move=round(xreq, 2), enough=r[hk]["move"] >= xreq)
                    trades.append(r)

    # ---- summaries
    def agg(rs, hk):
        hs = [r[hk] for r in rs if hk in r]
        if not hs: return None
        f = lambda k: np.array([q[k] for q in hs if k in q], float)
        out = dict(n=len(hs), stale=int(sum(q["stale"] for q in hs)))
        for k in ("move", "opt", "net", "cost", "c_time", "c_spot", "c_vol", "iv_chg", "exp_carry", "req_move"):
            v = f(k)
            if len(v): out[k] = round(float(v.mean()), 2)
        v = f("net"); out["net_median"] = round(float(np.median(v)), 2); out["win"] = round(float((v > 0).mean() * 100), 1)
        out["t_net"] = round(float(v.mean() / (v.std(ddof=1) / math.sqrt(len(v)))), 2) if len(v) > 2 and v.std() > 0 else None
        m = f("move"); out["move_median"] = round(float(np.median(m)), 2)
        en = [q["enough"] for q in hs if "enough" in q]
        if en: out["pct_move_enough"] = round(100 * sum(en) / len(en), 1)
        return out

    def describe(rs):
        g = dict(n=len(rs), years=sorted({r["signal_time"][:4] if "signal_time" in r else r["entry_time"][:4] for r in rs}))
        for k in ("premium", "extrinsic", "dte", "iv", "delta", "gamma", "theta_day"):
            v = [r[k] for r in rs if r.get(k) is not None]
            if v: g[k] = round(float(np.mean(v)), 4 if k in ("iv", "delta", "gamma") else 2)
        for hk in HKEYS: g[hk] = agg(rs, hk)
        return g

    res = dict(r=R_RATE, lot=LOT, slip=SLIP, coverage=cover, grid={}, control={}, control_by_hour={})
    for defname in ("R-A", "R-B"):
        for side, dv in (("bearish", -1), ("bullish", 1)):
            for ek, _, _ in EXPIRIES:
                for ch in CHOICES:
                    rs = [r for r in trades if r["defn"] == defname and r["dir"] == dv and r["expiry_kind"] == ek and r["choice"] == ch]
                    if rs: res["grid"][f"{defname} {side} {ek} {ch}"] = describe(rs)
                for bk in sorted({r["dte_bucket"] for r in trades}):
                    rs = [r for r in trades if r["defn"] == defname and r["dir"] == dv and r["dte_bucket"] == bk and r["choice"] == "ITM1"]
                    if len(rs) >= 20: res["grid"][f"{defname} {side} ITM1 dte {bk}"] = describe(rs)
    for bk in sorted({r["dte_bucket"] for r in control}):
        for right in ("CE", "PE"):
            rs = [r for r in control if r["dte_bucket"] == bk and r["right"] == right]
            if rs: res["control"][f"{right} dte {bk}"] = describe(rs)
    for hr in sorted({r["hour"] for r in control}):
        rs = [r for r in control if r["hour"] == hr]
        res["control_by_hour"][hr] = {hk: agg(rs, hk) for hk in ("60", "eod")}
    json.dump(res, open(os.path.join(OUT, "phase4_9.json"), "w"), indent=1)
    flat = []
    for r in trades:
        base = {k: v for k, v in r.items() if not isinstance(v, dict)}
        for hk in HKEYS:
            if hk in r: flat.append(dict(base, horizon=hk, **r[hk]))
    cols = []
    for f_ in flat:
        for k in f_:
            if k not in cols: cols.append(k)
    with open(os.path.join(OUT, "option_trades.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(flat)
    print(f"{len(trades)} option entries priced, {len(control)} control entries; years {sorted({r['signal_time'][:4] for r in trades})}")


if __name__ == "__main__":
    main()
