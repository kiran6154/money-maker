"""S164 - the option's own session VWAP together with CHoCH / BOS on the option's chart.

Session VWAP = sum(hlc3 * volume) / sum(volume) of the contract's 1-min bars from 09:15 of that day (known at each minute's
close; no value until the day has volume).

Part A - the gate on the existing structure books (G1 - G4, G6, G7 = ST151 - 154, 156, 157; ST158 = S6.6 SELL + BUY,
ST159 = S12.2 positional SELL + BUY): each trade's entry compared with its contract's session VWAP at the signal close.
"with" = BUY above / SELL below the VWAP, "against" = the opposite. Nothing is re-simulated: the trades are the books' own.

Part B - standalone, on nifty_bt's 09:19 picks (ATM, p100; CE and PE; expiry the nearest strictly after the day):
  * 5-min bars of the contract, 09:15-anchored, continuous over the two previous sessions and the day (pivot warm-up);
    CHoCH / BOS from nifty_bt.indicators.pivot_structure(N) at the bar close
  * BUY the option on a bullish event, SELL (write) it on a bearish one; events: CHoCH only, or CHoCH + BOS
  * gate "svwap": BUY only if the signal close > session VWAP, SELL only if < ; gate "none": every event (the comparison)
  * signal bars closing 09:20 - 14:30 of the pick day; entry at the signal close; one position per contract at a time,
    the next signal taken after the exit
  * stop at the last confirmed swing (BUY: swing low, SELL: swing high), watched on 1-min bars, filled at the worse of the
    minute's open and the stop; skipped if there is no swing on the right side of the entry
  * exit "swing" = the stop, else 15:15; "swing+vwap" = also a 5-min close back across the session VWAP (at that close)
  * grid: N in (2, 3) x events x side x gate x exit, per pick, CE + PE together. 1 lot of 75, nifty_bt charges, Rs0.10 a side.

    python tools/svwap_choch.py       (from research/strategy_lab_v2)
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain, indicators as I
from nifty_bt.costs import net, LOT

OUT = os.path.join(chain.CACHE, "svwap_choch")
os.makedirs(OUT, exist_ok=True)
SESS = chain.sessions()
IDX = {d: i for i, d in enumerate(SESS)}
COLS = ("datetime", "strike", "right", "open", "high", "low", "close", "volume")
FIRST, LAST, EOD = 9 * 60 + 20, 14 * 60 + 30, 15 * 60 + 15


def with_vwap(g):
    """1-min frame of one contract -> adds the session VWAP known at each minute's close."""
    g = g.copy(); tp = (g.high + g.low + g.close) / 3.0; v = g.volume.astype(float)
    cv = v.groupby(g.date).cumsum(); cpv = (tp * v).groupby(g.date).cumsum()
    g["svwap"] = np.where(cv > 0, cpv / cv.where(cv > 0, 1), np.nan)
    return g


# ------------------------------------------------------------------ Part B
def prep(g, D, N):
    """the 5-min structure of one contract around session D. g = 1-min frame (with svwap) holding D and earlier sessions."""
    i = IDX.get(D)
    if i is None or i < 2: return None
    g = g[g.date >= SESS[i - 2]].reset_index(drop=True)
    B = I.agg(g, 5)
    if len(B) < 20: return None
    x = g[g.date == D].reset_index(drop=True)
    if len(x) < 200: return None
    return dict(B=B, S=I.pivot_structure(B, N), x=x, vw_at=dict(zip(g.datetime + pd.Timedelta(minutes=1), g.svwap)))


def day_trades(P, evmode, side, gate, exitm):
    """trades on the pick day for one setting."""
    B, S, x, vw_at = P["B"], P["S"], P["x"], P["vw_at"]; D = x.date.iloc[0]
    tod = x.tod.values; o, h, l, c, vw = x.open.values, x.high.values, x.low.values, x.close.values, x.svwap.values
    ct = B.ct.values; bday = (B.bk.dt.normalize() == D).values
    ctod = (B.ct.dt.hour * 60 + B.ct.dt.minute).values
    out, busy_until = [], -1
    for j in np.flatnonzero(bday):
        if ctod[j] < FIRST or ctod[j] > LAST or ctod[j] <= busy_until: continue
        ev = S["ev"][j]
        if ev == 0 or (evmode == "choch" and abs(ev) != 2): continue
        d = 1 if ev > 0 else -1
        if d != side: continue
        E = float(B.close.values[j]); V = vw_at.get(pd.Timestamp(ct[j]), np.nan)
        if gate == "svwap" and not (V == V and (E > V if d == 1 else E < V)): continue
        stop = S["last_sl"][j] if d == 1 else S["last_sh"][j]
        if not (stop == stop) or (d == 1 and stop >= E) or (d == -1 and stop <= E): continue
        k0 = np.searchsorted(tod, ctod[j])                                    # first minute after the signal close
        ex = None
        for k in range(k0, len(x)):
            if tod[k] >= EOD: ex = (tod[k], float(o[k]), "eod"); break
            if d == 1 and l[k] <= stop: ex = (tod[k] + 1, float(min(o[k], stop)), "stop"); break
            if d == -1 and h[k] >= stop: ex = (tod[k] + 1, float(max(o[k], stop)), "stop"); break
            if exitm == "swing+vwap" and (tod[k] - 555 + 1) % 5 == 0 and vw[k] == vw[k] and (c[k] < vw[k] if d == 1 else c[k] > vw[k]):
                ex = (tod[k] + 1, float(c[k]), "vwap"); break
        if ex is None:
            if not len(x): continue
            ex = (tod[-1] + 1, float(c[-1]), "eod")
        out.append(dict(date=D, t_in=int(ctod[j]), entry=E, stop=float(stop), t_out=int(ex[0]), exit=ex[1], why=ex[2], side=d,
                        kind="CHoCH" if abs(ev) == 2 else "BOS", vwap=V))
        busy_until = ex[0]
    return out


