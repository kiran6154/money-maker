"""Jilly's ORB + Noise Band on NIFTY, from the paper-trading spec (family module for ST110 / ST111).

Built 2026-10-25 from the user's file "jilly_paper_spec.md" (Downloads). Every rule below is the spec's; the choices it leaves
open are marked BUILD.

Signals - the near-month futures, 1-minute bars, IST. "key" = minutes since 09:15 at a bar's close (the 09:15 bar is key 1).
  valid session   its first bar is 09:15; "stub" = a session whose last bar has key <= 195 (not used for PC or sigma).
  O, PC           O = the 09:15 bar's open; PC = the last close of the previous full (non-stub) session.
  UP / DN         max(O, PC) / min(O, PC); on the first session of a new contract (the expiry differs from the previous
                  session's) UP = DN = O.
  sigma(m)        for keys 1..375: the mean over the prior 20 full sessions of |close(m) / open(day) - 1| (missing minutes
                  forward-filled within a session). BUILD: fewer than 20 prior full sessions -> no trade.
  bands           UB(m) = UP x (1 + band_k * sigma(m)), LB(m) = DN x (1 - band_k * sigma(m)); band_k 1.25.
  vol filter      (`filter`) today's sigma(30) ranked against the sigma(30) of the previous 250 sessions in the data (the
                  fraction smaller); rank < 0.20 -> skip the day; fewer than 120 values -> no filter.
  OR              ORH / ORL = the high / low of keys 1..15; ORM = (ORH + ORL) / 2 rounded to 0.05.
  ATR             ta.atr(9), Wilder RMA seeded with the mean of the first 9 TRs, on 5-minute futures bars aligned to 09:15,
                  continuous across days; at a checkpoint, the 5-minute bar that contains the checkpoint minute (closed then).
  VWAP            session VWAP of hlc3 with the futures volume, reset at 09:15.
  checkpoints     the closes at keys 30, 45 ... 285 (09:45 ... 14:00). LONG: close > ORH + 0.3 ATR and > UB(key) and > VWAP;
                  SHORT: close < ORL - 0.3 ATR and < LB(key) and < VWAP. The first signal of the day only.
Entry - the open of the next 1-minute bar (the futures "fill").
Exits - read on the FUTURE: a 1-minute bar touching the stop or the target exits at the next minute's open (both in one
  minute: the stop); whatever is open goes at the 15:20 bar's open.
  FUT   stop = fill -/+ round_0.05(stop_atr x ATR at the signal); target = fill +/- target_r x that distance (10, 1R).
  OPT   (`opt_stop`) "orm": the stop is the OR midpoint on the future (if it is not beyond the signal close, the stop_atr x ATR
        distance instead), target = fill +/- target_r_opt x |fill - stop| (2R); "atr": the FUT stop and target_r_opt.
        The option is bought at the open of the futures fill minute and sold at the open of the minute after the futures
        trigger (BUILD: the first option candle at or after that minute in the session; none at the entry -> no trade).
        From `opt_from` (2020-02-01, the spec's option window). Strike: ATM = round(NIFTY spot at the signal minute / 50) x 50, CE for a long, PE for a short; ITM1 = 50 points in the
        money. Expiry: the nearest weekly on or after today (the same-day contract on expiry days). Option candles: the
        download store (store_reader.py, read-only).
Costs - slippage 0.5 point a side on futures, max(0.5, 0.5% of the premium) a side on options; Indian F&O charges by trade
  date. BUILD (the spec gives none): STT on the sell side 0.0125% futures / 0.0625% options before 2024-10-01, 0.02% / 0.1%
  from then, 0.05% / 0.15% from 2026-04-01 (this matches the spec's worked example to the rupee: futures Rs 882, option
  Rs 69.9); exchange 0.002% / 0.05% before 2024-10-01, 0.00173% / 0.03503% from then; brokerage 0.03% capped at Rs 20 per
  futures order, Rs 20 flat per option order; GST 18% on brokerage + exchange + SEBI; stamp 0.002% / 0.003% on the buy;
  SEBI Rs 10 a crore. Lot 65.
Data - the download store D:/nifty_data (read-only), as the spec: the near-month futures (on each day the contract with the
  earliest expiry on or after it; unadjusted; with the futures volume) and the index, 1-minute, 2018-01 → 2026-10-23; the
  options 1-minute from the store (expiries 2020-07 on). Not the lab's cache (which stops at 2026-10-09).
"""
import datetime as Dt
import numpy as np
import core
import store_reader

