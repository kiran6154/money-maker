"""Index filters (spec §4.4-4.7): daily Supertrend direction, ADR, the choppy-day filter, the day-type score."""
import functools
import numpy as np, pandas as pd
from . import data, indicators as I


@functools.lru_cache(None)
def daily_bars():
    b = data.index_1m()
    return b.groupby("date").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last")).reset_index()


def daily_st(p=10, m=3.0):
    """§4.4 direction for day D = the daily Supertrend at D-1's close."""
    D = daily_bars(); return pd.Series(I.st_dir(D, p, m), index=D.date).shift(1)


@functools.lru_cache(None)
def adr():
    """§4.5 mean(high - low) of the previous 20 sessions (at least 5), excluding today."""
    D = daily_bars(); return pd.Series(((D.high - D.low).rolling(20, min_periods=5).mean().shift(1)).values, index=D.date)


@functools.lru_cache(None)
def chop_features():
    """§4.6 day-so-far features at each 1-min index bar's close (bars <= that bar only), indexed by the bar's start time."""
    b = data.index_1m(); c = b.close.values; g = b.groupby("date")
    dopen = g.open.transform("first").values
    dhi = g.high.cummax().values; dlo = g.low.cummin().values
    path = g.close.transform(lambda s: s.diff().abs().fillna(0).cumsum()).values + np.abs(g.close.transform("first").values - dopen)
    ER = np.abs(c - dopen) / np.maximum(path, 1e-9)
    rng_so_far = (dhi - dlo) / b.date.map(adr()).values
    pos = (c - dlo) / np.maximum(dhi - dlo, 1e-9)
    return pd.DataFrame(dict(ER=ER, rng_so_far=rng_so_far, pos_in_rng=pos, dopen=dopen, close=c), index=b.datetime.values)


def chop_ok(sig, side, right, er_min=0.10, rng_min=0.8, pos_min=0.8):
    """§4.6 trade only if range-so-far / ADR >= 0.8, ER >= 0.10 and the index sits in the top (bottom) 20% of the day's range
    for a trade that bets on a rise (fall). Evaluated on the 1-min bar that closes at the signal time."""
    F = chop_features(); X = F.reindex(pd.to_datetime(sig) - pd.Timedelta(minutes=1))
    idir = np.asarray(side) * np.where(np.asarray(right) == "CE", 1, -1)
    posd = np.where(idir > 0, X.pos_in_rng.values, 1 - X.pos_in_rng.values)
    with np.errstate(invalid="ignore"):
        return (X.ER.values >= er_min) & (X.rng_so_far.values >= rng_min) & (posd >= pos_min)


def daily_ok(sig, side, right, p=10, m=3.0):
    """§4.4: the trade's index direction agrees with the daily Supertrend at the previous close."""
    dst = daily_st(p, m); idir = np.asarray(side) * np.where(np.asarray(right) == "CE", 1, -1)
    return pd.to_datetime(pd.Series(np.asarray(sig))).dt.normalize().map(dst).values == idir


DAYTYPE_12 = dict(move=0.34, er=0.09, side=0.62, crosses=2)        # §4.7 thresholds at 12:00 (others: day_type/rules.json, not in the pack)


def day_type_score(at_tod=720, th=DAYTYPE_12):
    """§4.7 live day-type score per session at a checkpoint: |price - open| / ADR, ER, one-sidedness (share of minutes on one
    side of the running average close), crosses of the day open. 1 point each; 0-4."""
    b = data.index_1m(); b = b[b.tod <= at_tod - 1]; out = {}
    A = adr()
    for d, g in b.groupby("date"):
        c = g.close.values; o = g.open.values[0]; a = A.get(d, np.nan)
        if not len(c) or not np.isfinite(a): continue
        path = np.abs(np.diff(c)).sum() + abs(c[0] - o); er = abs(c[-1] - o) / max(path, 1e-9)
        ravg = np.cumsum(c) / np.arange(1, len(c) + 1); side = max((c > ravg).mean(), (c < ravg).mean())
        crosses = int((np.diff(np.sign(c - o)) != 0).sum())
        out[d] = int(abs(c[-1] - o) / a >= th["move"]) + int(er >= th["er"]) + int(side >= th["side"]) + int(crosses <= th["crosses"])
    return pd.Series(out)
