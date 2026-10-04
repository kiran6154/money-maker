"""The slice of v1 lab.py the learner (rl.py) calls, for v2: the functions below are copied verbatim from v1 lab.py
(string times, as rl.py uses them), except two: manage() runs its candle loop in numba (_manage_loop, the same statements
on arrays; the records it returns are built exactly as v1's, in the same order), and fut_contracts reads v2's cached
futures file. Nothing here is used by the other strategies, which run on core.py.
"""
import bisect, calendar, datetime as D, json, math, os, re
import numpy as np
from numba import njit
import core

_ARR = {}                     # id(times list) -> (o, h, l, c, day) arrays of the same candles (rl_engine.load registers them)
def register(bars, b):
    _ARR[id(bars["t"])] = (b.o, b.h, b.l, b.c, b.day, bars["t"])


@njit(cache=True)
def _manage_loop(o, h, l, c, day, i0, iend, long, e, R, stop, tgt, trail, start_r, lag_r):
    """v1 manage()'s candle loop. tgt: per lot, the target or nan (the trailing rest). Returns per lot the exit candle
    (-1 = still open), price and reason (0 target, 1 stop_loss, 2 trail_stop)."""
    m = len(tgt)
    xk = np.full(m, -1, np.int64); xp = np.zeros(m); xr = np.zeros(m, np.int8)
    open_ = np.ones(m, np.bool_); nopen = m
    sg = 1.0 if long else -1.0
    best = e; trailing = False
    for k in range(i0, iend + 1):
        first = k > 0 and day[k] != day[k - 1]
        gap = o[k] <= stop if long else o[k] >= stop
        if gap or (l[k] <= stop if long else h[k] >= stop):
            px = c[k] if first else (o[k] if gap else stop)
            for j in range(m):
                if open_[j]:
                    xk[j] = k; xp[j] = px; xr[j] = 2 if trailing else 1; open_[j] = False
            nopen = 0
            break
        for j in range(m):
            if not open_[j] or np.isnan(tgt[j]): continue
            t_ = tgt[j]
            g = o[k] >= t_ if long else o[k] <= t_
            if first:
                if c[k] >= t_ if long else c[k] <= t_:
                    xk[j] = k; xp[j] = c[k]; xr[j] = 0; open_[j] = False; nopen -= 1
            elif g or (h[k] >= t_ if long else l[k] <= t_):
                xk[j] = k; xp[j] = o[k] if g else t_; xr[j] = 0; open_[j] = False; nopen -= 1
        if nopen == 0: break
        if trail:
            best = max(best, h[k]) if long else min(best, l[k])
            reached = math.floor(sg * (best - e) / R + 1e-9)
            if reached >= start_r:
                new = e + sg * (reached - lag_r) * R
                if (new > stop) if long else (new < stop):
                    stop = new; trailing = True
    return xk, xp, xr

HERE = os.path.dirname(os.path.abspath(__file__))
POSITION_DEFAULT = {"lots": 1, "lock": "strike", "scale_out": [], "exit": "strategy", "stop": None, "trail": None,
                    "square_off": None, "reverse": None}
REVERSE_TRIGGERS = ("initial_stop",)
POSITION_EXITS = ("strategy", "position")
POSITION_LOCKS = ("strike", "none")


def position_of(spec):
    """The file's `position` block over POSITION_DEFAULT, validated:
    {lots, lock, scale_out: [{lots, target_pts | target_r}], exit, stop: {futures_pts, option_pct}, trail: {start_r, lag_r}}."""
    p = dict(POSITION_DEFAULT, **(spec.get("position") or {}))
    unknown = set(p) - set(POSITION_DEFAULT)
    if unknown: raise ValueError(f"unknown key(s) {sorted(unknown)}")
    if not isinstance(p["lots"], int) or p["lots"] < 1: raise ValueError("lots must be a whole number >= 1")
    if p["lock"] not in POSITION_LOCKS: raise ValueError(f"lock must be one of {POSITION_LOCKS}")
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
    if p["exit"] not in POSITION_EXITS: raise ValueError(f"exit must be one of {POSITION_EXITS}")
    if p["stop"] is not None and (set(p["stop"]) != {"futures_pts", "option_pct"} or not all(map(num, p["stop"].values()))):
        raise ValueError('stop is {"futures_pts": pts > 0, "option_pct": % of the entry premium > 0}')
    if p["trail"] is not None and (set(p["trail"]) != {"start_r", "lag_r"} or not all(map(num, p["trail"].values()))):
        raise ValueError('trail is {"start_r": R > 0, "lag_r": R > 0}')
    if p["exit"] == "position" and p["stop"] is None: raise ValueError('exit "position" needs a stop (lots would never close)')
    if p["reverse"] is not None:
        rv = p["reverse"]
        if not isinstance(rv, dict) or set(rv) != {"trigger", "max"} or rv["trigger"] not in REVERSE_TRIGGERS \
                or not isinstance(rv["max"], int) or rv["max"] < 1:
            raise ValueError(f'reverse is {{"trigger": one of {REVERSE_TRIGGERS}, "max": reversals per signal >= 1}}, or null')
        if p["exit"] != "position": raise ValueError('reverse needs exit "position" (it reverses at the managed stop)')
    if p["square_off"] is not None and not (isinstance(p["square_off"], str) and re.fullmatch(r"\d\d:\d\d", p["square_off"])
                                            and "09:15" < p["square_off"] <= "15:30"):
        raise ValueError('square_off is "HH:MM" after 09:15 and up to 15:30 (every position closed by then), or null')
    if (p["trail"] or any("target_r" in so for so in p["scale_out"])) and p["stop"] is None:
        raise ValueError("target_r / trail are multiples of the stop distance (R): they need a stop")
    for so in p["scale_out"]:
        if set(so) not in ({"lots", "target_pts"}, {"lots", "target_r"}):
            raise ValueError('each scale_out entry is {"lots": n, "target_pts": pts} or {"lots": n, "target_r": R}')
        if not isinstance(so["lots"], int) or so["lots"] < 1: raise ValueError("scale_out lots must be a whole number >= 1")
        if not num(so.get("target_pts", so.get("target_r"))): raise ValueError("a target must be > 0")
    if sum(so["lots"] for so in p["scale_out"]) > p["lots"]: raise ValueError("scale_out lots add up to more than lots")
    return p


