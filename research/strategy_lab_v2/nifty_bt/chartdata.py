"""Chart payloads for the lab dashboard (strategies/handoff.py, ST151 - ST159): every option contract is rebuilt exactly as
the books built it (the same 1-minute rows, the same 3-session trim of engine.Contract) and every line and mark comes from
the engine's own functions, so what is drawn is what the engine read.

Recipes (SPEC['handoff']['chart']):
  stswing  tf-minute candles of the premium; Supertrend(p, m); the Supertrend-segment swings (a swing high = the highest
           high of a finished up segment, known at the flip bar) and their CHoCH / BOS (§12.2: G1, G2, ST159)
  chochst  tf-minute candles; N-bar pivot swings and their CHoCH / BOS; Supertrend(p, m) that has to agree (§12.4: G6)
  conf     5-minute candles with the 3-bar pivot CHoCH / BOS (the entry trigger) and the 15-minute Supertrend(p, m) as the
           engine knew it at each 5-minute close; a 15-minute view below with its Supertrend (§6.3 / §6.5: G3, G4, ST158)
  intraday the same with the 15-minute EMA20 (the exit) and the index chop-filter values at each signal (§12.5: G7)
  atm      60-minute candles of the front-expiry ATM contract over its whole folder history; Supertrend(p, m) (§6.1: G5)
Times: a candle is stamped with its start; a mark that the engine knows at a bar's close is put on that bar.
"""
import functools, os
import numpy as np, pandas as pd
from . import data, chain, indicators as I, filters as F
from .engine import Contract

UP, DN = "#089981", "#f23645"


