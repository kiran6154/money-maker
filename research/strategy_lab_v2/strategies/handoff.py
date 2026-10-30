"""The handoff "NIFTY Supertrend / CHoCH-BOS option strategies" books (nifty_bt/, STRATEGY_ANALYSIS_TODO S162) on the
dashboard - family module for ST151 - ST159.

The books are built by nifty_bt (09:19 strike scan, premium-chart Supertrend / swing structure, locks, sequencing; lot 75,
the spec's option charges incl. Rs 0.10 slippage a side). This module only reads the trade lists nifty_bt wrote and hands
them to the lab, so the dashboard numbers are nifty_bt's numbers:
    G1 - G7      results/nifty_bt/golden/G<n>.csv           python -m nifty_bt.golden
    the books    results/nifty_bt/books/<book>.csv          python -m nifty_bt.books
SPEC['handoff'] = {'source': 'golden' | 'books', 'file': <csv name without .csv>, 'side': -1 / +1 (lists without a side
column; G5 sells)}.
"""
import datetime as Dt
import os
import numpy as np
import pandas as pd
import core

ENTRY_RULES = ("handoff_v1",)
TYPES = ("OPT_FUT_SIGNAL",)
UNDERLYINGS = ("FUT", "INDEX")
OWN_COVERAGE = True
REFUSED_WHY = "the handoff books trade the option contracts themselves; only the Options type runs"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(HERE, "results", "nifty_bt")
LOT = 75
_MEM = {}


def trades_of(P):
    key = (P["source"], P["file"])
    if key in _MEM: return _MEM[key]
    sub, cmd = ("golden", "python -m nifty_bt.golden") if P["source"] == "golden" else ("books", "python -m nifty_bt.books")
    f = os.path.join(RES, sub, P["file"] + ".csv")
    if not os.path.exists(f): raise FileNotFoundError(f"{f} is missing - run `{cmd}` from research/strategy_lab_v2 first")
    T = pd.read_csv(f, parse_dates=["sig", "entry_time", "exit_time"])
    if "side" not in T: T["side"] = P.get("side", -1)
    _MEM[key] = T
    return T


