"""S163 - the option's own previous-day average price as the gate to buy it the next day.

Contract per session and right: the 09:19 pick of nifty_bt (ATM = strike nearest the 09:15 five-minute spot, p100 = cheapest
premium in Rs100-500; expiry the nearest strictly after the day) - known at 09:20, nothing chosen with hindsight.
Level L = that same contract's previous-session average price:
    vwap  = sum(typical * volume) / sum(volume) over the previous session's 1-min bars (needs volume > 0)
    mean  = mean of the previous session's 1-min closes
Entry (5-minute bars, 09:15-anchored, a bar known at its close; first entry 09:20 = the 09:15 bar's close, last 14:30):
    cross = the first 5-min close above L whose previous 5-min close was <= L (a fresh cross-over)
    above = the first 5-min close above L (already above at 09:20 counts)
Exit:
    eod   = 15:15 one-minute close
    back  = the first 5-min close back below L (at that close), else eod
    low   = stop at the signal bar's low, watched on 1-min bars (fill at the worse of the bar's open and the stop), else eod
Baselines (no gate): buy at 09:20 and hold to 15:15, split by whether the 09:19 close was above or below L.
Then the gate on the existing BUY books (ST152 = G2, ST154 = G4, ST157 = G7, the BUY legs of ST158 / ST159): their trades
split by entry price above / below the entry contract's previous-session average.
One lot of 75, nifty_bt charges, Rs0.10 slippage per side (and the result at Rs1). Simulation only.

    python tools/prevavg_cross.py          (from research/strategy_lab_v2; ~10-20 min, one expiry in memory at a time)
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain
from nifty_bt.costs import net, LOT

OUT = os.path.join(chain.CACHE, "prevavg")
os.makedirs(OUT, exist_ok=True)
SESS = chain.sessions()
PREV = {d: SESS[i - 1] for i, d in enumerate(SESS) if i}
FIRST, LAST, EOD = 9 * 60 + 20, 14 * 60 + 30, 15 * 60 + 15


def prev_levels(g, D):
    """(vwap, mean, bars) of contract frame g on the session before D."""
    p = PREV.get(D)
    if p is None: return None
    y = g[g.date == p]
    if len(y) < 200: return None
    tp = (y.high + y.low + y.close) / 3.0; v = y.volume.astype(float)
    vw = float((tp * v).sum() / v.sum()) if v.sum() > 0 else np.nan
    return vw, float(y.close.mean()), len(y)


def bars5(x):
    """5-min bars of one session's 1-min frame x (09:15-anchored): [start tod, close tod, o, h, l, c]."""
    k = (x.tod.values - 555) // 5
    b = x.groupby(k).agg(o=("open", "first"), h=("high", "max"), l=("low", "min"), c=("close", "last"), t=("tod", "last"))
    b["start"] = b.index * 5 + 555; b["ct"] = b.start + 5          # known at ct (the 1-min close of the bar's last minute)
    return b.reset_index(drop=True)


def exit_from(x, b, i, L, how, stop=None):
    """exit (tod, price, why) for an entry at 5-min bar i's close."""
    t0 = b.ct[i]
    if how == "back":
        for j in range(i + 1, len(b)):
            if b.ct[j] > EOD: break
            if b.c[j] < L: return int(b.ct[j]), float(b.c[j]), "back below"
    if how == "low":
        m = x[(x.tod >= t0) & (x.tod < EOD)]
        hit = m[m.low <= stop]
        if len(hit):
            r = hit.iloc[0]; return int(r.tod), float(min(r.open, stop)), "stop"
    e = x[x.tod <= EOD - 1]
    if not len(e): return None
    return int(e.tod.iloc[-1]) + 1, float(e.close.iloc[-1]), "eod"


def trades_for(D, r, pick, x, lv):
    out = []
    b = bars5(x)
    if len(b) < 10: return out
    vw, mn, _ = lv
    c919 = x[x.tod <= 559]
    if len(c919):                                   # the no-gate baseline: buy at 09:20 (the 09:19 close)
        E = float(c919.close.iloc[-1]); ex = exit_from(x, b, 0, None, "eod")
        if ex:
            for lvn, L in (("vwap", vw), ("mean", mn)):
                if L == L:
                    out.append(dict(date=D, right=r, pick=pick, level=lvn, entry_rule="base_" + ("above" if E > L else "below"), exit_rule="eod",
                                    L=L, t_in=FIRST, entry=E, t_out=ex[0], exit=ex[1], why=ex[2]))
    for lvn, L in (("vwap", vw), ("mean", mn)):
        if L != L: continue
        for rule in ("cross", "above"):
            i = None
            for j in range(len(b)):
                if b.ct[j] < FIRST: continue
                if b.ct[j] > LAST: break
                if b.c[j] > L and (rule == "above" or (j > 0 and b.c[j - 1] <= L)):
                    i = j; break
            if i is None: continue
            E = float(b.c[i])
            for how in ("eod", "back", "low"):
                ex = exit_from(x, b, i, L, how, stop=float(b.l[i]))
                if ex: out.append(dict(date=D, right=r, pick=pick, level=lvn, entry_rule=rule, exit_rule=how, L=L,
                                       t_in=int(b.ct[i]), entry=E, t_out=ex[0], exit=ex[1], why=ex[2]))
    return out


