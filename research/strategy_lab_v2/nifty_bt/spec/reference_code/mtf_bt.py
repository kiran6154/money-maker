"""Multi-timeframe intraday NIFTY strategy (no look-ahead), futures 1 lot, 2018 -> Oct 2026.

Trend filter (higher timeframe): pivots on 5-min and/or 15-min bars. Regime from the last two confirmed swing highs/lows:
    UP = higher highs and higher lows, DOWN = lower highs and lower lows, else SIDEWAYS (no trade).
    A 1-min bar may only use 5-/15-min bars that have CLOSED by the end of that 1-min bar.
Entry (1-min): a CHoCH or BOS on the 1-min chart in the direction of the higher-timeframe trend
    (BOS = continuation break of the last 1-min swing; CHoCH = first break against the 1-min trend, i.e. the end of a 1-min
    pullback against the higher-timeframe trend). Signal on the 1-min close, fill at the next 1-min open + 1 pt slippage.
Stop: the protective 1-min swing (last swing low for a long / high for a short); trades whose risk is under 10 points are
    skipped (round-trip costs are ~9 points). Stop fills at the worse of bar open / stop.
Trailing: once open profit reaches +1R (best price reached), the stop moves to break-even and the trailing exit takes over:
    ema9 / ema20  - exit at the next open after a 1-min close beyond the EMA
    chandelier    - stop ratchets to (highest high since entry - 3 x ATR14) for a long (mirror for a short)
    supertrend    - exit at the next open after the 1-min Supertrend(10, 3) flips against the trade
    swing         - stop ratchets to each newly confirmed 1-min swing in the trade direction
    R2            - reference: fixed target at 2R, no trailing
Session: entries 09:30-14:45, one position at a time, flat at the 15:15 open (or the day's last bar).
Costs: lot 75, ₹20/order, STT 0.02% sell, NSE, SEBI, stamp, GST (≈ ₹500/round trip) + slippage 1 pt per side.
"""
import sys, os, time, json, pickle
import numpy as np, pandas as pd
sys.path.insert(0, '/home/claude/tt')
from tt_backtest import fut_costs
LOT = 75; OUT = '/home/claude/bt/mtf'; os.makedirs(OUT, exist_ok=True)


def pivots(h, l, N):
    H = pd.Series(h); L = pd.Series(l)
    lh = H.shift(1).rolling(N).max().values; rh = H[::-1].shift(1).rolling(N).max()[::-1].values
    ll = L.shift(1).rolling(N).min().values; rl = L[::-1].shift(1).rolling(N).min()[::-1].values
    return (h > lh) & (h >= rh), (l < ll) & (l <= rl)


def regime_series(b, N):
    """+1 UP, -1 DOWN, 0 SIDEWAYS/none at the close of each bar (swings confirmed N bars later)."""
    h, l = b.high.values, b.low.values; ph, pl = pivots(h, l, N); n = len(h)
    sh, sl = [], []; out = np.zeros(n, dtype=np.int8)
    for i in range(n):
        p = i - N
        if p >= 0:
            if ph[p]: sh.append(h[p])
            if pl[p]: sl.append(l[p])
        if len(sh) >= 2 and len(sl) >= 2:
            out[i] = 1 if (sh[-1] > sh[-2] and sl[-1] > sl[-2]) else -1 if (sh[-1] < sh[-2] and sl[-1] < sl[-2]) else 0
    return out


def map_htf(m1_dt, htf, reg, minutes):
    """For each 1-min bar (start t, closes t+1) the regime of the last HTF bar that closed by t+1 (start <= t+1-minutes)."""
    key = pd.DataFrame({'k': (m1_dt + pd.Timedelta(minutes=1 - minutes)).values.astype('datetime64[ns]')})
    H = pd.DataFrame({'k': pd.to_datetime(htf.datetime).values.astype('datetime64[ns]'), 'r': reg})
    m = pd.merge_asof(key.reset_index().sort_values('k'), H.sort_values('k'), on='k', direction='backward').sort_values('index')
    r = m.r.fillna(0).values.astype(np.int8)
    # never carry a regime across days: only HTF bars of the same session count
    hd = pd.merge_asof(key.reset_index().sort_values('k'), pd.DataFrame({'k': H.k, 'hd': pd.to_datetime(H.k).dt.normalize()}).sort_values('k'), on='k', direction='backward').sort_values('index').hd.values
    return r, hd


def load_1m():
    r = pd.read_parquet('/home/claude/idx/nifty_1min_raw.parquet')
    r['tod'] = r.datetime.dt.hour * 60 + r.datetime.dt.minute
    r = r[(r.tod >= 555) & (r.tod <= 929)]
    r = r[~((r.date >= pd.Timestamp('2026-08-03')) & (r.tod >= 915))].sort_values('datetime').reset_index(drop=True)
    days = r.groupby('date').size(); r = r[r.date.isin(days[days >= 300].index)].reset_index(drop=True)
    return r


