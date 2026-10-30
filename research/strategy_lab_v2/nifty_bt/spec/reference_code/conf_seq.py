import pickle, numpy as np, pandas as pd
pd.set_option('display.width', 280); pd.set_option('display.max_columns', 30)
C = pd.read_pickle('possell/conf_candidates.pkl'); C['year'] = C.entry_time.dt.year
res = {}; rows = []
for pick in ('ATM', 'p100', 'p300'):
    Cp = C[C.picks.apply(lambda s: pick in s)]
    for (st, conf, ex), x in Cp.groupby(['st', 'conf', 'exit_rule']):
        x = x.sort_values('sig'); keep = []
        for r in ('CE', 'PE'):
            free = np.datetime64('1900-01-01'); y = x[x.right == r]
            for i, s_, xt in zip(y.index, y.sig.values, y.exit_time.values):
                if s_ < free: continue
                keep.append(i); free = xt
        T = x.loc[keep].sort_values('exit_time'); res[(pick, st, conf, ex)] = T
        eq = T.net.cumsum(); yr = T.groupby('year').net.sum()
        rows.append(dict(pick=pick, st=st, entry={'none': 'ST flip', '1m': 'ST + 1m BOS/CHoCH', '5m': 'ST + 5m BOS/CHoCH'}[conf], exit=ex, trades=len(T), net=round(T.net.sum()),
                         avg=round(T.net.mean()), win=round((T.net > 0).mean(), 2), maxDD=round((eq - eq.cummax()).min()), worst=round(T.net.min()), worst_open=round(T.worst_open.min()),
                         yrs_pos=f'{(yr > 0).sum()}/{len(yr)}', n18_22=round(T[T.year <= 2022].net.sum()), n23_26=round(T[T.year >= 2023].net.sum()),
                         hold_h=round(((T.exit_time - T.entry_time).dt.total_seconds() / 3600).median(), 1), target_hits=round(T.why.str.contains('target').mean(), 2),
                         by_year=' '.join(f'{k%100}:{v/1000:+.0f}k' for k, v in yr.items())))
S = pd.DataFrame(rows); S.to_csv('possell/conf_summary.csv', index=False); pickle.dump(res, open('possell/conf_books.pkl', 'wb'))
S['ret_dd'] = (S.net / -S.maxDD).round(1)
print(S.groupby(['entry']).agg(runs=('net', 'size'), pos=('net', lambda v: (v > 0).sum()), med=('net', 'median'), med_dd=('maxDD', 'median')).to_string())
print(S.groupby(['exit']).agg(runs=('net', 'size'), pos=('net', lambda v: (v > 0).sum()), med=('net', 'median'), med_dd=('maxDD', 'median'), med_ret_dd=('ret_dd', 'median')).sort_values('med').to_string())
c = ['pick', 'st', 'entry', 'exit', 'trades', 'net', 'avg', 'win', 'maxDD', 'worst', 'yrs_pos', 'n18_22', 'n23_26', 'hold_h', 'ret_dd']
print(S[(S.st == '15m ST(4,3)') & (S.pick == 'p100')][c].to_string(index=False))
print('\nTop 15 by net/maxDD:'); print(S.sort_values('ret_dd', ascending=False).head(15)[c].to_string(index=False))
