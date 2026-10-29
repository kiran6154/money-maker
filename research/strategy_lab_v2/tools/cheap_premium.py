"""S166 - buy cheap out-of-the-money options: small fixed loss, occasional multi-bagger. Which premium band / horizon /
target pays?

Chain: every strike's 09:19 close (regular + .wide + .wide3k files - the widest strike range in the store), OTM only
(CE strike > 09:15 five-minute spot, PE strike < spot). Pick per (day, right, band) = the strike whose 09:19 premium is
nearest the band's middle, inside the band; no strike in the band -> no trade that day (coverage reported).
    bands (Rs): 2-5, 5-10, 10-20, 20-40, 40-70
Horizon:
    0dte  = the expiry's own day (bought 09:20 on expiry day)
    next  = the nearest expiry strictly after the day (as nifty_bt's picks), exited the same day ("next/intraday") or
            held to the expiry day's 15:15 ("next/to_expiry")
Entry at the 09:19 close (known at 09:20). Exit: target = k x entry (k in 2, 3, 5, 10; filled at the target, or the
minute's open if it opened above), else 15:15 (of the day, or of the expiry day for to_expiry); "none" = no target.
No stop: the loss is the premium paid at most. 1 lot of 75, nifty_bt charges, Rs0.10 a side (Rs0.05 / Rs0.25 shown).

    python tools/cheap_premium.py      (from research/strategy_lab_v2; reads every expiry once)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain
from nifty_bt.costs import net, LOT

data.FILES = ("", ".wide", ".wide3k"); data._zip_members.cache_clear(); data.expiries.cache_clear()
OUT = os.path.join(chain.CACHE, "cheap_premium")
os.makedirs(OUT, exist_ok=True)
BANDS = [(2, 5), (5, 10), (10, 20), (20, 40), (40, 70)]
KS = (2, 3, 5, 10, None)
EOD = 15 * 60 + 15
COLS = ("datetime", "strike", "right", "open", "high", "low", "close")


def walk(m, E, k, end_tod):
    """m = 1-min rows from 09:20 to the exit day (sorted); target k x E; returns (exit price, why, exit datetime, max multiple)."""
    if not len(m): return None
    hi = m.high.values; op = m.open.values; last = (m.date.values == m.date.values[-1]) & (m.tod.values >= end_tod)
    mx = float(np.nanmax(hi[:np.argmax(last)] if last.any() else hi)) / E
    if k is not None:
        hit = np.flatnonzero(hi >= k * E)
        if len(hit) and (not last.any() or hit[0] < np.argmax(last)):
            j = hit[0]; return float(max(op[j], k * E)), f"{k}x", m.datetime.values[j], mx
    if last.any():
        j = np.argmax(last); return float(op[j]), "eod", m.datetime.values[j], mx
    return float(m.close.values[-1]), "eod", m.datetime.values[-1], mx


def run():
    f = os.path.join(OUT, "trades.parquet")
    if os.path.exists(f): return pd.read_parquet(f)
    plan = chain.plan(); spot = data.spot_0915()
    by_e = {}
    for D, e in plan.items(): by_e.setdefault(e, []).append(("next", D))
    for e in data.expiries():
        D = pd.Timestamp(e)
        if D in spot.index: by_e.setdefault(e, []).append(("0dte", D))
    rows, cov = [], []
    for e in sorted(by_e):
        X = data.read_expiry(e, columns=COLS)
        if X is None: continue
        X = X[X.date >= min(D for _, D in by_e[e])]
        S = X[X.tod == 559]
        G = {k: g for k, g in X.groupby(["strike", "right"])}
        ed = pd.Timestamp(e)
        for hz, D in by_e[e]:
            sp = spot.get(D)
            s = S[S.date == D]
            for r in ("CE", "PE"):
                c = s[(s.right == r) & ((s.strike > sp) if r == "CE" else (s.strike < sp)) & (s.close > 0)]
                for lo, hi in BANDS:
                    b = c[(c.close >= lo) & (c.close < hi)]
                    cov.append(dict(date=D, horizon=hz, right=r, band=f"{lo}-{hi}", ok=len(b) > 0))
                    if not len(b): continue
                    p = b.iloc[(b.close - (lo + hi) / 2).abs().argmin()]
                    E = float(p.close); g = G[(int(p.strike), r)]
                    for mode in (("intraday", "to_expiry") if hz == "next" else ("intraday",)):
                        end_day = D if mode == "intraday" else ed
                        m = g[(g.datetime > D + pd.Timedelta(minutes=559)) & (g.date <= end_day)]
                        m = m[(m.date < end_day) | (m.tod <= EOD)]
                        for k in KS:
                            w = walk(m, E, k, EOD)
                            if w is None: continue
                            rows.append(dict(date=D, expiry=e, horizon=f"{hz}/{mode}", right=r, band=f"{lo}-{hi}", strike=int(p.strike),
                                             dist=int(p.strike - sp) if r == "CE" else int(sp - p.strike), entry=E, target="none" if k is None else f"{k}x",
                                             exit=w[0], why=w[1], exit_time=pd.Timestamp(w[2]), max_mult=w[3]))
        print(e, len(rows), flush=True)
    T = pd.DataFrame(rows)
    T["net"] = [net(a, b, 1, LOT, 0.10) for a, b in zip(T.entry, T.exit)]
    T.to_parquet(f); pd.DataFrame(cov).to_parquet(os.path.join(OUT, "coverage.parquet"))
    return T


def summ(x):
    n = len(x); v = x.net; y = pd.to_datetime(x.date).dt.year
    pf = lambda s: round(s[s > 0].sum() / max(-s[s < 0].sum(), 1), 2)
    h1, h2 = v[y <= 2022], v[y >= 2023]; yr = v.groupby(y).sum()
    return dict(n=n, avg_prem=round(x.entry.mean(), 1), risk_per_trade=round(x.entry.mean() * LOT), win=round((v > 0).mean() * 100, 1),
                hit5x=round((x.max_mult >= 5).mean() * 100, 1), hit10x=round((x.max_mult >= 10).mean() * 100, 1),
                avg_win=round(v[v > 0].mean()) if (v > 0).any() else 0, avg_loss=round(v[v <= 0].mean()), best=round(v.max()),
                net=round(v.sum()), PF=pf(v), PF_18_22=pf(h1), PF_23_26=pf(h2), t=round(v.mean() / (v.std() / np.sqrt(n)), 2),
                yrs_pos=f"{(yr > 0).sum()}/{len(yr)}", slip05=round(v.sum() + n * LOT * 2 * 0.05), slip25=round(v.sum() - n * LOT * 2 * 0.15))


if __name__ == "__main__":
    pd.set_option("display.width", 260); pd.set_option("display.max_rows", 500); pd.set_option("display.max_columns", 30)
    T = run()
    C = pd.read_parquet(os.path.join(OUT, "coverage.parquet"))
    print(C.groupby(["horizon", "band", C.date.dt.year]).ok.mean().unstack().round(2).to_string())
    rows = [dict(zip(["horizon", "band", "target", "right"], k), **summ(g)) for k, g in T.groupby(["horizon", "band", "target", "right"])]
    rows += [dict(zip(["horizon", "band", "target"], k), right="CE+PE", **summ(g)) for k, g in T.groupby(["horizon", "band", "target"])]
    S = pd.DataFrame(rows).sort_values(["horizon", "band", "target", "right"]); S.to_csv(os.path.join(OUT, "summary.csv"), index=False)
    print(S.to_string(index=False))
