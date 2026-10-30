"""S55 data audit - prices and volume only, no forward outcome is computed. python audit.py"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

F1 = "D:/nifty/niftyfut_nearmonth_minute_2021-10-01_to_2026-09-25.csv"
F5 = "D:/nifty/niftyfut_nearmonth_5minute_2021-10-01_to_2026-09-25.csv"
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)


def load(p):
    x = pd.read_csv(p, parse_dates=["datetime"])
    x = x[x.datetime >= "2024-01-01"].copy()
    x["date"] = x.datetime.dt.normalize()
    x["hm"] = x.datetime.dt.strftime("%H:%M")
    return x


a = {}
m1, m5 = load(F1), load(F5)
for name, x, per in (("1min", m1, 375), ("5min", m5, 75)):
    g = x.groupby("date")
    n = g.size()
    rng = (x.high / x.low - 1) * 1e4
    med = rng.groupby(x.hm).median()
    a[name] = dict(
        rows=int(len(x)), sessions=int(len(n)),
        short_sessions={str(k.date()): int(v) for k, v in n[n < per * 0.9].items()},
        first_last_time=[x.hm.min(), x.hm.max()],
        contracts=sorted(x.contract.unique().tolist()),
        front_month_values=x.front_month.value_counts().to_dict(),
        zero_volume_share=float((x.volume == 0).mean()),
        median_range_bp_by_time={k: round(float(v), 1) for k, v in med.items() if k in ("09:15", "09:20", "12:00", "15:20", "15:25", "15:29")},
        bars_range_gt_10x_time_median=int((rng > 10 * rng.groupby(x.hm).transform("median")).sum()),
        worst_bars=x.assign(rbp=rng).nlargest(8, "rbp")[["datetime", "open", "high", "low", "close", "volume", "rbp"]]
        .astype(str).values.tolist(),
    )
    # roll: contract changes between consecutive sessions, and the close-to-open gap on those days
    last = g.contract.last()
    first = g.contract.first()
    rolls = [str(d.date()) for d, c0, c1 in zip(first.index[1:], last.values[:-1], first.values[1:]) if c0 != c1]
    intraday_switch = [str(d.date()) for d, s in g.contract.nunique().items() if s > 1]
    a[name]["roll_days"] = rolls
    a[name]["sessions_with_two_contracts"] = intraday_switch
# 5-minute file vs 1-minute resampled
r = m1.set_index("datetime").groupby("date").resample("5min", origin="start_day", offset="9h15min").agg(
    {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index(level=0, drop=True)
mm = m5.set_index("datetime")[["open", "high", "low", "close", "volume"]].join(r, rsuffix="_r", how="inner")
a["5min_vs_resampled_1min"] = dict(matched=int(len(mm)), **{
    c: dict(exact=float(((mm[c] - mm[c + "_r"]).abs() < 0.06).mean()),
            p99_abs=float((mm[c] - mm[c + "_r"]).abs().quantile(.99))) for c in ("open", "high", "low", "close")},
    volume_ratio_median=float((mm.volume / mm.volume_r).median()))
# volume by time of day (5-minute), share of session volume
vt = m5.groupby("hm").volume.median()
a["5min_volume_median_by_time"] = {k: float(v) for k, v in vt.items() if k in ("09:15", "09:20", "10:00", "12:00", "14:00", "15:00", "15:25")}
(OUT / "audit.json").write_text(json.dumps(a, indent=1, default=str))
print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk not in ("contracts",)}) for k, v in a.items()}, indent=1, default=str)[:6000])
