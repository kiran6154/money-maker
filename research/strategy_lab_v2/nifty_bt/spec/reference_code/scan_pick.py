"""Pick per (day, right) from the 09:19 chain of the trade expiry: ATM (nearest spot), p100 (cheapest premium >= 100), p300 (premium closest to 300),
p500 (dearest premium <= 500). Then pass 2: load full 1-min history of every picked contract."""
import pandas as pd, numpy as np, glob, os, time, collections
t0 = time.time()
S = pd.read_parquet('/home/claude/opt/chain_0919.parquet'); S = S[S.close > 0]
rows = []
for (d, r), g in S.groupby(['date', 'right']):
    sp = g.spot.iloc[0]; atm = g.iloc[(g.strike - sp).abs().argmin()]
    rows.append(dict(date=d, right=r, pick='ATM', expiry=atm.expiry, strike=atm.strike, prem=atm.close, spot=sp))
    c = g[(g.close >= 100) & (g.close <= 500)]
    if not len(c): continue
    for name, row in (('p100', c.loc[c.close.idxmin()]), ('p300', c.iloc[(c.close - 300).abs().argmin()]), ('p500', c.loc[c.close.idxmax()])):
        rows.append(dict(date=d, right=r, pick=name, expiry=row.expiry, strike=row.strike, prem=row.close, spot=sp))
P = pd.DataFrame(rows); P['otm_pts'] = np.where(P.right == 'CE', P.strike - P.spot, P.spot - P.strike)
P.to_parquet('/home/claude/opt/picks.parquet')
print(P.groupby('pick').agg(days=('date', 'size'), prem_med=('prem', 'median'), otm_med=('otm_pts', 'median'), otm_p10=('otm_pts', lambda v: v.quantile(.1)), otm_p90=('otm_pts', lambda v: v.quantile(.9))).round(0))
print('days with a 100-500 option, by year:', P[P.pick == 'p100'].groupby(P.date.dt.year).size().to_dict())
need = collections.defaultdict(set)
for e, k in P[['expiry', 'strike']].drop_duplicates().values: need[e].add(k)
UP = '/mnt/user-data/uploads/nifty_data/options/1minute'; expdirs = {}
for r in [f'{UP}/{y}' for y in range(2018, 2027)] + ['/home/claude/optzip']:
    for d in sorted(glob.glob(r + '/20??-??-??')): expdirs.setdefault(os.path.basename(d), []).append(d)
os.makedirs('/home/claude/opt/picked', exist_ok=True)
first = P.groupby(['expiry', 'strike']).date.min()
n = 0
for e, ks in need.items():
    parts = []
    for f in sorted(f for d in expdirs[e] for f in glob.glob(d + '/*.parquet')):
        d = pd.read_parquet(f, columns=['datetime', 'strike', 'right', 'open', 'high', 'low', 'close'])
        d = d[d.strike.isin(ks)]
        if len(d): parts.append(d)
    if not parts: continue
    X = pd.concat(parts); X['right'] = X.right.astype(str); X = X.drop_duplicates(['strike', 'right', 'datetime'])
    X['tod'] = (X.datetime.dt.hour * 60 + X.datetime.dt.minute).astype('int16'); X = X[(X.tod >= 555) & (X.tod <= 929)]
    X['date'] = X.datetime.dt.normalize()
    f0 = X.strike.map(lambda k: first.get((e, k))) - pd.Timedelta(days=7)          # warm-up: a week before first pick
    X = X[X.date >= f0]
    for c in ('open', 'high', 'low', 'close'): X[c] = X[c].astype('float32')
    X.assign(expiry=e).sort_values(['strike', 'right', 'datetime']).to_parquet(f'/home/claude/opt/picked/{e}.parquet'); n += len(X)
print('rows', n, f'{time.time()-t0:.0f}s')
