"""Jilly's ORB + Noise Band read DIRECTLY on the option's own 1-minute chart (family module for ST112 / ST113).

Built 2026-10-25 at the user's word after Strategies 110 / 111: "try applying this directly on options instead of the future".
Strategies 110 / 111 read every rule on the near-month future and only bought the option. Here the rules of jilly.py run on
the option's candles; BUILD marks what the futures spec does not carry over and had to be chosen:

  the legs        BUILD: each session, the day-open ATM (the index's 09:15 open rounded to 50; `strike`: ATM, or ITM1 = 50
                  points in the money; or PREM - ST121 / ST122, the user: "stick to an opening range of 100 - 250, not just
                  ATM" - the strike nearest the money whose 09:15 open is between prem_lo and prem_hi, none in range: no trade
                  on that side) CE and PE of the nearest weekly expiry on or after today. Each leg is its own chart and
                  can trade once a day; both may trade the same day.
  the side        (`sides`) "buy" (ST112 / ST113): a leg trades its UPSIDE breakout - the close above ORH + 0.3 ATR, above
                  UB(key) and above VWAP at a checkpoint - by buying it. "both" (ST119 / ST120, the user: "apply it directly on
                  ATM, both sides, and trade both sides"): the DOWNSIDE breakdown - the close below ORL - 0.3 ATR, below
                  LB(key) = min(O, PC) x (1 - band_k x sigma) and below VWAP - SELLS the leg; stop above (fill + stop_atr x ATR,
                  or the OR midpoint), target below (floored at 0.05). Either way the first signal per leg per day.
  structure       (`struct`, ST121, the user: "take trades outside protected levels") the Foundation engine (`struct_rules`,
                  Strategy 1's) on the leg's own candles: the leg's trend = the side of its last CHoCH; a BUY is taken only
                  when the leg's structure is bullish (trading above its protected swing low), a SELL only when bearish.
  trail           (`trail`: "prot", `trail_after`: 30, the user: "SL once profit reaches 30 points ... trail by protected
                  level") once the trade is `trail_after` premium points in profit (on its best high / low), the stop moves
                  to the leg's protected level whenever the structure is on the trade's side and that level is beyond the
                  current stop; it never loosens. A stop hit after a move is "trail_stop".
  O, PC, UP       O = the leg's 09:15 open; PC = the same contract's last close of the previous session; UP = max(O, PC);
                  UP = O when the contract has no candles the previous session (the new-contract rule). A leg without a
                  09:15 candle does not trade that day.
  sigma(m)        BUILD: the mean over the prior 20 sessions of |close(m) / open - 1| of THAT session's day-open ATM option
                  of the same right (the typical intraday path of an at-the-money premium, not one contract's - a weekly
                  contract does not have 20 sessions behind it); UB(m) = UP x (1 + band_k x sigma(m)).
  vol filter      (`filter`) today's sigma(30) of the leg ranked against the previous 250 sessions' (rank < 0.20: skip).
  OR, ATR, VWAP   the leg's own: keys 1..15; ATR(9) Wilder on the contract's 5-minute bars from its first candle in the
                  window read (up to 10 sessions back); VWAP of hlc3 with the option's volume.
  exits           on the option: `stop` "atr": fill - stop_atr x ATR (floored at 0.05) and target_r x that distance;
                  "orm": the leg's OR midpoint and target_r x |fill - ORM|. A touch exits at the next minute's open (both:
                  the stop); flat at the 15:20 open. Costs: max(0.5, 0.5% of the premium) a side; option charges by date
                  (jilly.py). Data: the download store, options from 2020-02.
"""
import datetime as Dt
import os
import numpy as np
import core
import store_reader

ENTRY_RULES = ("jilly_orb_noise_opt_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT",)
OWN_COVERAGE = True
REFUSED_WHY = "Strategies 112 / 113 read the rules on the option's own chart; only the Options type runs"
DAY = core.DAY
_J = core.family("jilly")


