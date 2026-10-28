"""INTRADAY option-chart grid (sell & buy). All trades flat by 15:15 the same day. Entries 09:20-14:30 on watched days.
d=-1 SELL premium (trend = premium ST down, bearish confirm), d=+1 BUY (mirror). Writes per-expiry candidate chunks."""
import sys, glob, gc, time, os; sys.path.insert(0, '/home/claude/bt')
import numpy as np, pandas as pd
from mtf_st import st_dir
from opt_sim import costs
import mtf_bt as M
LOT = 75; t0 = time.time(); OUT = '/home/claude/bt/possell/igrid'; os.makedirs(OUT, exist_ok=True)
def agg(g, tf):
    k = ((g.tod.astype(int) - 555) // tf).clip(lower=0); bk = g.date + pd.to_timedelta(555 + k * tf, unit='m')
    B = g.assign(bk=bk).groupby('bk').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'), last_dt=('datetime', 'last')).reset_index()
    B[['open', 'high', 'low', 'close']] = B[['open', 'high', 'low', 'close']].astype(float); B['ct'] = B.last_dt + pd.Timedelta(minutes=1); return B
SETS = [('/home/claude/opt/picks.parquet', '/home/claude/opt/picked', ['p100']), ('/home/claude/opt/picks2.parquet', '/home/claude/opt/picked2', ['p500up'])]
EXITS = ('st', 'chandelier', 'ema20'); LOCKS = {'none': None, 'lock20': 20, 'lock40': 40}
for si, (pfile, pdir, picks) in enumerate(SETS):
    P = pd.read_parquet(pfile); P = P[P.pick.isin(picks)]
    wdays = P.groupby(['expiry', 'strike', 'right']).date.apply(set).to_dict(); first = P.groupby(['expiry', 'strike', 'right']).date.min().to_dict()
    for f in sorted(glob.glob(pdir + '/*.parquet')):
        e = f.split('/')[-1][:-8]; X = pd.read_parquet(f); rows = []
        for (K, r), g in X.groupby(['strike', 'right']):
            wd = wdays.get((e, K, r))
            if not wd: continue
            days = np.sort(g.date.unique()); fi = np.searchsorted(days, np.datetime64(first[(e, K, r)])); g = g[g.date >= days[max(0, fi - 3)]].reset_index(drop=True)
            if len(g) < 200: continue
            dt = g.datetime.values; op = g.open.values.astype(float); lo1 = g.low.values.astype(float); hi1 = g.high.values.astype(float); cl1 = g.close.values.astype(float)
            dday = pd.to_datetime(dt).normalize().values
            s5 = M.structure_1m(agg(g, 5)[['open', 'high', 'low', 'close']], 3); B5 = agg(g, 5); ct5 = B5.ct.values
            s1 = M.structure_1m(g[['open', 'high', 'low', 'close']].astype(float), 5); t1 = dt + np.timedelta64(1, 'm')
            ev = {('5m', 1): ct5[s5['ev'] > 0], ('5m', -1): ct5[s5['ev'] < 0], ('1m', 1): t1[s1['ev'] > 0], ('1m', -1): t1[s1['ev'] < 0]}
            for tf in (5, 15):
                B = B5 if tf == 5 else agg(g, 15); c = B.close.values; ct = B.ct.values
                ema = pd.Series(c).ewm(span=20, adjust=False).mean().values
                tr = np.nan_to_num(np.maximum.reduce([B.high - B.low, (B.high - B.close.shift()).abs(), (B.low - B.close.shift()).abs()]).astype(float))
                atr = pd.Series(tr).ewm(alpha=1 / 22, adjust=False).mean().values; hh = pd.Series(B.high).rolling(22, min_periods=1).max().values; ll = pd.Series(B.low).rolling(22, min_periods=1).min().values
                for (p, m) in ((4, 3.0), (10, 3.0)):
                    dd_ = st_dir(B, p, m); flip = np.r_[0, np.diff(dd_.astype(int))]
                    for d in (-1, 1):
                        ex_t = {'st': ct[flip * d < 0], 'chandelier': ct[(c > ll + 3 * atr) if d < 0 else (c < hh - 3 * atr)], 'ema20': ct[(c > ema) if d < 0 else (c < ema)]}
                        for conf in ('none', '1m', '5m'):
                            times = ct[flip * d > 0] if conf == 'none' else ev[(conf, d)]
                            for t in times:
                                tt = pd.Timestamp(t); day = tt.normalize(); tdm = tt.hour * 60 + tt.minute
                                if day not in wd or not (560 <= tdm <= 870): continue
                                if conf != 'none':
                                    j = np.searchsorted(ct, t, side='right') - 1
                                    if j < 0 or dd_[j] != d: continue
                                i0 = np.searchsorted(dt, t)
                                if i0 >= len(dt) or dday[i0] != np.datetime64(day) or op[i0] < 2: continue
                                eod_t = np.datetime64(day + pd.Timedelta(minutes=915)); j_eod = min(np.searchsorted(dt, eod_t), len(dt) - 1)
                                if dday[j_eod] != np.datetime64(day): j_eod -= 1
                                E = op[i0]
                                for ex in EXITS:
                                    nx = ex_t[ex]; nx = nx[nx > t]; tx = nx[0] if len(nx) else np.datetime64('2100-01-01')
                                    i1 = min(np.searchsorted(dt, tx), j_eod) if tx < eod_t else j_eod; why = ex if (tx < eod_t and i1 < j_eod) else 'eod'
                                    px = op[i1]
                                    for lk, L in LOCKS.items():
                                        k_, px_, w_ = i1, px, why
                                        if L is not None:
                                            fav = (hi1[i0:i1 + 1] >= E + L) if d > 0 else (lo1[i0:i1 + 1] <= E - L); hit = np.flatnonzero(fav)
                                            if len(hit) and i0 + hit[0] < i1:
                                                s = i0 + hit[0] + 1; adv = (lo1[s:j_eod + 1] <= E) if d > 0 else (hi1[s:j_eod + 1] >= E); b = np.flatnonzero(adv)
                                                if len(b) and s + b[0] < j_eod: k_ = s + b[0]; px_ = min(op[k_], E) if d > 0 else max(op[k_], E); w_ = 'locked: back to entry'
                                                else: k_ = j_eod; px_ = op[j_eod]; w_ = 'locked: eod'
                                        rows.append((d, f'{tf}m ST({p},{m:g})', conf, ex, lk, r, t, dt[i0], dt[k_], E, px_, w_, d * (px_ - E) * LOT - costs(E, px_, d)))
        if rows:
            D = pd.DataFrame(rows, columns=['side', 'st', 'conf', 'exit_rule', 'lock', 'right', 'sig', 'entry_time', 'exit_time', 'entry', 'exit', 'why', 'net'])
            for cc in ('st', 'conf', 'exit_rule', 'lock', 'right', 'why'): D[cc] = D[cc].astype('category')
            D['pick'] = picks[0]; D.to_parquet(f'{OUT}/{si}_{e}.parquet')
        del X; gc.collect(); print(si, e, f'{time.time()-t0:.0f}s', flush=True)
print('done')
