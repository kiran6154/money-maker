"""500+ premium shorts: once the premium is 50 pts below entry, stop -> entry price and ignore the normal exit; then exit only on
premium back to entry (fill max(open, entry)), premium down to 50 (fill min(open, 50)) or 15:15 on expiry day.
Re-evaluates every candidate trade of conf2 and re-runs the one-short-per-leg sequencing."""
import sys, pickle, numpy as np, pandas as pd; sys.path.insert(0, '/home/claude/bt')
from opt_sim import costs
LOT = 75
C = pd.read_pickle('possell/conf2_candidates.pkl'); C['year'] = C.entry_time.dt.year
C = C[~C.exit_rule.isin(['rsi30', 'psar'])].reset_index(drop=True)
new = np.empty(len(C), dtype=object)
for e, idx in C.groupby('expiry').groups.items():
    X = pd.read_parquet(f'/home/claude/opt/picked2/{e}.parquet'); exp_close = np.datetime64(pd.Timestamp(e) + pd.Timedelta(minutes=915))
    G = {k: (g.datetime.values, g.open.values.astype(float), g.high.values.astype(float), g.low.values.astype(float), g.close.values.astype(float)) for k, g in X.groupby(['strike', 'right'])}
    for i in idx:
        r = C.loc[i]; dt, op, hi, lo, cl = G[(r.strike, r.right)]
        i0 = np.searchsorted(dt, np.datetime64(r.entry_time)); i1 = np.searchsorted(dt, np.datetime64(r.exit_time)); E = r.entry
        hit = np.flatnonzero(lo[i0:i1 + 1] <= E - 50)
        if not len(hit) or i0 + hit[0] >= i1:                                   # never 50 in profit before the normal exit
            new[i] = (r.exit_time, r.exit, r.why, r.net, False); continue
        a = i0 + hit[0]; j1 = min(np.searchsorted(dt, exp_close), len(dt) - 1); s = a + 1
        st = np.flatnonzero(hi[s:j1 + 1] >= E); tg = np.flatnonzero(lo[s:j1 + 1] <= 50)
        ks = s + st[0] if len(st) else 10 ** 9; kt = s + tg[0] if len(tg) else 10 ** 9
        if min(ks, kt) <= j1 and min(ks, kt) < 10 ** 9:
            if ks <= kt: k = ks; px = max(op[k], E); why = 'locked: back to entry'
            else: k = kt; px = min(op[k], 50.0); why = 'locked: premium 50 target'
        else:
            k = j1; px = op[k] if dt[k] >= exp_close else cl[k]; why = 'locked: expiry 15:15'
        net = (E - px) * LOT - costs(E, px, -1); new[i] = (pd.Timestamp(dt[k]), px, why, net, True)
    print(e, flush=True)
C[['exit_time', 'exit', 'why', 'net', 'locked']] = pd.DataFrame(list(new), index=C.index)
res = {}; rows = []
for pick in ('p500up', 'p750'):
    Cp = C[C.picks.apply(lambda s: pick in s)]
    for (st, conf, ex), x in Cp.groupby(['st', 'conf', 'exit_rule']):
        x = x.sort_values('sig'); keep = []
        for rr in ('CE', 'PE'):
            free = np.datetime64('1900-01-01'); y = x[x.right == rr]
            for i, s_, xt in zip(y.index, y.sig.values, y.exit_time.values):
                if s_ < free: continue
                keep.append(i); free = np.datetime64(xt)
        T = x.loc[keep].sort_values('exit_time'); res[(pick, st, conf, ex)] = T; eq = T.net.cumsum(); yr = T.groupby('year').net.sum()
        rows.append(dict(pick=pick, st=st, entry={'none': 'ST flip', '1m': 'ST + 1m BOS/CHoCH', '5m': 'ST + 5m BOS/CHoCH'}[conf], exit=ex, trades=len(T), net=round(T.net.sum()),
                         avg=round(T.net.mean()), win=round((T.net > 0).mean(), 2), maxDD=round((eq - eq.cummax()).min()), worst=round(T.net.min()), yrs_pos=f'{(yr > 0).sum()}/{len(yr)}',
                         n18_22=round(T[T.year <= 2022].net.sum()), n23_26=round(T[T.year >= 2023].net.sum()), locked_share=round(T.locked.mean(), 2),
                         lock_be=int((T.why == 'locked: back to entry').sum()), lock_tgt=int((T.why == 'locked: premium 50 target').sum()), lock_exp=int((T.why == 'locked: expiry 15:15').sum()),
                         hold_days=round(((T.exit_time - T.entry_time).dt.total_seconds() / 86400).median(), 1), slip2=round(T.net.sum() - len(T) * 75 * 2 * 1.9),
                         by_year=' '.join(f'{k%100}:{v/1000:+.0f}k' for k, v in yr.items())))
S = pd.DataFrame(rows); S.to_csv('possell/lock50_summary.csv', index=False); pickle.dump(res, open('possell/lock50_books.pkl', 'wb'))
B = pd.read_csv('possell/conf2_summary.csv'); M = S.merge(B[['pick', 'st', 'entry', 'exit', 'net', 'maxDD', 'n23_26', 'yrs_pos']], on=['pick', 'st', 'entry', 'exit'], suffixes=('', '_before'))
M['change'] = M.net - M.net_before; M.to_csv('possell/lock50_vs_before.csv', index=False)
pd.set_option('display.width', 280)
print(M[['pick', 'st', 'entry', 'exit', 'trades', 'net_before', 'net', 'change', 'maxDD_before', 'maxDD', 'n23_26_before', 'n23_26', 'yrs_pos', 'locked_share', 'lock_be', 'lock_tgt', 'lock_exp', 'hold_days', 'slip2']].sort_values('net', ascending=False).to_string(index=False))
print('better in', (M.change > 0).sum(), 'of', len(M), '| DD better in', (M.maxDD > M.maxDD_before).sum())
