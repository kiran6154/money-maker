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


def chart_main(ctx, body, day, to):
    """The traded contract's own candles on the book's timeframe (the first trade entered in the range, else the latest one
    open by then), with every trade on that contract."""
    from nifty_bt import data, indicators as I
    C = {k: i for i, k in enumerate(body["cols"])}; rows = body["trades"]
    pick = next((x for x in rows if day <= str(x[C["entry_time"]])[:10] <= to), None)
    if pick is None:
        live = [x for x in rows if str(x[C["entry_time"]])[:10] <= to and str(x[C["exit_time"]])[:10] >= day]
        pick = live[-1] if live else None
    if pick is None: raise ValueError(f"no trade open between {day} and {to}")
    exp, k, r = str(pick[C["expiry"]]), int(pick[C["strike"]]), str(pick[C["opt_type"]])
    X = data.read_expiry(exp, strikes={k})
    g = X[(X.strike == k) & (X.right == r)].reset_index(drop=True)
    B = I.agg(g, core.TF_MIN[ctx["spec"]["timeframe"]])
    dd = B.bk.dt.strftime("%Y-%m-%d")
    sel = np.nonzero(((dd >= day) & (dd <= to)).values)[0]
    if not len(sel): sel = np.nonzero((dd >= str(pick[C["entry_time"]])[:10]).values)[0][:80]
    candles = [[_ts(B.bk.iloc[i]), float(B.open.iloc[i]), float(B.high.iloc[i]), float(B.low.iloc[i]), float(B.close.iloc[i]), 0.0] for i in sel]
    nm = f"NIFTY {Dt.date.fromisoformat(exp):%d%b%y} {k} {r}".upper()
    return dict(day=day, to=to, inst=nm, candles=candles, cols=body["cols"], trades=[x for x in rows if str(x[C["instrument"]]) == nm],
                own=True, lines=[], line_names=[], line_colors=[], sessions=len(set(dd.iloc[sel])) if len(sel) else 1,
                derived=dict(what=f"{nm}, {ctx['spec']['timeframe']} bars of the option itself"))
