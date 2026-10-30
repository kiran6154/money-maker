"""S55 reserve confirmation (CONFIRM.md). Reuses frozen accel.py functions unchanged. python confirm.py"""
import hashlib
import json

import numpy as np
import pandas as pd

import accel as A

SHA = hashlib.sha256((A.HERE / "CONFIRM.md").read_bytes()).hexdigest()
PATH = A.CACHE / "fut_5_reserve.parquet"


def reserve_bars(tf=5):
    """Same arithmetic as accel.fut_bars, reserve dates only."""
    if PATH.exists():
        return pd.read_parquet(PATH)
    x = pd.read_csv(A.F1, parse_dates=["datetime"], usecols=["datetime", "open", "high", "low", "close", "volume"])
    x = x[(x.datetime >= "2021-10-01") & (x.datetime < "2024-01-01")].rename(columns={"datetime": "dt"})
    x["date"] = x.dt.dt.normalize()
    n = x.groupby("date").size()
    x = x[x.date.isin(n[n >= 0.9 * 375].index)]
    mins = (x.dt - x.date - pd.Timedelta("9h15min")).dt.total_seconds() // 60
    x["bar"] = x.date + pd.Timedelta("9h15min") + pd.to_timedelta((mins // tf) * tf, unit="m")
    g = x.groupby("bar")
    x = pd.DataFrame({"open": g.open.first(), "high": g.high.max(), "low": g.low.min(), "close": g.close.last(),
                      "volume": g.volume.sum()}).reset_index().rename(columns={"bar": "dt"})
    x["date"] = x.dt.dt.normalize()
    x = x.sort_values("dt").reset_index(drop=True)
    x["bis"] = x.groupby("date").cumcount().astype(np.int16)
    x["newsess"] = x.bis == 0
    x["tod"] = (x.dt.dt.hour * 60 + x.dt.dt.minute).astype(np.int16)
    for c in ("open", "high", "low", "close"):
        x["l" + c[0]] = np.log(x[c])
    cal = np.array(A.WD.expiry_calendar(), dtype="datetime64[ns]")
    d = x.date.values.astype("datetime64[ns]")
    nxt = cal[np.searchsorted(cal, d)]
    x["expiry"] = nxt
    x["dte"] = ((nxt - d) / np.timedelta64(1, "D")).astype(int)
    x["year"] = x.date.dt.year
    x["tf"] = tf
    x.to_parquet(PATH)
    return x


b_all = reserve_bars()
evs, per_year, grid = [], {}, []
for y in (2021, 2022, 2023):
    b, f, o, el, sig, pl, ev = A.run_period(b_all, 5, y, A.PRIMARY)
    ev["year"] = y
    evs.append(ev)
    per_year[y] = {c: A.cboot(ev.xM30[ev.code == c], ev.week[ev.code == c]) for c in ("P", "PV", "V", "C", "O")}
    for prm in A.GRID:
        g = A.run_period(b_all, 5, y, prm)[6]
        for c in ("P", "PV"):
            x = g[g.code == c]
            grid.append(dict(year=y, **prm, code=c, n=int(len(x)), sum=float(x.xM30.sum()), cnt=int(x.xM30.notna().sum())))
    print(y, {k: int((v != 0).sum()) for k, v in sig.items()}, flush=True)
ev = pd.concat(evs, ignore_index=True)
ev.to_parquet(A.OUT / "events_tf5_reserve.parquet")


def boot(v, w, lvl):
    r = A.cboot(v, w)
    vv, ww = np.asarray(v, float), np.asarray(w)
    ok = ~np.isnan(vv)
    u, inv = np.unique(ww[ok], return_inverse=True)
    s, c = np.bincount(inv, vv[ok]), np.bincount(inv)
    dr = A.RNG.integers(0, len(u), (5000, len(u)))
    m = s[dr].sum(1) / c[dr].sum(1)
    a = (1 - lvl) / 2 * 100
    r[f"lo{lvl}"], r[f"hi{lvl}"] = float(np.percentile(m, a)), float(np.percentile(m, 100 - a))
    return r


pv, p = ev[ev.code == "PV"], ev[ev.code == "P"]
up, dn = pv[pv.d > 0], pv[pv.d < 0]
res = dict(
    C1_PV=boot(pv.xM30, pv.week, 0.95), C2_P=boot(p.xM30, p.week, 0.95),
    C3_PV_up_CE=boot(up.xM30, up.week, 0.9833), C4_PV_down_PE=boot(dn.xM30, dn.week, 0.9833),
    P_up=A.cboot(p.xM30[p.d > 0], p.week[p.d > 0]), P_down=A.cboot(p.xM30[p.d < 0], p.week[p.d < 0]),
)
# C5: up minus down, Bonferroni 98.33 % via the same joint-week bootstrap
weeks = np.unique(pv.week.values)
iu, idn = np.searchsorted(weeks, up.week.values), np.searchsorted(weeks, dn.week.values)
su, cu = np.bincount(iu, up.xM30.fillna(0).values * up.xM30.notna(), len(weeks)), np.bincount(iu, up.xM30.notna().astype(float), len(weeks))
sd, cd = np.bincount(idn, dn.xM30.fillna(0).values * dn.xM30.notna(), len(weeks)), np.bincount(idn, dn.xM30.notna().astype(float), len(weeks))
dr = A.RNG.integers(0, len(weeks), (5000, len(weeks)))
with np.errstate(all="ignore"):
    dd = su[dr].sum(1) / cu[dr].sum(1) - sd[dr].sum(1) / cd[dr].sum(1)
res["C5_up_minus_down"] = dict(diff=float(up.xM30.mean() - dn.xM30.mean()), lo9833=float(np.nanpercentile(dd, 0.835)),
                               hi9833=float(np.nanpercentile(dd, 99.165)))
res["controls_pooled"] = {c: A.cboot(ev.xM30[ev.code == c], ev.week[ev.code == c]) for c in ("V", "C", "O", "PnoV")}
res["H2_PV_minus_PnoV"] = A.cboot_diff(pv.xM30, pv.week, ev.xM30[ev.code == "PnoV"], ev.week[ev.code == "PnoV"])
res["per_year"] = {str(k): v for k, v in per_year.items()}
G = pd.DataFrame(grid).groupby(["L", "a", "v", "code"])[["sum", "cnt"]].sum()
G["mean"] = G["sum"] / G["cnt"]
res["grid_PV_share_pos"] = float((G.xs("PV", level="code")["mean"] > 0).mean())
res["grid_P_share_pos"] = float((G.xs("P", level="code")["mean"] > 0).mean())
res["grid_PV_median"] = float(G.xs("PV", level="code")["mean"].median())
res["perm_PV"] = None
tr = {}
for y in (2021, 2022, 2023):
    e = ev[ev.year == y]
    tr[str(y)] = A.translate(e, 2024)  # S54 development table, fixed before
res["translation_with_2024_table"] = tr
res["confirm_sha256"] = SHA
A.jdump(dict(results=res), "confirm_reserve.json")
print(json.dumps({k: v for k, v in res.items() if k not in ("translation_with_2024_table",)}, indent=1, default=float)[:5000])
