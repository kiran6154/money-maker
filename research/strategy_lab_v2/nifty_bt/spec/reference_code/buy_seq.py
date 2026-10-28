import pickle, numpy as np, pandas as pd
pd.set_option('display.width', 280); pd.set_option('display.max_columns', 30)
C = pd.read_pickle('possell/buy_candidates.pkl'); C['year'] = C.entry_time.dt.year
rows = []; res = {}
for pick in ('p100', 'p500up', 'p750'):
    Cp = C[C.picks.apply(lambda s: pick in s)]
    for (st, conf, ex, lk), x in Cp.groupby(['st', 'conf', 'exit_rule', 'lock']):
        x = x.sort_values('sig'); keep = []
        for rr in ('CE', 'PE'):
            free = np.datetime64('1900-01-01'); y = x[x.right == rr]
            for i, s_, xt in zip(y.index, y.sig.values, y.exit_time.values):
                if s_ < free: continue
                keep.append(i); free = xt
        T = x.loc[keep].sort_values('exit_time'); res[(pick, st, conf, ex, lk)] = T; eq = T.net.cumsum(); yr = T.groupby('year').net.sum()
        rows.append(dict(pick=pick, st=st, entry={'none': 'ST flip', '1m': 'ST + 1m BOS/CHoCH', '5m': 'ST + 5m BOS/CHoCH'}[conf], exit=ex, lock=lk, trades=len(T),
                         net=round(T.net.sum()), avg=round(T.net.mean()), win=round((T.net > 0).mean(), 2), maxDD=round((eq - eq.cummax()).min()), worst=round(T.net.min()),
                         yrs_pos=f'{(yr > 0).sum()}/{len(yr)}', n18_22=round(T[T.year <= 2022].net.sum()), n23_26=round(T[T.year >= 2023].net.sum()),
                         slip2=round(T.net.sum() - len(T) * 75 * 2 * 1.9), CE=round(T[T.right == 'CE'].net.sum()), PE=round(T[T.right == 'PE'].net.sum()),
                         locked_exp=int((T.why == 'locked: expiry 15:15').sum()), locked_be=int((T.why == 'locked: back to entry').sum()), locked_2x=int((T.why == 'locked: 2x target').sum()),
                         by_year=' '.join(f'{k%100}:{v/1000:+.0f}k' for k, v in yr.items())))
S = pd.DataFrame(rows); S.to_csv('possell/buy_summary.csv', index=False); pickle.dump(res, open('possell/buy_books.pkl', 'wb'))
print(S.pivot_table(index=['pick', 'lock'], values='net', aggfunc=['count', lambda v: (v > 0).sum(), 'median', 'max']).round(0).to_string())
c = ['pick', 'st', 'entry', 'exit', 'lock', 'trades', 'net', 'avg', 'win', 'maxDD', 'yrs_pos', 'n18_22', 'n23_26', 'slip2', 'CE', 'PE', 'locked_exp', 'locked_be', 'locked_2x']
for pk in ('p100', 'p500up', 'p750'):
    print(f'\n== {pk}: top 8 =='); print(S[S.pick == pk].sort_values('net', ascending=False).head(8)[c].to_string(index=False))