ENTRY_RULES = ("jilly_orb_noise_v1",)
TYPES = ("FUT", "OPT_FUT_SIGNAL")
UNDERLYINGS = ("FUT",)
OWN_COVERAGE = True
REFUSED_WHY = "Jilly's ORB + noise band reads the near-month futures; Options (via futures) and Futures run"
DAY = core.DAY


# ---------------------------------------------------------------- costs
def _charges(day, kind, buy, sell, qty):
    """Round-trip charges by trade date (see BUILD in the module text)."""
    new, newer = day >= "2024-10-01", day >= "2026-04-01"
    B, S = buy * qty, sell * qty
    if kind == "FUT":
        brk = min(B * 0.0003, 20) + min(S * 0.0003, 20)
        stt = S * (0.0005 if newer else 0.0002 if new else 0.000125)
        exch = (B + S) * (0.0000173 if new else 0.00002); stamp = B * 0.00002
    else:
        brk = 40.0
        stt = S * (0.0015 if newer else 0.001 if new else 0.000625)
        exch = (B + S) * (0.0003503 if new else 0.0005); stamp = B * 0.00003
    sebi = (B + S) * 0.000001; gst = 0.18 * (brk + exch + sebi)
    return dict(brokerage=brk, stt=stt, exchange=exch, sebi=sebi, stamp=stamp, gst=gst, total=brk + stt + exch + sebi + stamp + gst)


def _price(ctx, rec, kind):
    """pts, gross, charges and net with the spec's slippage (0.5 futures; max(0.5, 0.5%) options)."""
    lot = ctx["lot_size"] * rec.setdefault("lots", 1)
    sl = (lambda p: 0.5) if kind == "FUT" else (lambda p: max(0.5, 0.005 * p))
    buy0, sell0 = (rec["entry_px"], rec["exit_px"]) if rec["position"] == "LONG" else (rec["exit_px"], rec["entry_px"])
    buy, sell = buy0 + sl(buy0), sell0 - sl(sell0)
    pts = sell - buy
    rec.update(pts=pts, gross=pts * lot, chg=_charges(core.tstr(rec["entry_time"])[:10], kind, buy, sell, lot))
    rec["net"] = rec["gross"] - rec["chg"]["total"]
    return rec


# ---------------------------------------------------------------- data: the download store (to 2026-10-23, as the spec)
_DATA = {}


