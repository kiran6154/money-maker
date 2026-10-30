"""INTRADAY dual-Supertrend on the option premium (₹100+ pick). Slow ST = direction, fast ST = timing.
Entry 'pullback': slow dir == d and fast flips to d (bar close). Entry 'agree': first bar where slow and fast both == d after not both.
Exit: 'fast' = fast flips against; 'slow' = slow flips against; 'slow+lock20/40' = slow exit until +20/40 pts, then stop = entry, hold to 15:15.
Always flat by 15:15; entries 09:20-14:30 on watched days. d=-1 sell, +1 buy."""
import sys, glob, gc, time, os; sys.path.insert(0, '/home/claude/bt')
import numpy as np, pandas as pd
from mtf_st import st_dir
from opt_sim import costs
LOT = 75; t0 = time.time(); OUT = '/home/claude/bt/possell/dual'; os.makedirs(OUT, exist_ok=True)
def agg(g, tf):
    k = ((g.tod.astype(int) - 555) // tf).clip(lower=0); bk = g.date + pd.to_timedelta(555 + k * tf, unit='m')
    B = g.assign(bk=bk).groupby('bk').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'), last_dt=('datetime', 'last')).reset_index()
    B[['open', 'high', 'low', 'close']] = B[['open', 'high', 'low', 'close']].astype(float); B['ct'] = B.last_dt + pd.Timedelta(minutes=1); return B
P = pd.read_parquet('/home/claude/opt/picks.parquet'); P = P[P.pick == 'p100']
wdays = P.groupby(['expiry', 'strike', 'right']).date.apply(set).to_dict(); first = P.groupby(['expiry', 'strike', 'right']).date.min().to_dict()
PAIRS = {'10,4/5,2': ((10, 4.0), (5, 2.0)), '14,4/7,2': ((14, 4.0), (7, 2.0))}
for f in sorted(glob.glob('/home/claude/opt/picked/*.parquet')):
    e = f.split('/')[-1][:-8]; X = pd.read_parquet(f); rows = []
    for (K, r), g in X.groupby(['strike', 'right']):
        wd = wdays.get((e, K, r))
        if not wd: continue
        days = np.sort(g.date.unique()); fi = np.searchsorted(days, np.datetime64(first[(e, K, r)])); g = g[g.date >= days[max(0, fi - 3)]].reset_index(drop=True)
        if len(g) < 200: continue
        dt = g.datetime.values; op = g.open.values.astype(float); lo1 = g.low.values.astype(float); hi1 = g.high.values.astype(float); dday = pd.to_datetime(dt).normalize().values
        for tf in (1, 3, 5):
            B = agg(g, tf); ct = B.ct.values
            for pname, (sp, fp) in PAIRS.items():
                ds = st_dir(B, *sp).astype(int); dfst = st_dir(B, *fp).astype(int)
                for d in (-1, 1):
                    fl_f = np.r_[0, np.diff(dfst)]; both = (ds == d) & (dfst == d)
                    sig = {'pullback': ct[(ds == d) & (fl_f * d > 0)], 'agree': ct[both & ~np.r_[False, both[:-1]]]}
                    ex_t = {'fast': ct[np.r_[0, np.diff(dfst)] * d < 0], 'slow': ct[np.r_[0, np.diff(ds)] * d < 0]}
                    for ent, times in sig.items():
                        for t in times:
                            tt = pd.Timestamp(t); day = tt.normalize(); tdm = tt.hour * 60 + tt.minute
                            if day not in wd or not (560 <= tdm <= 870): continue
                            i0 = np.searchsorted(dt, t)
                            if i0 >= len(dt) or dday[i0] != np.datetime64(day) or op[i0] < 2: continue
                            eod_t = np.datetime64(day + pd.Timedelta(minutes=915)); j_eod = min(np.searchsorted(dt, eod_t), len(dt) - 1)
                            if dday[j_eod] != np.datetime64(day): j_eod -= 1
                            E = op[i0]
                            for ex in ('fast', 'slow', 'slow+lock20', 'slow+lock40'):
                                nx = ex_t['fast' if ex == 'fast' else 'slow']; nx = nx[nx > t]; tx = nx[0] if len(nx) else np.datetime64('2100-01-01')
                                i1 = min(np.searchsorted(dt, tx), j_eod) if tx < eod_t else j_eod; why = ex.split('+')[0] if i1 < j_eod else 'eod'; px = op[i1]; k_ = i1
                                if 'lock' in ex:
                                    L = 20 if ex.endswith('20') else 40
                                    hit = np.flatnonzero((hi1[i0:i1 + 1] >= E + L) if d > 0 else (lo1[i0:i1 + 1] <= E - L))
                                    if len(hit) and i0 + hit[0] < i1:
                                        s = i0 + hit[0] + 1; bb = np.flatnonzero((lo1[s:j_eod + 1] <= E) if d > 0 else (hi1[s:j_eod + 1] >= E))
                                        if len(bb) and s + bb[0] < j_eod: k_ = s + bb[0]; px = min(op[k_], E) if d > 0 else max(op[k_], E); why = 'locked: back to entry'
                                        else: k_ = j_eod; px = op[j_eod]; why = 'locked: eod'
                                rows.append((d, f'{tf}m', pname, ent, ex, r, t, dt[i0], dt[k_], E, px, why, d * (px - E) * LOT - costs(E, px, d)))
    if rows:
        D = pd.DataFrame(rows, columns=['side', 'tf', 'pair', 'entry_rule', 'exit_rule', 'right', 'sig', 'entry_time', 'exit_time', 'entry', 'exit', 'why', 'net'])
        for cc in ('tf', 'pair', 'entry_rule', 'exit_rule', 'right', 'why'): D[cc] = D[cc].astype('category')
        D.to_parquet(f'{OUT}/{e}.parquet')
    del X; gc.collect(); print(e, f'{time.time()-t0:.0f}s', flush=True)
print('done')
