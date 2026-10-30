"""Live (no look-ahead) choppy-day detection; skip trades the filter flags. Thresholds chosen on 2018-2022, tested on 2023-2026."""
import sys, os, pickle; sys.path.insert(0, '/home/claude/bt')
import numpy as np, pandas as pd
import mtf_bt as M
from st_instances import day_types
OUT = '/home/claude/bt/chop'; os.makedirs(OUT, exist_ok=True)
b = M.load_1m(); D = day_types(b)
o, h, l, c = (b[k].values for k in ('open', 'high', 'low', 'close')); day = b.date.values; tod = b.tod.values
g = b.groupby('date')
# ---- day-so-far features at each 1-min bar close (uses bars <= i only)
dopen = g.open.transform('first').values
dhi = g.high.cummax().values; dlo = g.low.cummin().values
path = g.close.transform(lambda s: s.diff().abs().fillna(0).cumsum()).values + np.abs(c - dopen) * 0  # sum |Δclose|
path = path + np.abs(g.close.transform('first').values - dopen)
ER = np.abs(c - dopen) / np.maximum(path, 1e-9)                         # Kaufman efficiency of the day so far (1=straight line)
# prior-day info (known at the open)
pdD = D.shift(1); ad = (D.hi - D.lo).rolling(20, min_periods=5).mean().shift(1)            # 20-day avg range, prior days only
rng_so_far = (dhi - dlo) / pd.Series(day).map(ad).values                                   # today's range so far / normal day range
# opening range 09:15-09:44 (known from 09:45)
orw = b[b.tod < 585].groupby('date').apply(lambda x: x.high.max() - x.low.min()); orw_rel = (orw / ad)
ORW = np.where(tod >= 585, pd.Series(day).map(orw_rel).values, np.nan)
# where price sits in today's range so far (0=low,1=high): mid-range = no trend yet
pos_in_rng = (c - dlo) / np.maximum(dhi - dlo, 1e-9)
# 1-min structure flips so far today (CHoCH count) -- N=5 structure, confirmed events only
st5 = M.structure_1m(b, 5); choch = (np.abs(st5['ev']) == 2).astype(int)
CH = pd.Series(choch).groupby(day).cumsum().values
# 15-min choppiness index & ADX on the last CLOSED 15-min bar (can include the prior day's bars)
b15 = pd.read_parquet('/home/claude/tt/bars_15m.parquet'); b15['tod'] = pd.to_datetime(b15.datetime).dt.hour * 60 + pd.to_datetime(b15.datetime).dt.minute
b15 = b15[b15.tod < 930].reset_index(drop=True)
H, L, C = b15.high.values, b15.low.values, b15.close.values; pc = np.r_[C[0], C[:-1]]
tr = np.maximum.reduce([H - L, np.abs(H - pc), np.abs(L - pc)]); n = 14
chop = 100 * np.log10(pd.Series(tr).rolling(n).sum() / (pd.Series(H).rolling(n).max() - pd.Series(L).rolling(n).min())) / np.log10(n)
up = np.r_[0, np.diff(H)]; dn = np.r_[0, -np.diff(L)]; pdm = np.where((up > dn) & (up > 0), up, 0); ndm = np.where((dn > up) & (dn > 0), dn, 0)
rma = lambda x: pd.Series(x).ewm(alpha=1 / n, adjust=False).mean()
atr = rma(tr); pdi = 100 * rma(pdm) / atr; ndi = 100 * rma(ndm) / atr; adx = rma(100 * np.abs(pdi - ndi) / (pdi + ndi).replace(0, np.nan))
key = pd.DataFrame({'k': (b.datetime + pd.Timedelta(minutes=-14)).values.astype('datetime64[ns]')}).reset_index()
Hk = pd.DataFrame({'k': pd.to_datetime(b15.datetime).values.astype('datetime64[ns]'), 'chop': chop.values, 'adx': adx.values})
m = pd.merge_asof(key.sort_values('k'), Hk, on='k', direction='backward').sort_values('index')
CHOP15 = m.chop.values; ADX15 = m.adx.values
F = pd.DataFrame(dict(datetime=b.datetime, date=b.date, ER=ER, rng_so_far=rng_so_far, ORW=ORW, pos_in_rng=pos_in_rng, choch_today=CH,
                      chop15=CHOP15, adx15=ADX15, gap=pd.Series(day).map(D.gap.abs()).values,
                      prev_type=pd.Series(day).map(pdD.type).values, prev_rng_rel=pd.Series(day).map((pdD.rng / ad)).values))
F.to_parquet(f'{OUT}/features.parquet')
pickle.dump(D, open(f'{OUT}/D.pkl', 'wb'))
print('features ok', F.describe().T[['mean', '50%']].round(2))
