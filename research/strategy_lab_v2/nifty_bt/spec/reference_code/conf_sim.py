"""Option standalone, positional SELL. Trend = 15-min Supertrend on the premium (last closed 15-min bar).
Entry: 'none' = the ST down-flip itself; '1m' / '5m' = a bearish BOS or CHoCH on the premium's 1-min (pivot 5) / 5-min (pivot 3)
structure while the 15-min ST is down. Only on a day the contract is the scanned pick, 09:20-15:00; sell at the next 1-min open.
Exit (first of; always also 15:15 on expiry day):
  st_up      15-min ST turns up (baseline)
  ema20      15-min close above EMA20
  chandelier 15-min close above lowest-low(22) + 3*ATR(22)
  psar       15-min Parabolic SAR (0.02/0.2) flips bullish
  choch5_up  bullish structure break on the 5-min premium chart (pivot 3)
  tgt50      premium falls to 50% of the entry price (limit fill) ; stop = st_up
  rsi30      15-min RSI(14) below 30 (take profit) ; stop = st_up
State exits fill at the next 1-min open after the bar close. Lot 75, option charges + Rs 0.10 slippage/side."""
import sys, glob, gc, time, pickle; sys.path.insert(0, '/home/claude/bt')
import numpy as np, pandas as pd
from mtf_st import st_dir
from opt_sim import costs
import mtf_bt as M
LOT = 75; t0 = time.time()
P = pd.read_parquet('/home/claude/opt/picks.parquet'); P = P[P.pick.isin(['ATM', 'p100', 'p300'])]
watch = P.groupby(['expiry', 'strike', 'right']).apply(lambda g: g.groupby('date').pick.apply(set).to_dict()).to_dict()
first = P.groupby(['expiry', 'strike', 'right']).date.min().to_dict()
EXITS = ['st_up', 'ema20', 'chandelier', 'psar', 'choch5_up', 'tgt50', 'rsi30']

