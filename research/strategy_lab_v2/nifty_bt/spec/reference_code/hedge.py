"""Add a cheap OTM long option (same expiry, same right) to every short. Hedge strike chosen from the 09:19 chain of the entry day
(premium closest to the target, OTM only); bought at the short's entry minute open, sold at the short's exit minute open.
Mark-to-market per minute on closes for the worst open loss (naked vs hedged on the same basis)."""
import sys, glob, os, pickle, collections; sys.path.insert(0, '/home/claude/bt')
import numpy as np, pandas as pd
from opt_sim import costs
LOT = 75
S = pd.read_parquet('/home/claude/opt/chain_0919.parquet').reset_index(drop=True); S = S[S.close > 0]
S['otm'] = np.where(S.right == 'CE', S.strike > S.spot, S.strike < S.spot); S = S[S.otm]
R1 = pickle.load(open('possell/conf_books.pkl', 'rb')); R2 = pickle.load(open('possell/conf2_books.pkl', 'rb'))
BOOKS = {'₹100+ · ST(4,3) + 1m confirm → ST up': (R1[('p100', '15m ST(4,3)', '1m', 'st_up')], 'picked'),
         '₹100+ · ST(4,3) + 5m confirm → EMA20': (R1[('p100', '15m ST(4,3)', '5m', 'ema20')], 'picked'),
         '₹500+ · ST(10,3) flip → ST up': (R2[('p500up', '15m ST(10,3)', 'none', 'st_up')], 'picked2')}
TGTS = (5, 10, 20)
# hedge strike per (date, expiry, right, target)
H = {}
for (d, e, r), g in S.groupby(['date', 'expiry', 'right']):
    for t in TGTS:
        row = g.iloc[(g.close - t).abs().argmin()]; H[(d, e, r, t)] = (row.strike, row.close)
UP = '/mnt/user-data/uploads/nifty_data/options/1minute'; expdirs = {}
for rt in [f'{UP}/{y}' for y in range(2018, 2027)] + ['/home/claude/optzip']:
    for dd in sorted(glob.glob(rt + '/20??-??-??')): expdirs.setdefault(os.path.basename(dd), []).append(dd)
allT = []
for name, (T, src) in BOOKS.items():
    T = T.copy(); T['book'] = name; T['src'] = src; T['d'] = T.entry_time.dt.normalize(); allT.append(T)
A = pd.concat(allT, ignore_index=True)
out = []
for e, g in A.groupby('expiry'):
    need = set()
    for _, r in g.iterrows():
        for t in TGTS:
            h = H.get((r.d, e, r.right, t))
            if h: need.add((h[0], r.right))
    ks = {k for k, _ in need}; parts = []
    for f in sorted(f for dd in expdirs[e] for f in glob.glob(dd + '/*.parquet')):
        x = pd.read_parquet(f, columns=['datetime', 'strike', 'right', 'open', 'close']); x = x[x.strike.isin(ks)]
        if len(x): parts.append(x)
    X = pd.concat(parts); X['right'] = X.right.astype(str); X = X.drop_duplicates(['strike', 'right', 'datetime']).set_index(['strike', 'right', 'datetime']).sort_index()
    short_src = {}
    for _, r in g.iterrows():
        src = r.src
        if src not in short_src:
            sp = pd.read_parquet(f'/home/claude/opt/{src}/{e}.parquet', columns=['strike', 'right', 'datetime', 'close']); short_src[src] = sp.set_index(['strike', 'right', 'datetime']).sort_index()
        sh = short_src[src].loc[(r.strike, r.right)].close.loc[r.entry_time:r.exit_time].astype(float)
        mtm_naked = (r.entry - sh) * LOT
        rec = dict(book=r.book, entry_time=r.entry_time, right=r.right, net_naked=r.net, worst_naked=mtm_naked.min() if len(sh) else 0.0, year=r.year)
        for t in TGTS:
            h = H.get((r.d, e, r.right, t)); ok = False
            if h and (h[0], r.right) in X.index.droplevel(2):
                hx = X.loc[(h[0], r.right)]
                i0 = hx.index.searchsorted(r.entry_time); i1 = hx.index.searchsorted(r.exit_time)
                if i0 < len(hx) and (hx.index[i0] - r.entry_time) <= pd.Timedelta(minutes=5):
                    i1 = min(i1, len(hx) - 1); he = float(hx.open.iloc[i0]); hxp = float(hx.open.iloc[i1]) if hx.index[i1] >= r.exit_time else float(hx.close.iloc[i1])
                    c = costs(he, hxp, 1); hnet = (hxp - he) * LOT - c
                    hp = hx.close.loc[r.entry_time:r.exit_time].astype(float).reindex(sh.index).ffill().fillna(he)
                    mtm = mtm_naked + (hp - he) * LOT
                    rec.update({f'net_h{t}': r.net + hnet, f'worst_h{t}': mtm.min() if len(mtm) else 0.0, f'hprem{t}': he, f'hstrike_gap{t}': abs(h[0] - r.strike)}); ok = True
            if not ok: rec.update({f'net_h{t}': r.net, f'worst_h{t}': rec['worst_naked'], f'hprem{t}': np.nan, f'hstrike_gap{t}': np.nan})
            rec[f'hedged{t}'] = ok
        out.append(rec)
    print(e, len(out), flush=True)
Z = pd.DataFrame(out); Z.to_pickle('possell/hedge_trades.pkl'); print('done', len(Z))
