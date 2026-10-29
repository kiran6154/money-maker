"""S170 - rate NIFTY's intraday price movement as directional / sideways, as it is known at each hour, and check whether
the rating says anything about the rest of the day (the user, 2026-10-30: "can we rate the strength of price movement as
directional sideways so on").

Inputs known at checkpoint t (NIFTY index 1-min, 5-min bars from 09:15, bars that closed by t):
    move  = close(t) - the 09:15 bar's open
    ER    = |move| / sum |5-min close changes| since the open    (Kaufman efficiency: 1 = straight line, ~0 = back and forth)
    S     = |move| / ADR20                                           (ADR20 = mean high-low range of the 20 previous sessions)
Rating (thresholds fixed before the run):
    strong trend  ER >= 0.5 and S >= 0.5
    mild trend    ER >= 0.3 and S >= 0.25 (and not strong)
    sideways      otherwise
  with the side (up / down) from the sign of move. Checkpoints 10:15, 11:15, 12:15, 13:15, 14:15.
Pre-open rating (known at 09:15): yesterday's full-day rating + the gap (09:15 open - yesterday's close) in ADR20 units.

Checks:
  1. distribution of ratings per checkpoint
  2. what follows each rating to 15:15: rest-of-day move in ADR (signed with the rating's side), share that continue,
     rest-of-day range in ADR, and the full-day rating it ends as
  3. the ladder (S169, hourly re-centring, intraday, no stop) day P&L grouped by the pre-open rating and by the 10:15
     rating; and by the end-of-day rating (descriptive: the end-of-day rating is not known in advance)

    python tools/regime_rating.py      (from research/strategy_lab_v2; needs results/nifty_bt/ladder_stop_60m/days.parquet)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain

OUT = os.path.join(chain.CACHE, "regime_rating")
os.makedirs(OUT, exist_ok=True)
CHECKS = {"10:15": 615, "11:15": 675, "12:15": 735, "13:15": 795, "14:15": 855}
EOD = 915


def rate(er, s, move):
    if er >= 0.5 and s >= 0.5: k = "strong"
    elif er >= 0.3 and s >= 0.25: k = "mild"
    else: return "sideways"
    return f"{k} {'up' if move > 0 else 'down'}"


def build():
    d = data.index_1m_all()
    d = d[d.tod < EOD]
    days = sorted(d.date.unique())
    hl = d.groupby("date").agg(h=("high", "max"), l=("low", "min"), o=("open", "first"), c=("close", "last"))
    adr = (hl.h - hl.l).rolling(20).mean().shift(1)
    rows = []
    for D, g in d.groupby("date"):
        A = adr.get(D)
        if not (A == A) or len(g) < 300: continue
        k = (g.tod.values - 555) // 5
        b = g.groupby(k).agg(o=("open", "first"), c=("close", "last"), h=("high", "max"), l=("low", "min"))
        b["ct"] = b.index * 5 + 560
        O = b.o.iloc[0]
        def at(t):
            x = b[b.ct <= t]
            if not len(x): return None
            mv = x.c.iloc[-1] - O; path = np.abs(np.diff(np.r_[O, x.c.values])).sum()
            return mv, (abs(mv) / path if path > 0 else 0.0), abs(mv) / A, x.c.iloc[-1], x.h.max(), x.l.min()
        fin = at(EOD)
        r = dict(date=D, adr=A, day_move=fin[0] / A, day_er=fin[1], day_rating=rate(fin[1], fin[2], fin[0]), day_range=(fin[4] - fin[5]) / A)
        for name, t in CHECKS.items():
            z = at(t)
            if z is None: continue
            rest = b[b.ct > t]
            r[f"r_{name}"] = rate(z[1], z[2], z[0]); r[f"er_{name}"] = z[1]; r[f"s_{name}"] = z[2]; r[f"mv_{name}"] = z[0] / A
            r[f"rest_{name}"] = (fin[3] - z[3]) / A
            r[f"restrng_{name}"] = ((rest.h.max() - rest.l.min()) / A) if len(rest) else 0.0
        rows.append(r)
    R = pd.DataFrame(rows).set_index("date")
    R["prev_rating"] = R.day_rating.shift(1)
    R["gap"] = ((hl.o - hl.c.shift(1)) / adr).reindex(R.index)
    R["preopen"] = R.prev_rating.str.split().str[0].fillna("na") + np.where(R.gap.abs() >= 0.25, " + gap", "")
    return R


if __name__ == "__main__":
    pd.set_option("display.width", 220); pd.set_option("display.max_rows", 200)
    R = build(); R.to_parquet(os.path.join(OUT, "ratings.parquet"))
    print("days", len(R), R.index.min().date(), R.index.max().date())
    print("\n1. share of days per rating at each checkpoint (%)")
    print(pd.DataFrame({n: R[f"r_{n}"].value_counts(normalize=True) * 100 for n in CHECKS} | {"day end": R.day_rating.value_counts(normalize=True) * 100}).round(1))
    print("\n2. what follows each rating, to 15:15 (moves in ADR20 units; 'with' = in the rating's direction)")
    out = []
    for n in CHECKS:
        for k, g in R.groupby(f"r_{n}"):
            sgn = 1 if k.endswith("up") else (-1 if k.endswith("down") else np.sign(g[f"mv_{n}"]))
            w = g[f"rest_{n}"] * sgn
            out.append(dict(check=n, rating=k, days=len(g), rest_with=round(w.mean(), 3), continue_pct=round((w > 0).mean() * 100, 1),
                            rest_abs=round(g[f"rest_{n}"].abs().mean(), 3), rest_range=round(g[f"restrng_{n}"].mean(), 3),
                            ends_sideways=round((g.day_rating == "sideways").mean() * 100, 1), ends_strong=round(g.day_rating.str.startswith("strong").mean() * 100, 1)))
    T = pd.DataFrame(out); T.to_csv(os.path.join(OUT, "follow.csv"), index=False); print(T.to_string(index=False))
    print("\n   pre-open rating -> the day")
    print(R.groupby("preopen").agg(days=("adr", "size"), day_abs_move=("day_move", lambda s: round(s.abs().mean(), 3)), day_range=("day_range", "mean"),
                                    ends_sideways=("day_rating", lambda s: round((s == "sideways").mean() * 100, 1)),
                                    ends_strong=("day_rating", lambda s: round(s.str.startswith("strong").mean() * 100, 1))).round(3).to_string())
    f = os.path.join(chain.CACHE, "ladder_stop_60m", "days.parquet")
    if os.path.exists(f):
        L = pd.read_parquet(f); L = L[(L["mode"] == "intraday") & (L["stop"] == "none")].sort_values("date")
        L["day"] = np.diff(np.r_[0.0, L.equity.values]); L = L.set_index("date").join(R, how="inner")
        print("\n3. ladder (hourly, intraday, no stop) day P&L by rating")
        for col, note in (("preopen", "known at 09:15"), ("r_10:15", "known at 10:15 - the day's P&L includes 09:15-10:15"), ("day_rating", "end of day - not known in advance")):
            g = L.groupby(col).day
            print(f"   by {col} ({note})"); print(pd.DataFrame(dict(days=g.size(), avg=g.mean().round(), total=g.sum().round(), win_pct=(g.apply(lambda s: (s > 0).mean() * 100)).round(1))).to_string())