def _leg_candles(exp, k, right, day, back=10):
    """The contract's 1-minute candles from `back` sessions before `day` to `day` (store, cached on disk per day)."""
    ss = core.sessions(); d = core.dnum(day); i = int(np.searchsorted(ss, d))
    d0 = core.dstr(int(ss[max(0, i - back)])) if i < len(ss) and ss[i] == d else day
    os.makedirs(os.path.join(core.CACHE, "jilly_opt"), exist_ok=True)
    f = os.path.join(core.CACHE, "jilly_opt", f"{exp}_{k}_{right}_{day}.npy")
    if os.path.exists(f): return np.load(f)
    c = store_reader.option_candles(exp, k, right, d0, day, "minute")
    a = np.array([x[:6] for x in c], dtype=np.float64) if c else np.zeros((0, 6))
    np.save(f, a)
    return a


_LEGS = {}


def legs(J, d0, d1):
    """{(day, right): dict(...)} - each session's day-open ATM / ITM1 leg with its own candles, profile and signal."""
    key = (tuple(sorted((k, str(v)) for k, v in J.items() if k not in ("notes", "stop", "stop_atr", "target_r", "trail", "trail_after", "opp"))), d0, d1)   # the exits do not change the legs
    if key in _LEGS: return _LEGS[key]
    sp = _J._store_bars("index"); f = _J._store_bars("fut")
    exps = sorted(e["expiry"] for e in store_reader.expiries())
    days = sorted({core.dstr(int(x)) for x in np.unique(sp.day)})
    # the profile days start earlier than d0 so sigma and its rank are warm (20 + 250 sessions)
    j0 = max(0, days.index(next(x for x in days if x >= d0)) - (J["sigma_lb"] + J["rank_lb"] + 5))
    days = [x for x in days[j0:] if x <= d1]
    out, R = {}, {"CE": [], "PE": []}                         # R: per right, [(day, profile or None)] in order
    for day in days:
        i = int(np.searchsorted(sp.t, core.dnum(day) * DAY + 555 * 60))
        if i >= len(sp) or core.dstr(int(sp.day[i])) != day: continue
        atm = int(round(float(sp.o[i]) / 50) * 50)
        ex = next((e for e in exps if e >= day), None)
        if not ex: continue
        for right in ("CE", "PE"):
            if J["strike"] == "PREM":                            # the strike nearest the money opening (09:15) at a premium in range
                k, a = None, np.zeros((0, 6))
                for n_ in range(0, J.get("prem_steps", 12) + 1):
                    for k_ in ((atm,) if n_ == 0 else (atm + 50 * n_, atm - 50 * n_)):
                        a_ = _leg_candles(ex, k_, right, day)
                        if not len(a_): continue
                        t_ = a_[:, 0].astype(np.int64); w_ = np.nonzero((t_ // DAY == core.dnum(day)) & (t_ % DAY == 555 * 60))[0]
                        if len(w_) and J["prem_lo"] <= a_[w_[0], 1] <= J["prem_hi"]: k, a = k_, a_; break
                    if k is not None: break
                if k is None:
                    rec = dict(day=day, right=right, k=atm, exp=ex, signal=None, why=f"no strike opening at {J['prem_lo']} - {J['prem_hi']}")
                    R[right].append((day, None)); out[(day, right)] = rec; continue
            else:
                k = atm if J["strike"] == "ATM" else (atm - 50 if right == "CE" else atm + 50)
                a = _leg_candles(ex, k, right, day)
            rec = dict(day=day, right=right, k=k, exp=ex, signal=None, why=None)
            if not len(a): rec["why"] = "no candles in the store"; R[right].append((day, None)); out[(day, right)] = rec; continue
            t = a[:, 0].astype(np.int64); dd = t // DAY; dn = core.dnum(day)
            m = dd == dn
            if not m.any(): rec["why"] = "no candles today"; R[right].append((day, None)); out[(day, right)] = rec; continue
            ia = int(np.argmax(m)); iz = ia + int(m.sum())
            kv = ((t[ia:iz] % DAY) - 555 * 60) // 60 + 1
            o, h, l, c, v = (a[ia:iz, q] for q in range(1, 6))
            # today's profile |close(m) / open - 1| (forward-filled), for the later sessions' sigma
            prof = None
            if kv[0] == 1 and kv[-1] > 195:
                row = np.full(375, np.nan); ok = (kv >= 1) & (kv <= 375); row[kv[ok] - 1] = c[ok]
                for q in range(1, 375):
                    if np.isnan(row[q]): row[q] = row[q - 1]
                prof = np.abs(row / o[0] - 1)
            prev = [p for _, p in R[right] if p is not None][-J["sigma_lb"]:]   # the last 20 sessions WITH a profile (as the futures version)
            R[right].append((day, prof))
            out[(day, right)] = rec
            rec.update(t=t[ia:iz], o=o, h=h, l=l, c=c, v=v, kv=kv)
            if J.get("struct") or J.get("trail"):                 # the leg's own structure: trend and protected level per minute
                eng = core.foundation(core.Bars(t, a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]), J["struct_rules"])
                tr = np.zeros(len(t), np.int8)
                for j in range(len(eng.ei)):                       # the trend = the side of the last CHoCH (the last BOS before any)
                    if eng.ek[j] == 1 or not tr[int(eng.ei[j]):].any(): tr[int(eng.ei[j]):] = eng.ed[j]
                rec.update(trend=tr[ia:iz], prot=np.asarray(eng.prot)[ia:iz])
            if kv[0] != 1: rec["why"] = "no 09:15 candle"; continue
            if len(prev) < J["sigma_lb"]: rec["why"] = "fewer than 20 prior profiles"; continue
            sig = np.mean(prev, axis=0); rec["sigma30"] = float(sig[29])
            O = float(o[0]); pcm = dd[:ia] < dn
            PC = float(a[:ia][pcm][-1, 4]) if pcm.any() else None
            UP = O if PC is None else max(O, PC); DN = O if PC is None else min(O, PC)
            UB = UP * (1 + J["band_k"] * sig); LB = DN * (1 - J["band_k"] * sig); rec.update(O=O, PC=PC, UP=UP, DN=DN, UB=UB, LB=LB)
            # ATR(9) Wilder on the contract's 5-minute bars, continuous over the window read
            kv_all = ((t % DAY) - 555 * 60) // 60
            b5 = dd * 1000 + kv_all // 5
            cb = np.concatenate([[0], np.nonzero(np.diff(b5))[0] + 1, [len(t)]])
            H5 = np.maximum.reduceat(a[:, 2], cb[:-1]); L5 = np.minimum.reduceat(a[:, 3], cb[:-1]); C5 = a[cb[1:] - 1, 4]
            TR = np.empty(len(H5)); TR[0] = H5[0] - L5[0]
            TR[1:] = np.maximum(H5[1:] - L5[1:], np.maximum(np.abs(H5[1:] - C5[:-1]), np.abs(L5[1:] - C5[:-1])))
            N = J["atr_n"]; A = np.full(len(TR), np.nan)
            if len(TR) >= N:
                A[N - 1] = TR[:N].mean()
                for q in range(N, len(TR)): A[q] = (A[q - 1] * (N - 1) + TR[q]) / N
            bar5 = np.repeat(np.arange(len(H5)), np.diff(cb))[ia:iz]
            orm = (kv >= 1) & (kv <= J["or_keys"])
            ORH, ORL = float(h[orm].max()), float(l[orm].min()); rec.update(ORH=ORH, ORL=ORL, ORM=_J._r05((ORH + ORL) / 2))
            hlc3 = (h + l + c) / 3; cv = np.cumsum(v); vw = np.where(cv > 0, np.cumsum(hlc3 * v) / np.where(cv > 0, cv, 1), np.nan); rec["vwap"] = vw
            rec["rank"] = None; rec["cands"] = cands = []          # every checkpoint signal of the day (the `opp` exits read them)
            for ck in range(J["ck_first"], J["ck_last"] + 1, J["ck_step"]):
                w = np.nonzero(kv == ck)[0]
                if not len(w): continue
                q = int(w[0]); C = float(c[q]); atr = float(A[bar5[q]])
                if np.isnan(atr) or np.isnan(vw[q]): continue
                if C > ORH + J["atr_buf"] * atr and C > UB[ck - 1] and C > vw[q]: side = 1
                elif J.get("sides") == "both" and C < ORL - J["atr_buf"] * atr and C < LB[ck - 1] and C < vw[q]: side = -1
                else: continue
                if J.get("struct") and rec["trend"][q] != side: continue     # outside the protected level of the leg's own structure only
                if q + 1 >= len(c): break
                cands.append((q, side, ck, C, atr))
                if rec["signal"] is None: rec.update(signal=side, q=q, key=ck, close=C, atr=atr, fill_q=q + 1, fill=float(o[q + 1]))
            if rec["signal"] is None: rec["why"] = "no signal"
    # the vol filter: today's sigma(30) against the previous 250 sessions' of the same right
    for right in ("CE", "PE"):
        hist = [(day, out[(day, right)].get("sigma30")) for day in days if (day, right) in out]
        for n, (day, s30) in enumerate(hist):
            r = out[(day, right)]
            if s30 is None: continue
            past = [x for _, x in hist[max(0, n - J["rank_lb"]):n] if x is not None]
            r["rank"] = float(np.mean(np.array(past) < s30)) if len(past) >= J["rank_min"] else None
            if J["filter"] and r["rank"] is not None and r["rank"] < J["rank_cut"] and r["signal"] is not None:
                r["signal"] = None; r["why"] = f"vol filter: sigma(30) rank {r['rank']:.3f} < {J['rank_cut']}"
    _LEGS.clear(); _LEGS[key] = out
    return out


def _stops(J, sd, fill, close, atr, ORM):
    dist = _J._r05(J["stop_atr"] * atr)
    if sd > 0:
        stop = ORM if J["stop"] == "orm" and ORM < close else max(0.05, fill - dist); target = fill + J["target_r"] * (fill - stop)
    else:
        stop = ORM if J["stop"] == "orm" and ORM > close else fill + dist; target = max(0.05, fill - J["target_r"] * (stop - fill))
    return stop, target


def _run_opp(ctx, J, L, d0, d1, flat_key, lots):
    """`opp`: what a later opposite signal does to an open trade (the user: "if there is a sell in CE and a buy comes in, or
    close CE"). A leg's market direction: CE buy / PE sell = up, CE sell / PE buy = down.
      "close"   an opposite signal on the SAME leg (a buy while it is sold, a sell while it is bought) closes it;
      "reverse" the same, and the leg is traded the other way from there (its stop / target by the same rules), once a day;
      "xclose"  a signal on the OTHER leg pointing the other market way closes it;
      "both"    "reverse" plus "xclose";
      "flip"    after the trade is stopped out, the first later opposite signal on the same leg (a buy after a stopped sell,
                a sell after a stopped buy) is traded, once a day - an open trade is rarely met by an opposite signal, since
                its stop sits between the two breakouts; "flip_x" = "flip" plus "xclose".
    A signal is known at its checkpoint candle's close: out (and in) at the next minute's open. Stops / targets first."""
    mode = J["opp"]; same = mode in ("close", "reverse", "both"); cross = mode in ("xclose", "both", "flip_x"); rev = mode in ("reverse", "both")
    flip = mode in ("flip", "flip_x")                 # "flip": after a stop, the leg's next opposite signal is taken (once a day)
    mkt = lambda right, sd: sd if right == "CE" else -sd
    trs = []
    for day in sorted({d for d, _ in L}):
        if not (d0 <= day <= d1): continue
        for right in ("CE", "PE"):
            r = L.get((day, right))
            if not r or r.get("signal") is None: continue
            o_ = L.get((day, "PE" if right == "CE" else "CE"))
            o, h, l, c, kv, t = r["o"], r["h"], r["l"], r["c"], r["kv"], r["t"]
            # the other leg's signals mapped onto this leg's minutes (its checkpoint close time)
            xs = [(int(np.searchsorted(t, int(o_["t"][q]))), s2) for q, s2, *_ in (o_.get("cands") or [])] if (cross and o_ and o_.get("signal") is not None) else []
            sd, fq, fill, q0, close, atr = r["signal"], r["fill_q"], r["fill"], r["q"], r["close"], r["atr"]
            label, reversed_ = f"{'LONG' if sd > 0 else 'SHORT'} {right}", False
            while True:
                stop, target = _stops(J, sd, fill, close, atr, r["ORM"])
                opp_q = sorted([q for q, s2, *_ in r["cands"] if same and q > q0 and s2 == -sd] +
                               [q for q, s2 in xs if q > q0 and q < len(c) and mkt("PE" if right == "CE" else "CE", s2) == -mkt(right, sd)])
                xq, why, xp, nxt = len(c) - 1, "eod", float(c[-1]), None
                for m in range(fq, len(c)):
                    if kv[m] >= flat_key: xq, why, xp = m, "eod", float(o[m]); break
                    hs, ht = ((l[m] <= stop), (h[m] >= target)) if sd > 0 else ((h[m] >= stop), (l[m] <= target))
                    if hs or ht:
                        why = "stop_loss" if hs else "target 1"
                        xq, xp = (m + 1, float(o[m + 1])) if m + 1 < len(c) else (m, float(c[m])); break
                    if opp_q and m == opp_q[0] and m + 1 < len(c) and kv[m + 1] < flat_key:
                        same_hit = any(q == m and s2 == -sd for q, s2, *_ in r["cands"]) and same
                        xq, xp = m + 1, float(o[m + 1])
                        why = "opposite_signal" if same_hit else "other_leg_signal"
                        if same_hit and rev and not reversed_:
                            cq = next(x for x in r["cands"] if x[0] == m and x[1] == -sd)
                            nxt = (-sd, m + 1, float(o[m + 1]), m, cq[3], cq[4])
                        break
                    if opp_q and m >= opp_q[0]: opp_q.pop(0)
                name = f"NIFTY {Dt.date.fromisoformat(r['exp']):%d%b%y} {r['k']} {right}".upper()
                pos = "LONG" if sd > 0 else "SHORT"
                rec = dict(dir="up" if sd > 0 else "down", signal="BULLISH" if sd > 0 else "BEARISH", choch_time=int(t[q0]), und_entry=fill, und_exit=xp, stale=False, lots=lots, tranche="",
                           position=pos, opt_type=right, kind="OPT", instrument=name, strike=r["k"], expiry=r["exp"], entry_time=int(t[fq]),
                           entry_px=fill, exit_time=int(t[xq]), exit_px=xp, exit_reason=why, open=False, sl=stop, label=label, signal_key=r["key"])
                trs.append(_J._price(ctx, rec, "OPT"))
                if flip and nxt is None and why == "stop_loss" and not reversed_:
                    cq = next((x for x in r["cands"] if x[0] >= xq and x[1] == -sd and x[0] + 1 < len(c) and kv[x[0] + 1] < flat_key), None)
                    if cq is not None: nxt = (-sd, cq[0] + 1, float(o[cq[0] + 1]), cq[0], cq[3], cq[4])
                if nxt is None: break
                sd, fq, fill, q0, close, atr = nxt; reversed_ = True
                label = f"{'LONG' if sd > 0 else 'SHORT'} {right} · {'after the stop' if flip else 'reverse'}"
    trs.sort(key=lambda x: x["entry_time"])
    return trs


def run(ctx):
    spec = ctx["spec"]; J = spec["jilly"]; lots = ctx["position"]["lots"]
    d0, d1 = max(ctx["date_from"], J["opt_from"]), ctx["date_to"]
    flat_key = (core.hhmm_sec(J["flatten"]) - 555 * 60) // 60 + 1
    res = {}
    for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL"):
        Jc = dict(J, strike="ATM" if ch.endswith("ATM") else "PREM" if ch.endswith("PREM") else "ITM1")
        L = legs(Jc, d0, d1)
        if J.get("opp"):
            res[ch] = dict(trades=_run_opp(ctx, J, L, d0, d1, flat_key, lots), skipped=[], signals=[]); continue
        trs, skipped = [], []
        for (day, right), r in sorted(L.items()):
            if not (d0 <= day <= d1) or r["signal"] is None: continue
            fill = r["fill"]; sd = r["signal"]; dist = _J._r05(J["stop_atr"] * r["atr"])
            if sd > 0:                                   # bought on the leg's upside break
                stop = r["ORM"] if J["stop"] == "orm" and r["ORM"] < r["close"] else max(0.05, fill - dist)
                target = fill + J["target_r"] * (fill - stop)
            else:                                        # sold on the leg's downside break (sides "both")
                stop = r["ORM"] if J["stop"] == "orm" and r["ORM"] > r["close"] else fill + dist
                target = max(0.05, fill - J["target_r"] * (stop - fill))
            o, h, l, c, kv, t = r["o"], r["h"], r["l"], r["c"], r["kv"], r["t"]
            xq, why, xp = len(c) - 1, "eod", float(c[-1])
            best, moved = fill, 0
            for m in range(r["fill_q"], len(c)):
                if kv[m] >= flat_key: xq, why, xp = m, "eod", float(o[m]); break
                hs, ht = ((l[m] <= stop), (h[m] >= target)) if sd > 0 else ((h[m] >= stop), (l[m] <= target))
                if hs or ht:
                    why = ("trail_stop" if moved else "stop_loss") if hs else "target 1"
                    xq, xp = (m + 1, float(o[m + 1])) if m + 1 < len(c) else (m, float(c[m])); break
                if J.get("trail") == "prot":                       # once `trail_after` points in profit, the stop follows the leg's
                    best = max(best, float(h[m])) if sd > 0 else min(best, float(l[m]))       # protected level (never loosens)
                    if (best - fill if sd > 0 else fill - best) >= J["trail_after"]:
                        pv = float(r["prot"][m])
                        if not np.isnan(pv) and r["trend"][m] == sd and ((sd > 0 and c[m] > pv > stop) or (sd < 0 and c[m] < pv < stop)):
                            stop = pv; moved += 1
            name = f"NIFTY {Dt.date.fromisoformat(r['exp']):%d%b%y} {r['k']} {right}".upper()
            pos = "LONG" if sd > 0 else "SHORT"
            rec = dict(dir="up" if sd > 0 else "down", signal="BULLISH" if sd > 0 else "BEARISH", choch_time=int(t[r["q"]]), und_entry=fill, und_exit=xp, stale=False, lots=lots, tranche="",
                       position=pos, opt_type=right, kind="OPT", instrument=name, strike=r["k"], expiry=r["exp"], entry_time=int(t[r["fill_q"]]),
                       entry_px=fill, exit_time=int(t[xq]), exit_px=xp, exit_reason=why, open=False, sl=stop, label=f"{pos} {right}", signal_key=r["key"])
            trs.append(_J._price(ctx, rec, "OPT"))
        trs.sort(key=lambda x: x["entry_time"])
        res[ch] = dict(trades=trs, skipped=skipped, signals=[])
    return res


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """Standalone: the main chart is the option leg itself - the leg of the day's first trade (else the CE) - with its own band,
    opening range and VWAP and its trades; the CE / PE panes show both legs (chart_leg). The future is not drawn: nothing in
    these strategies reads it (the index's 09:15 open only picks the ATM strike)."""
    C = {k: i for i, k in enumerate(body["cols"])}
    mine = sorted((x for x in body["trades"] if day <= str(x[C["entry_time"]])[:10] <= to), key=lambda x: x[C["entry_time"]])
    return chart_leg(ctx, body, day, to, atm=mine[0][C["opt_type"]] if mine else "CE")


def chart_leg(ctx, body, day, to, atm=None, inst=None):
    """One leg's own 1-minute chart over day..to, from the store: the day-open ATM CE or PE of each session (or the contract of a
    trade picked from the table), with its noise band UB / LB, its opening range ORH / ORL / ORM after 09:30 and its VWAP, and
    every trade of that right - bought and sold."""
    J = ctx["spec"]["jilly"]; C = {k: i for i, k in enumerate(body["cols"])}
    right = atm or str(inst).split()[-1]
    sd_ = ctx["spec"]["options"].get("strike_default", "ATM")
    L = legs(dict(J, strike="PREM" if sd_ == "PREM" else "ATM" if sd_ == "ATM" else "ITM1"), day, to)
    NM = [("UB", "#e5484d"), ("LB", "#30a46c"), ("ORH", "#8e4ec6"), ("ORL", "#8e4ec6"), ("ORM", "#f5a524"), ("VWAP", "#2962ff")]
    candles, lines, names, trades = [], [[] for _ in NM], [], []
    for d in sorted({k[0] for k in L if day <= k[0] <= to}):
        r = L.get((d, right))
        if not r or "t" not in r: continue
        t = r["t"]; names.append(f"{d[5:]}: {r['exp'][5:]} {r['k']} {right}")
        brk = bool(candles)                           # a new session is usually another contract: every line breaks at its first minute
        candles += [[int(t[i]), float(r["o"][i]), float(r["h"][i]), float(r["l"][i]), float(r["c"][i]), float(r["v"][i])] for i in range(len(t))]
        for i in range(len(t)):
            kk, tt = int(r["kv"][i]), int(t[i])
            if brk and i == 0:
                for ln in lines:
                    if ln: ln.append([tt, None])
                continue
            if "UB" in r and 1 <= kk <= 375: lines[0].append([tt, round(float(r["UB"][kk - 1]), 2)]); lines[1].append([tt, round(float(r["LB"][kk - 1]), 2)])
            if "ORH" in r and kk > J["or_keys"]:
                lines[2].append([tt, r["ORH"]]); lines[3].append([tt, r["ORL"]]); lines[4].append([tt, r["ORM"]])
            if "vwap" in r and not np.isnan(r["vwap"][i]): lines[5].append([tt, round(float(r["vwap"][i]), 2)])
        trades += [list(x) for x in body["trades"] if str(x[C["entry_time"]])[:10] == d and x[C["opt_type"]] == right]
    if not candles: raise ValueError(f"no {right} candles for the day-open ATM legs from {day} in the store")
    keep = [k for k in range(len(NM)) if lines[k]]
    return dict(day=day, to=to, inst=f"ATM {right} (" + "; ".join(names) + ")", candles=candles, cols=body["cols"], trades=trades, own=True,
                lines=[lines[k] for k in keep], line_names=[NM[k][0] for k in keep], line_colors=[NM[k][1] for k in keep],
                sessions=len({c[0] // DAY for c in candles}),
                derived=dict(what=f"the day-open ATM {right}'s own 1-minute chart, standalone ({'; '.join(names)}): its noise band UB / LB, its opening range ORH / ORL / ORM, its VWAP - the signals, stops and exits are all read here, not on the future"))