def _store_bars(kind):
    """core.Bars of the store's near-month futures (with the contract expiry of every bar) or the index, 1-minute, all of it,
    cached in cache/jilly_<kind>.<signature>.npz until a store file changes."""
    if kind in _DATA: return _DATA[kind]
    import glob, hashlib, os
    import pandas as pd
    files = sorted(glob.glob(os.path.join(store_reader.ROOT, "futures" if kind == "fut" else "index", "1minute", "*", "*.parquet")))
    # the current contract's file is still ".partial" while it downloads: it is read too (a contract with both files is
    # de-duplicated by the minute below, the later file winning)
    sig = hashlib.sha1("|".join(f"{x}:{os.path.getmtime(x)}" for x in files).encode()).hexdigest()[:12]
    npz = os.path.join(core.CACHE, f"jilly_{kind}.{sig}.npz")
    if os.path.exists(npz):
        z = np.load(npz); b = core.Bars(z["t"], z["o"], z["h"], z["l"], z["c"], z["v"], dict(expiry=z["e"]) if "e" in z.files else None)
    else:
        cols = ["datetime", "open", "high", "low", "close", "volume"] + (["expiry"] if kind == "fut" else [])
        df = store_reader._read(files, columns=cols)
        df = df[(df["datetime"].dt.hour * 60 + df["datetime"].dt.minute >= 555) & (df["datetime"].dt.hour * 60 + df["datetime"].dt.minute <= 929)]
        if kind == "fut":
            df = df.assign(day=df["datetime"].dt.normalize(), exp=pd.to_datetime(df["expiry"]))
            df = df[df["exp"] >= df["day"]]
            df = df[df["exp"] == df.groupby("day")["exp"].transform("min")]       # the near month on each day
        df = df.sort_values("datetime").drop_duplicates("datetime", keep="last")
        t = df["datetime"].to_numpy().astype("datetime64[s]").astype("int64")
        arr = dict(t=t, o=df["open"].to_numpy(float), h=df["high"].to_numpy(float), l=df["low"].to_numpy(float), c=df["close"].to_numpy(float),
                   v=(df["volume"].to_numpy(float) if "volume" in df else np.zeros(len(df))))
        if kind == "fut": arr["e"] = df["exp"].dt.strftime("%Y-%m-%d").to_numpy().astype("U10")
        os.makedirs(core.CACHE, exist_ok=True); np.savez(npz, **arr)
        b = core.Bars(arr["t"], arr["o"], arr["h"], arr["l"], arr["c"], arr["v"], dict(expiry=arr["e"]) if "e" in arr else None)
    _DATA[kind] = b
    return b


# ---------------------------------------------------------------- the signal engine (every session, once per spec)
_ENG = {}


def _r05(x): return round(round(x / 0.05) * 0.05, 2)


