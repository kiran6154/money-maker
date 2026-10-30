"""Indicator STANDALONE on the option chart: VWAP Range Breakout computed on each ATM contract's own
5-min premium series; trades taken on the premium with the indicator's own geometry; P&L in rupees per
lot of 75 after real charges.

Sides:  d=+1  buy the option (long premium)      d=-1  sell the option (short premium)
Signal -> side mapping (as on any chart):  ▲ buy, ▼ sell, X-lower buy, X-upper sell, ◉up buy, ◉down sell,
retest-up buy, retest-down sell.
Entries at the detection bar's close, only on bars of the day the contract is the ATM chart, from the
09:20 bar on (the strike is chosen at 09:20 from the 09:15 spot bar).  Flat at the 15:20 bar close.
Stop filled at the worse of bar open / stop; stop before target if a bar touches both.
"""
import pandas as pd, numpy as np, sys
sys.path.insert(0, '/home/claude/bt')
from vrb import compute
import structure as st

LOT = 75

def costs(entry, exit_, d):
    """Round-trip charges in rupees for one lot. Buy side / sell side premiums depend on direction."""
    buy_px, sell_px = (entry, exit_) if d == 1 else (exit_, entry)
    turnover_buy = buy_px * LOT; turnover_sell = sell_px * LOT
    brokerage = 40.0                                   # Rs 20 per order x 2
    stt = 0.001 * turnover_sell                        # 0.1% on the sell-side premium (since Oct 2024)
    exch = 0.0003503 * (turnover_buy + turnover_sell)  # NSE options transaction charge
    sebi = 1e-6 * (turnover_buy + turnover_sell)
    stamp = 0.00003 * turnover_buy
    gst = 0.18 * (brokerage + exch + sebi)
    slip = 0.10 * LOT * 2                              # two ticks each way
    return brokerage + stt + exch + sebi + stamp + gst + slip


def simulate_contract(r, fam, gate=None, pref='s_', rr=2.0, stop_atr=0.25):
    """r: one contract's 5-min frame with indicator columns + is_trade + session info."""
    r = r.reset_index(drop=True)
    o, h, l, c = r.open.values, r.high.values, r.low.values, r.close.values
    mid, hi, lo, atr = r.mid.values, r.hi.values, r.lo.values, r.atr.values
    rngNew = r.rngNew.values; is_trade = r.is_trade.values; eod = r.eod.values; tod = r.tod.values
    if 'day_bars' in r.columns: is_trade = is_trade & (r.day_bars.values >= MIN_DAY_BARS)
    cov = r['cov'].values if 'cov' in r.columns else np.array(['full'] * len(r))
    brLvl = r.brLvl.values; hi_prev = np.roll(hi, 1); lo_prev = np.roll(lo, 1); dte_arr = r.dte.values
    if fam == 'arrow':   sig = np.where(r.buy.values, 1, np.where(r.sell.values, -1, 0))
    elif fam == 'arrowF': sig = np.where(r.buyF.values, 1, np.where(r.sellF.values, -1, 0))
    elif fam == 'fakeout': sig = np.where(r.failDn.values, 1, np.where(r.failUp.values, -1, 0))
    elif fam == 'breakout': sig = np.where(r.brUp.values, 1, np.where(r.brDn.values, -1, 0))
    elif fam == 'retest': sig = np.where(r.retUp.values, 1, np.where(r.retDn.values, -1, 0))
    if gate is not None:
        lab = st.regime(pd.DataFrame({'s_trend': r[pref + 'trend'].values, 's_last': r[pref + 'last'].values, 's_chop': r[pref + 'chop'].values}))
        strend = r[pref + 'trend'].values
    tr = []; i = 0; n = len(r)
    while i < n:
        d = sig[i]
        if d == 0 or not is_trade[i] or tod[i] < 560 or np.isnan(mid[i]) or i > eod[i] - 3 or c[i] < 2.0:
            i += 1; continue
        if gate is not None and not gate(d, lab[i], strend[i], dte_arr[i]):
            i += 1; continue
        e = c[i]
        if fam in ('arrow', 'arrowF'):
            tgt = mid[i]; stp = lo[i] if d == 1 else hi[i]
        elif fam == 'fakeout':
            tgt = mid[i]; j = i - 1; ext = h[j] if d == -1 else l[j]
            while j > 0 and ((d == -1 and h[j] >= hi[i]) or (d == 1 and l[j] <= lo[i])):
                ext = max(ext, h[j]) if d == -1 else min(ext, l[j]); j -= 1
            stp = ext
        elif fam == 'breakout':
            lvl = hi_prev[i] if d == 1 else lo_prev[i]
            stp = lvl - stop_atr * atr[i] if d == 1 else lvl + stop_atr * atr[i]
            tgt = e + d * rr * abs(e - stp)
        elif fam == 'retest':
            lvl = brLvl[i]
            stp = min(l[i], lvl) - 0.5 * atr[i] if d == 1 else max(h[i], lvl) + 0.5 * atr[i]
            tgt = e + d * 2.0 * abs(e - stp)
        if d == 1 and stp < 0.05: stp = 0.05
        if (d == 1 and (tgt <= e or stp >= e)) or (d == -1 and (tgt >= e or stp <= e)):
            i += 1; continue
        j = i + 1; px = None; why = None
        while j < n:
            if d == 1:
                if l[j] <= stp: px = min(o[j], stp); why = 'stop'; break
                if h[j] >= tgt: px = tgt if o[j] < tgt else o[j]; why = 'target'; break
            else:
                if h[j] >= stp: px = max(o[j], stp); why = 'stop'; break
                if l[j] <= tgt: px = tgt if o[j] > tgt else o[j]; why = 'target'; break
            if fam in ('arrow', 'arrowF', 'fakeout') and rngNew[j]: px = c[j]; why = 'reset'; break
            if j >= eod[j]: px = c[j]; why = 'eod'; break
            j += 1
        if px is None: px = c[n - 1]; why = 'end'; j = n - 1
        pts = d * (px - e); cost = costs(e, px, d)
        tr.append(dict(entry_time=r.datetime[i], expiry=r.expiry[i], strike=int(r.strike[i]), right=r.right[i], dir=d, entry=e, exit=px, exit_time=r.datetime[j],
                       reason=why, pts=pts, gross=pts * LOT, cost=cost, net=pts * LOT - cost, target=tgt, stop=stp, bars=j - i, dte=int(r.dte[i]),
                       state=(lab[i] if gate is not None else ''), cov=cov[i]))
        i = j + 1
    return pd.DataFrame(tr)