def indicators(b):
    c = b.close.values; h = b.high.values; l = b.low.values
    ema9 = pd.Series(c).ewm(span=9, adjust=False).mean().values; ema20 = pd.Series(c).ewm(span=20, adjust=False).mean().values
    tr = np.maximum.reduce([h - l, np.abs(h - np.r_[c[0], c[:-1]]), np.abs(l - np.r_[c[0], c[:-1]])])
    atr14 = pd.Series(tr).ewm(alpha=1 / 14, adjust=False).mean().values; atr10 = pd.Series(tr).ewm(alpha=1 / 10, adjust=False).mean().values
    hl2 = (h + l) / 2; ub = hl2 + 3 * atr10; lb = hl2 - 3 * atr10; n = len(c)
    fu = ub.copy(); fl = lb.copy(); st_dir = np.ones(n, dtype=np.int8)
    for i in range(1, n):
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or c[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or c[i - 1] < fl[i - 1]) else fl[i - 1]
        st_dir[i] = 1 if c[i] > fu[i - 1] else -1 if c[i] < fl[i - 1] else st_dir[i - 1]
    return dict(ema9=ema9, ema20=ema20, atr14=atr14, st_dir=st_dir)


def structure_1m(b, N):
    h, l, c = b.high.values, b.low.values, b.close.values; ph, pl = pivots(h, l, N); n = len(c)
    ev = np.zeros(n, dtype=np.int8); last_sl = np.full(n, np.nan); last_sh = np.full(n, np.nan)
    new_sl = np.full(n, np.nan); new_sh = np.full(n, np.nan)
    top = bot = np.nan; tx = bx = True; trend = 0; s_l = s_h = np.nan
    for i in range(n):
        p = i - N
        if p >= 0:
            if ph[p]: top = h[p]; tx = False; s_h = h[p]; new_sh[i] = h[p]
            if pl[p]: bot = l[p]; bx = False; s_l = l[p]; new_sl[i] = l[p]
        if not tx and c[i] > top: ev[i] = 1 if trend == 1 else 2; tx = True; trend = 1
        if not bx and c[i] < bot: ev[i] = -1 if trend == -1 else -2; bx = True; trend = -1
        last_sl[i] = s_l; last_sh[i] = s_h
    return dict(ev=ev, last_sl=last_sl, last_sh=last_sh, new_sl=new_sl, new_sh=new_sh)


def simulate(b, ind, st, htf_reg, sig, exit_mode, act_R=1.0, min_risk=10.0):
    o, h, l, c = b.open.values, b.high.values, b.low.values, b.close.values
    tod = b.tod.values; day = b.date.values; n = len(c)
    last_of_day = np.r_[day[1:] != day[:-1], True]
    ev = st['ev']; ema = ind['ema9'] if exit_mode == 'ema9' else ind['ema20']; atr = ind['atr14']; sdir = ind['st_dir']
    trades = []; pos = 0; pend = None; exit_next = False
    for i in range(n):
        if pend is not None:
            d, stp = pend; pend = None
            if pos == 0 and i > 0 and day[i] == day[i - 1] and tod[i] <= 885:
                e = o[i] + d; risk = (e - stp) * d
                if risk >= min_risk:
                    pos = d; entry = e; stop = stp; risk0 = risk; ebar = i; active = False; best = e
                    tgt = e + d * 2 * risk if exit_mode == 'R2' else np.nan
        if pos != 0:
            why = None
            if exit_next: px = o[i] - pos; why = 'trail exit'; exit_next = False
            elif tod[i] >= 915: px = o[i] - pos; why = 'eod'
            elif (pos > 0 and l[i] <= stop) or (pos < 0 and h[i] >= stop):
                px = (min(o[i], stop) if pos > 0 else max(o[i], stop)) - pos; why = 'trail stop' if active else 'stop'
            elif exit_mode == 'R2' and ((pos > 0 and h[i] >= tgt) or (pos < 0 and l[i] <= tgt)):
                px = max(o[i], tgt) if pos > 0 else min(o[i], tgt); why = 'target'
            elif last_of_day[i]: px = c[i] - pos; why = 'eod'
            if why:
                pts = pos * (px - entry); cost = fut_costs(entry, px, pos, slip_pts=0.0)
                trades.append(dict(entry_time=b.datetime.iloc[ebar], exit_time=b.datetime.iloc[i], dir=pos, entry=entry, exit=px, risk=risk0, why=why,
                                   R=pts / risk0, pts=pts, gross=pts * LOT, cost=cost, net=pts * LOT - cost, mins=i - ebar, active=active))
                pos = 0
            else:
                best = max(best, h[i]) if pos > 0 else min(best, l[i])
                if not active and (best - entry) * pos >= act_R * risk0:
                    active = True
                    if exit_mode != 'R2': stop = max(stop, entry) if pos > 0 else min(stop, entry)
                if active and exit_mode != 'R2':
                    if exit_mode in ('ema9', 'ema20') and (c[i] - ema[i]) * pos < 0: exit_next = True
                    elif exit_mode == 'supertrend' and sdir[i] * pos < 0: exit_next = True
                    elif exit_mode == 'chandelier':
                        ns = best - pos * 3 * atr[i]
                        if (ns - stop) * pos > 0: stop = ns
                    elif exit_mode == 'swing':
                        ns = st['new_sl'][i] if pos > 0 else st['new_sh'][i]
                        if not np.isnan(ns) and (ns - stop) * pos > 0: stop = ns
                if last_of_day[i] and pos != 0 and not exit_next: pass
        # new entry signal on this bar's close
        e_ = ev[i]
        if e_ == 0 or pos != 0 or pend is not None or last_of_day[i] or not (569 <= tod[i] <= 884): continue
        d = 1 if e_ > 0 else -1; kind = 'BOS' if abs(e_) == 1 else 'CHoCH'
        if kind not in sig or htf_reg[i] != d: continue
        stp = st['last_sl'][i] if d > 0 else st['last_sh'][i]
        if not np.isnan(stp): pend = (d, stp)
    T = pd.DataFrame(trades)
    if len(T): T['year'] = pd.to_datetime(T.entry_time).dt.year
    return T


