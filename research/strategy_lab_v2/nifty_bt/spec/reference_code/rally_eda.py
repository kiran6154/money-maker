"""EDA: one-sided rally size after ₹100+ BUY signals and which signal-time features predict it."""
import sys, pickle, numpy as np, pandas as pd; sys.path.insert(0, '/home/claude/bt')
from mtf_st import st_dir
import mtf_bt as M
pd.set_option('display.width', 250)
R = pd.read_pickle('possell/late_entry.pkl'); R = R[R.pick == 'p100'].reset_index(drop=True)
C = pd.read_pickle('possell/buy_candidates.pkl')
C = C[(C.st == '15m ST(4,3)') & (C.conf == '5m') & (C.exit_rule == 'st_dn') & (C.lock == 'lock_exp') & C.picks.apply(lambda s: 'p100' in s)]
key = ['sig', 'right', 'entry_time']; R = R.merge(C[key + ['expiry', 'strike', 'net', 'why', 'exit_time']].rename(columns={'net': 'net_lock'}), on=key, how='left')
# option-side features from the contract's own path up to the signal
feat = []
for e, g in R.groupby('expiry'):
    X = pd.read_parquet(f'/home/claude/opt/picked/{e}.parquet')
    for (K, r), gg in g.groupby(['strike', 'right']):
        h = X[(X.strike == K) & (X.right == r)].sort_values('datetime'); dt = h.datetime.values; cl = h.close.values.astype(float); hi = h.high.values.astype(float); lo = h.low.values.astype(float)
        b15 = h.assign(k=h.datetime.dt.floor('15min')).groupby('k').agg(o=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last')).astype(float)
        stl = st_dir(b15, 4, 3.0)
        tr = pd.Series(np.nan_to_num(np.maximum.reduce([b15.high - b15.low, (b15.high - b15.close.shift()).abs(), (b15.low - b15.close.shift()).abs()]).astype(float)), index=b15.index)
        atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
        for i, rr in gg.iterrows():
            j = np.searchsorted(dt, np.datetime64(rr.entry_time)) - 1          # last bar fully known (signal bar)
            d0 = np.searchsorted(dt, np.datetime64(rr.entry_time.normalize()))
            day_open = float(h.open.values[d0]); jb = b15.index.searchsorted(rr.sig, side='right') - 1
            feat.append(dict(idx=i, prem=rr.E, chg_day=(cl[j] - day_open) / day_open, dayrng=(hi[d0:j + 1].max() - lo[d0:j + 1].min()) / day_open,
                             atr_pct=atr.iloc[jb - 1] / rr.E if jb >= 1 else np.nan, pos_day=(cl[j] - lo[d0:j + 1].min()) / max(hi[d0:j + 1].max() - lo[d0:j + 1].min(), 1e-9),
                             st_age=int((pd.Series(stl[:jb]) [::-1] == 1).cumprod().sum()) if jb > 0 else 0))
F = pd.DataFrame(feat).set_index('idx'); R = R.join(F)
P = pd.read_parquet('/home/claude/opt/picks.parquet'); P = P[P.pick == 'p100'][['date', 'right', 'strike', 'spot', 'otm_pts']]
R['date'] = R.entry_time.dt.normalize(); R = R.merge(P, on=['date', 'right', 'strike'], how='left')
R['dte'] = (pd.to_datetime(R.expiry) - R.date).dt.days; R['tod'] = R.sig.dt.hour * 60 + R.sig.dt.minute; R['dow'] = R.date.dt.dayofweek
R['idir'] = np.where(R.right == 'CE', 1, -1)
b = M.load_1m(); Dd = b.groupby('date').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last')).reset_index()
dST = pd.Series(st_dir(Dd, 10, 3.0), index=Dd.date).shift(1); R['daily_aligned'] = (R.date.map(dST) == R.idir).astype(int)
I = pd.read_parquet('chop/features.parquet').set_index('datetime'); Xi = I.reindex(R.sig - pd.Timedelta(minutes=1)).reset_index(drop=True)
R['idx_ER'] = Xi.ER.values; R['idx_rng'] = Xi.rng_so_far.values; R['idx_pos_dir'] = np.where(R.idir > 0, Xi.pos_in_rng.values, 1 - Xi.pos_in_rng.values); R['gap_abs'] = Xi.gap.values
dop = b.groupby('date').open.first(); bi = b.set_index('datetime').close; ic = bi.reindex(R.sig - pd.Timedelta(minutes=1)).values
adr = (Dd.set_index('date').high - Dd.set_index('date').low).rolling(20, min_periods=5).mean().shift(1)
R['idx_move_dir'] = R.idir * (ic - R.date.map(dop).values) / R.date.map(adr).values
R['rally100'] = (R.mfe >= 100).astype(int); R['train'] = R.year <= 2022
R.to_pickle('possell/rally_eda.pkl')
print('signals', len(R), '| rally size (MFE pts) quantiles:', R.mfe.quantile([.1, .25, .5, .75, .9, .95, .99]).round(0).to_dict())
print('share reaching +50/+100/+200/+300:', [round((R.mfe >= x).mean(), 3) for x in (50, 100, 200, 300)])
from sklearn.metrics import roc_auc_score
feats = ['prem', 'otm_pts', 'dte', 'tod', 'dow', 'chg_day', 'dayrng', 'atr_pct', 'pos_day', 'st_age', 'daily_aligned', 'idx_ER', 'idx_rng', 'idx_pos_dir', 'idx_move_dir', 'gap_abs']
rows = []
for f in feats:
    for part, m in (('train', R.train), ('test', ~R.train)):
        y = R[m & R[f].notna()]
        rows.append(dict(feat=f, part=part, auc=roc_auc_score(y.rally100, y[f]), corr_net=np.corrcoef(y[f], y.net_lock.fillna(0))[0, 1]))
A = pd.DataFrame(rows).pivot(index='feat', columns='part', values=['auc', 'corr_net']).round(3); print(A.sort_values(('auc', 'train')).to_string())
Q = []
for f in feats:
    q = pd.qcut(R[f].rank(method='first'), 5, labels=False)
    t = R.groupby(q).agg(lo=(f, 'min'), hi=(f, 'max'), rally100=('rally100', 'mean'), mfe_med=('mfe', 'median'), net_avg_train=('net_lock', lambda v: v[R.loc[v.index, 'train']].mean()),
                         net_avg_test=('net_lock', lambda v: v[~R.loc[v.index, 'train']].mean()))
    t['feat'] = f; Q.append(t.reset_index())
Q = pd.concat(Q); Q.to_csv('possell/rally_quintiles.csv', index=False)
for f in feats: print('\n', f); print(Q[Q.feat == f].drop(columns='feat').round(3).to_string(index=False))
