"""How much traded inside a price band on a day, and how often price came back into it (the user, 2026-10-30: "say price is
moving from 23000-23200 and multiple times price has placed between 23080-23120, let me know how many trades happened").

Source: NIFTY near-month futures (the index has no volume). Where the store has 1-second futures bars
(D:/nifty_data/seconds/futures, read-only) those are used - each second's volume is counted at its close price, so the
band total is close to exact; otherwise 1-minute bars, each minute's volume spread evenly over its high-low range (the
usual volume-profile approximation). The store has volume (contracts x lot units), not the count of individual trades -
`lots` = volume / lot size.

Per day: visits = times price entered the band from outside (a close inside after a close outside); time inside; volume
inside the band and its share of the day; the volume profile in `step`-point buckets.

    python tools/volume_at_price.py 2026-10-06 22700 22740                 one day, band 22700 - 22740
    python tools/volume_at_price.py --find 23000 23200 23080 23120 [N]     the last N days the futures spent inside 23000 - 23200
                                                                          (>= 70 % of the session) and crossed 23080 - 23120
"""
import os, sys, glob, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
import store_reader as S

SEC = "D:/nifty_data/seconds/futures"
LOT = 65


def seconds(day):
    fs = sorted(glob.glob(os.path.join(SEC, "*", f"{day}.parquet")))
    return pd.read_parquet(fs[-1]) if fs else None


def minutes(frm, to):
    """near-month futures 1-min bars; read a month at a time (store_reader returns one contract span per call)."""
    out = []
    for s in pd.date_range(pd.Timestamp(frm).replace(day=1), to, freq="MS"):
        e = min(s + pd.offsets.MonthEnd(0), pd.Timestamp(to)); s = max(s, pd.Timestamp(frm))
        c, _ = S.futures_candles(str(s.date()), str(e.date()))
        if len(c): out.append(pd.DataFrame(c, columns=["datetime", "open", "high", "low", "close", "volume", "open_interest"]))
    c = pd.concat(out, ignore_index=True).drop_duplicates("datetime")
    c["datetime"] = pd.to_datetime(c["datetime"], unit="s")
    return c.sort_values("datetime").reset_index(drop=True)


def band_stats(d, lo, hi, exact, step=10.0):
    """d = one session's bars (datetime, high, low, close, volume)."""
    inside = (d.close >= lo) & (d.close <= hi)
    visits = int((inside & ~inside.shift(1, fill_value=False)).sum())
    secs = d.datetime.diff().dt.total_seconds().fillna(0).clip(upper=60).shift(-1).fillna(1 if exact else 60)
    edges = np.arange(np.floor(d.low.min() / step) * step, d.high.max() + step, step)
    prof = np.zeros(len(edges) - 1)
    if exact:
        vin = float(d.volume[inside].sum())
        np.add.at(prof, np.clip(np.searchsorted(edges, d.close.values, side="right") - 1, 0, len(prof) - 1), d.volume.values)
    else:                                                  # spread each minute's volume over its high-low range
        vin = 0.0
        for h, l, v in zip(d.high.values, d.low.values, d.volume.values):
            rng = max(h - l, 0.05)
            vin += v * max(0.0, min(h, hi) - max(l, lo)) / rng if h > l else (v if lo <= l <= hi else 0.0)
            ov = np.clip(np.minimum(edges[1:], h) - np.maximum(edges[:-1], l), 0, None)
            prof += v * ov / ov.sum() if ov.sum() > 0 else 0
    tot = float(d.volume.sum())
    return dict(visits=visits, minutes_inside=round(float(secs[inside].sum()) / 60, 1), volume_inside=round(vin), lots_inside=round(vin / LOT),
                day_volume=round(tot), share_pct=round(vin / tot * 100, 1) if tot else np.nan, low=float(d.low.min()), high=float(d.high.max()),
                source="1-second" if exact else "1-minute (volume spread over each bar's range)"), pd.Series(prof, index=edges[:-1])


def one_day(day, lo, hi):
    d = seconds(day); exact = d is not None
    if not exact:
        d = minutes(day, day)
    d = d[(d.datetime.dt.hour * 60 + d.datetime.dt.minute).between(555, 929)].reset_index(drop=True)
    return band_stats(d, lo, hi, exact)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("args", nargs="+"); ap.add_argument("--find", action="store_true")
    a = ap.parse_args()
    if a.find:
        olo, ohi, lo, hi = map(float, a.args[:4]); n = int(a.args[4]) if len(a.args) > 4 else 5
        m = minutes("2018-01-01", "2026-12-31"); m = m[(m.datetime.dt.hour * 60 + m.datetime.dt.minute).between(555, 929)]
        m["date"] = m.datetime.dt.normalize()
        ok = m.groupby("date").close.apply(lambda s: s.between(olo, ohi).mean() >= 0.7 and s.between(lo, hi).any())
        days = [str(x.date()) for x in ok[ok].index][-n:]
        print(f"last {len(days)} days with >= 70 % of closes in {olo:.0f} - {ohi:.0f} and touching {lo:.0f} - {hi:.0f}:")
    else:
        days, lo, hi = [a.args[0]], float(a.args[1]), float(a.args[2])
    for day in days:
        st, prof = one_day(day, lo, hi)
        print(f"\n{day}  band {lo:.0f} - {hi:.0f}  ({st.pop('source')})")
        for k, v in st.items(): print(f"   {k:<15} {v:,}" if isinstance(v, (int, float)) else f"   {k:<15} {v}")
        top = prof.sort_values(ascending=False).head(5)
        print("   busiest 10-pt levels: " + ", ".join(f"{k:.0f}: {v / LOT:,.0f} lots" for k, v in top.items()))