def run_b():
    f = os.path.join(OUT, "trades.parquet")
    if os.path.exists(f): return pd.read_parquet(f)
    P = chain.picks(("ATM", "p100")); P = P[P.pick.isin(["ATM", "p100"])]
    grid = [(N, em, sd, gt, xm) for N in (2, 3) for em in ("choch", "both") for sd in (1, -1) for gt in ("svwap", "none") for xm in ("swing", "swing+vwap")]
    rows = []
    for e, g in P.groupby("expiry"):
        X = data.read_expiry(e, columns=COLS, strikes=set(g.strike))
        if X is None: continue
        G = {k: with_vwap(v) for k, v in X.groupby(["strike", "right"])}
        for p in g.itertuples():
            c = G.get((p.strike, p.right))
            if c is None: continue
            for N in (2, 3):
                P_ = prep(c, p.date, N)
                if P_ is None: continue
                for N_, em, sd, gt, xm in grid:
                    if N_ != N: continue
                    for t in day_trades(P_, em, sd, gt, xm):
                        rows.append(dict(t, pick=p.pick, right=p.right, N=N, events=em, gate=gt, exit_rule=xm, expiry=e, strike=p.strike))
        print(e, len(rows), flush=True)
    T = pd.DataFrame(rows)
    T["net"] = [net(a, b, d, LOT, 0.10) for a, b, d in zip(T.entry, T.exit, T.side)]
    T.to_parquet(f)
    return T


# ------------------------------------------------------------------ Part A
BOOKS = {"ST151 G1": "golden/G1.csv", "ST152 G2": "golden/G2.csv", "ST153 G3": "golden/G3.csv", "ST154 G4": "golden/G4.csv",
         "ST156 G6": "golden/G6.csv", "ST157 G7": "golden/G7.csv", "ST158": "books/S6.6_p100_SELL_+_BUY.csv",
         "ST159": "books/S12.2_p100_positional_SELL_+_BUY.csv"}


def run_a():
    T = []
    for name, fn in BOOKS.items():
        t = pd.read_csv(os.path.join(os.path.dirname(OUT), fn), parse_dates=["sig", "entry_time", "exit_time"])
        T.append(t[["side", "right", "sig", "entry_time", "exit_time", "entry", "exit", "net", "expiry", "strike"]].assign(book=name))
    T = pd.concat(T, ignore_index=True); T["expiry"] = T.expiry.astype(str).str[:10]
    vw = {}
    for e, g in T.groupby("expiry"):
        X = data.read_expiry(e, columns=COLS, strikes=set(g.strike))
        if X is None: continue
        G = {k: with_vwap(v) for k, v in X.groupby(["strike", "right"])}
        for k, r, s in set(zip(g.strike, g.right, g.sig)):
            c = G.get((int(k), r))
            if c is None: continue
            y = c[(c.date == s.normalize()) & (c.datetime < s)]
            if len(y): vw[(e, int(k), r, s)] = float(y.svwap.iloc[-1])
    T["svwap"] = [vw.get((e, int(k), r, s), np.nan) for e, k, r, s in zip(T.expiry, T.strike, T.right, T.sig)]
    return T


def summ(x, pts_sign=None):
    n = len(x)
    if not n: return dict(n=0)
    y = pd.to_datetime(x.date if "date" in x else x.entry_time).dt.year; v = x.net
    pf = lambda s: round(s[s > 0].sum() / max(-s[s < 0].sum(), 1), 2)
    yr = v.groupby(y).sum(); h1, h2 = v[y <= 2022], v[y >= 2023]
    return dict(n=n, win=round((v > 0).mean() * 100, 1), net=round(v.sum()), PF=pf(v), PF_18_22=pf(h1), PF_23_26=pf(h2),
                net_18_22=round(h1.sum()), net_23_26=round(h2.sum()), t=round(v.mean() / (v.std() / np.sqrt(n)), 2) if n > 2 else np.nan,
                yrs_pos=f"{(yr > 0).sum()}/{len(yr)}", slip1=round(v.sum() - n * LOT * 2 * 0.9))


if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400); pd.set_option("display.max_columns", 30)
    A = run_a(); A.to_parquet(os.path.join(OUT, "books.parquet"))
    rows = []
    for name, g in A.groupby("book", sort=False):
        ok = g.svwap == g.svwap
        w = ok & np.where(g.side == 1, g.entry > g.svwap, g.entry < g.svwap)
        for sd, gs in [("all", g.side != 0), ("BUY", g.side == 1), ("SELL", g.side == -1)]:
            if not gs.any(): continue
            rows.append(dict(book=name, side=sd, split="all", **summ(g[gs])))
            rows.append(dict(book=name, side=sd, split="with svwap", **summ(g[gs & w])))
            rows.append(dict(book=name, side=sd, split="against svwap", **summ(g[gs & ok & ~w])))
            rows.append(dict(book=name, side=sd, split="no svwap", **summ(g[gs & ~ok])))
    SA = pd.DataFrame(rows); SA.to_csv(os.path.join(OUT, "books_summary.csv"), index=False); print(SA.to_string(index=False))
    T = run_b()
    rows = []
    for k, g in T.groupby(["pick", "N", "events", "side", "gate", "exit_rule"]):
        rows.append(dict(zip(["pick", "N", "events", "side", "gate", "exit"], k), **summ(g)))
    SB = pd.DataFrame(rows); SB.to_csv(os.path.join(OUT, "summary.csv"), index=False); print(SB.to_string(index=False))
