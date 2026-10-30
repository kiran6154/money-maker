"""S175 - EDA: at a touch of a daily floor pivot, is the ATM PE priced above the CE, and does that say anything about what
NIFTY does next (the user, 2026-10-30: "check below if ATM PE price is more than CE near pivot, what is the behaviour, do
EDA; take care of price as pivot might not be in multiples of 50").

Put-call parity: at one strike K, PE - CE ~= K - F (F = the forward). So
    raw    ATM PE - CE at the nearest-50 strike ~= K_atm - F: mostly where price sits against that strike
    pivot  PE - CE interpolated to the pivot price itself (between the two strikes around it) ~= pivot - F: whether the
           forward is below the pivot - position, not sentiment
    resid  the option-implied forward (K_atm + CE - PE) minus the actual futures price at that minute: the part of the
           PE / CE comparison that parity does not explain (option demand vs futures)
Levels: floor pivots from the previous session's NIFTY index H / L / C: P = (H+L+C)/3, R1 = 2P - L, S1 = 2P - H,
R2 = P + (H - L), S2 = P - (H - L) - not multiples of 50.
Touch: the first 1-min index bar whose low-high range holds the level, after the index was >= 20 points away from it
(a fresh approach), 09:30 - 14:45; side = the side it came from. One touch per level per day.
Options: the nearest expiry on or after the day (expiry day included, flagged), 1-min closes at the touch minute; the
two strikes around the pivot and the ATM strike must all have printed within the last 5 minutes.
Outcome (index, from the touch close): move over 15 / 30 / 60 minutes, signed so + = back to the side it came from
(bounce), - = through the level (break); bounce = +move > 0.

    python tools/pivot_pcp.py      (from research/strategy_lab_v2)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import data, chain
import volume_at_price as V

data.FILES = ("", ".wide", ".wide3k"); data._zip_members.cache_clear(); data.expiries.cache_clear()
OUT = os.path.join(chain.CACHE, "pivot_pcp")
os.makedirs(OUT, exist_ok=True)
FIRST, LAST, AWAY, STALE = 570, 885, 20.0, 5
HORIZ = (15, 30, 60)


def touches():
    idx = data.index_1m_all()
    days = sorted(idx.date.unique())
    hlc = idx.groupby("date").agg(h=("high", "max"), l=("low", "min"), c=("close", "last"))
    out = []
    for i in range(1, len(days)):
        D = days[i]; p = hlc.loc[days[i - 1]]
        P = (p.h + p.l + p.c) / 3; R = p.h - p.l
        lv = dict(P=P, R1=2 * P - p.l, S1=2 * P - p.h, R2=P + R, S2=P - R)
        g = idx[idx.date == D].reset_index(drop=True)
        if len(g) < 300: continue
        tod, h, l, c = g.tod.values, g.high.values, g.low.values, g.close.values
        for name, L in lv.items():
            away_side = 0
            for k in range(len(g)):
                if l[k] - L >= AWAY: away_side = 1
                elif L - h[k] >= AWAY: away_side = -1
                if away_side and l[k] <= L <= h[k] and FIRST <= tod[k] <= LAST:
                    fut = {}
                    for hz in HORIZ:
                        j = np.searchsorted(tod, tod[k] + hz)
                        fut[hz] = (c[min(j, len(c) - 1)] - c[k]) * away_side if j < len(c) else np.nan
                    out.append(dict(date=D, level=name, L=L, tod=int(tod[k]), side="from above" if away_side > 0 else "from below",
                                    sgn=away_side, spot=c[k], **{f"m{hz}": fut[hz] for hz in HORIZ}))
                    break
    return pd.DataFrame(out)


def add_options(T):
    fut = V.minutes(str(T.date.min().date()), str(T.date.max().date()))
    fut = fut.set_index("datetime").close
    T["t"] = T.date + pd.to_timedelta(T.tod, unit="m")
    T["fut"] = fut.reindex(T.t).values
    T["expiry"] = [chain.trade_expiry(D, strictly_after=False) for D in T.date]
    rows = []
    for e, g in T.dropna(subset=["expiry"]).groupby("expiry"):
        ks = set()
        for L, s in zip(g.L, g.spot):
            k1 = int(np.floor(L / 50) * 50); ks |= {k1, k1 + 50, int(round(s / 50) * 50)}
        X = data.read_expiry(e, columns=("datetime", "strike", "right", "close"), strikes=ks)
        if X is None: continue
        X = X.set_index(["strike", "right", "datetime"]).close.sort_index()
        def px(k, r, t):
            try: s = X.loc[(k, r)]
            except KeyError: return np.nan
            s = s.loc[t - pd.Timedelta(minutes=STALE):t]
            return float(s.iloc[-1]) if len(s) else np.nan
        for r in g.itertuples():
            k1 = int(np.floor(r.L / 50) * 50); k2 = k1 + 50; ka = int(round(r.spot / 50) * 50); w = (r.L - k1) / 50
            ce1, pe1, ce2, pe2 = px(k1, "CE", r.t), px(k1, "PE", r.t), px(k2, "CE", r.t), px(k2, "PE", r.t)
            cea, pea = px(ka, "CE", r.t), px(ka, "PE", r.t)
            rows.append(dict(i=r.Index, ce_piv=(1 - w) * ce1 + w * ce2, pe_piv=(1 - w) * pe1 + w * pe2, ce_atm=cea, pe_atm=pea, k_atm=ka,
                             dte=(pd.Timestamp(e) - r.date).days))
        print(e, len(rows), flush=True)
    O = pd.DataFrame(rows).set_index("i")
    T = T.join(O, how="inner").dropna(subset=["ce_piv", "pe_piv", "ce_atm", "pe_atm", "fut"])
    T["raw"] = T.pe_atm - T.ce_atm                       # what the screen shows
    T["piv"] = T.pe_piv - T.ce_piv                       # at the pivot price itself
    T["f_imp"] = T.k_atm + T.ce_atm - T.pe_atm           # option-implied forward
    T["resid"] = T.f_imp - T.fut                         # options vs futures (+ = options price the forward higher)
    T["basis"] = T.fut - T.spot
    return T


def grp(T, col, name):
    rows = []
    for k, g in T.groupby(col, observed=True):
        r = dict(split=name, group=str(k), touches=len(g))
        for hz in HORIZ:
            m = g[f"m{hz}"].dropna(); r[f"bounce_{hz}m"] = round((m > 0).mean() * 100, 1); r[f"avg_{hz}m"] = round(m.mean(), 1)
        rows.append(r)
    return rows


if __name__ == "__main__":
    pd.set_option("display.width", 230); pd.set_option("display.max_rows", 200)
    f = os.path.join(OUT, "touches.parquet")
    if os.path.exists(f): T = pd.read_parquet(f)
    else:
        T = add_options(touches()); T.to_parquet(f)
    print("touches with prices", len(T), T.date.min().date(), T.date.max().date())
    print("\nparity check (correlations):")
    print("   raw ATM PE-CE  vs  K_atm - futures :", round(np.corrcoef(T.raw, T.k_atm - T.fut)[0, 1], 3))
    print("   PE-CE at pivot vs  pivot - futures :", round(np.corrcoef(T.piv, T.L - T.fut)[0, 1], 3))
    print("   raw PE>CE share by where spot sits vs the ATM strike:")
    T["spot_vs_k"] = pd.cut(T.spot - T.k_atm, [-30, -10, -3, 3, 10, 30])
    print((T.groupby("spot_vs_k", observed=True).raw.apply(lambda s: (s > 0).mean() * 100)).round(1).to_string())
    print("   resid (implied forward - futures), points: median %.2f, IQR %.2f .. %.2f" % (T.resid.median(), T.resid.quantile(.25), T.resid.quantile(.75)))
    T["raw_sign"] = np.where(T.raw > 0, "ATM PE > CE", "ATM CE >= PE")
    T["piv_sign"] = np.where(T.piv > 0, "PE > CE at pivot", "CE >= PE at pivot")
    T["resid_q"] = pd.qcut(T.resid, 3, labels=["options forward below futures", "middle", "options forward above futures"])
    T["exp"] = np.where(T.dte == 0, "expiry day", "other days")
    rows = grp(T, "level", "all touches by level") + grp(T, "side", "approach")
    for side, g in T.groupby("side"):
        rows += grp(g, "raw_sign", f"{side}: raw ATM") + grp(g, "piv_sign", f"{side}: at pivot") + grp(g, "resid_q", f"{side}: parity residual")
    rows += grp(T, ["exp", "piv_sign"], "expiry day x pivot sign")
    S = pd.DataFrame(rows); S.to_csv(os.path.join(OUT, "summary.csv"), index=False); print(); print(S.to_string(index=False))
    y = T.date.dt.year <= 2022
    print("\nhalves (30m bounce %, by pivot sign and approach):")
    print(T.groupby([np.where(y, "2018-22", "2023-26"), "side", "piv_sign"]).m30.apply(lambda s: round((s > 0).mean() * 100, 1)).unstack().to_string())
