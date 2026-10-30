import pickle, numpy as np, pandas as pd, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
pd.set_option('display.width', 250)
SL = pickle.load(open('possell/p100_sell_lock.pkl', 'rb')); L5 = pickle.load(open('possell/lock50_books.pkl', 'rb')); BB = pickle.load(open('possell/buy_books.pkl', 'rb'))
books = {'₹100+ SELL': SL['tgt50'], '₹100+ BUY': BB[('p100', '15m ST(4,3)', '5m', 'st_dn', 'lock_exp')],
         '₹500+ SELL': L5[('p500up', '15m ST(4,3)', '5m', 'st_up')], '₹500+ BUY': BB[('p500up', '15m ST(4,3)', '5m', 'st_dn', 'lock_exp')]}
Y = pd.DataFrame({k: v.groupby(v.entry_time.dt.year).net.sum() for k, v in books.items()}).fillna(0)
Y['₹100+ SELL+BUY'] = Y['₹100+ SELL'] + Y['₹100+ BUY']; Y['₹500+ SELL+BUY'] = Y['₹500+ SELL'] + Y['₹500+ BUY']
Y.loc['Total'] = Y.sum(); print((Y / 1e3).round(0).astype(int).to_string())
# buy-only yearly incl. the ₹750 and the normal-exit versions
BY = pd.DataFrame({lab: BB[k].groupby(BB[k].entry_time.dt.year).net.sum() for lab, k in (
    ('₹100+ BUY normal exit', ('p100', '15m ST(4,3)', '5m', 'st_dn', 'normal')), ('₹100+ BUY lock→expiry', ('p100', '15m ST(4,3)', '5m', 'st_dn', 'lock_exp')),
    ('₹500+ BUY lock→expiry', ('p500up', '15m ST(4,3)', '5m', 'st_dn', 'lock_exp')), ('₹500+ BUY lock+2x', ('p500up', '15m ST(4,3)', '5m', 'st_dn', 'lock_2x')),
    ('~₹750 BUY lock+2x', ('p750', '15m ST(10,3)', '5m', 'st_dn', 'lock_2x')))}).fillna(0)
cnt = pd.DataFrame({lab: BB[k].groupby(BB[k].entry_time.dt.year).size() for lab, k in (('₹100+ trades', ('p100', '15m ST(4,3)', '5m', 'st_dn', 'lock_exp')),)})
BY.loc['Total'] = BY.sum(); print('\nBUY yearly (₹ thousand):'); print((BY / 1e3).round(0).astype(int).join(cnt).to_string())
BY.to_csv('possell/buy_yearly.csv'); Y.to_csv('possell/combo_yearly.csv')
rows = []
for name, parts in (('₹100+ SELL+BUY', ['₹100+ SELL', '₹100+ BUY']), ('₹500+ SELL+BUY', ['₹500+ SELL', '₹500+ BUY'])):
    T = pd.concat([books[p].assign(book=p) for p in parts]).sort_values('exit_time'); eq = T.net.cumsum()
    ev = pd.concat([pd.Series(1, index=T.entry_time), pd.Series(-1, index=T.exit_time)]).sort_index(kind='stable'); conc = ev.cumsum()
    m = pd.Series(T.net.values, index=T.exit_time).resample('ME').sum()
    rows.append(dict(portfolio=name, trades=len(T), net=round(T.net.sum()), maxDD=round((eq - eq.cummax()).min()),
                     single_DDs=' / '.join(f"{p}: {round(((books[p].net.cumsum()) - books[p].net.cumsum().cummax()).min()/1e3)}k" for p in parts),
                     yrs_pos=f"{(Y.loc[Y.index != 'Total', name] > 0).sum()}/9", months_pos=round((m > 0).mean(), 2), max_open_positions=int(conc.max()),
                     corr_monthly=round(pd.concat([pd.Series(books[p].net.values, index=books[p].exit_time).resample('ME').sum() for p in parts], axis=1).fillna(0).corr().iloc[0, 1], 2)))
    books[name] = T
R = pd.DataFrame(rows); print('\n', R.to_string(index=False)); R.to_csv('possell/combo_summary.csv', index=False)
INK, GRID, AXIS, ORANGE, BLUE, PURPLE = '#2b2b2b', '#e1e0d9', '#c3c2b7', '#eb6834', '#2a78d6', '#9b5de5'
fig, ax = plt.subplots(1, 2, figsize=(17, 5.8), dpi=120)
for a, nm in zip(ax, ('₹100+', '₹500+')):
    for k, col, lw in ((f'{nm} SELL', ORANGE, 1.4), (f'{nm} BUY', BLUE, 1.4), (f'{nm} SELL+BUY', PURPLE, 2.2)):
        T = books[k].sort_values('exit_time'); eq = T.net.cumsum()
        a.plot(T.exit_time, eq / 1e5, color=col, lw=lw, label=f'{k}: {T.net.sum()/1e5:+.2f} L · DD {(eq - eq.cummax()).min()/1e5:.2f} L')
    a.axhline(0, color=AXIS, lw=0.8); a.legend(frameon=False, fontsize=8.5, loc='upper left')
    a.set_title(f'{nm} options · 15m ST(4,3) + 5m BOS/CHoCH · ST exit · +50 lock', loc='left', fontsize=9.5, color=INK)
    for s in ('top', 'right'): a.spines[s].set_visible(False)
    a.spines['left'].set_color(AXIS); a.spines['bottom'].set_color(AXIS); a.grid(axis='y', color=GRID, lw=0.6); a.set_axisbelow(True); a.tick_params(labelsize=8, colors=INK)
fig.suptitle('Sell and buy run together, separate lots (1 lot each for sell-CE, sell-PE, buy-CE, buy-PE) · cumulative net ₹ lakh', x=0.01, ha='left', fontsize=10.5, color=INK)
fig.text(0.01, 0.01, 'Sell: premium ST down + bearish 5m break; Buy: premium ST up + bullish 5m break. Lock: 50 pts in profit → stop at entry, normal exit ignored (sell: till expiry or premium ₹50; buy: till expiry).', fontsize=8, color=INK)
fig.tight_layout(rect=(0, 0.03, 1, 0.95)); fig.savefig('possell/combo.png')