def engine(J):
    """Per session: the signal (if any) and the arrays the exits and the chart need. Cached per parameter set."""
    key = tuple(sorted((k, str(v)) for k, v in J.items() if k != "notes"))
    if key in _ENG: return _ENG[key]
    f = _store_bars("fut")
    t, o, h, l, c, v = f.t, f.o, f.h, f.l, f.c, f.v
    exp = f.extra["expiry"]
    tod = t % DAY; keyv = (tod - 555 * 60) // 60 + 1
    cut = np.concatenate([[0], np.nonzero(np.diff(f.day))[0] + 1, [len(t)]])
    S = [(int(a), int(z)) for a, z in zip(cut[:-1], cut[1:])]
    n = len(S)
    valid = np.array([keyv[a] == 1 for a, z in S]); full = np.array([keyv[z - 1] > 195 for a, z in S])
    # forward-filled closes by key, and |close / open - 1| per key, for every full session
    R = np.full((n, 375), np.nan)
    for s, (a, z) in enumerate(S):
        if not full[s]: continue
        row = np.full(375, np.nan); k = keyv[a:z]; ok = (k >= 1) & (k <= 375)
        row[k[ok] - 1] = c[a:z][ok]
        for m in range(1, 375):
            if np.isnan(row[m]): row[m] = row[m - 1]
        if np.isnan(row[0]): continue
        R[s] = np.abs(row / o[a] - 1)
    full_idx = np.nonzero(full & ~np.isnan(R[:, 0]))[0]
    sig = [None] * n; s30 = np.full(n, np.nan)
    for s in range(n):
        prev = full_idx[full_idx < s][-J["sigma_lb"]:]
        if len(prev) < J["sigma_lb"]: continue
        sig[s] = R[prev].mean(axis=0); s30[s] = sig[s][29]
    # 5-minute bars aligned to 09:15, continuous; Wilder ATR
    b5 = f.day * 1000 + (keyv - 1) // 5
    cb = np.concatenate([[0], np.nonzero(np.diff(b5))[0] + 1, [len(t)]])
    H5 = np.maximum.reduceat(h, cb[:-1]); L5 = np.minimum.reduceat(l, cb[:-1]); C5 = c[cb[1:] - 1]
    TR = np.empty(len(H5)); TR[0] = H5[0] - L5[0]
    TR[1:] = np.maximum(H5[1:] - L5[1:], np.maximum(np.abs(H5[1:] - C5[:-1]), np.abs(L5[1:] - C5[:-1])))
    N = J["atr_n"]; A = np.full(len(TR), np.nan); A[N - 1] = TR[:N].mean()
    for i in range(N, len(TR)): A[i] = (A[i - 1] * (N - 1) + TR[i]) / N
    bar5 = np.repeat(np.arange(len(H5)), np.diff(cb))                 # the 5-minute bar of each 1-minute bar
    out = []
    pc_last, exp_prev = None, None
    for s, (a, z) in enumerate(S):
        rec = dict(session=s, day=core.dstr(int(f.day[a])), a=a, z=z, signal=None, why=None)
        day_exp = exp[a]; new_con = exp_prev is not None and day_exp != exp_prev
        pc = pc_last
        if full[s]: pc_last = float(c[z - 1])
        exp_prev = exp[z - 1]
        out.append(rec)
        if not valid[s]: rec["why"] = "first bar not 09:15"; continue
        if sig[s] is None or pc is None: rec["why"] = "fewer than 20 prior full sessions"; continue
        O = float(o[a]); UP, DN = (O, O) if new_con else (max(O, pc), min(O, pc))
        UB = UP * (1 + J["band_k"] * sig[s]); LB = DN * (1 - J["band_k"] * sig[s])
        rec.update(O=O, PC=pc, UP=UP, DN=DN, UB=UB, LB=LB, new_contract=bool(new_con), sigma30=float(s30[s]), sigma=sig[s])
        # the vol filter
        past = s30[max(0, s - J["rank_lb"]):s]; past = past[~np.isnan(past)]
        rank = float((past < s30[s]).mean()) if len(past) >= J["rank_min"] else None
        rec["rank"] = rank
        if J["filter"] and rank is not None and rank < J["rank_cut"]: rec["why"] = f"vol filter: sigma(30) rank {rank:.3f} < {J['rank_cut']}"; continue
        k = keyv[a:z]; orm = (k >= 1) & (k <= J["or_keys"])
        if not orm.any(): rec["why"] = "no opening range"; continue
        ORH, ORL = float(h[a:z][orm].max()), float(l[a:z][orm].min())
        rec.update(ORH=ORH, ORL=ORL, ORM=_r05((ORH + ORL) / 2))
        hlc3 = (h[a:z] + l[a:z] + c[a:z]) / 3; cv = np.cumsum(v[a:z]); vw = np.where(cv > 0, np.cumsum(hlc3 * v[a:z]) / np.where(cv > 0, cv, 1), np.nan)
        rec["vwap"] = vw
        for ck in range(J["ck_first"], J["ck_last"] + 1, J["ck_step"]):
            w = np.nonzero(k == ck)[0]
            if not len(w): continue
            i = a + int(w[0]); C = float(c[i]); atr = float(A[bar5[i]])
            if np.isnan(atr) or np.isnan(vw[i - a]): continue
            if C > ORH + J["atr_buf"] * atr and C > UB[ck - 1] and C > vw[i - a]: side = 1
            elif C < ORL - J["atr_buf"] * atr and C < LB[ck - 1] and C < vw[i - a]: side = -1
            else: continue
            if i + 1 >= z: break
            rec.update(signal=side, i=i, key=ck, close=C, atr=atr, fill_i=i + 1, fill=float(o[i + 1]))
            break
        if rec["signal"] is None: rec["why"] = "no signal"
    _ENG.clear(); _ENG[key] = (f, keyv, out); _AUX["atr"] = (A, bar5)
    return _ENG[key]


