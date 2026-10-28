"""Positional option SELLING with Supertrend on the option premium chart itself.
Watch list: each session D, the ATM CE and ATM PE of the front expiry (strike = 09:15 5-min close rounded to 50, known 09:20).
Signal: Supertrend(p, m) on that contract's own premium bars (15-min or 60-min, continuous across days). When it turns DOWN
(bar close) on a watched contract at or after 09:20 and no later than 15:00 -> SELL 1 lot at the next 1-min open.
Hold overnight on that same contract until ITS Supertrend turns UP (exit at the next 1-min open) or 15:15 on expiry day.
One position per leg (CE leg, PE leg independent). Charges per trade incl. Rs 0.10 slippage/side; lot 75."""
import sys, pickle, itertools; sys.path.insert(0, '/home/claude/bt')
import numpy as np, pandas as pd
from mtf_st import st_dir
from opt_sim import costs
LOT = 75
O = pd.read_parquet('/home/claude/opt/atm_1min_all.parquet')
O['tod'] = O.datetime.dt.hour * 60 + O.datetime.dt.minute
watch = O[O.is_trade][['date', 'expiry', 'strike', 'right']].drop_duplicates()
W = set(map(tuple, watch.values.tolist()))                                    # (date, expiry, strike, right)

def contract_events(g, tf, p, m):
    g = g.sort_values('datetime').reset_index(drop=True)
    k = ((g.tod - 555) // tf).clip(lower=0)
    g['bk'] = g.date + pd.to_timedelta(555 + k * tf, unit='m')
    B = g.groupby('bk').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'), close=('close', 'last'), last_dt=('datetime', 'last')).reset_index()
    d = st_dir(B, p, m); flip = np.r_[0, np.diff(d.astype(int))]
    B['close_time'] = B.last_dt + pd.Timedelta(minutes=1)                    # bar is complete at this time
    return g, B.assign(dir=d, flip=flip)

def run(tf, p, m):
    out = []
    for right in ('CE', 'PE'):
        ents = []; C = {}
        for (e, K), g in O[O.right == right].groupby(['expiry', 'strike']):
            g1, B = contract_events(g, tf, p, m); C[(e, K)] = (g1, B)
            dn = B[B.flip < 0]
            for _, r in dn.iterrows():
                t = r.close_time; d = t.normalize(); tod = t.hour * 60 + t.minute
                if (d, e, K, right) in W and 560 <= tod <= 900: ents.append((t, e, K))
        ents.sort(); free_at = pd.Timestamp('1900-01-01')
        for t, e, K in ents:
            if t < free_at: continue
            g1, B = C[(e, K)]; dt = g1.datetime.values
            i0 = np.searchsorted(dt, np.datetime64(t));
            if i0 >= len(g1) or g1.date.iloc[i0] != t.normalize(): continue
            entry = g1.open.iloc[i0]
            if entry < 2: continue
            up = B[(B.flip > 0) & (B.close_time > t)].close_time
            t_up = up.iloc[0] if len(up) else pd.Timestamp('2100-01-01')
            exp_close = pd.Timestamp(e) + pd.Timedelta(minutes=915)
            t_x = min(t_up, exp_close); why = 'ST turned up' if t_up < exp_close else 'expiry 15:15'
            i1 = np.searchsorted(dt, np.datetime64(t_x)); i1 = min(i1, len(g1) - 1)
            px = g1.open.iloc[i1] if g1.datetime.iloc[i1] >= t_x else g1.close.iloc[i1]
            pts = entry - px; cost = costs(entry, px, -1)
            mae = g1.high.iloc[i0:i1 + 1].max() - entry
            out.append(dict(right=right, expiry=e, strike=K, entry_time=g1.datetime.iloc[i0], exit_time=g1.datetime.iloc[i1], entry=entry, exit=px, why=why, pts=pts,
                            cost=cost, net=pts * LOT - cost, worst_open_loss=-mae * LOT, nights=(g1.date.iloc[i1] - g1.date.iloc[i0]).days > 0,
                            dte_entry=g1.dte.iloc[i0]))
            free_at = g1.datetime.iloc[i1]
    T = pd.DataFrame(out); T['year'] = T.entry_time.dt.year; return T

def straddle_baseline():
    x = O[O.is_trade]; rows = []
    for (d, right), g in x.groupby(['date', 'right']):
        a = g[g.tod == 560]; z = g[g.tod == 915]
        if len(a) and len(z):
            e, px = a.open.iloc[0], z.open.iloc[0]; c = costs(e, px, -1); rows.append(dict(date=d, right=right, net=(e - px) * LOT - c, year=d.year, expiry_day=g.dte.iloc[0] == 0))
    return pd.DataFrame(rows)

if __name__ == '__main__':
    res = {}
    for tf, (p, m) in itertools.product((15, 60), ((10, 3.0), (7, 2.0), (4, 3.0))):
        T = run(tf, p, m); res[(tf, p, m)] = T
        print(f'{tf}m ST({p},{m:g}) trades {len(T)} net {T.net.sum():+,.0f}  CE {T[T.right=="CE"].net.sum():+,.0f} PE {T[T.right=="PE"].net.sum():+,.0f}', flush=True)
    S = straddle_baseline(); res['baseline'] = S; print('baseline intraday ATM straddle sell 09:20->15:15:', round(S.net.sum()), 'days', S.date.nunique())
    pickle.dump(res, open('possell/books.pkl', 'wb'))
