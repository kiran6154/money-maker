"""S168 - the S167 short ladder with a Rs50,000 loss stop, intraday and positional (the user, 2026-10-29: "when rolling stop
if loss is more than 50k, check both intraday and positional").

Ladder and roll rule exactly as tools/ladder_short.py (ATM + 9 OTM CE and PE short, one lot each, re-centred every 15 min
on the NIFTY 1-min close rounded to 50). Expiry = the nearest on or after the day ("front", expiry day included).
    intraday   = sold 09:15, everything bought back 15:15 every day
    positional = the ladder is carried overnight (re-centred from 09:15 the next day) and bought back at the expiry day's
                 15:15; the next session starts a new ladder on the new front expiry
Stop: the open position's P&L since it was opened (booked legs + open legs marked at their last 1-min close) <= -50,000
    -> everything bought back at that minute's close.
    stop_min  = checked every minute; stop_roll = checked only at the 15-minute roll times (09:15 + 15k); none = no stop.
After a stop: intraday - flat for the rest of the day; positional - flat until the next session's 09:15, which opens a new
ladder (same expiry, or the next one after an expiry day).
Lot 75, nifty_bt charges per leg, Rs0.10 a side (Rs0.25 / 0.50 shown). Daily P&L = change in equity (booked net + open legs
marked at the day's last close).

    python tools/ladder_stop.py      (from research/strategy_lab_v2; LADDER_STEP=60 for hourly re-centring)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain
from nifty_bt.costs import costs, LOT
from ladder_short import ladder, STEP_K, OPEN, EOD, COLS

data.FILES = ("", ".wide", ".wide3k"); data._zip_members.cache_clear(); data.expiries.cache_clear()
STEP, STOP = int(os.environ.get("LADDER_STEP", "15")), -50000.0      # minutes between re-centring (S168: 15, S169: 60)
OUT = os.path.join(chain.CACHE, "ladder_stop" + ("" if STEP == 15 else f"_{STEP}m"))
os.makedirs(OUT, exist_ok=True)
SPIKES = [0]


def clean(P):
    """blank 1-min closes more than 3x (or under a third of) the median of the surrounding 5 minutes, then carry forward."""
    med = P.rolling(5, center=True, min_periods=1).median()
    bad = (P > 3 * med + 2) | (P < med / 3 - 2)
    SPIKES[0] += int(bad.values.sum())
    return P.mask(bad).ffill()


VARIANTS = [(m, s) for m in ("intraday", "positional") for s in ("none", "stop_min", "stop_roll")]


def sim_expiry(days, mode, stopm):
    """days = [(D, P, spot)] of one front expiry in order. Returns daily rows and closed legs."""
    held, legs, out = {}, [], []
    booked = 0.0                                      # net of closed legs (after costs), all episodes
    ep_gross = 0.0                                    # gross of legs closed in the current episode
    last_px = {}                                      # last known close per leg (carried overnight for marks)
    for di, (D, P, spot) in enumerate(days):
        last_day = di == len(days) - 1; n_legs0 = len(legs)
        stopped, nstop, rolls, worst = False, 0, 0, 0.0
        checks = [OPEN] + list(range(OPEN + STEP, EOD, STEP))
        cols = set(P.columns)

        def px_at(k, t):
            if k in cols:
                s = P[k].loc[:t]
                if len(s) and s.iloc[-1] == s.iloc[-1]: return float(s.iloc[-1])
            return last_px.get(k, np.nan)

        def close_all(t):
            nonlocal booked, ep_gross
            for k, (E, t0, d0) in list(held.items()):
                x = px_at(k, t)
                if x != x: x = E
                legs.append((k, d0, t0, E, D, t, x)); booked += (E - x) * LOT - costs(E, x, -1, LOT, 0.10)
                del held[k]
            ep_gross = 0.0

        if mode == "intraday": ep_gross = 0.0
        for n, t in enumerate(checks):
            if stopped: break
            if t not in spot.index: continue
            A = int(round(spot[t] / STEP_K) * STEP_K); want = ladder(A)
            for k in [k for k in held if k not in want]:
                x = px_at(k, t)
                if x != x: continue
                E, t0, d0 = held.pop(k); legs.append((k, d0, t0, E, D, t, x)); rolls += 1
                booked += (E - x) * LOT - costs(E, x, -1, LOT, 0.10); ep_gross += (E - x) * LOT
            for k in want - set(held):
                x = P[k].loc[:t].iloc[-1] if k in cols and (P.index <= t).any() else np.nan
                if x == x and x > 0: held[k] = (float(x), t, D)
            # mark minute by minute to the next roll
            t_next = checks[n + 1] if n + 1 < len(checks) else EOD
            ks = list(held)
            seg = P.loc[t:t_next - 1].reindex(columns=ks)
            for j, k in enumerate(ks):                 # legs that have not printed today: carry yesterday's close
                if seg[k].isna().all() and k in last_px: seg[k] = last_px[k]
                else: seg[k] = seg[k].ffill().fillna(last_px.get(k, held[k][0]))
            if len(seg) and ks:
                ent = np.array([held[k][0] for k in ks])
                m = ep_gross + ((ent - seg.values) * LOT).sum(axis=1)
                hit, upto = None, len(m)
                if stopm == "stop_min":
                    w = np.flatnonzero(m <= STOP)
                    if len(w): hit = int(seg.index[w[0]]); upto = w[0] + 1
                elif stopm == "stop_roll" and m[0] <= STOP:
                    hit = t; upto = 1
                worst = min(worst, float(m[:upto].min()))
                if hit is not None:
                    close_all(hit); stopped = True; nstop = 1
            elif stopm != "none" and ep_gross <= STOP:
                close_all(t); stopped = True; nstop = 1
        if not stopped and (mode == "intraday" or last_day):
            close_all(EOD - 1)
        for k in held:
            v = px_at(k, EOD - 1)
            if v == v: last_px[k] = v
        open_mtm = sum((E - last_px.get(k, E)) * LOT for k, (E, _, _) in held.items())
        out.append(dict(date=D, mode=mode, stop=stopm, equity=booked + open_mtm, rolls=rolls, stopped=nstop, worst_mark=worst,
                        open_legs=len(held), expiry_day=last_day, closed=len(legs) - n_legs0))
        if stopped and mode == "positional": ep_gross = 0.0       # a new episode starts next session
        if mode == "positional" and not held: ep_gross = 0.0
    return out, legs


def run():
    f = os.path.join(OUT, "days.parquet")
    if os.path.exists(f): return pd.read_parquet(f)
    idx = data.index_1m_all(); spot_by_day = {d: g.set_index("tod").close for d, g in idx.groupby("date")}
    jobs = {}
    for D in chain.sessions():
        if D not in spot_by_day: continue
        e = chain.trade_expiry(D, strictly_after=False)
        if e: jobs.setdefault(e, []).append(D)
    rows, carry = [], {v: 0.0 for v in VARIANTS}
    for e in sorted(jobs):
        ds = sorted(jobs[e])
        lo = min(spot_by_day[D].min() for D in ds) - 1000; hi = max(spot_by_day[D].max() for D in ds) + 1000
        X = data.read_expiry(e, columns=COLS, strikes=set(range(int(lo // 50 * 50), int(hi) + 50, 50)))
        if X is None: continue
        days = []
        for D in ds:
            g = X[X.date == D]
            if not len(g): continue
            P = g.pivot_table(index="tod", columns=["right", "strike"], values="close", aggfunc="last").sort_index().ffill()
            P.columns = list(P.columns); days.append((D, clean(P), spot_by_day[D]))
        if not days: continue
        for v in VARIANTS:
            out, _ = sim_expiry(days, *v)
            for r in out: r["equity"] += carry[v]; r["expiry"] = e
            carry[v] = out[-1]["equity"]; rows += out
        print(e, len(rows), flush=True)
    Dd = pd.DataFrame(rows); Dd.to_parquet(f); print("spike prints blanked:", SPIKES[0])
    return Dd


def summ(x):
    x = x.sort_values("date"); eq = x.equity.values; v = pd.Series(np.diff(np.r_[0.0, eq]), index=x.index)
    y = pd.to_datetime(x.date).dt.year; yr = v.groupby(y).sum(); n = len(v)
    pf = lambda s: round(s[s > 0].sum() / max(-s[s < 0].sum(), 1), 2)
    wk = v.groupby(x.expiry).sum()
    return dict(days=n, stops=int(x.stopped.sum()), net=round(v.sum()), avg_day=round(v.mean()), win_days=round((v > 0).mean() * 100, 1),
                worst_day=round(v.min()), worst_mark=round(x.worst_mark.min()), worst_week=round(wk.min()), win_weeks=round((wk > 0).mean() * 100, 1),
                maxDD=round((pd.Series(eq) - pd.Series(eq).cummax()).min()), PF_days=pf(v), PF_18_22=pf(v[y <= 2022]), PF_23_26=pf(v[y >= 2023]),
                t=round(v.mean() / (v.std() / np.sqrt(n)), 2), net_s25=round(v.sum() - (x.closed * LOT * 2 * 0.15).sum()),
                net_s50=round(v.sum() - (x.closed * LOT * 2 * 0.40).sum()), yrs_pos=f"{(yr > 0).sum()}/{len(yr)}",
                by_year=" ".join(f"{k % 100}:{s / 1e5:+.2f}L" for k, s in yr.items()))


if __name__ == "__main__":
    pd.set_option("display.width", 260); pd.set_option("display.max_columns", 30); pd.set_option("display.max_colwidth", 120)
    Dd = run()
    rows = [dict(mode=m, stop=s, **summ(g)) for (m, s), g in Dd.groupby(["mode", "stop"], sort=False)]
    S = pd.DataFrame(rows); S.to_csv(os.path.join(OUT, "summary.csv"), index=False); print(S.to_string(index=False))
