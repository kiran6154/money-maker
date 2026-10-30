"""Buy only after the option has already rallied X points from the signal price (buy-stop at E+X, valid until the normal ST-down exit).
Exits after the late entry: 'st' = ST down / expiry; 'sl50' = stop 50 below late entry, else ST down / expiry;
'lock' = ST down until a further +50, then stop = late entry and hold to expiry. Baseline = enter at signal (lock_exp book)."""
import sys, pickle, numpy as np, pandas as pd; sys.path.insert(0, '/home/claude/bt')
from opt_sim import costs
pd.set_option('display.width', 250)
LOT = 75
C = pd.read_pickle('possell/buy_candidates.pkl')
C = C[(C.st == '15m ST(4,3)') & (C.conf == '5m') & (C.exit_rule == 'st_dn') & (C.lock == 'normal')].reset_index(drop=True)
rows = []
for pick, pdir in (('p100', 'picked'), ('p500up', 'picked2')):
    Cp = C[C.picks.apply(lambda s: pick in s)]
    for e, g in Cp.groupby('expiry'):
        X = pd.read_parquet(f'/home/claude/opt/{pdir}/{e}.parquet'); exp_close = np.datetime64(pd.Timestamp(e) + pd.Timedelta(minutes=915))
        G = {k: (h.datetime.values, h.open.values.astype(float), h.high.values.astype(float), h.low.values.astype(float), h.close.values.astype(float)) for k, h in X.groupby(['strike', 'right'])}
        for _, r in g.iterrows():
            dt, op, hi, lo, cl = G[(r.strike, r.right)]; E = r.entry
            i0 = np.searchsorted(dt, np.datetime64(r.entry_time)); i1 = min(np.searchsorted(dt, np.datetime64(r.exit_time)), len(dt) - 1); j_exp = min(np.searchsorted(dt, exp_close), len(dt) - 1)
            mfe = hi[i0:i1 + 1].max() - E
            rec = dict(pick=pick, right=r.right, sig=r.sig, entry_time=r.entry_time, normal_exit=r.exit_time, E=E, mfe=mfe, year=r.entry_time.year)
            for Xp in (50, 100, 150):
                hit = np.flatnonzero(hi[i0:i1 + 1] >= E + Xp)
                if not len(hit) or i0 + hit[0] >= i1:
                    for v in ('st', 'sl50', 'lock'): rec[f'{v}{Xp}'] = np.nan; rec[f'x{v}{Xp}'] = r.exit_time
                    continue
                k = i0 + hit[0]; L = max(op[k], E + Xp)                                     # buy-stop fill
                outs = {}
                outs['st'] = (i1, op[i1] if dt[i1] >= np.datetime64(r.exit_time) else cl[i1])
                s = np.flatnonzero(lo[k + 1:i1 + 1] <= L - 50)
                outs['sl50'] = (k + 1 + s[0], min(op[k + 1 + s[0]], L - 50)) if len(s) else outs['st']
                a = np.flatnonzero(hi[k + 1:i1 + 1] >= L + 50)
                if len(a):
                    s2 = k + 1 + a[0] + 1; b = np.flatnonzero(lo[s2:j_exp + 1] <= L)
                    outs['lock'] = (s2 + b[0], min(op[s2 + b[0]], L)) if len(b) else (j_exp, op[j_exp] if dt[j_exp] >= exp_close else cl[j_exp])
                else: outs['lock'] = outs['st']
                for v, (kk, px) in outs.items():
                    rec[f'{v}{Xp}'] = (px - L) * LOT - costs(L, px, 1); rec[f'x{v}{Xp}'] = pd.Timestamp(dt[kk])
            rows.append(rec)
        print(pick, e, flush=True)
R = pd.DataFrame(rows); R.to_pickle('possell/late_entry.pkl')
