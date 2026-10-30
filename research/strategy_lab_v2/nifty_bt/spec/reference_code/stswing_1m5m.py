"""Supertrend-segment swings + CHoCH/BOS on the option premium chart.
Swing low = lowest low of a completed ST-DOWN segment (confirmed at the flip-up bar close); swing high = highest high of a completed ST-UP segment.
Bullish break: close > last confirmed swing high (uncrossed) -> CHoCH if structure trend was bearish/none, else BOS. Bearish mirror.
Trade: bullish -> BUY the option, SL = last confirmed swing low; bearish -> SELL the option, SL = last confirmed swing high.
Trail: each newly confirmed swing in the trade's favour moves the SL (never loosens). Optional lock50: after +50 pts, SL floor = entry.
Fills: next 1-min open; SL at worse of open/SL; positional = until SL or 15:15 expiry day; intraday = until SL or 15:15 same day (entries 09:20-14:30)."""
import sys, glob, gc, time, os; sys.path.insert(0, '/home/claude/bt')
import numpy as np, pandas as pd
from mtf_st import st_dir
from opt_sim import costs
LOT = 75; t0 = time.time(); OUT = '/home/claude/bt/possell/stswing15'; os.makedirs(OUT, exist_ok=True)
def agg(g, tf):
    k = ((g.tod.astype(int) - 555) // tf).clip(lower=0); bk = g.date + pd.to_timedelta(555 + k * tf, unit='m')
    B = g.assign(bk=bk).groupby('bk').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'), last_dt=('datetime', 'last')).reset_index()
    B[['open', 'high', 'low', 'close']] = B[['open', 'high', 'low', 'close']].astype(float); B['ct'] = B.last_dt + pd.Timedelta(minutes=1); return B
def swings_1m(g, p, m):
    G1 = g[['open', 'high', 'low', 'close']].astype(float).reset_index(drop=True); d = st_dir(G1, p, m).astype(int)
    h, l = G1.high.values, G1.low.values; ct = g.datetime.values + np.timedelta64(1, 'm'); sh = []; sl = []; hi = lo = np.nan
    for i in range(len(d)):
        if i > 0 and d[i] != d[i - 1]:
            if d[i - 1] == 1: sh.append((ct[i], hi))
            else: sl.append((ct[i], lo))
            hi, lo = h[i], l[i]
        else:
            hi = h[i] if np.isnan(hi) else max(hi, h[i]); lo = l[i] if np.isnan(lo) else min(lo, l[i])
    return np.array([t for t, _ in sh]), np.array([v for _, v in sh]), np.array([t for t, _ in sl]), np.array([v for _, v in sl])
def structure_1m5m(B5, sh_t, sh_v, sl_t, sl_v):
    c, ct = B5.close.values, B5.ct.values; ev = []; trend = 0; Hx = Lx = True; lastH = lastL = -1
    for i in range(len(c)):
        jh = np.searchsorted(sh_t, ct[i], side='right') - 1; jl = np.searchsorted(sl_t, ct[i], side='right') - 1
        if jh != lastH: lastH = jh; Hx = False
        if jl != lastL: lastL = jl; Lx = False
        H = sh_v[jh] if jh >= 0 else np.nan; L = sl_v[jl] if jl >= 0 else np.nan
        if not Hx and not np.isnan(H) and c[i] > H: ev.append((ct[i], 1, 'BOS' if trend == 1 else 'CHoCH', L)); Hx = True; trend = 1
        if not Lx and not np.isnan(L) and c[i] < L: ev.append((ct[i], -1, 'BOS' if trend == -1 else 'CHoCH', H)); Lx = True; trend = -1
    return ev
def structure(B, d):
    h, l, c, ct = B.high.values, B.low.values, B.close.values, B.ct.values; n = len(c)
    seg_hi = seg_lo = np.nan; H = L = np.nan; Hx = Lx = True; trend = 0; ev = []; sh = []; sl = []
    for i in range(n):
        if i > 0 and d[i] != d[i - 1]:                       # segment completed at this bar's close
            if d[i - 1] == 1: H = seg_hi; Hx = False; sh.append((ct[i], H))
            else: L = seg_lo; Lx = False; sl.append((ct[i], L))
            seg_hi, seg_lo = h[i], l[i]
        else:
            seg_hi = h[i] if np.isnan(seg_hi) else max(seg_hi, h[i]); seg_lo = l[i] if np.isnan(seg_lo) else min(seg_lo, l[i])
        if not Hx and c[i] > H: ev.append((ct[i], 1, 'BOS' if trend == 1 else 'CHoCH', L)); Hx = True; trend = 1
        if not Lx and c[i] < L: ev.append((ct[i], -1, 'BOS' if trend == -1 else 'CHoCH', H)); Lx = True; trend = -1
    return ev, np.array([t for t, _ in sh]), np.array([v for _, v in sh]), np.array([t for t, _ in sl]), np.array([v for _, v in sl])
SETS = [('/home/claude/opt/picks.parquet', '/home/claude/opt/picked', 'p100'), ('/home/claude/opt/picks2.parquet', '/home/claude/opt/picked2', 'p500up')]
for si, (pfile, pdir, pick) in enumerate(SETS):
    P = pd.read_parquet(pfile); P = P[P.pick == pick]
    wdays = P.groupby(['expiry', 'strike', 'right']).date.apply(set).to_dict(); first = P.groupby(['expiry', 'strike', 'right']).date.min().to_dict()
    for f in sorted(glob.glob(pdir + '/*.parquet')):
        e = f.split('/')[-1][:-8]; X = pd.read_parquet(f); rows = []; exp_close = np.datetime64(pd.Timestamp(e) + pd.Timedelta(minutes=915))
        for (K, r), g in X.groupby(['strike', 'right']):
            wd = wdays.get((e, K, r))
            if not wd: continue
            days = np.sort(g.date.unique()); fi = np.searchsorted(days, np.datetime64(first[(e, K, r)])); g = g[g.date >= days[max(0, fi - 3)]].reset_index(drop=True)
            if len(g) < 200: continue
            dt = g.datetime.values; op = g.open.values.astype(float); lo1 = g.low.values.astype(float); hi1 = g.high.values.astype(float); dday = pd.to_datetime(dt).normalize().values
            j_exp = min(np.searchsorted(dt, exp_close), len(dt) - 1)
            B5 = agg(g, 5)
            for tf in ('1m-swings/5m-signals',):
                for (p, m) in ((10, 3.0), (4, 3.0), (10, 4.0)):
                    sh_t, sh_v, sl_t, sl_v = swings_1m(g, p, m); ev = structure_1m5m(B5, sh_t, sh_v, sl_t, sl_v)
                    for t, s, kind, stop0 in ev:
                        tt = pd.Timestamp(t); day = tt.normalize(); tdm = tt.hour * 60 + tt.minute
                        if day not in wd or np.isnan(stop0) or not (560 <= tdm <= 900): continue
                        i0 = np.searchsorted(dt, t)
                        if i0 >= len(dt) or dday[i0] != np.datetime64(day) or op[i0] < 2: continue
                        E = op[i0]
                        if (E - stop0) * s < 2: continue                              # stop must be on the losing side, >= 2 pts away
                        upd_t, upd_v = (sl_t, sl_v) if s > 0 else (sh_t, sh_v)
                        m_ = upd_t > t; upd_t, upd_v = upd_t[m_], upd_v[m_]
                        for mode in ('positional', 'intraday'):
                            if mode == 'intraday' and tdm > 870: continue
                            eod_t = exp_close if mode == 'positional' else np.datetime64(day + pd.Timedelta(minutes=915))
                            j_end = min(np.searchsorted(dt, eod_t), len(dt) - 1)
                            if mode == 'intraday' and dday[j_end] != np.datetime64(day): j_end -= 1
                            for lock in ('trail', 'trail+lock50'):
                                stop = stop0; k = i0; px = None; why = 'end'; locked = False; ui = 0
                                bounds = list(np.searchsorted(dt, upd_t[upd_t < dt[j_end]])) + [j_end + 1]
                                seg_start = i0
                                for bi, bnd in enumerate(bounds):
                                    a, z = seg_start, min(bnd, j_end + 1)
                                    if a < z:
                                        if lock == 'trail+lock50' and not locked:
                                            fav = np.flatnonzero((hi1[a:z] >= E + 50) if s > 0 else (lo1[a:z] <= E - 50))
                                            hitst = np.flatnonzero((lo1[a:z] <= stop) if s > 0 else (hi1[a:z] >= stop))
                                            if len(fav) and (not len(hitst) or fav[0] < hitst[0]):
                                                aa = a + fav[0]; px_hit = None
                                                if len(hitst) and hitst[0] == fav[0]: pass
                                                locked = True; stop = max(stop, E) if s > 0 else min(stop, E)
                                                h2 = np.flatnonzero((lo1[aa + 1:z] <= stop) if s > 0 else (hi1[aa + 1:z] >= stop))
                                                if len(h2): k = aa + 1 + h2[0]; px = min(op[k], stop) if s > 0 else max(op[k], stop); why = 'stop'; break
                                                seg_start = z
                                                if bi < len(upd_v): stop = max(stop, upd_v[bi]) if s > 0 else min(stop, upd_v[bi])
                                                continue
                                        hit = np.flatnonzero((lo1[a:z] <= stop) if s > 0 else (hi1[a:z] >= stop))
                                        if len(hit): k = a + hit[0]; px = min(op[k], stop) if s > 0 else max(op[k], stop); why = 'stop' if stop == stop0 else 'trail stop'; break
                                    seg_start = z
                                    if bi < len(upd_v): stop = max(stop, upd_v[bi]) if s > 0 else min(stop, upd_v[bi])
                                if px is None: k = j_end; px = op[j_end]; why = 'expiry 15:15' if mode == 'positional' else 'eod 15:15'
                                rows.append((s, f'1m ST({p},{m:g}) swings · 5m signals', kind, mode, lock, r, t, dt[i0], dt[k], E, stop0, px, why, s * (px - E) * LOT - costs(E, px, s)))
        if rows:
            D = pd.DataFrame(rows, columns=['side', 'st', 'kind', 'mode', 'lock', 'right', 'sig', 'entry_time', 'exit_time', 'entry', 'stop0', 'exit', 'why', 'net'])
            for cc in ('st', 'kind', 'mode', 'lock', 'right', 'why'): D[cc] = D[cc].astype('category')
            D['pick'] = pick; D.to_parquet(f'{OUT}/{si}_{e}.parquet')
        del X; gc.collect(); print(si, e, f'{time.time()-t0:.0f}s', flush=True)
print('done')
