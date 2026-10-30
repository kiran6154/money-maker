"""₹100+ SELL book (15m ST(4,3) + 5m BOS/CHoCH -> ST up) with the lock rule: once premium <= entry-50, stop = entry, normal exit ignored;
exit at entry, at premium 50 ('tgt50' variant; only if 50 < entry-50) or 15:15 expiry ('exp' variant = no target)."""
import sys, pickle, numpy as np, pandas as pd; sys.path.insert(0, '/home/claude/bt')
from opt_sim import costs
LOT = 75
C = pd.read_pickle('possell/conf_candidates.pkl')
C = C[(C.st == '15m ST(4,3)') & (C.conf == '5m') & (C.exit_rule == 'st_up') & C.picks.apply(lambda s: 'p100' in s)].reset_index(drop=True); C['year'] = C.entry_time.dt.year
out = {v: [] for v in ('tgt50', 'exp')}
for e, idx in C.groupby('expiry').groups.items():
    X = pd.read_parquet(f'/home/claude/opt/picked/{e}.parquet'); exp_close = np.datetime64(pd.Timestamp(e) + pd.Timedelta(minutes=915))
    G = {k: (g.datetime.values, g.open.values.astype(float), g.high.values.astype(float), g.low.values.astype(float), g.close.values.astype(float)) for k, g in X.groupby(['strike', 'right'])}
    for i in idx:
        r = C.loc[i]; dt, op, hi, lo, cl = G[(r.strike, r.right)]; E = r.entry
        i0 = np.searchsorted(dt, np.datetime64(r.entry_time)); i1 = np.searchsorted(dt, np.datetime64(r.exit_time))
        hit = np.flatnonzero(lo[i0:i1 + 1] <= E - 50)
        for v in out:
            if not len(hit) or i0 + hit[0] >= i1: out[v].append((i, r.exit_time, r.exit, r.why, r.net, False)); continue
            a = i0 + hit[0]; j1 = min(np.searchsorted(dt, exp_close), len(dt) - 1); s = a + 1
            st = np.flatnonzero(hi[s:j1 + 1] >= E); ks = s + st[0] if len(st) else 10 ** 9; kt = 10 ** 9
            if v == 'tgt50' and E - 50 > 50:
                tg = np.flatnonzero(lo[s:j1 + 1] <= 50); kt = s + tg[0] if len(tg) else 10 ** 9
            if min(ks, kt) <= j1:
                if ks <= kt: k = ks; px = max(op[k], E); w = 'locked: back to entry'
                else: k = kt; px = min(op[k], 50.0); w = 'locked: premium 50 target'
            else: k = j1; px = op[k] if dt[k] >= exp_close else cl[k]; w = 'locked: expiry 15:15'
            out[v].append((i, pd.Timestamp(dt[k]), px, w, (E - px) * LOT - costs(E, px, -1), True))
res = {}
for v, rows in out.items():
    Y = C.copy(); Z = pd.DataFrame(rows, columns=['i', 'exit_time', 'exit', 'why', 'net', 'locked']).set_index('i'); Y[['exit_time', 'exit', 'why', 'net', 'locked']] = Z[['exit_time', 'exit', 'why', 'net', 'locked']]
    Y = Y.sort_values('sig'); keep = []
    for rr in ('CE', 'PE'):
        free = np.datetime64('1900-01-01'); y = Y[Y.right == rr]
        for i, s_, xt in zip(y.index, y.sig.values, y.exit_time.values):
            if s_ < free: continue
            keep.append(i); free = np.datetime64(xt)
    T = Y.loc[keep].sort_values('exit_time'); res[v] = T; eq = T.net.cumsum()
    print(v, len(T), round(T.net.sum()), 'DD', round((eq - eq.cummax()).min()), '2023-26', round(T[T.year >= 2023].net.sum()), T.groupby('why').net.agg(['size', 'sum']).round().to_dict())
pickle.dump(res, open('possell/p100_sell_lock.pkl', 'wb'))