def run_picks():
    f = os.path.join(OUT, "trades.parquet")
    if os.path.exists(f): return pd.read_parquet(f)
    P = chain.picks(("ATM", "p100")); P = P[P.pick.isin(["ATM", "p100"])]
    rows, cov = [], dict(days=0, with_prev=0, vwap=0)
    for e, g in P.groupby("expiry"):
        X = data.read_expiry(e, columns=("datetime", "strike", "right", "open", "high", "low", "close", "volume"),
                             strikes=set(g.strike))
        if X is None: continue
        G = {k: v for k, v in X.groupby(["strike", "right"])}
        for p in g.itertuples():
            cov["days"] += 1
            c = G.get((p.strike, p.right))
            if c is None: continue
            lv = prev_levels(c, p.date)
            x = c[c.date == p.date]
            if lv is None or len(x) < 200: continue
            cov["with_prev"] += 1; cov["vwap"] += lv[0] == lv[0]
            rows += trades_for(p.date, p.right, p.pick, x, lv)
        print(e, len(rows), flush=True)
    T = pd.DataFrame(rows)
    T["net"] = [net(a, b, d, LOT, 0.10) for a, b, d in zip(T.entry, T.exit, [1] * len(T))]
    T.to_parquet(f); json.dump({k: int(v) for k, v in cov.items()}, open(os.path.join(OUT, "coverage.json"), "w"))
    return T


def summ(x):
    n = len(x)
    if not n: return dict(n=0)
    y = pd.to_datetime(x.date).dt.year; v = x.net
    g, l = v[v > 0].sum(), -v[v < 0].sum()
    h1, h2 = v[y <= 2022], v[y >= 2023]
    pf = lambda s: round(s[s > 0].sum() / max(-s[s < 0].sum(), 1), 2)
    yr = v.groupby(y).sum()
    return dict(n=n, win=round((v > 0).mean() * 100, 1), pts=round((x.exit - x.entry).mean(), 2), net=round(v.sum()),
                PF=round(g / max(l, 1), 2), PF_18_22=pf(h1), PF_23_26=pf(h2), net_18_22=round(h1.sum()), net_23_26=round(h2.sum()),
                t=round(v.mean() / (v.std() / np.sqrt(n)), 2) if n > 2 else np.nan, yrs_pos=f"{(yr > 0).sum()}/{len(yr)}",
                slip1=round(v.sum() - n * LOT * 2 * 0.9))


def gate_books():
    """split each BUY book's trades by entry price vs the entry contract's previous-session average."""
    RES = os.path.join(os.path.dirname(OUT), "")
    books = {"ST152 G2": "golden/G2.csv", "ST154 G4": "golden/G4.csv", "ST157 G7": "golden/G7.csv",
             "ST158 BUY": "books/S6.6_p100_SELL_+_BUY.csv", "ST159 BUY": "books/S12.2_p100_positional_SELL_+_BUY.csv"}
    T = []
    for name, fn in books.items():
        t = pd.read_csv(os.path.join(RES, fn), parse_dates=["entry_time", "exit_time"])
        if "side" in t: t = t[t.side == 1]
        T.append(t.assign(book=name))
    T = pd.concat(T, ignore_index=True); T["date"] = T.entry_time.dt.normalize()
    lv = {}
    for e, g in T.groupby("expiry"):
        X = data.read_expiry(str(e)[:10], columns=("datetime", "strike", "right", "open", "high", "low", "close", "volume"), strikes=set(g.strike))
        if X is None: continue
        G = {k: v for k, v in X.groupby(["strike", "right"])}
        for (k, r, D) in set(zip(g.strike, g.right, g.date)):
            c = G.get((int(k), r))
            if c is not None and (v := prev_levels(c, D)): lv[(str(e)[:10], int(k), r, D)] = v
    key = list(zip(T.expiry.astype(str).str[:10], T.strike.astype(int), T.right, T.date))
    T["vwap"] = [lv.get(k, (np.nan,) * 3)[0] for k in key]; T["mean"] = [lv.get(k, (np.nan,) * 3)[1] for k in key]
    return T


if __name__ == "__main__":
    T = run_picks()
    cov = json.load(open(os.path.join(OUT, "coverage.json")))
    print("coverage", cov)
    rows = []
    for (pick, r, lvn, er, xr), g in T.groupby(["pick", "right", "level", "entry_rule", "exit_rule"]):
        rows.append(dict(pick=pick, right=r, level=lvn, entry=er, exit=xr, **summ(g)))
    for (pick, lvn, er, xr), g in T.groupby(["pick", "level", "entry_rule", "exit_rule"]):
        rows.append(dict(pick=pick, right="CE+PE", level=lvn, entry=er, exit=xr, **summ(g)))
    S = pd.DataFrame(rows); S.to_csv(os.path.join(OUT, "summary.csv"), index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 300); pd.set_option("display.max_columns", 30)
    print(S.to_string(index=False))
    B = gate_books(); B.to_parquet(os.path.join(OUT, "books_gate.parquet"))
    rows = []
    for name, g in B.groupby("book"):
        rows.append(dict(book=name, split="all", **summ(g)))
        for lvn in ("vwap", "mean"):
            h = g[g[lvn] == g[lvn]]
            rows.append(dict(book=name, split=f"{lvn}: no level", **summ(g[g[lvn] != g[lvn]])))
            rows.append(dict(book=name, split=f"{lvn}: entry > prev avg", **summ(h[h.entry > h[lvn]])))
            rows.append(dict(book=name, split=f"{lvn}: entry <= prev avg", **summ(h[h.entry <= h[lvn]])))
    G = pd.DataFrame(rows); G.to_csv(os.path.join(OUT, "books_gate.csv"), index=False)
    print(G.to_string(index=False))
