"""S167 - intraday short ladder: sell 10 strikes per side (ATM and the next 9 OTM, CE and PE), re-centred on the ATM every
15 minutes (the user, 2026-10-29: "start from 9:15, sell 10 strikes start from atm to otm on both ce and pe side. Step in
15min, when atm shifts close itm and sell atm and shift other side as well in other side it will be farthest otm. Keep
continuing for intraday").

Rule as coded: the book always holds CE strikes ATM, ATM+50 .. ATM+450 and PE strikes ATM, ATM-50 .. ATM-450 (one lot each,
short). ATM = NIFTY 1-min close rounded to 50. At 09:15 (the first minute's close) the 20 legs are sold; every `step`
minutes after that the ATM is re-read and the book is moved to the new ladder: when NIFTY rises one strike, the old ATM CE
(now ITM) is bought back, a new farthest-OTM CE is sold, a new ATM PE is sold and the PE that is now 10 strikes away is
bought back (mirror on a fall; a jump of several strikes rolls several). Everything is bought back at 15:15. No stop.
Trades at the option's 1-min close of that minute (the last printed close if the strike did not print that minute; a
strike with no print yet that day is skipped until it prints). Lot 75, nifty_bt charges per leg, Rs0.10 a side
(Rs0.25 / 0.5 / 1 shown). Expiry: "front" = the nearest expiry on or after the day (expiry day included), "next" = the
nearest strictly after. step in (15, 5, 30) - 15 is the user's rule, the others are sensitivity.

    python tools/ladder_short.py      (from research/strategy_lab_v2)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain
from nifty_bt.costs import costs, LOT

data.FILES = ("", ".wide", ".wide3k"); data._zip_members.cache_clear(); data.expiries.cache_clear()
OUT = os.path.join(chain.CACHE, "ladder_short")
os.makedirs(OUT, exist_ok=True)
NLEG, STEP_K, OPEN, EOD = 10, 50, 555, 915
STEPS = (15, 5, 30)
COLS = ("datetime", "strike", "right", "close")


def ladder(A):
    return {("CE", A + i * STEP_K) for i in range(NLEG)} | {("PE", A - i * STEP_K) for i in range(NLEG)}


def sim_day(P, spot, step):
    """P = minute x (right, strike) close matrix (ffilled within the day), index tod 555..; spot = index close by tod."""
    checks = [OPEN] + list(range(OPEN + step, EOD, step))
    held, legs, skipped, rolls = {}, [], 0, 0
    tods = P.index.values
    mtm_min, realized = 0.0, 0.0
    for n, t in enumerate(checks):
        if t not in spot.index: continue
        A = int(round(spot[t] / STEP_K) * STEP_K)
        want = ladder(A)
        row = P.loc[:t].iloc[-1] if (tods <= t).any() else None
        if row is None: continue
        for k in [k for k in held if k not in want]:
            px = row.get(k, np.nan)
            if px != px: continue                                        # no price: keep it until it prints
            E, t0 = held.pop(k); legs.append((k, t0, E, t, float(px))); realized += (E - px) * LOT; rolls += 1
        for k in want - set(held):
            px = row.get(k, np.nan)
            if px != px or px <= 0: skipped += 1; continue
            held[k] = (float(px), t)
        # mark-to-market to the next check (worst minute)
        t_next = checks[n + 1] if n + 1 < len(checks) else EOD
        seg = P.loc[t:t_next - 1, [k for k in held if k in P.columns]]
        if len(seg) and len(held):
            ent = np.array([held[k][0] for k in seg.columns])
            m = realized + ((ent - seg.values) * LOT).sum(axis=1)
            mtm_min = min(mtm_min, float(np.nanmin(m)))
    last = P.loc[:EOD - 1].iloc[-1]
    for k, (E, t0) in list(held.items()):
        px = last.get(k, np.nan)
        if px == px: legs.append((k, t0, E, EOD, float(px)))
    return legs, skipped, rolls, mtm_min


def run():
    f = os.path.join(OUT, "days.parquet")
    if os.path.exists(f): return pd.read_parquet(f), pd.read_parquet(os.path.join(OUT, "legs.parquet"))
    idx = data.index_1m_all(); spot_by_day = {d: g.set_index("tod").close for d, g in idx.groupby("date")}
    sess = [d for d in chain.sessions() if d in spot_by_day]
    jobs = {}
    for D in sess:
        for name, sa in (("front", False), ("next", True)):
            e = chain.trade_expiry(D, strictly_after=sa)
            if e: jobs.setdefault(e, []).append((name, D))
    days, legrows = [], []
    for e in sorted(jobs):
        ds = sorted({D for _, D in jobs[e]})
        lo = min(spot_by_day[D].min() for D in ds) - 1000; hi = max(spot_by_day[D].max() for D in ds) + 1000
        X = data.read_expiry(e, columns=COLS, strikes=set(range(int(lo // 50 * 50), int(hi) + 50, 50)))
        if X is None: continue
        X = X[X.date.isin(ds)]
        for D, g in X.groupby("date"):
            P = g.pivot_table(index="tod", columns=["right", "strike"], values="close", aggfunc="last").sort_index().ffill()
            P.columns = list(P.columns)
            sp = spot_by_day[D]
            for name, DD in jobs[e]:
                if DD != D: continue
                for step in STEPS:
                    legs, sk, rolls, mm = sim_day(P, sp, step)
                    gross = sum((E - x) * LOT for _, _, E, _, x in legs)
                    cost = sum(costs(E, x, -1, LOT, 0.10) for _, _, E, _, x in legs)
                    prem0 = sum(E for (_, t0, E, _, _) in legs if t0 == OPEN)
                    days.append(dict(date=D, expiry=e, dte=(pd.Timestamp(e) - D).days, book=name, step=step, legs=len(legs), rolls=rolls,
                                     skipped=sk, prem_open=prem0, gross=gross, cost=cost, net=gross - cost, worst_mtm=mm,
                                     spot_move=float(sp.loc[:EOD - 1].iloc[-1] - sp.iloc[0])))
                    if step == 15:
                        legrows += [dict(date=D, book=name, right=k[0], strike=k[1], t_in=t0, entry=E, t_out=t1, exit=x) for k, t0, E, t1, x in legs]
        print(e, len(days), flush=True)
    Dd = pd.DataFrame(days); L = pd.DataFrame(legrows)
    Dd.to_parquet(f); L.to_parquet(os.path.join(OUT, "legs.parquet"))
    return Dd, L


def summ(x):
    v = x.net; n = len(x); y = pd.to_datetime(x.date).dt.year; eq = v.cumsum(); yr = v.groupby(y).sum()
    pf = lambda s: round(s[s > 0].sum() / max(-s[s < 0].sum(), 1), 2)
    xl = x.legs * LOT * 2
    return dict(days=n, legs_day=round(x.legs.mean(), 1), rolls_day=round(x.rolls.mean(), 1), prem_open=round(x.prem_open.mean()),
                win_days=round((v > 0).mean() * 100, 1), avg_day=round(v.mean()), worst_day=round(v.min()), worst_mtm=round(x.worst_mtm.min()),
                best_day=round(v.max()), net=round(v.sum()), maxDD=round((eq - eq.cummax()).min()), PF=pf(v), PF_18_22=pf(v[y <= 2022]),
                PF_23_26=pf(v[y >= 2023]), t=round(v.mean() / (v.std() / np.sqrt(n)), 2), yrs_pos=f"{(yr > 0).sum()}/{len(yr)}",
                cost_day=round(x.cost.mean()), net_s25=round(v.sum() - (xl * 0.15).sum()), net_s50=round(v.sum() - (xl * 0.40).sum()),
                net_s100=round(v.sum() - (xl * 0.90).sum()), by_year=" ".join(f"{k % 100}:{s / 1e5:+.2f}L" for k, s in yr.items()))


if __name__ == "__main__":
    pd.set_option("display.width", 260); pd.set_option("display.max_rows", 200); pd.set_option("display.max_columns", 30); pd.set_option("display.max_colwidth", 120)
    Dd, L = run()
    rows = [dict(zip(["book", "step"], k), **summ(g)) for k, g in Dd.groupby(["book", "step"])]
    rows += [dict(book=f"front, {'expiry day' if k else 'not expiry day'}", step=15, **summ(g)) for k, g in Dd[(Dd.book == "front") & (Dd.step == 15)].groupby(Dd.dte == 0)]
    S = pd.DataFrame(rows); S.to_csv(os.path.join(OUT, "summary.csv"), index=False); print(S.to_string(index=False))
    f15 = Dd[(Dd.book == "front") & (Dd.step == 15)].copy(); f15["absmove"] = f15.spot_move.abs()
    print(f15.groupby(pd.cut(f15.absmove, [0, 50, 100, 150, 200, 300, 500, 5000])).net.agg(["size", "mean", "sum"]).round())
    print(f15.nsmallest(10, "net")[["date", "dte", "spot_move", "net", "worst_mtm", "rolls"]].to_string(index=False))
