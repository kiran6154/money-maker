"""S165 - buy the option when its own RSI(14) rises back above 30, and which exit (if any) wins 80 % of the time.

Contract: nifty_bt's 09:19 picks (ATM, p100; CE and PE; expiry the nearest strictly after the day).
RSI(14) (Wilder) on the contract's own tf-minute bars, 09:15-anchored, continuous over the two previous sessions and the
day (warm-up). Signal = a bar closing with RSI > 30 after a bar with RSI <= 30, closing 09:20 - 14:30 of the pick day.
Entry at the signal close; one position per contract at a time, the next signal taken after the exit; flat at 15:15.
Exits (fixed before the run), watched on 1-min bars, a stop filled at the worse of the minute's open and the stop, the
stop first when a minute touches both:
    tgt T% / stop S%  T in (5, 10, 20), S in (10, 20, 30, none)
    rsi50 / rsi70     the first tf-bar close with RSI >= 50 / 70 (at that close), else 15:15
    eod               15:15
tf in (1, 3, 5, 15). 1 lot of 75, nifty_bt charges, Rs0.10 a side (Rs1 shown).

    python tools/rsi_buy.py       (from research/strategy_lab_v2)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain, indicators as I
from nifty_bt.costs import net, LOT

OUT = os.path.join(chain.CACHE, "rsi_buy")
os.makedirs(OUT, exist_ok=True)
SESS = chain.sessions(); IDX = {d: i for i, d in enumerate(SESS)}
COLS = ("datetime", "strike", "right", "open", "high", "low", "close")
FIRST, LAST, EOD = 9 * 60 + 20, 14 * 60 + 30, 15 * 60 + 15
TFS = (1, 3, 5, 15)
EXITS = [f"tgt{t}/stop{s}" for t in (5, 10, 20) for s in (10, 20, 30, "none")] + ["rsi50", "rsi70", "eod"]


def day_trades(g, D, tf):
    i = IDX.get(D)
    if i is None or i < 2: return {}
    g = g[g.date >= SESS[i - 2]].reset_index(drop=True)
    x = g[g.date == D].reset_index(drop=True)
    if len(x) < 200: return {}
    B = I.agg(g, tf)
    if len(B) < 40: return {}
    r = I.rsi(B.close.values.astype(float), 14)
    ctod = (B.ct.dt.hour * 60 + B.ct.dt.minute).values; bday = (B.bk.dt.normalize() == D).values
    tod = x.tod.values; o, h, l, c = x.open.values, x.high.values, x.low.values, x.close.values
    rsi_at = {int(t): v for t, v, d in zip(ctod, r, bday) if d}          # bar close tod -> RSI, pick day only
    sig = [j for j in np.flatnonzero(bday) if j > 0 and r[j - 1] <= 30 < r[j] and FIRST <= ctod[j] <= LAST]
    out = {}
    for ex in EXITS:
        busy, rows = -1, []
        for j in sig:
            if ctod[j] <= busy: continue
            E = float(B.close.values[j]); k0 = np.searchsorted(tod, ctod[j])
            tg = st = None
            if ex.startswith("tgt"):
                a, b = ex[3:].split("/stop"); tg = E * (1 + int(a) / 100); st = None if b == "none" else E * (1 - int(b) / 100)
            res = None
            for k in range(k0, len(x)):
                if tod[k] >= EOD: res = (tod[k], float(o[k]), "eod"); break
                if st is not None and l[k] <= st: res = (tod[k] + 1, float(min(o[k], st)), "stop"); break
                if tg is not None and h[k] >= tg: res = (tod[k] + 1, float(max(o[k], tg)), "target"); break
                if ex in ("rsi50", "rsi70"):
                    v = rsi_at.get(int(tod[k]) + 1)
                    if v is not None and v >= (50 if ex == "rsi50" else 70): res = (tod[k] + 1, float(c[k]), ex); break
            if res is None: res = (tod[-1] + 1, float(c[-1]), "eod")
            rows.append(dict(date=D, t_in=int(ctod[j]), entry=E, t_out=int(res[0]), exit=res[1], why=res[2]))
            busy = res[0]
        out[ex] = rows
    return out


def run():
    f = os.path.join(OUT, "trades.parquet")
    if os.path.exists(f): return pd.read_parquet(f)
    P = chain.picks(("ATM", "p100")); P = P[P.pick.isin(["ATM", "p100"])]
    rows = []
    for e, g in P.groupby("expiry"):
        X = data.read_expiry(e, columns=COLS, strikes=set(g.strike))
        if X is None: continue
        G = {k: v for k, v in X.groupby(["strike", "right"])}
        for p in g.itertuples():
            c = G.get((p.strike, p.right))
            if c is None: continue
            for tf in TFS:
                for ex, ts in day_trades(c, p.date, tf).items():
                    rows += [dict(t, pick=p.pick, right=p.right, tf=tf, exit_rule=ex) for t in ts]
        print(e, len(rows), flush=True)
    T = pd.DataFrame(rows)
    T["net"] = [net(a, b, 1, LOT, 0.10) for a, b in zip(T.entry, T.exit)]
    T.to_parquet(f)
    return T


def summ(x):
    n = len(x); v = x.net; y = pd.to_datetime(x.date).dt.year
    pf = lambda s: round(s[s > 0].sum() / max(-s[s < 0].sum(), 1), 2)
    h1, h2 = v[y <= 2022], v[y >= 2023]; yr = v.groupby(y).sum()
    return dict(n=n, win_gross=round((x.exit > x.entry).mean() * 100, 1), win_net=round((v > 0).mean() * 100, 1),
                avg_win=round(v[v > 0].mean()), avg_loss=round(v[v <= 0].mean()), net=round(v.sum()), PF=pf(v),
                PF_18_22=pf(h1), PF_23_26=pf(h2), t=round(v.mean() / (v.std() / np.sqrt(n)), 2), yrs_pos=f"{(yr > 0).sum()}/{len(yr)}",
                slip1=round(v.sum() - n * LOT * 2 * 0.9))


if __name__ == "__main__":
    pd.set_option("display.width", 250); pd.set_option("display.max_rows", 400); pd.set_option("display.max_columns", 30)
    T = run()
    rows = [dict(zip(["pick", "tf", "exit"], k), **summ(g)) for k, g in T.groupby(["pick", "tf", "exit_rule"])]
    S = pd.DataFrame(rows); S.to_csv(os.path.join(OUT, "summary.csv"), index=False); print(S.to_string(index=False))
