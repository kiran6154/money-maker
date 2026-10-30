import glob, pickle, sys, numpy as np, pandas as pd; sys.path.insert(0, '/home/claude/bt')
from mtf_st import st_dir
import mtf_bt as M
pd.set_option('display.width', 280); pd.set_option('display.max_columns', 30)
b = M.load_1m(); Dd = b.groupby('date').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last')).reset_index()
dST = pd.Series(st_dir(Dd, 10, 3.0), index=Dd.date).shift(1)
F = pd.read_parquet('chop/features.parquet').set_index('datetime')
rows = []; books = {}
for pick in ('p100', 'p500up'):
    C = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(f'possell/igrid/{0 if pick == "p100" else 1}_*.parquet'))], ignore_index=True)
    for cc in ('st', 'conf', 'exit_rule', 'lock', 'right', 'why'): C[cc] = C[cc].astype(str)
    C['sig'] = pd.to_datetime(C.sig); C['year'] = pd.to_datetime(C.entry_time).dt.year; d0 = C.sig.dt.normalize()
    idir = C.side.values * np.where(C.right == 'CE', 1, -1)
    C['f_daily'] = d0.map(dST).values == idir
    X = F.reindex(C.sig - pd.Timedelta(minutes=1)); posd = np.where(idir > 0, X.pos_in_rng.values, 1 - X.pos_in_rng.values)
    C['f_chop'] = (X.ER.values >= 0.10) & (X.rng_so_far.values >= 0.8) & (posd >= 0.8)
    print(pick, 'candidates', len(C), flush=True)
    for (side, st, conf, ex, lk), x0 in C.groupby(['side', 'st', 'conf', 'exit_rule', 'lock']):
        for filt in ('none', 'daily', 'chop'):
            x = (x0 if filt == 'none' else x0[x0[f'f_{filt}']]).sort_values('sig'); keep = []
            for rr in ('CE', 'PE'):
                y = x[x.right == rr]; free = np.datetime64('1900-01-01')
                for i, s_, xt in zip(y.index.values, y.sig.values, y.exit_time.values):
                    if s_ < free: continue
                    keep.append(i); free = xt
            T = x.loc[keep].sort_values('exit_time')
            if not len(T): continue
            eq = T.net.cumsum(); yr = T.groupby('year').net.sum(); key = (pick, 'SELL' if side < 0 else 'BUY', st, conf, ex, lk, filt)
            books[key] = T[['right', 'sig', 'entry_time', 'exit_time', 'entry', 'exit', 'why', 'net', 'year']]
            rows.append(dict(pick=pick, side=key[1], st=st, entry=conf, exit=ex, lock=lk, filter=filt, trades=len(T), per_yr=round(len(T) / 8.8), win=round((T.net > 0).mean(), 2),
                             net=round(T.net.sum()), maxDD=round((eq - eq.cummax()).min()), train=round(T[T.year <= 2022].net.sum()), test=round(T[T.year >= 2023].net.sum()),
                             yrs_pos=f'{(yr > 0).sum()}/{len(yr)}', slip05=round(T.net.sum() - len(T) * 75 * 2 * 0.4), by_year=' '.join(f'{k%100}:{v/1000:+.0f}k' for k, v in yr.items())))
    del C
S = pd.DataFrame(rows); S.to_csv('possell/igrid_summary.csv', index=False); pickle.dump(books, open('possell/igrid_books.pkl', 'wb'))
print('books', len(S), '| net>0', (S.net > 0).sum(), '| train>0', (S.train > 0).sum(), '| test>0', (S.test > 0).sum(), '| both', ((S.train > 0) & (S.test > 0)).sum())
for dim in ('pick', 'side', 'st', 'entry', 'exit', 'lock', 'filter'):
    print(S.groupby(dim).agg(books=('net', 'size'), med_train=('train', 'median'), med_test=('test', 'median'), both_pos=('test', lambda v: round(((v > 0) & (S.loc[v.index, 'train'] > 0)).mean(), 2))).to_string(), '\n')
c = ['pick', 'side', 'st', 'entry', 'exit', 'lock', 'filter', 'trades', 'per_yr', 'win', 'train', 'test', 'net', 'maxDD', 'yrs_pos', 'slip05']
for pk in ('p100', 'p500up'):
    for sd in ('SELL', 'BUY'):
        x = S[(S.pick == pk) & (S.side == sd)]
        print(f'\n== {pk} {sd}: top 6 chosen on 2018-22 -> 2023-26 =='); print(x.sort_values('train', ascending=False).head(6)[c].to_string(index=False))
