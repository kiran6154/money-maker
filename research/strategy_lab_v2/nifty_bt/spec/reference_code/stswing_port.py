import pickle, numpy as np, pandas as pd, matplotlib, matplotlib.ticker; matplotlib.use('Agg'); import matplotlib.pyplot as plt
pd.set_option('display.width', 250)
B = pickle.load(open('possell/stswing_books.pkl', 'rb')); S = pd.read_csv('possell/stswing_summary.csv')
SL = pickle.load(open('possell/p100_sell_lock.pkl', 'rb'))['tgt50']; BB = pickle.load(open('possell/buy_books.pkl', 'rb'))
legs = {}
for pk in ('p100', 'p500up'):
    for md in ('positional', 'intraday'):
        for sd in ('SELL', 'BUY'):
            r = S[(S.pick == pk) & (S['mode'] == md) & (S.side == sd)].sort_values('train', ascending=False).iloc[0]   # chosen on 2018-22
            legs[(pk, md, sd)] = (f"{sd} · {r.st} · {r.signals} · {r.lock}{'' if r['filter'] == 'none' else ' · chop'}", B[(pk, sd, r.st, r.signals, md, r.lock, r['filter'])])
def stats(nm, T):
    T = T.sort_values('exit_time'); eq = T.net.cumsum(); yr = T.groupby('year').net.sum()
    return dict(book=nm, trades=len(T), win=round((T.net > 0).mean(), 2), net_L=round(T.net.sum() / 1e5, 2), maxDD_L=round((eq - eq.cummax()).min() / 1e5, 2),
                n18_22_L=round(T[T.year <= 2022].net.sum() / 1e5, 2), n23_26_L=round(T[T.year >= 2023].net.sum() / 1e5, 2), yrs_pos=f'{(yr > 0).sum()}/{len(yr)}',
                slip1_L=round((T.net.sum() - len(T) * 75 * 2 * 0.9) / 1e5, 2), by_year_k=' '.join(f'{k%100}:{v/1000:+.0f}' for k, v in yr.items()))
rows = []
for (pk, md, sd), (lab, T) in legs.items(): rows.append(stats(f'{pk} {md} {lab}', T))
ports = {}
for pk in ('p100', 'p500up'):
    for md in ('positional', 'intraday'):
        T = pd.concat([legs[(pk, md, 'SELL')][1], legs[(pk, md, 'BUY')][1]]); ports[(pk, md)] = T; rows.append(stats(f'PORTFOLIO {pk} {md} SELL+BUY', T))
old = pd.concat([SL, BB[('p100', '15m ST(4,3)', '5m', 'st_dn', 'lock_exp')]]); rows.append(stats('previous best: ₹100+ ST-flip + 5m confirm + lock SELL+BUY', old))
R = pd.DataFrame(rows); print(R.to_string(index=False)); R.to_csv('possell/stswing_portfolio.csv', index=False)
INK, GRID, AXIS = '#2b2b2b', '#e1e0d9', '#c3c2b7'
fig, ax = plt.subplots(1, 2, figsize=(17, 6), dpi=120)
for a, pk in zip(ax, ('p100', 'p500up')):
    for (md, sd), c, lw in ((('positional', 'SELL'), '#eb6834', 1.3), (('positional', 'BUY'), '#2a78d6', 1.3), (('intraday', 'SELL'), '#f2a07b', 1.0), (('intraday', 'BUY'), '#8fb8ea', 1.0)):
        lab, T = legs[(pk, md, sd)]; T = T.sort_values('exit_time'); a.plot(T.exit_time, T.net.cumsum() / 1e5, color=c, lw=lw, label=f'{md} {lab}: {T.net.sum()/1e5:+.2f} L')
    T = ports[(pk, 'positional')].sort_values('exit_time'); eq = T.net.cumsum(); a.plot(T.exit_time, eq / 1e5, color=INK, lw=2.4, label=f'positional SELL+BUY: {eq.iloc[-1]/1e5:+.2f} L · DD {(eq - eq.cummax()).min()/1e5:.2f} L')
    if pk == 'p100':
        T = old.sort_values('exit_time'); a.plot(T.exit_time, T.net.cumsum() / 1e5, color='#8a8984', lw=1.6, ls='--', label=f'previous best ₹100+ SELL+BUY: {T.net.sum()/1e5:+.2f} L')
    a.axhline(0, color=AXIS, lw=0.8); a.legend(frameon=False, fontsize=7.4, loc='upper left')
    a.set_title(f"{'₹100+ (≈ATM)' if pk == 'p100' else '₹500+ (deep ITM, illiquid)'} option chart · Supertrend-swing CHoCH/BOS", loc='left', fontsize=10, color=INK)
    a.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, p: f'₹{v:.0f} L'))
    for s in ('top', 'right'): a.spines[s].set_visible(False)
    a.spines['left'].set_color(AXIS); a.spines['bottom'].set_color(AXIS); a.grid(axis='y', color=GRID, lw=0.6); a.set_axisbelow(True); a.tick_params(labelsize=8, colors=INK)
fig.suptitle('Swing low = lowest low of each Supertrend-DOWN leg, swing high = highest high of each UP leg · break above high → BUY (SL swing low), below low → SELL (SL swing high), trail to new swings · 1 lot (75)/leg',
             x=0.01, ha='left', fontsize=9.5, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.94)); fig.savefig('possell/stswing.png')