_AUX = {}


def _resignal(J, f, keyv, r, k):
    """After a fixed stop at 1-minute bar k (the exit bar): the day starts again there (the user, S123). O' = the open of bar k,
    the opening range = the high / low of the `reset_lookback` minutes before it (the previous hour), the band
    UB'(m) = O' x (1 + band_k x sigma(m - k0 + 1)) and LB' the mirror, measured from the reset minute (k0 = its key); the session
    VWAP and the ATR as before. The next checkpoints (keys ck_step apart, after the reset, up to ck_last) can signal either way.
    Returns a signal record like the engine's, or None."""
    A, bar5 = _AUX["atr"]; o, h, l, c = f.o, f.h, f.l, f.c
    a, z = r["a"], r["z"]; k0 = int(keyv[k])
    lb = max(a, k - J["reset_lookback"])
    if k - lb < 5: return None
    ORH, ORL, O = float(h[lb:k].max()), float(l[lb:k].min()), float(o[k])
    sig = r["sigma"]; vw = r["vwap"]
    for ck in range(J["ck_first"], J["ck_last"] + 1, J["ck_step"]):
        if ck <= k0: continue
        w = np.nonzero(keyv[a:z] == ck)[0]
        if not len(w): continue
        i = a + int(w[0]); C = float(c[i]); atr = float(A[bar5[i]]); mm = min(374, ck - k0)
        UB, LB = O * (1 + J["band_k"] * sig[mm]), O * (1 - J["band_k"] * sig[mm])
        if np.isnan(atr) or np.isnan(vw[i - a]): continue
        if C > ORH + J["atr_buf"] * atr and C > UB and C > vw[i - a]: side = 1
        elif C < ORL - J["atr_buf"] * atr and C < LB and C < vw[i - a]: side = -1
        else: continue
        if i + 1 >= z: return None
        return dict(r, signal=side, i=i, key=ck, close=C, atr=atr, fill_i=i + 1, fill=float(o[i + 1]), ORH=ORH, ORL=ORL, ORM=_r05((ORH + ORL) / 2), reset_at=int(f.t[k]))
    return None


def _stop_target(J, r, side, fill, dist, rule, tr):
    """The futures stop and target. rule: "atr" (fill -/+ dist), "orm" (the OR midpoint when it is beyond the signal close,
    else the atr distance), "or_far" (the far side of the opening range: ORL for a long, ORH for a short), "fixed" (fill -/+
    J["stop_pts"]). tr: the target in R of |fill - stop|; None = no target (out at the stop or the flatten)."""
    if rule == "orm" and ((side > 0 and r["ORM"] < r["close"]) or (side < 0 and r["ORM"] > r["close"])): stop = r["ORM"]
    elif rule == "or_far": stop = r["ORL"] if side > 0 else r["ORH"]
    elif rule == "fixed": stop = fill - side * J["stop_pts"]
    else: stop = fill - side * dist
    target = fill + side * (tr * abs(fill - stop) if tr is not None else 1e9)
    return stop, target


def _walk(f, keyv, r, stop, target, side, flat_key):
    """The futures exit: (bar index, why, futures price). A touch exits at the next bar's open; the flatten bar's open
    closes what is left; a session that ends before it (or a touch on its last bar) closes at its last close."""
    h, l, o, c = f.h, f.l, f.o, f.c
    for m in range(r["fill_i"], r["z"]):
        if keyv[m] >= flat_key: return m, "eod", float(o[m])
        hit_s = (l[m] <= stop) if side > 0 else (h[m] >= stop)
        hit_t = (h[m] >= target) if side > 0 else (l[m] <= target)
        if hit_s or hit_t:
            why = "stop_loss" if hit_s else "target 1"
            return (m + 1, why, float(o[m + 1])) if m + 1 < r["z"] else (m, why, float(c[m]))
    return r["z"] - 1, "eod", float(c[r["z"] - 1])