def ts(x):
    return int(pd.Timestamp(x).value // 10**9)


def st_line(B, p, m):
    """(direction, line) of Supertrend(p, m): the loop of indicators._st_loop, keeping the final bands; the line is the
    lower band while up, the upper band while down (TradingView's plot)."""
    h, l, c = (B[k].values.astype(float) for k in ("high", "low", "close"))
    atr = pd.Series(I.true_range(h, l, c)).ewm(alpha=1 / p, adjust=False).mean().values
    n = len(c); hl2 = (h + l) / 2; ub = hl2 + m * atr; lb = hl2 - m * atr; fu = ub.copy(); fl = lb.copy(); d = np.ones(n, np.int8)
    for i in range(1, n):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = 1 if c[i] > fu[i - 1] else (-1 if c[i] < fl[i - 1] else d[i - 1])
    assert (d == I.st_dir(B, p, m)).all()
    return d, np.where(d == 1, fl, fu)


def seg_structure(B, d):
    """indicators.st_segment_structure with the bar of each swing: events [(i, side, kind)], swings [(H/L, bar, value, i)]."""
    h, l, c = B.high.values, B.low.values, B.close.values; n = len(c)
    seg_hi = seg_lo = np.nan; ihi = ilo = 0; H = L = np.nan; Hx = Lx = True; trend = 0; ev, sw = [], []
    for i in range(n):
        if i > 0 and d[i] != d[i - 1]:
            if d[i - 1] == 1: H = seg_hi; Hx = False; sw.append(("H", ihi, H, i))
            else: L = seg_lo; Lx = False; sw.append(("L", ilo, L, i))
            seg_hi, seg_lo, ihi, ilo = h[i], l[i], i, i
        else:
            if np.isnan(seg_hi) or h[i] > seg_hi: seg_hi, ihi = h[i], i
            if np.isnan(seg_lo) or l[i] < seg_lo: seg_lo, ilo = l[i], i
        if not Hx and c[i] > H: ev.append((i, 1, "BOS" if trend == 1 else "CHoCH")); Hx = True; trend = 1
        if not Lx and c[i] < L: ev.append((i, -1, "BOS" if trend == -1 else "CHoCH")); Lx = True; trend = -1
    ref = I.st_segment_structure(B, d)[0]
    assert [(B.ct.values[i], s, k) for i, s, k in ev] == [(t, s, k) for t, s, k, _ in ref]
    return ev, sw


def pivot_marks(B, N):
    st = I.pivot_structure(B, N); h, l = B.high.values, B.low.values
    ev = [(i, 1 if v > 0 else -1, "CHoCH" if abs(v) == 2 else "BOS") for i, v in enumerate(st["ev"]) if v]
    sw = [("H", i - N, h[i - N], i) for i in np.flatnonzero(~np.isnan(st["new_sh"]))] + \
         [("L", i - N, l[i - N], i) for i in np.flatnonzero(~np.isnan(st["new_sl"]))]
    return ev, sorted(sw, key=lambda x: x[3])


# ------------------------------------------------------------------ the contracts, as the books loaded them
@functools.lru_cache(None)
def _picks():
    return pd.read_parquet(os.path.join(chain.CACHE, "picks.parquet"))


@functools.lru_cache(None)
def _fam(first_rule):
    """watched days and first watched day per p100 contract (G3 counted its first day over ATM / p100 / p300), and the
    p100 pick per (day, right)."""
    P = _picks(); q = P[P.pick == "p100"]; key = ["expiry", "strike", "right"]
    wd = q.groupby(key).date.apply(set).to_dict()
    src = P[P.pick.isin(["ATM", "p100", "p300"])] if first_rule == "first3" else q
    first = src.groupby(key).date.min().to_dict()
    pick = {(d, r): (e, int(k)) for d, r, e, k in q[["date", "right", "expiry", "strike"]].itertuples(index=False)}
    return wd, first, pick


@functools.lru_cache(None)
def _atm_plan():
    return {D: (e, K) for D, e, K in chain.front_atm_plan()}


@functools.lru_cache(maxsize=48)
def contract(rule, e, K, r):
    """(1-minute frame, Contract or None) of one contract: G5 ('atm') keeps the whole folder in float64; the rest is an
    engine.Contract trimmed to 3 sessions before the first watched day."""
    X = data.read_expiry(e, strikes={K}, f32=rule != "atm")
    if X is None: raise ValueError(f"no data for {e} {K} {r}")
    g = X[(X.strike == K) & (X.right == r)].reset_index(drop=True)
    if rule == "atm" or (e, K, r) not in _fam(rule)[0]: return g, None
    wd, first, _ = _fam(rule)
    return g, Contract(e, K, r, g, wd[(e, K, r)], first[(e, K, r)])


def bars_of(rule, e, K, r, tf):
    g, C = contract(rule, e, K, r)
    return C.bars(tf) if C is not None else I.agg(g, tf)


# ------------------------------------------------------------------ one contract's payload over its whole loaded history
@functools.lru_cache(maxsize=48)
def layers(recipe, rule, e, K, r):
    """everything drawn for one contract: candles + lines on the pane timeframe, events, swings, an optional view."""
    R = dict(recipe)
    if R["chart"] in ("conf", "intraday"):
        B = bars_of(rule, e, K, r, 5); B15 = bars_of(rule, e, K, r, 15)
        d15, ln15 = st_line(B15, R["p"], R["m"])
        j = np.searchsorted(B15.ct.values, B.ct.values, side="right") - 1          # the 15-minute bar known at each 5-minute close
        known = lambda v: np.where(j >= 0, v[np.clip(j, 0, None)], np.nan)
        lines = {"15m ST up (as known)": (np.where(known(d15) == 1, known(ln15), np.nan), UP),
                 "15m ST down (as known)": (np.where(known(d15) == -1, known(ln15), np.nan), DN)}
        vlines = {"ST up": (np.where(d15 == 1, ln15, np.nan), UP), "ST down": (np.where(d15 == -1, ln15, np.nan), DN)}
        if R["chart"] == "intraday":
            em = I.ema(B15.close.values, 20); lines["15m EMA20 (as known)"] = (known(em), "#2962ff"); vlines["EMA20"] = (em, "#2962ff")
        ev, sw = pivot_marks(B, 3)
        view = dict(B=B15, lines=vlines, label=f"15-minute candles · Supertrend({R['p']},{R['m']:g})" + (" · EMA20" if R["chart"] == "intraday" else ""))
    else:
        B = bars_of(rule, e, K, r, R["tf"]); d, ln = st_line(B, R["p"], R["m"])
        lines = {f"ST({R['p']},{R['m']:g}) up": (np.where(d == 1, ln, np.nan), UP), f"ST({R['p']},{R['m']:g}) down": (np.where(d == -1, ln, np.nan), DN)}
        ev, sw = seg_structure(B, d) if R["chart"] == "stswing" else pivot_marks(B, R["N"]) if R["chart"] == "chochst" else ([], [])
        view = None
        if R.get("view_tf"):                           # a second leg on another timeframe (ST159: the BUY leg on 15 minutes)
            B2 = bars_of(rule, e, K, r, R["view_tf"]); d2, ln2 = st_line(B2, R["view_p"], R["view_m"]); ev2, sw2 = seg_structure(B2, d2)
            view = dict(B=B2, lines={"ST up": (np.where(d2 == 1, ln2, np.nan), UP), "ST down": (np.where(d2 == -1, ln2, np.nan), DN)},
                        ev=ev2, sw=sw2, label=f"{R['view_tf']}-minute candles · Supertrend({R['view_p']},{R['view_m']:g}) swings · {R.get('view_note', '')}")
    return dict(B=B, lines=lines, ev=ev, sw=sw, view=view)


def name(e, K, r):
    return f"NIFTY {pd.Timestamp(e):%d%b%y} {K} {r}".upper()


# ------------------------------------------------------------------ the pane: one contract, or the right's timeline
def _segments(recipe, rule, right, days, trades):
    """per session the contract the book watched or held: a trade's contract while it is open (from its entry session to its
    exit, switching at the exit when the next trade starts that session), else that day's pick."""
    T = sorted((t for t in trades if t["right"] == right), key=lambda t: t["t_in"])
    out = []
    for D in days:
        d0, d1 = D, D + pd.Timedelta(days=1)
        live = [t for t in T if t["t_in"] < d1 and t["t_out"] >= d0]
        if live:
            start = d0
            for k, t in enumerate(live):                  # one position per leg: the next trade starts after this one's exit
                end = d1 if k == len(live) - 1 else min(max(t["t_out"] + pd.Timedelta(minutes=1), start), d1)
                out.append((t["key"], start, end)); start = end
            continue
        if recipe["chart"] == "atm": c = _atm_plan().get(D)
        else: c = _fam(rule)[2].get((D, right))
        if c: out.append(((c[0], int(c[1]), right), d0, d1))
    return out


def pane_tf(recipe):
    return 5 if recipe["chart"] in ("conf", "intraday") else recipe["tf"]


def pane(recipe, rule, days, trades, rows_of, right=None, inst=None):
    """the CE / PE pane payload. days: sessions (Timestamps); trades: [{right, t_in, t_out, key, side, sig, entry_time,
    exit_time, entry (price), stop0, lock, tf, row}] of the run (row = the lab's trade row); inst = (e, K, r) for one contract over the range."""
    segs = [(inst, days[0], days[-1] + pd.Timedelta(days=1))] if inst else _segments(recipe, rule, right, days, trades)
    if not segs: raise ValueError(f"no {right} contract watched or held in this range")
    R = recipe; candles, lines, names, events, swings, miles, trows, stops = [], {}, [], [], [], [], [], []
    vc, vl, vlab, vev, vsw = [], {}, None, [], []
    prev = None
    for key, a, z in segs:
        e, K, r = key
        L = layers(tuple(sorted(R.items())), rule, e, K, r); B = L["B"]
        m = ((B.bk >= a) & (B.bk < z)).values
        idx = np.flatnonzero(m)
        if not len(idx): continue
        brk = prev is not None and prev != key
        t = [ts(x) for x in B.bk.values[idx]]
        if prev != key: miles.append(dict(ts=t[0], label=f"{K} {r} {pd.Timestamp(e):%d%b}")); names.append(name(e, K, r))
        candles += [[t[q], float(B.open.values[i]), float(B.high.values[i]), float(B.low.values[i]), float(B.close.values[i]), 0.0] for q, i in enumerate(idx)]
        for nm, (v, col) in L["lines"].items():
            arr = lines.setdefault(nm, ([], col))[0]
            if brk and arr: arr.append([t[0], None])
            arr += [[t[q], None if not np.isfinite(v[i]) else round(float(v[i]), 2)] for q, i in enumerate(idx)]
        pos = {int(i): q for q, i in enumerate(idx)}
        events += [[t[pos[i]], k, "up" if s > 0 else "down"] for i, s, k in L["ev"] if i in pos]
        swings += [[k, ts(B.bk.values[p]), round(float(v), 2), t[pos[i]]] for k, p, v, i in L["sw"] if i in pos]
        if L["view"]:
            V = L["view"]; vlab = V["label"]; B2 = V["B"]; i2 = np.flatnonzero(((B2.bk >= a) & (B2.bk < z)).values)
            t2 = [ts(x) for x in B2.bk.values[i2]]
            vc += [[t2[q], float(B2.open.values[i]), float(B2.high.values[i]), float(B2.low.values[i]), float(B2.close.values[i]), 0.0] for q, i in enumerate(i2)]
            for nm, (v, col) in V["lines"].items():
                arr = vl.setdefault(nm, ([], col))[0]
                if brk and arr and t2: arr.append([t2[0], None])
                arr += [[t2[q], None if not np.isfinite(v[i]) else round(float(v[i]), 2)] for q, i in enumerate(i2)]
            p2 = {int(i): q for q, i in enumerate(i2)}
            vev += [[t2[p2[i]], k, "up" if s > 0 else "down"] for i, s, k in V.get("ev", []) if i in p2]
            vsw += [[k, ts(B2.bk.values[p]), round(float(v), 2), t2[p2[i]]] for k, p, v, i in V.get("sw", []) if i in p2]
        mine = rows_of(key)
        trows += [x for x in mine if x["entry_time"] <= B.bk.values[idx[-1]] + np.timedelta64(pane_tf(R), "m") and x["exit_time"] >= B.bk.values[idx[0]]]
        stops += _stop_paths(R, rule, key, mine, B, idx, t)
        prev = key
    if not candles: raise ValueError("no candles for this contract in this range")
    seen, rows = set(), []
    for x in trows:
        if id(x) not in seen: seen.add(id(x)); rows.append(x["row"])
    ln = list(lines.items())
    out = dict(candles=candles, lines=[v[0] for _, v in ln], line_names=[k for k, _ in ln], line_colors=[v[1] for _, v in ln],
               events=events, swings=swings, label_bos=True, wide=True, trades=rows, olines=stops, names=names,
               milestones=miles if len(miles) > 1 or not inst else [])
    if vc:
        vv = list(vl.items())
        out["views"] = [dict(label=vlab, candles=vc, lines=[v[0] for _, v in vv], line_names=[k for k, _ in vv], line_colors=[v[1] for _, v in vv],
                             events=vev, swings=vsw)]
    return out


def _stop_paths(R, rule, key, rows, B, idx, t):
    """per trade on this contract: the stop in force at each bar (swing books: the initial swing stop, moved to every newer
    confirmed swing - never loosened - and to the entry once the lock triggered) and the lock trigger level."""
    out = []
    if not rows: return out
    bk = B.bk.values[idx]; tsb = np.array(t); tf = np.timedelta64(pane_tf(R), "m")
    g, C = contract(rule, *key)
    for row in rows:
        side, E, et, xt, lock = row["side"], row["entry"], row["entry_time"], row["exit_time"], str(row.get("lock") or "none")
        live = (bk > et - tf) & (bk <= xt)
        if not live.any(): continue
        tt = tsb[live]
        if lock not in ("none", "normal", "trail", "nan"):              # the §5.4 locks and lock50 trigger at entry -/+ 50 points
            lv = E - 50 if side < 0 else E + 50
            out.append(dict(name="lock trigger", color="#8e8e93", pts=[[int(tt[0]), round(lv, 2)], [int(tt[-1]), round(lv, 2)]]))
        if row.get("stop0") is None or not np.isfinite(row["stop0"]) or C is None: continue
        Bs, sws = B, _upd_swings(R, rule, key)
        if R.get("view_tf") and row.get("tf") == R["view_tf"]:          # the 15-minute leg trails on its own swings
            V = layers(tuple(sorted(R.items())), rule, *key)["view"]; Bs, sws = V["B"], V["sw"]
        upd = [(Bs.ct.values[i], v) for (k, p, v, i) in sws if (k == "L") == (side > 0)]
        stop = row["stop0"]; pts = []; lk_t = None
        if "lock50" in lock:                                            # swing_trade: from the minute after +50, the stop is at least the entry
            j0 = np.searchsorted(C.dt, et); j1 = np.searchsorted(C.dt, xt)
            hit = np.flatnonzero((C.hi[j0:j1 + 1] >= E + 50) if side > 0 else (C.lo[j0:j1 + 1] <= E - 50))
            if len(hit): lk_t = C.dt[j0 + hit[0]] + np.timedelta64(1, "m")
        for b, tb in zip(bk[live], tt):
            for ut, v in upd:                                           # a swing confirmed at a bar close moves the stop from then on
                if row["sig"] < ut <= b: stop = max(stop, v) if side > 0 else min(stop, v)
            s_ = stop
            if lk_t is not None and lk_t < b + tf: s_ = max(s_, E) if side > 0 else min(s_, E)
            pts.append([int(tb), round(float(s_), 2)])
        out.append(dict(name="stop", color="#d32f2f", pts=pts))
    return out


@functools.lru_cache(maxsize=48)
def _upd_swings_c(recipe, rule, key):
    return layers(recipe, rule, *key)["sw"]


def _upd_swings(R, rule, key):
    return _upd_swings_c(tuple(sorted(R.items())), rule, key)


# ------------------------------------------------------------------ the main chart: the index for reference
@functools.lru_cache(maxsize=8)
def index_bars(tf):
    return I.agg(data.index_1m(), tf)


def chop_at(sig):
    """§4.6 day-so-far values at a signal (the 1-minute bar that closes at the signal time)."""
    X = F.chop_features().reindex([pd.Timestamp(sig) - pd.Timedelta(minutes=1)]).iloc[0]
    return dict(ER=round(float(X.ER), 3), rng_adr=round(float(X.rng_so_far), 2), pos=round(float(X.pos_in_rng), 2))