def ts(s): return calendar.timegm(D.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").timetuple())


def trade_charges(cs, buy_px, sell_px, qty):
    """Round-trip charges for one buy order and one sell order of qty units."""
    buy, sell = buy_px * qty, sell_px * qty
    pct = lambda v, p: v * p / 100
    if cs.get("brokerage_flat"):
        brokerage = 2 * cs["brokerage_flat"]
    else:
        brokerage = min(pct(buy, cs["brokerage_pct"]), cs["brokerage_cap"]) + min(pct(sell, cs["brokerage_pct"]), cs["brokerage_cap"])
    stt = pct(buy, cs["stt_buy_pct"]) + pct(sell, cs["stt_sell_pct"])
    exch = pct(buy + sell, cs["exchange_pct"])
    sebi = pct(buy + sell, cs["sebi_pct"])
    stamp = pct(buy, cs["stamp_buy_pct"])
    gst = pct(brokerage + exch + sebi, cs["gst_pct"])
    return dict(brokerage=brokerage, stt=stt, exchange=exch, sebi=sebi, stamp=stamp, gst=gst,
                total=brokerage + stt + exch + sebi + stamp + gst)


def excursion(tl, hl, ll, rec, long):
    """Max favourable / adverse move inside the trade, in traded-instrument points (before slippage).
    Uses candles after the entry candle up to and including the exit candle."""
    i0 = bisect.bisect_right(tl, rec["entry_time"]); i1 = bisect.bisect_right(tl, rec["exit_time"]) - 1
    if i1 < i0:
        rec.update(mfe=0.0, mae=0.0); return rec
    hi, lo, e = max(hl[i0:i1 + 1]), min(ll[i0:i1 + 1]), rec["entry_px"]
    fav, adv = (hi - e, lo - e) if long else (e - lo, e - hi)
    rec.update(mfe=round(max(fav, 0.0), 2), mae=round(min(adv, 0.0), 2))
    return rec


def price_trade(st, cs, rec):
    """Slippage, gross, charges, net for a trade record with entry_px / exit_px in traded-instrument units, for its `lots`
    (a scale-out tranche is charged as its own round trip)."""
    lot, slip = st["lot_size"] * rec.setdefault("lots", 1), st["slippage_pts"]
    if rec["position"] == "SHORT":                             # short: sell entry, buy exit
        sell, buy = rec["entry_px"] - slip, rec["exit_px"] + slip
    else:                                                      # long future or long option
        buy, sell = rec["entry_px"] + slip, rec["exit_px"] - slip
    pts = sell - buy
    rec.update(pts=pts, gross=pts * lot, chg=trade_charges(cs, buy, sell, lot))
    rec["net"] = rec["gross"] - rec["chg"]["total"]
    return rec


def position_cfg(st):
    return json.loads(st["position_json"]) if st.get("position_json") else dict(POSITION_DEFAULT)


class StrikeLock:
    """lock "strike": one open position per traded instrument (strike + expiry + right, or the futures contract). A new
    entry while that instrument's position is open is skipped; an exit and a new entry on the same candle count as
    exit first, so the new position is taken."""

    def __init__(self, st):
        self.on, self.until = position_cfg(st)["lock"] == "strike", {}     # inst -> (last exit time, still open at that candle)

    def held(self, inst, entry_time):
        """The open position's exit time if `inst` is locked at `entry_time`, else None. A position that has not exited
        (still open at its last candle, e.g. the data's end) locks that candle too."""
        u = self.until.get(inst)
        if not self.on or u is None: return None
        t, still_open = u
        return t if (entry_time <= t if still_open else entry_time < t) else None

    def hold(self, inst, exit_time, still_open=False):
        cur = self.until.get(inst)
        if cur is None or exit_time > cur[0] or (exit_time == cur[0] and still_open): self.until[inst] = (exit_time, still_open)


def square_off_at(st, entry_time):
    """The session-end cut for a position entered at entry_time ("YYYY-MM-DD HH:MM:00"), or None (position.square_off)."""
    T = position_cfg(st).get("square_off")
    return f"{entry_time[:10]} {T}:00" if T else None


def manage(st, rec, tl, ol, hl, ll, cl, cap, expiry=None):
    """exit "position": the position is managed from the entry fill on its own candles and the strategy's exit (the next
    CHoCH, rules.sl_rule) is not used. R = stop.futures_pts for futures, stop.option_pct % of the entry premium for options;
    the stop starts 1R against the entry for every lot. Candle by candle after the entry candle, up to `cap` (the backtest's
    last candle, or the contract's last candle before it):
      1. stop - all open lots exit at the stop (at the candle open if it opens beyond it; on a session's first candle at its
         close: no fill on the opening print). The stop is checked before targets on the same candle.
      2. targets - each scale_out lot exits at entry +/- target_r x R (or target_pts): at the candle open if it opens beyond
         the target, else at the target; on a session's first candle only if its close is still at or beyond the target,
         at that close.
      3. trail - from the best price so far: once start_r full R are reached, the stop moves to (reached R - lag_r) x R and
         steps up by whole R after that (never back). A move made on this candle applies from the next candle.
    Lots still open at `cap` close at its candle: reason 'expiry' at the contract's end, else 'open' (valued, marked *).
    Returns one record per lot group (tranche), like tranches()."""
    P = position_cfg(st)
    long, e, kind = rec["position"] == "LONG", rec["entry_px"], rec["kind"]
    sg = 1 if long else -1
    R = P["stop"]["futures_pts"] if kind == "FUT" else e * P["stop"]["option_pct"] / 100
    stop = e - sg * R
    tag = lambda so: f"{so['target_r']:g}R" if "target_r" in so else f"+{so['target_pts']:g}"
    lots = [dict(lots=so["lots"], tranche=f"T{n} {tag(so)}", tgt=e + sg * (so["target_r"] * R if "target_r" in so else so["target_pts"]),
                 why=f"target {tag(so)}") for n, so in enumerate(P["scale_out"], 1)]
    left = P["lots"] - sum(so["lots"] for so in P["scale_out"])
    if left: lots.append(dict(lots=left, tranche="rest" + (" (trail)" if P["trail"] else ""), tgt=None))
    eod = square_off_at(st, rec["entry_time"])
    if eod: cap = min(cap, eod)                       # intraday: the session-end cut is the last candle
    i0 = bisect.bisect_right(tl, rec["entry_time"]); iend = bisect.bisect_right(tl, cap) - 1
    out = []
    base = dict(rec, sl=round(stop, 2))
    o_, h_, l_, c_, day_, tl_ = _ARR[id(tl)]
    assert tl_ is tl and ol is not None
    T = P["trail"]
    xk, xp, xr = _manage_loop(o_, h_, l_, c_, day_, i0, iend, long, float(e), float(R), float(stop),
                              np.array([np.nan if x["tgt"] is None else x["tgt"] for x in lots], dtype=np.float64),
                              bool(T), float(T["start_r"]) if T else 0.0, float(T["lag_r"]) if T else 0.0)
    closed = sorted((int(xk[j]), j) for j in range(len(lots)) if xk[j] >= 0)    # v1's order: by candle, then lot order
    for k, j in closed:
        lot = lots[j]
        why = lot["why"] if xr[j] == 0 else ("trail_stop" if xr[j] == 2 else "stop_loss")
        out.append(dict(base, lots=lot["lots"], tranche=lot["tranche"], exit_time=tl[k], exit_px=round(float(xp[j]), 2),
                        exit_reason=why, open=False))
    lots = [lots[j] for j in range(len(lots)) if xk[j] < 0]
    if lots:
        k = max(iend, i0 - 1)
        ended = expiry is not None and k >= 0 and tl[k][:10] >= expiry     # the contract's end; the data's end alone leaves it open
        # the square-off candle: the one opening at the square-off time, or the last one before it when the next candle is past it;
        # data that simply ends earlier that day leaves the lots open
        at_eod = bool(eod) and k >= 0 and tl[k][:10] == eod[:10] and (tl[k] >= eod or (k + 1 < len(tl) and tl[k + 1] > eod))
        for lot in lots:
            out.append(dict(base, lots=lot["lots"], tranche=lot["tranche"], exit_time=tl[k], exit_px=cl[k],
                            exit_reason="expiry" if ended else "eod" if at_eod else "open", open=not (ended or at_eod)))
    return out


_FC = {}
def fut_contracts():
    """({time: (contract, expiry)}, {contract: its last candle time}) from the 1-minute futures file (v1 lab.fut_contracts)."""
    if "x" not in _FC:
        t_, con, exp, last = core.fut_contracts()
        ts_ = core.tstrs(t_).tolist()
        by = {x: (c, e or None) for x, c, e in zip(ts_, con.tolist(), exp.tolist())}
        _FC["x"] = (by, {c: core.tstr(v) for c, v in last.items()})
    return _FC["x"]
