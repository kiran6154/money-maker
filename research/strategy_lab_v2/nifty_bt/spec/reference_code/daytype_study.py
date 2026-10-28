"""Which live measures tell a trend day from a chop day, and how early. All features use bars up to the checkpoint only."""
import sys, pickle; sys.path.insert(0, '/home/claude/bt')
import numpy as np, pandas as pd
import mtf_bt as M
from st_instances import day_types
b = M.load_1m(); D = day_types(b)
D['eff'] = D.body.abs() / D.rng
D['trend'] = D.type.isin(['Trending up', 'Trending down']).astype(int)
D['chop'] = D.type.isin(['Sideways / range', 'Mixed / choppy', 'Reversal (V / inverted V)']).astype(int)
adr = D.rng.rolling(20, min_periods=5).mean().shift(1)
prev = D.shift(1)
nr7 = (D.rng == D.rng.rolling(7).min()).shift(1)            # yesterday was the narrowest of 7 days
inside = ((D.hi <= D.hi.shift(1)) & (D.lo >= D.lo.shift(1))).shift(1)
rows = []
for cp in (585, 615, 660, 720, 780):                        # checkpoints 09:45 10:15 11:00 12:00 13:00 (bar start < cp means closed by cp)
    x = b[b.tod < cp]; g = x.groupby('date')
    o = g.open.first(); c = g.close.last(); hi = g.high.max(); lo = g.low.min()
    path = g.close.apply(lambda s: s.diff().abs().sum()) + (g.close.first() - o).abs()
    twap = g.close.mean()
    side = x.assign(tw=x.groupby('date').close.transform(lambda s: s.expanding().mean())).assign(ab=lambda d: np.sign(d.close - d.tw))
    one_side = side.groupby('date').ab.apply(lambda s: abs(s.mean()))            # 1 = always on one side of the running average
    cross_open = x.assign(s=np.sign(x.close - x.groupby('date').open.transform('first'))).groupby('date').s.apply(lambda s: (s.diff().abs() > 0).sum())
    # opening range 09:15-09:29 and whether price is outside it now and never went back across to the other side
    orr = b[b.tod < 570].groupby('date'); orh = orr.high.max(); orl = orr.low.min()
    xa = x[x.tod >= 570].groupby('date'); brk_up = xa.high.max().reindex(orh.index) > orh; brk_dn = xa.low.min().reindex(orl.index) < orl
    or_one_way = (brk_up ^ brk_dn).astype(float).reindex(o.index)                                   # broke only one side of the 15-min opening range
    # one-way new extremes: share of new day-highs vs new day-lows made after 09:30
    nh = x.assign(h=x.groupby('date').high.cummax()).groupby('date').h.apply(lambda s: (s.diff() > 0).sum())
    nl = x.assign(l=x.groupby('date').low.cummin()).groupby('date').l.apply(lambda s: (s.diff() < 0).sum())
    F = pd.DataFrame(dict(
        rng_x_adr=(hi - lo) / adr,                      # range so far vs normal day range
        move_x_adr=(c - o).abs() / adr,                 # net move from open vs normal day range
        ER=(c - o).abs() / path,                        # efficiency of the path so far
        pos_extreme=np.maximum((c - lo) / (hi - lo), (hi - c) / (hi - lo)),   # 1 = sitting at the day's high or low
        one_side_twap=one_side,                         # one-sidedness around the running average price
        open_crosses=cross_open,                        # times price crossed the day's open
        extremes_one_way=(nh - nl).abs() / (nh + nl).clip(lower=1),
        or_one_way=or_one_way, or_x_adr=(orh - orl) / adr,
        gap=D.gap.abs(), prev_eff=prev.eff, prev_rng_x_adr=prev.rng / adr, nr7=nr7.astype(float), inside=inside.astype(float)))
    # what the rest of the day did in the direction of the move so far (what a trend trader earns from here)
    dirn = np.sign(c - o); F['fwd_pts'] = dirn * (D.c - c); F['cp'] = cp; F['date'] = F.index
    rows.append(F.join(D[['trend', 'chop', 'type', 'eff', 'rng']]))
X = pd.concat(rows).reset_index(drop=True); X['year'] = pd.to_datetime(X.date).dt.year
X = X[X.rng_x_adr.notna()]
X.to_parquet('daytype/features.parquet'); print(len(X), X.groupby('cp').size().to_dict())
print('base rates:', D.type.value_counts(normalize=True).round(3).to_dict())
