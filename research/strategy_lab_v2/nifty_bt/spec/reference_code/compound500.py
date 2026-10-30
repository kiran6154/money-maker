import pickle, numpy as np, pandas as pd, matplotlib, matplotlib.ticker; matplotlib.use('Agg'); import matplotlib.pyplot as plt
pd.set_option('display.width', 250)
L5 = pickle.load(open('possell/lock50_books.pkl', 'rb')); BB = pickle.load(open('possell/buy_books.pkl', 'rb'))
T = pd.concat([L5[('p500up', '15m ST(4,3)', '5m', 'st_up')].assign(side=-1), BB[('p500up', '15m ST(4,3)', '5m', 'st_dn', 'lock_exp')].assign(side=1)], ignore_index=True)
FIXED = 40 * 1.18; SLIP = 1.0
T['net1'] = T.net - 75 * 2 * (SLIP - 0.10)                     # per-lot net at ₹1 slippage (brokerage handled separately below)
CAP1 = 919483                                                   # capital per lot-per-leg at ₹1 slip (from scale500.csv)
MAXL = 10
ev = sorted([(r.entry_time, 1, i) for i, r in T.iterrows()] + [(r.exit_time, 0, i) for i, r in T.iterrows()], key=lambda z: (z[0], z[1]))
def run(rule):
    eq = CAP1; lots = 1; size = {}; hist = []
    for t, k, i in ev:
        if k == 1:                                             # entry: decide lots on realised equity
            if rule == 'fixed1': lots = 1
            elif rule == 'double_up':
                while lots * 2 <= MAXL and eq >= CAP1 * lots * 2: lots *= 2
            elif rule == 'double_updown':
                while lots * 2 <= MAXL and eq >= CAP1 * lots * 2: lots *= 2
                while lots > 1 and eq < CAP1 * lots: lots //= 2
            elif rule == 'add_one': lots = int(min(MAXL, max(1, eq // CAP1)))
            size[i] = lots
        else:
            n = size[i]; pnl = n * (T.at[i, 'net1'] + FIXED) - FIXED; eq += pnl; hist.append((t, eq, n, pnl))
    H = pd.DataFrame(hist, columns=['t', 'equity', 'lots', 'pnl']); return H
rows = []; Hs = {}
for rule, lab in (('fixed1', 'Fixed 1 lot'), ('double_up', 'Double lots when capital allows (never reduce)'), ('double_updown', 'Double when allowed, halve if equity falls short'), ('add_one', 'Add 1 lot whenever capital allows')):
    H = run(rule); Hs[lab] = H; dd = (H.equity - H.equity.cummax()); ddp = (H.equity / H.equity.cummax() - 1)
    yr = H.groupby(H.t.dt.year).agg(end=('equity', 'last'), lots=('lots', 'max')); start = CAP1
    first = {n: H.t[H.lots >= n].min() for n in (2, 4, 5, 8, 10)}
    rows.append(dict(rule=lab, start=CAP1, end_equity=round(H.equity.iloc[-1]), profit=round(H.equity.iloc[-1] - CAP1), CAGR=round(((H.equity.iloc[-1] / CAP1) ** (1 / 8.8) - 1) * 100, 1),
                     maxDD_rs=round(dd.min()), maxDD_pct=round(ddp.min() * 100, 1), final_lots=int(H.lots.iloc[-1]),
                     reached_2=str(first[2].date()) if pd.notna(first[2]) else '-', reached_4=str(first[4].date()) if pd.notna(first[4]) else '-', reached_8=str(first[8].date()) if pd.notna(first[8]) else '-',
                     reached_10=str(first[10].date()) if pd.notna(first[10]) else '-'))
    print('\n', lab); print(pd.DataFrame({'year_end_equity_L': (yr.end / 1e5).round(1), 'max_lots_in_year': yr.lots}).T.to_string())
R = pd.DataFrame(rows); RL = R.copy()
for c_ in ('start', 'end_equity', 'profit', 'maxDD_rs'): RL[c_] = (RL[c_] / 1e5).round(2)
RL = RL.rename(columns={'start': 'start_L', 'end_equity': 'end_equity_L', 'profit': 'profit_L', 'maxDD_rs': 'maxDD_L'}); print(RL.to_string(index=False)); RL.to_csv('possell/compound500.csv', index=False)
INK, GRID, AXIS = '#2b2b2b', '#e1e0d9', '#c3c2b7'; cols = ['#8a8984', '#2a78d6', '#1baf7a', '#9b5de5']
fig, ax = plt.subplots(2, 1, figsize=(14, 8.5), dpi=120, gridspec_kw=dict(height_ratios=[2.2, 1]), sharex=True)
for (lab, H), c in zip(Hs.items(), cols):
    r = R[R.rule == lab].iloc[0]; ax[0].plot(H.t, H.equity / 1e5, color=c, lw=2 if 'Double lots' in lab else 1.4, label=f'{lab}: ₹{r.end_equity/1e5:.1f} L · CAGR {r.CAGR}% · max DD ₹{-r.maxDD_rs/1e5:.1f} L ({r.maxDD_pct}%)')
    ax[1].step(H.t, H.lots, color=c, lw=1.4, where='post')
ax[0].set_ylabel('account equity (₹ lakh)', fontsize=8.5); ax[0].yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, p: f'₹{v:.0f} L'))
for (lab, H), c in zip(Hs.items(), cols): ax[0].text(H.t.iloc[-1], H.equity.iloc[-1] / 1e5, f' ₹{H.equity.iloc[-1]/1e5:.1f} L', color=c, fontsize=8.5, va='center'); ax[0].legend(frameon=False, fontsize=8.5, loc='upper left')
ax[0].set_title('Positional ₹500+ SELL + BUY · start ₹9.2 L (capital for 1 lot/leg) · ₹1 slippage/side · max 10 lots/leg', loc='left', fontsize=10, color=INK)
ax[1].set_ylabel('lots per leg', fontsize=8.5)
for a in ax:
    for s in ('top', 'right'): a.spines[s].set_visible(False)
    a.spines['left'].set_color(AXIS); a.spines['bottom'].set_color(AXIS); a.grid(axis='y', color=GRID, lw=0.6); a.set_axisbelow(True); a.tick_params(labelsize=8, colors=INK)
fig.tight_layout(); fig.savefig('possell/compound500.png')
