"""Post-hoc (user question 2026-09-30, not pre-registered): S55 real-option results split CE (up signals) vs PE (down).
Reuses the frozen accel.py functions unchanged. python side_split.py"""
import json
import sys

import numpy as np
import pandas as pd

import accel as A

sys.path.insert(0, str(A.WAVES))
import stages as WS  # noqa: E402

sp5 = A.WD.spot5().set_index("dt").close
out = {}
for y, per in ((2024, "dev"), (2025, "val"), (2026, "blind")):
    ev = pd.read_parquet(A.OUT / f"events_tf5_{y}.parquet")
    ev = ev[ev.code.isin(["P", "PV"])].copy()
    last5 = (pd.to_datetime(ev.dt) + pd.Timedelta(minutes=5) - pd.Timedelta(minutes=5)).dt.floor("5min")
    ev["strike"] = np.round(sp5.reindex(last5.values).values / 100) * 100
    ev["right"] = np.where(ev.d > 0, 0, 1)
    rows = []
    for (e, k, r), g in ev.groupby([ev.week, ev.strike, ev.right]):
        ey = pd.Timestamp(e).year
        if np.isnan(k) or ey not in A.WD.SOURCES:
            continue
        s = A.option_series(ey, e, k, r)
        if len(s) == 0:
            continue
        base = 5 if A.WD.SOURCES[ey][1] == "5minute" else 1
        s["expiry"] = pd.Timestamp(e)
        bars = (A.WD.resample(s, 5, base) if base != 5 else s).set_index("dt").sort_index()
        ref = s.ref_time.iloc[0]
        for row in g.itertuples():
            t0 = pd.Timestamp(row.dt)
            t30 = t0 + pd.Timedelta(minutes=30)
            if t0 not in bars.index or t30 not in bars.index:
                continue
            hind = bool(ref is not None and pd.notna(ref) and t0 < pd.Timestamp(ref))
            if hind or bool(bars.loc[t0, "filler"]) or bars.loc[t0, "close"] <= 5:
                continue
            rows.append(dict(code=row.code, side="CE" if r == 0 else "PE", week=e, p0=bars.loc[t0, "close"],
                             p30=bars.loc[t30, "close"], dteb=row.dteb, y30=row.y30))
    R = pd.DataFrame(rows)
    res = {}
    for (code, side), g in R.groupby(["code", "side"]):
        q = np.array([WS.lot_size(x) for x in g.week.values])
        nl, rs = WS.net_log(g.p0.values, g.p30.values, q, 0.005)
        res[f"{code}|{side}"] = dict(net_pct=A.cboot((np.exp(nl) - 1) * 100, g.week.values), rs_per_lot=float(rs.mean()),
                                     win=float((rs > 0).mean()), nifty_y30=float(g.y30.mean()))
    out[per] = res
    print(per, {k: (v["net_pct"]["n"], round(v["net_pct"]["mean"], 1), v["net_pct"].get("lo") and round(v["net_pct"]["lo"], 1),
                    v["net_pct"].get("hi") and round(v["net_pct"]["hi"], 1), round(v["rs_per_lot"]), round(v["win"], 2),
                    round(v["nifty_y30"], 1)) for k, v in res.items()}, flush=True)
A.jdump(dict(note="post-hoc CE/PE split of the frozen S55 option test; not pre-registered", results=out), "side_split_tf5.json")