def run(ctx):
    spec = ctx["spec"]; J = spec["jilly"]; typ = ctx["type"]; lots = ctx["position"]["lots"]
    f, keyv, E = engine(J)
    d0, d1 = ctx["date_from"], ctx["date_to"]
    if typ != "FUT": d0 = max(d0, J.get("opt_from") or d0)       # the spec's options start 2020-02 (the store has some from late 2018)
    flat_key = (core.hhmm_sec(J["flatten"]) - 555 * 60) // 60 + 1
    sp = _store_bars("index")
    exps = sorted(e["expiry"] for e in store_reader.expiries()) if typ != "FUT" else []
    res = {}
    for ch in core.choice_keys(spec, typ):
        trs, skipped = [], []
        chain = []                                    # (signal record, reset number) in order; resets are found as the trades close
        for r0 in E:
            if not (d0 <= r0["day"] <= d1) or r0["signal"] is None: continue
            chain.append((r0, 0))
        while chain:
            r, nreset = chain.pop(0)
            side = r["signal"]; fill = r["fill"]; dist = _r05(J["stop_atr"] * r["atr"])
            pos = "LONG" if side > 0 else "SHORT"
            base = dict(dir="up" if side > 0 else "down", signal="BULLISH" if side > 0 else "BEARISH", choch_time=int(f.t[r["i"]]),
                        und_entry=fill, stale=False, lots=lots, tranche="", sl=None)
            if typ == "FUT":
                stop, target = _stop_target(J, r, side, fill, dist, J.get("fut_stop", "atr"), J["target_r"])
                m, why, xp = _walk(f, keyv, r, stop, target, side, flat_key)
                _reset(J, f, keyv, r, m, why, nreset, chain)
                rec = dict(base, position=pos, opt_type="FUT", kind="FUT", instrument=f"NIFTY FUT {f.extra['expiry'][r['a']]}", strike=0, expiry=str(f.extra["expiry"][r["a"]]),
                           entry_time=int(f.t[r["fill_i"]]), entry_px=fill, exit_time=int(f.t[m]), exit_px=xp,
                           exit_reason=why, open=False, sl=stop, und_exit=xp, label=f"{pos} FUT" + (f" · reset {nreset}" if nreset else ""), signal_key=r["key"])
                trs.append(_price(ctx, rec, "FUT")); continue
            # ---- options: the stop / target read on the future, the option bought and sold
            stop, target = _stop_target(J, r, side, fill, dist, J["opt_stop"], J["target_r_opt"])
            m, why, xp = _walk(f, keyv, r, stop, target, side, flat_key)
            _reset(J, f, keyv, r, m, why, nreset, chain)
            si = int(np.searchsorted(sp.t, f.t[r["i"]]))
            if si >= len(sp) or sp.t[si] != f.t[r["i"]]: skipped.append(dict(base, position="LONG", opt_type="", instrument="", entry_time=int(f.t[r["fill_i"]]), why="no spot candle at the signal minute")); continue
            atm = int(round(float(sp.c[si]) / 50) * 50); right = "CE" if side > 0 else "PE"
            k = atm if ch.endswith("ATM") else (atm - 50 if right == "CE" else atm + 50)
            ex = next((e for e in exps if e >= r["day"]), None)
            name = f"NIFTY {Dt.date.fromisoformat(ex):%d%b%y} {k} {right}".upper() if ex else ""
            if not ex: skipped.append(dict(base, position="LONG", opt_type=right, instrument="", entry_time=int(f.t[r["fill_i"]]), why="no weekly expiry in the store")); continue
            oc = store_reader.option_candles(ex, k, right, r["day"], r["day"], "minute")
            ot = np.array([x[0] for x in oc], dtype=np.int64)
            te, tx = int(f.t[r["fill_i"]]), int(f.t[m])
            ie = int(np.searchsorted(ot, te)) if len(ot) else 0
            if ie >= len(ot) or ot[ie] - te > 300:
                skipped.append(dict(base, position="LONG", opt_type=right, strike=k, expiry=ex, instrument=name, entry_time=te, why="no option candle at the entry minute in the store")); continue
            ix = int(np.searchsorted(ot, tx))
            xpx = float(oc[ix][1]) if ix < len(ot) else float(oc[-1][4])
            rec = dict(base, position="LONG", opt_type=right, kind="OPT", instrument=name, strike=k, expiry=ex, entry_time=int(ot[ie]), entry_px=float(oc[ie][1]),
                       exit_time=int(ot[ix]) if ix < len(ot) else int(ot[-1]), exit_px=xpx, exit_reason=why, open=False, sl=stop, und_exit=xp,
                       label=f"LONG {right} ({'long' if side > 0 else 'short'} signal)" + (f" · reset {nreset}" if nreset else ""), signal_key=r["key"])
            trs.append(_price(ctx, rec, "OPT"))
        trs.sort(key=lambda x: x["entry_time"])
        res[ch] = dict(trades=trs, skipped=skipped, signals=[])
    return res


