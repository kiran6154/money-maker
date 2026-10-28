"""Build the per-day ATM CE / PE option series for ALL years (2018 -> Oct 2026).

Same rules as build_opt.py (no hindsight):
  * session D -> front expiry E = nearest expiry folder with E >= D
      - the front expiry must be within 35 calendar days of D (true for every weekly period and for
        every monthly period when the previous month's folder exists). Days whose nearest folder is
        further away are SKIPPED and counted (this is the March-2018 gap: no 2018-03-28 folder).
  * strike K = NIFTY 09:15 five-minute close rounded to the nearest 50  (known at 09:20)
  * two charts per day: (E, K, CE) and (E, K, PE); each contract keeps its own earlier history from the
    same expiry folder as warm-up for the indicator.
  * if the ATM strike has no data in the folder for that day, the contract-day is SKIPPED and counted
    (never substituted by a neighbouring strike).

Coverage labels per trade day (column `cov`):
  monthly : 2018 (monthly expiries only, regular files only)
  narrow  : 2019-01-22 .. 2019-09-11 (weeklies from Feb-2019, regular files only, no wide chain)
  full    : 2019-09-12 onwards (regular + wide = full chain)

Output: /home/claude/opt/atm_1min_all.parquet  (same schema as atm_5min.parquet + `cov`)
        /home/claude/opt/plan_all_1m.csv           (every planned session with its status)
"""
import pandas as pd, numpy as np, glob, os, sys, collections, time

idx = pd.read_parquet('/home/claude/idx/nifty_5min.parquet'); idx['date'] = idx.datetime.dt.normalize()
spot0915 = idx[idx.datetime.dt.strftime('%H:%M') == '09:15'].set_index('date').close
sessions = sorted(spot0915.index)
sess_arr = np.array(sessions, dtype='datetime64[ns]')

UP = '/mnt/user-data/uploads/nifty_data/options/1minute'
roots = [f'{UP}/{y}' for y in range(2018, 2027)] + ['/home/claude/optzip']
expdirs = {}
for r in roots:
    for d in sorted(glob.glob(r + '/20??-??-??')):
        expdirs.setdefault(os.path.basename(d), []).append(d)
expiries = sorted(expdirs)
print('expiry folders', len(expiries), expiries[0], expiries[-1])
exp_ts = np.array([np.datetime64(e) for e in expiries])

def front_expiry(D):
    i = np.searchsorted(exp_ts, np.datetime64(D))
    return expiries[i] if i < len(expiries) else None

def coverage(D):
    if D < pd.Timestamp('2019-01-01'): return 'monthly'
    if D < pd.Timestamp('2019-09-12'): return 'narrow'
    return 'full'

MAX_DAYS = 35
# periods whose true front-month folder is absent on the laptop (the March-2018 monthly, expiry 2018-03-28):
# the nearest folder is the NEXT month's contract, which was not the front contract then -> skip, never substitute
GAPS = [(pd.Timestamp('2018-02-23'), pd.Timestamp('2018-03-28'), 'missing_expiry_folder_2018-03-28')]
plan = []; skipped = []
for D in sessions:
    if D < pd.Timestamp('2018-01-01') or D > pd.Timestamp('2026-10-19'): continue
    gap = [why for a, b, why in GAPS if a <= D <= b]
    if gap: skipped.append((D, gap[0])); continue
    e = front_expiry(D)
    if e is None: skipped.append((D, 'no_expiry_folder')); continue
    if (pd.Timestamp(e) - D).days > MAX_DAYS: skipped.append((D, f'front_expiry_{(pd.Timestamp(e) - D).days}d_away_folder_missing')); continue
    K = int(round(spot0915[D] / 50.0) * 50)
    plan.append((D, e, K, coverage(D)))
print('sessions planned', len(plan), plan[0][:3], plan[-1][:3], '| skipped (no usable front expiry)', len(skipped))

need = collections.defaultdict(set)
for D, e, K, cov in plan: need[e].add(K)
out = []; t0 = time.time()
for n_e, e in enumerate(expiries):
    if e not in need: continue
    fs = sorted(f for d in expdirs[e] for f in glob.glob(d + '/*.parquet'))
    parts = []
    for f in fs:
        try:
            d = pd.read_parquet(f, columns=['datetime', 'strike', 'right', 'open', 'high', 'low', 'close', 'volume'])
        except Exception as ex:
            print('!! read fail', f, ex); continue
        d = d[d.strike.isin(need[e])]
        if len(d): parts.append(d)
    if not parts: print('!! no data for', e); continue
    d = pd.concat(parts, ignore_index=True)
    d['right'] = d.right.astype(str)
    d = d.drop_duplicates(['datetime', 'strike', 'right']).sort_values(['strike', 'right', 'datetime'])
    m = d.datetime.dt.hour * 60 + d.datetime.dt.minute
    d = d[(m >= 555) & (m <= 929)].copy()
    d['date'] = d.datetime.dt.normalize()
    g = d[['strike', 'right', 'datetime', 'open', 'high', 'low', 'close', 'volume']].copy(); g['expiry'] = e
    out.append(g)
    if n_e % 25 == 0: print(f'{e} strikes {len(need[e])} rows1 {len(g)}  [{time.time() - t0:.0f}s]', flush=True)
O = pd.concat(out, ignore_index=True)
O['date'] = O.datetime.dt.normalize()
tag = pd.DataFrame(plan, columns=['trade_date', 'expiry', 'strike', 'cov'])
O = O.merge(tag.rename(columns={'trade_date': 'date'}).assign(is_trade=True), on=['date', 'expiry', 'strike'], how='left')
O['is_trade'] = O.is_trade.fillna(False).astype(bool)
O['cov'] = O['cov'].fillna('')
# sessions-to-expiry: position of expiry (or last session <= expiry) minus position of the bar's date
exp_pos = np.searchsorted(sess_arr, O.expiry.values.astype('datetime64[ns]'), side='right') - 1
day_pos = np.searchsorted(sess_arr, O.date.values.astype('datetime64[ns]'), side='right') - 1
O['dte'] = exp_pos - day_pos
O = O.sort_values(['expiry', 'strike', 'right', 'datetime']).reset_index(drop=True)
os.makedirs('/home/claude/opt', exist_ok=True)
O.to_parquet('/home/claude/opt/atm_1min_all.parquet', index=False)

# coverage report
have = set(zip(O.loc[O.is_trade, 'date'], O.loc[O.is_trade, 'expiry'], O.loc[O.is_trade, 'strike'], O.loc[O.is_trade, 'right']))
rows = []
for D, e, K, cov in plan:
    rows.append(dict(date=D, expiry=e, strike=K, cov=cov, CE=(D, e, K, 'CE') in have, PE=(D, e, K, 'PE') in have))
for D, why in skipped:
    rows.append(dict(date=D, expiry='', strike=np.nan, cov='skipped:' + why, CE=False, PE=False))
P = pd.DataFrame(rows).sort_values('date'); P.to_csv('/home/claude/opt/plan_all_1m.csv', index=False)
P['year'] = P.date.dt.year
summ = P.groupby('year').agg(sessions=('date', 'size'), planned=('expiry', lambda x: (x != '').sum()), CE_ok=('CE', 'sum'), PE_ok=('PE', 'sum'))
print(summ.to_string())
print('contract-days with trade data:', len(have), '| bars', len(O), '| contracts', O.groupby(['expiry', 'strike', 'right']).ngroups)
cov = O[O.is_trade].groupby(['date', 'right']).size().unstack()
print('bars per trade day (CE) distribution:', cov['CE'].describe().round(1).to_dict())
print('done in', round(time.time() - t0), 's')
