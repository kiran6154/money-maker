import glob, pickle, numpy as np, pandas as pd
pd.set_option('display.width', 280); pd.set_option('display.max_columns', 30)
F = pd.read_parquet('chop/features.parquet').set_index('datetime')
C = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob('possell/chochst/*.parquet'))], ignore_index=True)
for cc in ('st', 'kind', 'mode', 'lock', 'right', 'why'): C[cc] = C[cc].astype(str)
C['sig'] = pd.to_datetime(C.sig); C['year'] = pd.to_datetime(C.entry_time).dt.year
idir = C.side.values * np.where(C.right == 'CE', 1, -1); X = F.reindex(C.sig - pd.Timedelta(minutes=1)); posd = np.where(idir > 0, X.pos_in_rng.values, 1 - X.pos_in_rng.values)
C['f_chop'] = (X.ER.values >= 0.10) & (X.rng_so_far.values >= 0.8) & (posd >= 0.8)
print('candidates', len(C), C.groupby(['kind']).size().to_dict(), flush=True)
rows = []; books = {}
def seq(x):
    keep = []
    for rr in ('CE', 'PE'):
        y = x[x.right == rr]; free = np.datetime64('1900-01-01')
        for i, s_, xt in zip(y.index.values, y.sig.values, y.exit_time.values):
            if s_ < free: continue
            keep.append(i); free = xt
    return x.loc[keep].sort_values('exit_time')
for (pick, side, st, mode, lock), x0 in C.groupby(['pick', 'side', 'st', 'mode', 'lock']):
    for sigs in ('CHoCH', 'CHoCH+BOS'):
        x1 = x0 if sigs == 'CHoCH+BOS' else x0[x0.kind == 'CHoCH']
        for filt in ('none', 'chop'):
            x = (x1 if filt == 'none' else x1[x1.f_chop]).sort_values('sig'); T = seq(x)
            if not len(T): continue
            eq = T.net.cumsum(); yr = T.groupby('year').net.sum(); key = (pick, 'BUY' if side > 0 else 'SELL', st, sigs, mode, lock, filt); books[key] = T
            rows.append(dict(pick=pick, side=key[1], st=st, signals=sigs, mode=mode, lock=lock, filter=filt, trades=len(T), per_yr=round(len(T) / 8.8), win=round((T.net > 0).mean(), 2),
                             net=round(T.net.sum()), maxDD=round((eq - eq.cummax()).min()), train=round(T[T.year <= 2022].net.sum()), test=round(T[T.year >= 2023].net.sum()),
                             yrs_pos=f'{(yr > 0).sum()}/{len(yr)}', slip1=round(T.net.sum() - len(T) * 75 * 2 * 0.9), by_year=' '.join(f'{k%100}:{v/1000:+.0f}k' for k, v in yr.items())))
S = pd.DataFrame(rows); S.to_csv('possell/chochst_summary.csv', index=False); pickle.dump(books, open('possell/chochst_books.pkl', 'wb'))
print('books', len(S), '| net>0', (S.net > 0).sum(), '| train>0', (S.train > 0).sum(), '| test>0', (S.test > 0).sum(), '| both', ((S.train > 0) & (S.test > 0)).sum())
for dim in ('pick', 'side', 'st', 'signals', 'mode', 'lock', 'filter'):
    print(S.groupby(dim).agg(books=('net', 'size'), med_net=('net', 'median'), med_train=('train', 'median'), med_test=('test', 'median'),
                             both_pos=('test', lambda v: round(((v > 0) & (S.loc[v.index, 'train'] > 0)).mean(), 2))).to_string(), '\n')
c = ['pick', 'side', 'st', 'signals', 'mode', 'lock', 'filter', 'trades', 'per_yr', 'win', 'train', 'test', 'net', 'maxDD', 'yrs_pos', 'slip1']
for pk in ('p100', 'p500up'):
    for md in ('positional', 'intraday'):
        for sd in ('BUY', 'SELL'):
            x = S[(S.pick == pk) & (S['mode'] == md) & (S.side == sd)]
            print(f'\n== {pk} {md} {sd}: top 4 chosen on 2018-22 =='); print(x.sort_values('train', ascending=False).head(4)[c].to_string(index=False))