def agg(g, tf):
    k = ((g.tod.astype(int) - 555) // tf).clip(lower=0); bk = g.date + pd.to_timedelta(555 + k * tf, unit='m')
    B = g.assign(bk=bk).groupby('bk').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'), last_dt=('datetime', 'last')).reset_index()
    B[['open', 'high', 'low', 'close']] = B[['open', 'high', 'low', 'close']].astype(float); B['ct'] = B.last_dt + pd.Timedelta(minutes=1); return B

def psar_bull(h, l, af0=0.02, afmax=0.2):
    n = len(h); bull = np.zeros(n, bool); up = True; ep = h[0]; sar = l[0]; af = af0
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if up:
            sar = min(sar, l[i - 1], l[i - 2] if i > 1 else l[i - 1])
            if l[i] < sar: up = False; sar = ep; ep = l[i]; af = af0
            elif h[i] > ep: ep = h[i]; af = min(af + af0, afmax)
        else:
            sar = max(sar, h[i - 1], h[i - 2] if i > 1 else h[i - 1])
            if h[i] > sar: up = True; sar = ep; ep = h[i]; af = af0
            elif l[i] < ep: ep = l[i]; af = min(af + af0, afmax)
        bull[i] = up
    return bull

def rsi(c, n=14):
    d = np.diff(c, prepend=c[0]); up = pd.Series(np.maximum(d, 0)).ewm(alpha=1 / n, adjust=False).mean(); dn = pd.Series(np.maximum(-d, 0)).ewm(alpha=1 / n, adjust=False).mean()
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(50).values

cand = []
for f in sorted(glob.glob('/home/claude/opt/picked/*.parquet')):
    e = f.split('/')[-1][:-8]; X = pd.read_parquet(f); exp_close = np.datetime64(pd.Timestamp(e) + pd.Timedelta(minutes=915))
    for (K, r), g in X.groupby(['strike', 'right']):
        wd = watch.get((e, K, r))
        if not wd: continue
        days = np.sort(g.date.unique()); fi = np.searchsorted(days, np.datetime64(first[(e, K, r)])); g = g[g.date >= days[max(0, fi - 3)]].reset_index(drop=True)
        if len(g) < 200: continue
        dt = g.datetime.values; op = g.open.values.astype(float); lo1 = g.low.values.astype(float); hi1 = g.high.values.astype(float); cl1 = g.close.values.astype(float)
        dts = pd.to_datetime(dt); dday = dts.normalize().values; tod = (dts.hour * 60 + dts.minute).values
        B15 = agg(g, 15); B5 = agg(g, 5); c15 = B15.close.values; ct15 = B15.ct.values; ct5 = B5.ct.values
        # 15-min exit states
        ema = pd.Series(c15).ewm(span=20, adjust=False).mean().values
        tr = np.maximum.reduce([B15.high - B15.low, (B15.high - B15.close.shift()).abs(), (B15.low - B15.close.shift()).abs()]); tr = np.nan_to_num(np.asarray(tr, float))
        atr22 = pd.Series(tr).ewm(alpha=1 / 22, adjust=False).mean().values; ll22 = pd.Series(B15.low).rolling(22, min_periods=1).min().values
        state = dict(ema20=c15 > ema, chandelier=c15 > ll22 + 3 * atr22, psar=psar_bull(B15.high.values, B15.low.values), rsi30=rsi(c15) < 30)
        s5 = M.structure_1m(B5[['open', 'high', 'low', 'close']], 3); ch5 = ct5[s5['ev'] > 0]
        bear5 = ct5[s5['ev'] < 0]
        s1 = M.structure_1m(g[['open', 'high', 'low', 'close']].astype(float), 5); bear1 = dt[s1['ev'] < 0] + np.timedelta64(1, 'm')     # 1-min bar closes 1 min after its start
        for (p, m) in ((4, 3.0), (10, 3.0)):
            d15 = st_dir(B15, p, m); flip = np.r_[0, np.diff(d15.astype(int))]
            st_up_t = ct15[flip > 0]
            # ST state at an arbitrary time t = dir of the last 15-min bar with ct <= t
            def st_at(t): j = np.searchsorted(ct15, t, side='right') - 1; return d15[j] if j >= 0 else 0
            sig = {'none': ct15[flip < 0], '5m': bear5, '1m': bear1}
            ex_t = {'st_up': st_up_t, 'choch5_up': ch5}
            for k_, s_ in state.items(): ex_t[k_] = ct15[s_]
            for conf, times in sig.items():
                for t in times:
                    tt = pd.Timestamp(t); dd = tt.normalize(); tdm = tt.hour * 60 + tt.minute
                    if dd not in wd or not (560 <= tdm <= 900): continue
                    if conf != 'none' and st_at(t) != -1: continue
                    i0 = np.searchsorted(dt, t)
                    if i0 >= len(dt) or dday[i0] != np.datetime64(dd) or op[i0] < 2: continue
                    entry = op[i0]
                    for ex in EXITS:
                        base = 'st_up' if ex in ('tgt50', 'rsi30') else ex
                        nx = ex_t[base]; nx = nx[nx > t]; tx = min(nx[0] if len(nx) else np.datetime64('2100-01-01'), exp_close); why = ex if tx < exp_close else 'expiry'
                        if ex == 'rsi30':
                            nr = ex_t['rsi30']; nr = nr[nr > t]
                            if len(nr) and nr[0] < tx: tx = nr[0]; why = 'rsi30 target'
                        i1 = min(np.searchsorted(dt, tx), len(dt) - 1)
                        px = op[i1] if dt[i1] >= tx else cl1[i1]
                        if ex == 'tgt50':
                            tg = 0.5 * entry; hit = np.flatnonzero(lo1[i0:i1 + 1] <= tg)
                            if len(hit): j = i0 + hit[0]; i1 = j; px = min(op[j], tg); why = 'tgt50 target'
                        c = costs(entry, px, -1)
                        cand.append((tuple(sorted(wd[dd])), f'15m ST({p},{m:g})', conf, ex, r, tt, e, K, pd.Timestamp(dt[i0]), pd.Timestamp(dt[i1]), entry, px, why,
                                     (entry - px) * LOT - c, -(hi1[i0:i1 + 1].max() - entry) * LOT))
    del X; gc.collect(); print(e, len(cand), f'{time.time()-t0:.0f}s', flush=True)
C = pd.DataFrame(cand, columns=['picks', 'st', 'conf', 'exit_rule', 'right', 'sig', 'expiry', 'strike', 'entry_time', 'exit_time', 'entry', 'exit', 'why', 'net', 'worst_open'])
C.to_pickle('/home/claude/bt/possell/conf_candidates.pkl'); print('candidates', len(C), f'{time.time()-t0:.0f}s')