def _reset(J, f, keyv, r, m, why, nreset, chain):
    """`reset`: a trade out at its (fixed) stop starts the day again at the exit bar - the next signal joins the chain."""
    if not J.get("reset") or why != "stop_loss" or nreset >= J["reset_max"]: return
    nxt = _resignal(J, f, keyv, r, m)
    if nxt is not None: chain.insert(0, (nxt, nreset + 1))


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


def chart_main(ctx, body, day, to):
    """The futures' 1-minute candles of the day with UB / LB, the opening range, ORM and VWAP, and the day's trades placed on
    the future (an option trade at the futures fill and exit)."""
    J = ctx["spec"]["jilly"]; f, keyv, E = engine(J)
    rows_by = {r["day"]: r for r in E}
    C = {k: i for i, k in enumerate(body["cols"])}
    candles, lines, trades = [], [[], [], [], [], [], []], []
    for d in sorted(x for x in rows_by if day <= x <= to):
        r = rows_by[d]; a, z = r["a"], r["z"]
        candles += core._chart_bars(f, a, z - 1)
        if "UB" in r:
            for i in range(a, z):
                kk = int(keyv[i]); tt = int(f.t[i])
                if 1 <= kk <= 375: lines[0].append([tt, round(float(r["UB"][kk - 1]), 2)]); lines[1].append([tt, round(float(r["LB"][kk - 1]), 2)])
                if "ORH" in r and kk > J["or_keys"]:
                    lines[2].append([tt, r["ORH"]]); lines[3].append([tt, r["ORL"]]); lines[4].append([tt, r["ORM"]])
                if "vwap" in r and not np.isnan(r["vwap"][i - a]): lines[5].append([tt, round(float(r["vwap"][i - a]), 2)])
        for x in body["trades"]:
            if str(x[C["entry_time"]])[:10] != d: continue
            x = list(x); x[C["entry_px"]], x[C["exit_px"]] = x[C["und_entry"]], x[C["und_exit"]]; trades.append(x)
    if not candles: raise ValueError(f"no futures candles from {day}")
    NM = [("UB", "#e5484d"), ("LB", "#30a46c"), ("ORH", "#8e4ec6"), ("ORL", "#8e4ec6"), ("ORM", "#f5a524"), ("VWAP", "#2962ff")]
    keep = [k for k in range(6) if lines[k]]
    return dict(day=day, to=to, inst=None, candles=candles, cols=body["cols"], trades=trades, own=True, lines=[lines[k] for k in keep],
                line_names=[NM[k][0] for k in keep], line_colors=[NM[k][1] for k in keep], sessions=len({c[0] // DAY for c in candles}),
                derived=dict(what="the near-month future: UB / LB (noise band), ORH / ORL / ORM after 09:30, session VWAP"))