def _ts(x):
    return int(pd.Timestamp(x).value // 10**9)


def run(ctx):
    spec = ctx["spec"]; d0, d1 = ctx["date_from"], ctx["date_to"]
    T = trades_of(spec["handoff"]); trs = []
    for t in T.itertuples(index=False):
        if not (d0 <= str(t.entry_time)[:10] <= d1): continue
        side = int(t.side); pts = side * (float(t.exit) - float(t.entry)); gross = pts * LOT
        bull = side * (1 if t.right == "CE" else -1) > 0
        name = f"NIFTY {Dt.date.fromisoformat(str(t.expiry)[:10]):%d%b%y} {int(t.strike)} {t.right}".upper()
        stop = getattr(t, "stop0", None)
        tag = " · ".join(str(v) for v in (getattr(t, "st", None), getattr(t, "kind", None) or getattr(t, "conf", None), getattr(t, "lock", None))
                         if isinstance(v, str) and v)
        trs.append(dict(dir="up" if bull else "down", signal="BULLISH" if bull else "BEARISH", choch_time=_ts(t.sig), und_entry=None,
                        und_exit=None, stale=False, lots=1, tranche="", position="LONG" if side > 0 else "SHORT", opt_type=t.right, kind="OPT",
                        instrument=name, strike=int(t.strike), expiry=str(t.expiry)[:10], entry_time=_ts(t.entry_time), entry_px=float(t.entry),
                        exit_time=_ts(t.exit_time), exit_px=float(t.exit), exit_reason=str(t.why), open=False,
                        sl=None if stop is None or stop != stop else float(stop), pts=pts, gross=gross, chg=dict(total=gross - float(t.net)),
                        net=float(t.net), label=f"{'BUY' if side > 0 else 'SELL'} {t.right}" + (f" · {tag}" if tag else "")))
    trs.sort(key=lambda x: x["entry_time"])
    return {ch: dict(trades=trs, skipped=[], signals=[]) for ch in core.choice_keys(spec, "OPT_FUT_SIGNAL")}


def signals(bars, spec):
    return core.foundation(bars, spec["rules"])


# ------------------------------------------------------------------ charts (nifty_bt/chartdata.py builds every line and mark)
RECIPE_WHAT = {
    "stswing": "Supertrend on the premium (green up / red down); swing = the highest high (lowest low) of a finished Supertrend segment, "
               "marked when the segment flips; CHoCH / BOS = a close beyond the last swing",
    "chochst": "pivot swings ({N} bars each side, marked when confirmed) and their CHoCH / BOS; the Supertrend has to agree before the entry",
    "conf": "5-minute candles: the 3-bar pivot CHoCH / BOS are the entry trigger; the 15-minute Supertrend is drawn as the engine knew it at "
            "each 5-minute close (the trade needs it on its side); the 15-minute chart is below",
    "intraday": "5-minute candles: the 3-bar pivot CHoCH / BOS trigger; the 15-minute Supertrend and EMA20 as known at each 5-minute close "
                "(a close through the EMA20 exits); the 15-minute chart is below; flat by 15:15",
    "atm": "60-minute candles of the front-expiry ATM contract over its whole folder history; sold when the Supertrend turns down",
}


def _recipe(spec):
    return {k: v for k, v in spec["handoff"]["chart"].items()}


def _rule(spec):
    return spec["handoff"]["chart"].get("first", "atm" if spec["handoff"]["chart"]["chart"] == "atm" else "p100")


def _sessions(day, to):
    from nifty_bt import chain
    d0, d1 = pd.Timestamp(day), pd.Timestamp(to)
    return [d for d in chain.sessions() if d0 <= d <= d1]


def _trade_info(spec, body, day, to):
    """the run's trades overlapping day..to with nifty_bt's own fields (signal time, initial stop, lock, timeframe)."""
    C = {k: i for i, k in enumerate(body["cols"])}
    T = trades_of(spec["handoff"]); T = T.assign(kk=T.entry_time.dt.strftime("%Y-%m-%d %H:%M"), expiry=T.expiry.astype(str).str[:10])
    by = {(r.expiry, int(r.strike), r.right, r.kk): r for r in T.itertuples(index=False)}
    out = []
    for x in body["trades"]:
        if str(x[C["exit_time"]])[:10] < day or str(x[C["entry_time"]])[:10] > to: continue
        key = (str(x[C["expiry"]]), int(x[C["strike"]]), str(x[C["opt_type"]]))
        r = by.get(key + (str(x[C["entry_time"]])[:16],))
        if r is None: continue
        st = str(getattr(r, "st", "") or "")
        out.append(dict(key=key, right=key[2], row=x, side=int(r.side), sig=np.datetime64(r.sig),
                        entry_time=np.datetime64(r.entry_time), exit_time=np.datetime64(r.exit_time), entry=float(r.entry),
                        stop0=getattr(r, "stop0", None), lock=getattr(r, "lock", None), tf=int(st.split("m")[0]) if st[:1].isdigit() else None))
    for o in out: o["t_in"], o["t_out"] = pd.Timestamp(o["entry_time"]), pd.Timestamp(o["exit_time"])
    return out


def chart_main(ctx, body, day, to):
    """NIFTY (index) candles on the book's chart timeframe, for reference - every signal is read on the option's own chart,
    in the CE / PE panes below (chart_leg). The trades are marked where they happened."""
    from nifty_bt import chartdata as CD
    R = _recipe(ctx["spec"]); tf = CD.pane_tf(R)
    B = CD.index_bars(tf); m = ((B.bk >= pd.Timestamp(day)) & (B.bk < pd.Timestamp(to) + pd.Timedelta(days=1))).values
    if not m.any(): raise ValueError(f"no index candles between {day} and {to}")
    S = B[m]
    candles = [[CD.ts(t), float(o), float(h), float(l), float(c), 0.0] for t, o, h, l, c in zip(S.bk, S.open, S.high, S.low, S.close)]
    what = RECIPE_WHAT[R["chart"]].format(**R)
    info = _trade_info(ctx["spec"], body, day, to)
    chop = ""
    if R["chart"] == "intraday":
        chop = " · chop filter at each signal (needs range / ADR >= 0.8, ER >= 0.10, position in the day's range >= 0.8): " + "; ".join(
            f"{str(o['sig'])[5:16].replace('T', ' ')} ER {c['ER']} rng/ADR {c['rng_adr']} pos {c['pos'] if o['side'] * (1 if o['right'] == 'CE' else -1) > 0 else round(1 - c['pos'], 2)}"
            for o in info if o["t_in"].strftime("%Y-%m-%d") >= day for c in [CD.chop_at(o["sig"])])
    return dict(day=day, to=to, inst=f"NIFTY index {tf}m", candles=candles, cols=body["cols"], trades=[o["row"] for o in info], own=False,
                sessions=len(set(S.bk.dt.normalize())),
                derived=dict(plain=True, what=f"NIFTY index {tf}-minute candles for reference only - the book reads nothing here; each signal is read on "
                                  f"the option's own chart in the CE / PE panes below: {what}; red step = the stop in force, grey = the lock "
                                  f"trigger (entry -/+ 50); purple tags = where the pane moves to another contract{chop}"))


def chart_leg(ctx, body, day, to, atm=None, inst=None):
    """One right's option chart over day..to: 'ATM' = the contract the book watched or held each session (the day's ₹100+ pick,
    the front ATM for G5, or the open trade's contract), or one traded contract over the whole range - candles of the option
    itself with the Supertrend, swings, CHoCH / BOS, the stop path, the lock level and the trades, as the engine read them."""
    from nifty_bt import chartdata as CD
    spec = ctx["spec"]; R = _recipe(spec); rule = _rule(spec)
    days = _sessions(day, to)
    if not days: raise ValueError(f"no sessions between {day} and {to}")
    info = _trade_info(spec, body, (days[0] - pd.Timedelta(days=40)).strftime("%Y-%m-%d"), to)   # positions opened before the range
    by = {}
    for o in info: by.setdefault(o["key"], []).append(o)
    one = None
    if inst:
        C = {k: i for i, k in enumerate(body["cols"])}
        x = next((x for x in body["trades"] if str(x[C["instrument"]]) == inst), None)
        if x is None: raise ValueError(f"{inst} is not traded in this run")
        one = (str(x[C["expiry"]]), int(x[C["strike"]]), str(x[C["opt_type"]]))
    right = one[2] if one else atm
    out = CD.pane(R, rule, days, info, lambda k: by.get(k, []), right=right, inst=one)
    nm = inst or f"{right} watched / held: " + ", ".join(n.split(" ", 1)[1] for n in out.pop("names"))
    out.pop("names", None)
    return dict(out, day=day, to=to, inst=nm, cols=body["cols"], own=True, sessions=len(days),
                derived=dict(plain=True, what=RECIPE_WHAT[R["chart"]].format(**R)))
