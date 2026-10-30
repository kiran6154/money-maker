import glob, pickle, sys, numpy as np, pandas as pd; sys.path.insert(0, '/home/claude/bt')
pd.set_option('display.width', 280); pd.set_option('display.max_columns', 30)
F = pd.read_parquet('chop/features.parquet').set_index('datetime')
C = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob('possell/dual/*.parquet'))], ignore_index=True)
for cc in ('tf', 'pair', 'entry_rule', 'exit_rule', 'right', 'why'): C[cc] = C[cc].astype(str)
C['sig'] = pd.to_datetime(C.sig); C['year'] = pd.to_datetime(C.entry_time).dt.year; C['day'] = C.sig.dt.normalize()
idir = C.side.values * np.where(C.right == 'CE', 1, -1); X = F.reindex(C.sig - pd.Timedelta(minutes=1)); posd = np.where(idir > 0, X.pos_in_rng.values, 1 - X.pos_in_rng.values)
C['f_chop'] = (X.ER.values >= 0.10) & (X.rng_so_far.values >= 0.8) & (posd >= 0.8)
print('candidates', len(C), flush=True)
rows = []; books = {}
for (side, tf, pair, ent, ex), x0 in C.groupby(['side', 'tf', 'pair', 'entry_rule', 'exit_rule']):
    for filt in ('none', 'chop'):
        x1 = (x0 if filt == 'none' else x0[x0.f_chop]).sort_values('sig')
        for cap in (1, 2, 99):
            keep = []
            for rr in ('CE', 'PE'):
                y = x1[x1.right == rr]; free = np.datetime64('1900-01-01'); cnt = {}
                for i, s_, xt, dy in zip(y.index.values, y.sig.values, y.exit_time.values, y.day.values):
                    if s_ < free or cnt.get(dy, 0) >= cap: continue
                    keep.append(i); free = xt; cnt[dy] = cnt.get(dy, 0) + 1
            T = x1.loc[keep].sort_values('exit_time')
            if not len(T): continue
            eq = T.net.cumsum(); yr = T.groupby('year').net.sum(); key = ('SELL' if side < 0 else 'BUY', tf, pair, ent, ex, filt, cap)
            books[key] = T[['right', 'sig', 'entry_time', 'exit_time', 'entry', 'exit', 'why', 'net', 'year']]
            rows.append(dict(side=key[0], tf=tf, pair=pair, entry=ent, exit=ex, filter=filt, max_per_day=cap if cap < 99 else 'all', trades=len(T), per_day=round(len(T) / T.sig.dt.normalize().nunique(), 2),
                             win=round((T.net > 0).mean(), 2), net=round(T.net.sum()), maxDD=round((eq - eq.cummax()).min()), train=round(T[T.year <= 2022].net.sum()), test=round(T[T.year >= 2023].net.sum()),
                             yrs_pos=f'{(yr > 0).sum()}/{len(yr)}', slip05=round(T.net.sum() - len(T) * 75 * 2 * 0.4), by_year=' '.join(f'{k%100}:{v/1000:+.0f}k' for k, v in yr.items())))
S = pd.DataFrame(rows); S.to_csv('possell/dual_summary.csv', index=False); pickle.dump(books, open('possell/dual_books.pkl', 'wb'))
print('books', len(S), '| net>0', (S.net > 0).sum(), '| train>0', (S.train > 0).sum(), '| test>0', (S.test > 0).sum(), '| both', ((S.train > 0) & (S.test > 0)).sum())
for dim in ('side', 'tf', 'pair', 'entry', 'exit', 'filter', 'max_per_day'):
    print(S.groupby(dim).agg(books=('net', 'size'), med_trades=('trades', 'median'), med_train=('train', 'median'), med_test=('test', 'median'),
                             both_pos=('test', lambda v: round(((v > 0) & (S.loc[v.index, 'train'] > 0)).mean(), 2))).to_string(), '\n')
c = ['side', 'tf', 'pair', 'entry', 'exit', 'filter', 'max_per_day', 'trades', 'per_day', 'win', 'train', 'test', 'net', 'maxDD', 'yrs_pos', 'slip05']
for sd in ('SELL', 'BUY'):
    print(f'\n== {sd}: top 8 chosen on 2018-22 -> 2023-26 =='); print(S[S.side == sd].sort_values('train', ascending=False).head(8)[c].to_string(index=False))
