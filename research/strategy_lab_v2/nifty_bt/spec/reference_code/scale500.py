import pickle, numpy as np, pandas as pd, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
pd.set_option('display.width', 250)
L5 = pickle.load(open('possell/lock50_books.pkl', 'rb')); BB = pickle.load(open('possell/buy_books.pkl', 'rb')); IB = pickle.load(open('possell/igrid_books.pkl', 'rb'))
PORTS = {'Positional ₹500+ SELL + BUY': [(L5[('p500up', '15m ST(4,3)', '5m', 'st_up')], -1), (BB[('p500up', '15m ST(4,3)', '5m', 'st_dn', 'lock_exp')], 1)],
         'Intraday ₹500+ SELL + BUY': [(IB[('p500up', 'SELL', '15m ST(10,3)', '5m', 'chandelier', 'none', 'chop')], -1), (IB[('p500up', 'BUY', '15m ST(10,3)', '5m', 'chandelier', 'lock40', 'chop')], 1)]}
FIXED = 40 * 1.18                       # brokerage + GST per round trip: per order, does not grow with lots
SHORT_MARGIN = 200000                   # assumed margin per short lot (deep-ITM NIFTY option ≈ futures margin, 2025-26 levels)
rows = []; curves = {}
for name, parts in PORTS.items():
    T = pd.concat([p.assign(side=s) for p, s in parts], ignore_index=True).sort_values('exit_time')
    ev = []
    for _, r in T.iterrows():
        ev += [(r.entry_time, 1, r.side, r.entry), (r.exit_time, -1, r.side, r.entry)]
    ev.sort(key=lambda z: (z[0], z[1]))
    ns = nl = 0; prem = 0.0; pk_s = pk_l = pk_prem = 0
    for t, k, s, e in ev:
        if s < 0: ns += k
        else: nl += k; prem += k * e * 75
        pk_s = max(pk_s, ns); pk_l = max(pk_l, nl); pk_prem = max(pk_prem, prem)
    yrs = (T.exit_time.max() - T.entry_time.min()).days / 365.25
    for N in (1, 2, 5, 10):
        for slip in (0.10, 1.0, 2.0):
            net_t = N * (T.net + FIXED) - FIXED - N * 75 * 2 * (slip - 0.10)
            eq = net_t.cumsum(); dd = (eq - eq.cummax()).min(); yr = net_t.groupby(T.year).sum()
            cap = N * (pk_s * SHORT_MARGIN + pk_prem) + 1.5 * abs(dd)
            rows.append(dict(portfolio=name, lots_per_leg=N, slip_per_side=slip, net=round(net_t.sum()), per_year=round(net_t.sum() / yrs), maxDD=round(dd), worst_year=round(yr.min()),
                             peak_shorts=pk_s * N, peak_longs=pk_l * N, capital=round(cap), ret_on_cap_pa=round(net_t.sum() / yrs / cap * 100, 1), ret_dd=round(net_t.sum() / -dd, 1)))
            if slip == 0.10: curves[(name, N)] = (T.exit_time.values, eq.values)
S = pd.DataFrame(rows); S.to_csv('possell/scale500.csv', index=False)
for name in PORTS:
    x = S[S.portfolio == name]; print(f'\n== {name} =='); print(x.drop(columns='portfolio').to_string(index=False))
INK, GRID, AXIS = '#2b2b2b', '#e1e0d9', '#c3c2b7'; cols = {1: '#8a8984', 2: '#2a78d6', 5: '#1baf7a', 10: '#9b5de5'}
fig, ax = plt.subplots(1, 2, figsize=(17, 5.8), dpi=120)
for a, name in zip(ax, PORTS):
    for N in (1, 2, 5, 10):
        t, eq = curves[(name, N)]; r = S[(S.portfolio == name) & (S.lots_per_leg == N) & (S.slip_per_side == 0.10)].iloc[0]; r2 = S[(S.portfolio == name) & (S.lots_per_leg == N) & (S.slip_per_side == 2.0)].iloc[0]
        a.plot(t, eq / 1e5, color=cols[N], lw=1.8, label=f'{N} lot/leg: {r.net/1e5:+.1f} L (₹2 slip {r2.net/1e5:+.1f} L) · DD {r.maxDD/1e5:.1f} L · capital ≈ ₹{r.capital/1e5:.1f} L · {r.ret_on_cap_pa:.0f}%/yr')
    a.axhline(0, color=AXIS, lw=0.8); a.legend(frameon=False, fontsize=7.8, loc='upper left'); a.set_title(name, loc='left', fontsize=10, color=INK)
    for s in ('top', 'right'): a.spines[s].set_visible(False)
    a.spines['left'].set_color(AXIS); a.spines['bottom'].set_color(AXIS); a.grid(axis='y', color=GRID, lw=0.6); a.set_axisbelow(True); a.tick_params(labelsize=8, colors=INK)
fig.suptitle('₹500+ option strategies scaled up · cumulative net ₹ lakh · capital = peak short margin (₹2 L/lot assumed) + peak long premium + 1.5× max drawdown', x=0.01, ha='left', fontsize=10, color=INK)
fig.tight_layout(rect=(0, 0, 1, 0.94)); fig.savefig('possell/scale500.png')