MIN_DAY_BARS = 60   # a trade day needs at least 60 of the 75 five-minute bars (drops Muhurat / Saturday / circuit-halt sessions)


def prepare(N_struct=10, src='/home/claude/opt/atm_5min.parquet', dst='/home/claude/opt/atm_ind.parquet'):
    O = pd.read_parquet(src)
    O['tod'] = O.datetime.dt.hour * 60 + O.datetime.dt.minute
    if 'cov' not in O.columns: O['cov'] = 'full'
    frames = []
    for (e, k, rt), g in O.groupby(['expiry', 'strike', 'right'], sort=False):
        g = g.sort_values('datetime').reset_index(drop=True)
        if len(g) < 120: continue
        r = compute(g[['datetime', 'open', 'high', 'low', 'close']])
        for col in ('expiry', 'strike', 'right', 'is_trade', 'dte', 'tod', 'date', 'cov'): r[col] = g[col].values
        # eod = index of the 15:20 bar of the same session (within this contract's frame)
        last = r[r.tod <= 15 * 60 + 20].groupby('date').apply(lambda x: x.index.max())
        r['eod'] = last.reindex(r.date).values
        r['day_bars'] = r.groupby('date').date.transform('size').values
        s = st.compute(r, N_struct)
        for col in s.columns: r[col] = s[col].values
        frames.append(r)
    R = pd.concat(frames, ignore_index=True)
    R.to_parquet(dst, index=False)
    return R


def stats(t, label):
    if len(t) == 0: return dict(book=label, N=0)
    x = t.net; g = x[x > 0].sum(); b = -x[x < 0].sum()
    wk = t.groupby(pd.to_datetime(t.entry_time).dt.to_period('W')).net.sum()
    dd = (x.cumsum() - x.cumsum().cummax()).min()
    return dict(book=label, N=len(t), gross=round(t.gross.sum()), cost=round(t.cost.sum()), net=round(x.sum()), avg_net=round(x.mean()), win=round((t.gross > 0).mean(), 3),
                PF=round(g / b, 2) if b > 0 else np.inf, t=round(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))), 2), worst=round(x.min()), worst_week=round(wk.min()),
                pos_weeks=round((wk > 0).mean(), 3), maxDD=round(dd), exits=t.reason.value_counts().to_dict())


if __name__ == '__main__':
    pd.set_option('display.width', 250); pd.set_option('display.max_columns', 40)
    R = prepare(10)
    print('contracts', R.groupby(['expiry', 'strike', 'right']).ngroups, 'bars', len(R), 'trade bars', int(R.is_trade.sum()))
    rows = []; books = {}
    for fam in ('arrow', 'arrowF', 'fakeout', 'breakout', 'retest'):
        parts = [simulate_contract(g, fam) for _, g in R.groupby(['expiry', 'strike', 'right'], sort=False)]
        t = pd.concat([p for p in parts if len(p)], ignore_index=True).sort_values('entry_time').reset_index(drop=True)
        books[fam] = t; t.to_csv(f'/home/claude/opt/trades_opt_{fam}.csv', index=False)
        for lab, sub in (('all', t), ('buy option', t[t.dir == 1]), ('sell option', t[t.dir == -1]), ('CE', t[t.right == 'CE']), ('PE', t[t.right == 'PE']),
                         ('ex expiry day', t[t.dte > 0]), ('expiry day only', t[t.dte == 0]), ('buy, ex expiry', t[(t.dir == 1) & (t.dte > 0)]), ('sell, ex expiry', t[(t.dir == -1) & (t.dte > 0)])):
            s = stats(sub, f'{fam} | {lab}'); rows.append(s)
            print(f"{s['book']:32s} N={s['N']:5d} gross={s.get('gross', 0):+9.0f} cost={s.get('cost', 0):7.0f} net={s.get('net', 0):+9.0f} avg={s.get('avg_net', 0):+6.0f} win={s.get('win', 0):.3f} PF={s.get('PF', 0)} t={s.get('t', 0)} maxDD={s.get('maxDD', 0)} posWk={s.get('pos_weeks', 0)}")
        print()
    pd.DataFrame(rows).to_csv('/home/claude/opt/opt_summary.csv', index=False)
