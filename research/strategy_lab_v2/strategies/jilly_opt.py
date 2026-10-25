"""Jilly's ORB + Noise Band read DIRECTLY on the option's own 1-minute chart (family module for ST112 / ST113).

Built 2026-10-25 at the user's word after Strategies 110 / 111: "try applying this directly on options instead of the future".
Strategies 110 / 111 read every rule on the near-month future and only bought the option. Here the rules of jilly.py run on
the option's candles; BUILD marks what the futures spec does not carry over and had to be chosen:

  the legs        BUILD: each session, the day-open ATM (the index's 09:15 open rounded to 50; `strike`: ATM, or ITM1 = 50
                  points in the money) CE and PE of the nearest weekly expiry on or after today. Each leg is its own chart and
                  can trade once a day; both may trade the same day.
  the side        BUY only (a bought option, as the spec's option configs): a leg trades its UPSIDE breakout - the close
                  above ORH + 0.3 ATR, above UB(key) and above VWAP at a checkpoint. Its downside break is not traded
                  (selling options is a different book).
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
    key = (tuple(sorted((k, str(v)) for k, v in J.items() if k != "notes")), d0, d1)
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
            prev = [p for _, p in R[right][-J["sigma_lb"]:] if p is not None]
            R[right].append((day, prof))
            out[(day, right)] = rec
            rec.update(t=t[ia:iz], o=o, h=h, l=l, c=c, v=v, kv=kv)
            if kv[0] != 1: rec["why"] = "no 09:15 candle"; continue
            if len(prev) < J["sigma_lb"]: rec["why"] = "fewer than 20 prior profiles"; continue
            sig = np.mean(prev, axis=0); rec["sigma30"] = float(sig[29])
            O = float(o[0]); pcm = dd[:ia] < dn
            PC = float(a[:ia][pcm][-1, 4]) if pcm.any() else None
            UP = O if PC is None else max(O, PC)
            UB = UP * (1 + J["band_k"] * sig); rec.update(O=O, PC=PC, UP=UP, UB=UB)
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
            rec["rank"] = None
            for ck in range(J["ck_first"], J["ck_last"] + 1, J["ck_step"]):
                w = np.nonzero(kv == ck)[0]
                if not len(w): continue
                q = int(w[0]); C = float(c[q]); atr = float(A[bar5[q]])
                if np.isnan(atr) or np.isnan(vw[q]): continue
                if C > ORH + J["atr_buf"] * atr and C > UB[ck - 1] and C > vw[q]:
                    if q + 1 >= len(c): break
                    rec.update(signal=1, q=q, key=ck, close=C, atr=atr, fill_q=q + 1, fill=float(o[q + 1])); break
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


def run(ctx):
    spec = ctx["spec"]; J = spec["jilly"]; lots = ctx["position"]["lots"]
    d0, d1 = max(ctx["date_from"], J["opt_from"]), ctx["date_to"]
    flat_key = (core.hhmm_sec(J["flatten"]) - 555 * 60) // 60 + 1
    res = {}
    for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL"):
        Jc = dict(J, strike="ATM" if ch.endswith("ATM") else "ITM1")
        L = legs(Jc, d0, d1)
        trs, skipped = [], []
        for (day, right), r in sorted(L.items()):
            if not (d0 <= day <= d1) or r["signal"] is None: continue
            fill = r["fill"]
            if J["stop"] == "orm": stop = r["ORM"] if r["ORM"] < r["close"] else max(0.05, fill - _J._r05(J["stop_atr"] * r["atr"]))
            else: stop = max(0.05, fill - _J._r05(J["stop_atr"] * r["atr"]))
            target = fill + J["target_r"] * (fill - stop)
            o, h, l, c, kv, t = r["o"], r["h"], r["l"], r["c"], r["kv"], r["t"]
            xq, why, xp = len(c) - 1, "eod", float(c[-1])
            for m in range(r["fill_q"], len(c)):
                if kv[m] >= flat_key: xq, why, xp = m, "eod", float(o[m]); break
                hs, ht = l[m] <= stop, h[m] >= target
                if hs or ht:
                    why = "stop_loss" if hs else "target 1"
                    xq, xp = (m + 1, float(o[m + 1])) if m + 1 < len(c) else (m, float(c[m])); break
            name = f"NIFTY {Dt.date.fromisoformat(r['exp']):%d%b%y} {r['k']} {right}".upper()
            rec = dict(dir="up", signal="BULLISH", choch_time=int(t[r["q"]]), und_entry=fill, und_exit=xp, stale=False, lots=lots, tranche="",
                       position="LONG", opt_type=right, kind="OPT", instrument=name, strike=r["k"], expiry=r["exp"], entry_time=int(t[r["fill_q"]]),
                       entry_px=fill, exit_time=int(t[xq]), exit_px=xp, exit_reason=why, open=False, sl=stop, label=f"LONG {right}", signal_key=r["key"])
            trs.append(_J._price(ctx, rec, "OPT"))
        trs.sort(key=lambda x: x["entry_time"])
        res[ch] = dict(trades=trs, skipped=skipped, signals=[])
    return res


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """The traded leg's own 1-minute candles (else the CE) with UB, ORH / ORL / ORM after 09:30 and VWAP, and its trades."""
    J = ctx["spec"]["jilly"]; Jc = dict(J, strike="ATM")
    C = {k: i for i, k in enumerate(body["cols"])}
    L = legs(Jc, day, to)
    candles, lines, trades = [], [[], [], [], [], []], []
    for d in sorted({k[0] for k in L if day <= k[0] <= to}):
        mine = [x for x in body["trades"] if str(x[C["entry_time"]])[:10] == d]
        right = mine[0][C["opt_type"]] if mine else "CE"
        r = L.get((d, right))
        if not r or "t" not in r: continue
        t = r["t"]
        candles += [[int(t[i]), float(r["o"][i]), float(r["h"][i]), float(r["l"][i]), float(r["c"][i]), float(r["v"][i])] for i in range(len(t))]
        for i in range(len(t)):
            kk = int(r["kv"][i])
            if "UB" in r and 1 <= kk <= 375: lines[0].append([int(t[i]), round(float(r["UB"][kk - 1]), 2)])
            if "ORH" in r and kk > J["or_keys"]: lines[1].append([int(t[i]), r["ORH"]]); lines[2].append([int(t[i]), r["ORL"]]); lines[3].append([int(t[i]), r["ORM"]])
            if "vwap" in r and not np.isnan(r["vwap"][i]): lines[4].append([int(t[i]), round(float(r["vwap"][i]), 2)])
        trades += [list(x) for x in mine if x[C["opt_type"]] == right]
    if not candles: raise ValueError(f"no option candles from {day} (the day-open ATM legs)")
    NM = [("UB", "#e5484d"), ("ORH", "#8e4ec6"), ("ORL", "#8e4ec6"), ("ORM", "#f5a524"), ("VWAP", "#2962ff")]
    keep = [k for k in range(5) if lines[k]]
    return dict(day=day, to=to, inst=None, candles=candles, cols=body["cols"], trades=trades, own=True, lines=[lines[k] for k in keep],
                line_names=[NM[k][0] for k in keep], line_colors=[NM[k][1] for k in keep], sessions=len({c[0] // DAY for c in candles}),
                derived=dict(what="the day-open ATM option's own candles: UB (its noise band), ORH / ORL / ORM after 09:30, VWAP"))