def stats(T, **k):
    if len(T) == 0: return dict(k, N=0)
    x = T.net; yr = T.groupby('year').net.sum(); g = x[x > 0].sum(); bl = -x[x < 0].sum()
    L = T[T.dir > 0].net; S = T[T.dir < 0].net
    return dict(k, N=len(T), per_day=round(len(T) / T.entry_time.dt.normalize().nunique(), 2), win=round((x > 0).mean(), 3), avgR=round(T.R.mean(), 3),
                net=round(x.sum()), PF=round(g / bl, 2) if bl else np.inf, t=round(x.mean() / x.std() * np.sqrt(len(x)), 2),
                maxDD=round((x.cumsum() - x.cumsum().cummax()).min()), years_pos=f'{(yr > 0).sum()}/{len(yr)}',
                long_N=len(L), long_net=round(L.sum()), short_N=len(S), short_net=round(S.sum()), cost=round(T.cost.sum()),
                by_year=' '.join(f'{y}:{v/1000:+.0f}k' for y, v in yr.items()))


if __name__ == '__main__':
    t0 = time.time()
    b = load_1m(); print('1-min bars', len(b), 'sessions', b.date.nunique(), f'[{time.time()-t0:.0f}s]', flush=True)
    ind = indicators(b)
    b5 = pd.read_parquet('/home/claude/tt/bars_5m.parquet'); b15 = pd.read_parquet('/home/claude/tt/bars_15m.parquet')
    for x in (b5, b15):
        x['tod'] = pd.to_datetime(x.datetime).dt.hour * 60 + pd.to_datetime(x.datetime).dt.minute
    b5 = b5[b5.tod < 930].reset_index(drop=True); b15 = b15[b15.tod < 930].reset_index(drop=True)
    R = {}
    for name, bb, mins, N in (('5m_N3', b5, 5, 3), ('5m_N5', b5, 5, 5), ('15m_N2', b15, 15, 2), ('15m_N3', b15, 15, 3)):
        reg = regime_series(bb, N); r, hd = map_htf(b.datetime, bb, reg, mins)
        r = np.where(pd.to_datetime(hd) == b.date.values, r, 0)          # same-session HTF bars only
        R[name] = r.astype(np.int8)
    print('regimes ready', {k: dict(zip(*np.unique(v, return_counts=True))) for k, v in R.items()}, f'[{time.time()-t0:.0f}s]', flush=True)
    HTF = {'5m': lambda a, c_: R[f'5m_N{a}'], '15m': lambda a, c_: R[f'15m_N{c_}'],
           'both': lambda a, c_: np.where(R[f'5m_N{a}'] == R[f'15m_N{c_}'], R[f'5m_N{a}'], 0)}
    rows = []; books = {}
    for N1 in (3, 5):
        st = structure_1m(b, N1)
        for (a5, a15) in ((3, 2), (5, 3)):
            for hname in ('5m', '15m', 'both'):
                reg = HTF[hname](a5, a15)
                for sig in (('BOS',), ('CHoCH',), ('BOS', 'CHoCH')):
                    for ex in ('R2', 'ema9', 'ema20', 'chandelier', 'supertrend', 'swing'):
                        T = simulate(b, ind, st, reg, sig, ex)
                        key = f"1m N={N1} | HTF {hname} (5m N={a5}, 15m N={a15}) | {'+'.join(sig)} | {ex}"
                        s = stats(T, key=key, N1=N1, htf=hname, htf_piv=f'5m N={a5}, 15m N={a15}', signals='+'.join(sig), exit=ex)
                        rows.append(s); books[key] = T
                        print(f"{key:70s} trades={s.get('N',0):5d} net={s.get('net',0):+11,} PF={s.get('PF')} t={s.get('t')} L={s.get('long_net',0):+,} S={s.get('short_net',0):+,}", flush=True)
    S = pd.DataFrame(rows); S.to_csv(f'{OUT}/summary.csv', index=False); pickle.dump(books, open(f'{OUT}/books.pkl', 'wb'))
    print('done', f'[{time.time()-t0:.0f}s]')
