"""Adds a Supertrend(10,3) DIRECTION filter to the 5/15-min pivot trend + 1-min CHoCH/BOS strategy (mtf_bt.py).
Entry only if Supertrend direction agrees with the trade: on 1-min (current bar), 5-min, 15-min, or 5-min AND 15-min
(closed bars only, same session). Also: Supertrend replacing the pivot trend filter. Everything else as mtf_bt.py."""
import sys, os, time, pickle
import numpy as np, pandas as pd
sys.path.insert(0, '/home/claude/bt')
import mtf_bt as M

def st_dir(b, period=10, mult=3.0):
    h, l, c = b.high.values, b.low.values, b.close.values; n = len(c)
    tr = np.maximum.reduce([h - l, np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])])
    atr = pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().values
    hl2 = (h + l) / 2; ub = hl2 + mult * atr; lb = hl2 - mult * atr; fu = ub.copy(); fl = lb.copy(); d = np.ones(n, dtype=np.int8)
    for i in range(1, n):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        d[i] = 1 if c[i] > fu[i - 1] else -1 if c[i] < fl[i - 1] else d[i - 1]
    return d

def simulate_f(b, ind, st, reg, sig, ex, filt):
    """reg = trend filter (pivots or supertrend), filt = extra direction filter (or None)."""
    r = reg if filt is None else np.where(filt == reg, reg, 0).astype(np.int8)
    return M.simulate(b, ind, st, r, sig, ex)

if __name__ == '__main__':
    t0 = time.time(); OUT = '/home/claude/bt/mtf_st'; os.makedirs(OUT, exist_ok=True)
    b = M.load_1m(); ind = M.indicators(b)
    b5 = pd.read_parquet('/home/claude/tt/bars_5m.parquet'); b15 = pd.read_parquet('/home/claude/tt/bars_15m.parquet')
    for x in (b5, b15): x['tod'] = pd.to_datetime(x.datetime).dt.hour * 60 + pd.to_datetime(x.datetime).dt.minute
    b5 = b5[b5.tod < 930].reset_index(drop=True); b15 = b15[b15.tod < 930].reset_index(drop=True)
    def htf_map(bb, arr, mins):
        r, hd = M.map_htf(b.datetime, bb, arr, mins); return np.where(pd.to_datetime(hd) == b.date.values, r, 0).astype(np.int8)
    R = {f'5m_N{N}': htf_map(b5, M.regime_series(b5, N), 5) for N in (3, 5)}
    R.update({f'15m_N{N}': htf_map(b15, M.regime_series(b15, N), 15) for N in (2, 3)})
    ST = {'ST 1m': ind['st_dir'].astype(np.int8), 'ST 5m': htf_map(b5, st_dir(b5), 5), 'ST 15m': htf_map(b15, st_dir(b15), 15)}
    ST['ST 5m+15m'] = np.where(ST['ST 5m'] == ST['ST 15m'], ST['ST 5m'], 0).astype(np.int8)
    print('ready', f'{time.time()-t0:.0f}s', {k: round(float((v != 0).mean()), 3) for k, v in ST.items()}, flush=True)
    rows = []; books = {}
    sts = {N1: M.structure_1m(b, N1) for N1 in (3, 5)}
    exits = ('R2', 'swing', 'chandelier', 'supertrend')
    jobs = []
    for N1 in (3, 5):
        for (a5, a15) in ((3, 2), (5, 3)):
            piv = {'pivots 5m': R[f'5m_N{a5}'], 'pivots 15m': R[f'15m_N{a15}'], 'pivots 5m+15m': np.where(R[f'5m_N{a5}'] == R[f'15m_N{a15}'], R[f'5m_N{a5}'], 0).astype(np.int8)}
            for pname, preg in piv.items():
                for fname in ('none', 'ST 1m', 'ST 5m', 'ST 15m', 'ST 5m+15m'):
                    jobs.append((N1, f'{pname} (5m N={a5}, 15m N={a15})', preg, fname))
        for fname in ('ST 5m', 'ST 15m', 'ST 5m+15m'):                     # Supertrend instead of pivots
            jobs.append((N1, f'{fname} only (no pivots)', ST[fname], 'none'))
    for N1, tname, treg, fname in jobs:
        for sig in (('BOS',), ('CHoCH',), ('BOS', 'CHoCH')):
            for ex in exits:
                T = simulate_f(b, ind, sts[N1], treg, sig, ex, None if fname == 'none' else ST[fname])
                key = f"1m N={N1} | trend: {tname} | ST filter: {fname} | {'+'.join(sig)} | {ex}"
                s = M.stats(T, key=key, N1=N1, trend=tname, st_filter=fname, signals='+'.join(sig), exit=ex)
                if len(T): s.update(gross=round(T.gross.sum()), pts_per_trade=round(T.pts.mean(), 2))
                rows.append(s); books[key] = T
        print(f'{N1} {tname} {fname} done [{time.time()-t0:.0f}s]', flush=True)
    S = pd.DataFrame(rows); S.to_csv(f'{OUT}/summary.csv', index=False); pickle.dump(books, open(f'{OUT}/books.pkl', 'wb'))
    print('done', len(S), f'[{time.time()-t0:.0f}s]')
