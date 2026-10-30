"""Option standalone, positional BUY (mirror of the sell study) + lock rule.
Trend: 15-min Supertrend on the premium. Entry: ST up-flip ('none'), or a bullish BOS/CHoCH on 1-min (pivot 5) / 5-min (pivot 3) while ST is up.
Only on a day the contract is the scanned pick, 09:20-15:00; buy at the next 1-min open. Normal exits (+ always 15:15 on expiry day):
  st_dn      15-min ST turns down        chandelier  15-min close < highest-high(22) - 3*ATR(22)
  ema20      15-min close < EMA20        tgt2x       premium doubles (limit) ; stop = st_dn
Lock overlays: once premium >= entry + 50 before the normal exit -> stop = entry, normal exit ignored;
  lock_exp  exit at entry (fill min(open, entry)) or 15:15 expiry ;  lock_2x  same, plus target 2x entry (fill max(open, 2x))."""
import sys, glob, gc, time, pickle; sys.path.insert(0, '/home/claude/bt')
import numpy as np, pandas as pd
from mtf_st import st_dir
from opt_sim import costs
import mtf_bt as M
def agg(g, tf):
    k = ((g.tod.astype(int) - 555) // tf).clip(lower=0); bk = g.date + pd.to_timedelta(555 + k * tf, unit='m')
    B = g.assign(bk=bk).groupby('bk').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'), last_dt=('datetime', 'last')).reset_index()
    B[['open', 'high', 'low', 'close']] = B[['open', 'high', 'low', 'close']].astype(float); B['ct'] = B.last_dt + pd.Timedelta(minutes=1); return B
LOT = 75; t0 = time.time()
SETS = [('/home/claude/opt/picks.parquet', '/home/claude/opt/picked', ['p100']), ('/home/claude/opt/picks2.parquet', '/home/claude/opt/picked2', ['p500up', 'p750'])]
EXITS = ['st_dn', 'chandelier', 'ema20', 'tgt2x']
cand = []
for pfile, pdir, picks in SETS:
    P = pd.read_parquet(pfile); P = P[P.pick.isin(picks)]
    watch = P.groupby(['expiry', 'strike', 'right']).apply(lambda g: g.groupby('date').pick.apply(set).to_dict()).to_dict()
    first = P.groupby(['expiry', 'strike', 'right']).date.min().to_dict()
    for f in sorted(glob.glob(pdir + '/*.parquet')):
        e = f.split('/')[-1][:-8]; X = pd.read_parquet(f); exp_close = np.datetime64(pd.Timestamp(e) + pd.Timedelta(minutes=915))
        for (K, r), g in X.groupby(['strike', 'right']):
            wd = watch.get((e, K, r))
            if not wd: continue
            days = np.sort(g.date.unique()); fi = np.searchsorted(days, np.datetime64(first[(e, K, r)])); g = g[g.date >= days[max(0, fi - 3)]].reset_index(drop=True)
            if len(g) < 200: continue
            dt = g.datetime.values; op = g.open.values.astype(float); lo1 = g.low.values.astype(float); hi1 = g.high.values.astype(float); cl1 = g.close.values.astype(float)
            dts = pd.to_datetime(dt); dday = dts.normalize().values; j_exp = min(np.searchsorted(dt, exp_close), len(dt) - 1)
            B15 = agg(g, 15); B5 = agg(g, 5); c15 = B15.close.values; ct15 = B15.ct.values; ct5 = B5.ct.values
            ema = pd.Series(c15).ewm(span=20, adjust=False).mean().values
            tr = np.nan_to_num(np.maximum.reduce([B15.high - B15.low, (B15.high - B15.close.shift()).abs(), (B15.low - B15.close.shift()).abs()]).astype(float))
            atr22 = pd.Series(tr).ewm(alpha=1 / 22, adjust=False).mean().values; hh22 = pd.Series(B15.high).rolling(22, min_periods=1).max().values
            s5 = M.structure_1m(B5[['open', 'high', 'low', 'close']], 3); bull5 = ct5[s5['ev'] > 0]
            s1 = M.structure_1m(g[['open', 'high', 'low', 'close']].astype(float), 5); bull1 = dt[s1['ev'] > 0] + np.timedelta64(1, 'm')
            for (p, m) in ((4, 3.0), (10, 3.0)):
                d15 = st_dir(B15, p, m); flip = np.r_[0, np.diff(d15.astype(int))]
                ex_t = {'st_dn': ct15[flip < 0], 'chandelier': ct15[c15 < hh22 - 3 * atr22], 'ema20': ct15[c15 < ema]}
                for conf, times in (('none', ct15[flip > 0]), ('5m', bull5), ('1m', bull1)):
                    for t in times:
                        tt = pd.Timestamp(t); dd = tt.normalize(); tdm = tt.hour * 60 + tt.minute
                        if dd not in wd or not (560 <= tdm <= 900): continue
                        if conf != 'none':
                            j = np.searchsorted(ct15, t, side='right') - 1
                            if j < 0 or d15[j] != 1: continue
                        i0 = np.searchsorted(dt, t)
                        if i0 >= len(dt) or dday[i0] != np.datetime64(dd) or op[i0] < 2: continue
                        E = op[i0]
                        for ex in EXITS:
                            base = 'st_dn' if ex == 'tgt2x' else ex
                            nx = ex_t[base]; nx = nx[nx > t]; tx = min(nx[0] if len(nx) else np.datetime64('2100-01-01'), exp_close); why = ex if tx < exp_close else 'expiry'
                            i1 = min(np.searchsorted(dt, tx), len(dt) - 1); px = op[i1] if dt[i1] >= tx else cl1[i1]
                            if ex == 'tgt2x':
                                hit = np.flatnonzero(hi1[i0:i1 + 1] >= 2 * E)
                                if len(hit): i1 = i0 + hit[0]; px = max(op[i1], 2 * E); why = 'tgt2x target'
                            outs = {'normal': (i1, px, why)}
                            hit = np.flatnonzero(hi1[i0:i1 + 1] >= E + 50)
                            for lk in ('lock_exp', 'lock_2x'):
                                if not len(hit) or i0 + hit[0] >= i1: outs[lk] = (i1, px, why); continue
                                s = i0 + hit[0] + 1; st_ = np.flatnonzero(lo1[s:j_exp + 1] <= E); ks = s + st_[0] if len(st_) else 10 ** 9
                                kt = 10 ** 9
                                if lk == 'lock_2x':
                                    tg = np.flatnonzero(hi1[s:j_exp + 1] >= 2 * E); kt = s + tg[0] if len(tg) else 10 ** 9
                                if min(ks, kt) <= j_exp:
                                    if ks <= kt: outs[lk] = (ks, min(op[ks], E), 'locked: back to entry')
                                    else: outs[lk] = (kt, max(op[kt], 2 * E), 'locked: 2x target')
                                else: outs[lk] = (j_exp, op[j_exp] if dt[j_exp] >= exp_close else cl1[j_exp], 'locked: expiry 15:15')
                            for lk, (k, px_, w) in outs.items():
                                cand.append((tuple(sorted(wd[dd])), f'15m ST({p},{m:g})', conf, ex, lk, r, tt, e, K, pd.Timestamp(dt[i0]), pd.Timestamp(dt[k]), E, px_, w,
                                             (px_ - E) * LOT - costs(E, px_, 1)))
        del X; gc.collect(); print(e, len(cand), f'{time.time()-t0:.0f}s', flush=True)
C = pd.DataFrame(cand, columns=['picks', 'st', 'conf', 'exit_rule', 'lock', 'right', 'sig', 'expiry', 'strike', 'entry_time', 'exit_time', 'entry', 'exit', 'why', 'net'])
C.to_pickle('/home/claude/bt/possell/buy_candidates.pkl'); print('candidates', len(C), f'{time.time()-t0:.0f}s')
