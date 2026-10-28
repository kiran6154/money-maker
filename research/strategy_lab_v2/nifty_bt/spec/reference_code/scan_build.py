"""Pass 1: for each session D, the trade expiry E = nearest expiry folder strictly after D (never the expiry day itself), within 35 days.
Read every strike of E at 09:19 (close known at 09:20). Save the chain snapshot for selection."""
import pandas as pd, numpy as np, glob, os, time, collections
t0 = time.time()
idx = pd.read_parquet('/home/claude/idx/nifty_5min.parquet'); idx['date'] = idx.datetime.dt.normalize()
spot = idx[idx.datetime.dt.strftime('%H:%M') == '09:15'].set_index('date').close
sessions = [d for d in sorted(spot.index) if pd.Timestamp('2018-01-01') <= d <= pd.Timestamp('2026-10-19')]
UP = '/mnt/user-data/uploads/nifty_data/options/1minute'
expdirs = {}
for r in [f'{UP}/{y}' for y in range(2018, 2027)] + ['/home/claude/optzip']:
    for d in sorted(glob.glob(r + '/20??-??-??')): expdirs.setdefault(os.path.basename(d), []).append(d)
expiries = sorted(expdirs); exp_ts = np.array([np.datetime64(e) for e in expiries])
plan = {}
for D in sessions:
    if pd.Timestamp('2018-02-23') <= D <= pd.Timestamp('2018-03-28'): continue
    i = np.searchsorted(exp_ts, np.datetime64(D), side='right')
    if i >= len(expiries): continue
    e = expiries[i]
    if (pd.Timestamp(e) - D).days > 35: continue
    plan[D] = e
byexp = collections.defaultdict(list)
for D, e in plan.items(): byexp[e].append(D)
snap = []
for e, days in byexp.items():
    for f in sorted(f for d in expdirs[e] for f in glob.glob(d + '/*.parquet')):
        try: d = pd.read_parquet(f, columns=['datetime', 'strike', 'right', 'close', 'volume'])
        except Exception as ex: print('!!', f, ex); continue
        d = d[(d.datetime.dt.hour == 9) & (d.datetime.dt.minute == 19)]
        d = d[d.datetime.dt.normalize().isin(days)]
        if len(d): snap.append(d.assign(expiry=e, right=d.right.astype(str)))
S = pd.concat(snap).drop_duplicates(['datetime', 'strike', 'right']); S['date'] = S.datetime.dt.normalize(); S['spot'] = S.date.map(spot)
S.to_parquet('/home/claude/opt/chain_0919.parquet'); print('snapshot rows', len(S), 'days', S.date.nunique(), 'of', len(plan), f'{time.time()-t0:.0f}s')
print(S.groupby(S.date.dt.year).apply(lambda x: x.groupby(['date', 'right']).strike.nunique().median()))
