"""Backtest of "Jilly's ToriTrades Trendline Break" on NIFTY 4H bars (D / W / M context), 2018 -> Oct 2026.

The decision logic is the script's, bar for bar (see tt_engine.py for the line engine).  Two fill models:
  fills='close'  the script's own accounting: entry at the signal bar's close, stop at the stop price, target at
                 the target, line / bias exits at the close (this is what the script's status table reports)
  fills='next'   realistic: entry and close-decided exits at the NEXT bar's open (so the 15:30 signals carry the
                 overnight gap), stop at the worse of bar open / stop, target at the better of bar open / target
P&L in index points and in rupees for one lot of 75 after futures charges.
"""
import math, sys, time, json
from collections import Counter
import numpy as np, pandas as pd
sys.path.insert(0, '/home/claude/tt')
from tt_engine import *

LOT = 75
_last_trades = []; _last_events = None
ARMED_CAP = 20


def fut_costs(entry, exit_, d, slip_pts=1.0):
    """Round-trip charges in rupees for one NIFTY futures lot: Rs 20/order x2, STT 0.02% on the sell side,
    NSE 0.00173% both sides, SEBI Rs 10/crore, stamp 0.002% on the buy side, 18% GST on brokerage+exchange+SEBI,
    one point of slippage per side.  Today's schedule is applied to all years."""
    buy_px, sell_px = (entry, exit_) if d == 1 else (exit_, entry)
    tb = buy_px * LOT; ts = sell_px * LOT
    brokerage = 40.0; stt = 0.0002 * ts; exch = 0.0000173 * (tb + ts); sebi = 1e-6 * (tb + ts); stamp = 0.00002 * tb
    gst = 0.18 * (brokerage + exch + sebi); slip = slip_pts * LOT * 2
    return brokerage + stt + exch + sebi + stamp + gst + slip


class Trade:
    def __init__(self, d, bar, entry, stop, target, risk, action, safety):
        self.dir = d; self.bar = bar; self.entry = entry; self.stop = stop; self.target = target; self.risk = risk
        self.action = action; self.safety = safety; self.exitBar = None; self.exitPrice = None; self.exitWhy = ''
        self.extended = False; self.half = False; self.tgtBar = None; self.lastPiv = None
        self.sBars = [bar]; self.sLines = [safety]; self.sStops = [stop]
        self.late = False; self.biasAll = 0; self.entryFill = None; self.exitFill = None; self.exitFillBar = None


def load_bars():
    import os
    B = {k: pd.read_parquet(f'/home/claude/tt/bars_{k}.parquet') for k in ('4h', '1h', '1d', '1w', '1m', '15m', '5m') if os.path.exists(f'/home/claude/tt/bars_{k}.parquet')}
    return B


def contexts(P, bars, B, keys=('1m', '1w', '1d')):
    """TF1 / TF2 / TF3 snapshots aligned to the chart bars (previous completed HTF bar, as request.security(...)[1])."""
    out = []
    for key, cfg in zip(keys, (P.tf1, P.tf2, P.tf3)):
        snaps, _ = run_context(B[key], P, cfg)
        out.append(ctx_for_bars(bars.t.values.astype('int64'), B[key].t.values.astype('int64'), snaps))
    return out      # ctx1 (M), ctx2 (W), ctx3 (D)


def run(P, bars, ctxs, fills='close', label='', verbose=True, armed_mode='script', armed_expire=10, eod_tod=None, allow=None, cost_fn=None, side_only=0, min_px=0.0):
    """armed_mode: 'script' (armed lines never expire, as written), 'off' (fresh breaks only), 'expire' (an armed line is dropped armed_expire bars after it was armed)."""
    n = len(bars); o = bars.open.values; h = bars.high.values; l = bars.low.values; c = bars.close.values; t = bars.t.values.astype('int64')
    ctx1, ctx2, ctx3 = ctxs
    eng = make_engine(P, bars, P.tapSpacing, P.angleWinDays, P.lookbackDays, P.atrLen, keepSafe=True)
    ph, pl = pivots(eng.hi, eng.lo, P.leftBars, P.rightBars)
    minAge = P.minLineDays
    dts = pd.to_datetime(bars.datetime); tod = (dts.dt.hour * 60 + dts.dt.minute).values; day = dts.dt.date.values
    minBars = getattr(P, 'minLineBars', None)
    pos = None; trades = []; armed = []; armedWhy = []; armedBar = []; nBreaks = 0; nTraded = 0; noTrade = Counter(); nB = 0; events = []; armedBar_first = {}
    barlog = np.zeros((n, 5))      # biasAll, chartBias, position, #bestSup, #bestRes
    t0 = time.time()

    def f_nearestLevel(i, d, entry, minDist):
        best = None
        for pv in (eng.pivHi if d > 0 else eng.pivLo):
            if (pv.price - entry) * d >= minDist and (best is None or (pv.price - best) * d < 0): best = pv.price
        for cx in (ctx1[i], ctx2[i], ctx3[i]):
            for ls in (cx.sup, cx.res):
                if ls.grade != GRADE_NONE and ls.pNow is not None and (ls.pNow - entry) * d >= minDist and (best is None or (ls.pNow - best) * d < 0): best = ls.pNow
        return best

    def f_check(i, ln, d, canEnter, late, close, atrNow, biasAll):
        code = ''; safe = stop = risk = target = None
        if minBars is None and int(t[i]) - ln.tA < minAge * DAY_MS: code = f'line < {minAge:g}d'
        elif minBars is not None and i - ln.barA < minBars: code = f'line < {minBars} bars'
        elif eod_tod is not None and (i + 1 >= n or tod[i + 1] >= eod_tod or day[i + 1] != day[i]): code = 'after entry cutoff'
        elif allow is not None and not (allow[i] and i + 1 < n and allow[i + 1]): code = 'not a trade bar'
        elif side_only and d != side_only: code = 'side switched off'
        elif close < min_px: code = 'premium too small'
        elif not canEnter: code = 'in a position'
        elif not late and (close - ln.priceAt(i)) * d < P.breakBuf * atrNow: code = 'break buffer'
        elif P.biasFilter and biasAll * d <= 0: code = 'against bias'
        if code == '':
            safe = eng.safetyFor(d, i, close)
            if safe is None: code = 'no safety line'
        if code == '':
            stop = tick(safe.priceAt(i + 4), d) if P.stopMode == 'MECH' else None
            risk = ((stop if P.stopMode == 'MECH' else safe.priceAt(i)) - close) * -d
            if risk <= 0: code = 'stop not beyond entry'
            elif P.riskFilter and risk > P.maxRiskAtr * atrNow: code = 'risk too large'
        if code == '':
            lvl = f_nearestLevel(i, d, close, P.minRR * risk)
            if lvl is None and P.needTarget: code = f'no level >= {P.minRR:g}R'
            else: target = tick(close + d * P.minRR * risk if lvl is None else lvl, d)
        return code, safe, stop, risk, target

    for i in range(n):
        eng.step(i, float(ph[i]), float(pl[i]), P.rightBars)
        atrV = float(eng.atrz[i]); close = float(c[i]); high = float(h[i]); low = float(l[i])
        chartBias = eng.tfBias(); b2 = ctx2[i].bias; b3 = ctx3[i].bias
        biasAll = b3 if P.biasFrom == 'D' else (b2 if b2 != 0 else b3)
        reverseOn = None
        if pos is not None and eod_tod is not None and (tod[i] >= eod_tod or day[i] != day[pos.bar]):
            if day[i] != day[pos.bar]:     # session ended before the cutoff bar (short / trimmed session): out at its last close
                pos.exitBar = i - 1; pos.exitPrice = float(c[i - 1])
            else:
                pos.exitBar = i; pos.exitPrice = float(o[i])
            pos.exitWhy = 'end of day'; pos.exitFill = pos.exitPrice; pos.exitFillBar = pos.exitBar
            trades.append(pos); pos = None
        flatAtStart = pos is None
        if pos is not None:
            agree = biasAll * pos.dir > 0
            stopHit = pos.stop is not None and (low <= pos.stop if pos.dir > 0 else high >= pos.stop)
            safeHit = (pos.safety.priceAt(i) - close) * pos.dir > 0
            tgtHit = (not pos.extended) and (high >= pos.target if pos.dir > 0 else low <= pos.target)
            biasEnd = pos.extended and not agree
            if tgtHit and agree and not stopHit and not safeHit:
                pos.extended = True; pos.tgtBar = i; tgtHit = False
            if stopHit or safeHit or tgtHit or biasEnd:
                pos.exitBar = i
                pos.exitPrice = pos.stop if stopHit else close if safeHit else pos.target if tgtHit else close
                pos.exitWhy = 'stop' if stopHit else 'safety line close' if safeHit else 'target' if tgtHit else 'bias turned'
                if safeHit and not stopHit: reverseOn = pos.safety
                if fills == 'close':
                    pos.exitFill = pos.exitPrice; pos.exitFillBar = i
                elif stopHit:
                    pos.exitFill = min(float(o[i]), pos.stop) if pos.dir > 0 else max(float(o[i]), pos.stop); pos.exitFillBar = i
                elif tgtHit:
                    pos.exitFill = float(o[i]) if (float(o[i]) - pos.target) * pos.dir > 0 else pos.target; pos.exitFillBar = i
                else:
                    pos.exitFill = float(o[i + 1]) if i + 1 < n else close; pos.exitFillBar = min(i + 1, n - 1)
                trades.append(pos); pos = None
            else:
                moved = False
                if not pos.half and ((high if pos.dir > 0 else low) - pos.entry) * pos.dir >= 0.5 * (pos.target - pos.entry) * pos.dir:
                    pos.half = True
                    if pos.stop is None or (pos.entry - pos.stop) * pos.dir > 0:
                        pos.stop = pos.entry; moved = True
                nl = None
                if pos.half:
                    drawn = eng.bestSup if pos.dir > 0 else eng.bestRes
                    nl, _ = nearestSafe(drawn, pos.dir, i, close, pos.bar, (close - pos.safety.priceAt(i)) * pos.dir)
                    fPivs = eng.pivLo if pos.dir > 0 else eng.pivHi
                    if P.followOn and fPivs and fPivs[-1].bar > pos.bar and fPivs[-1].bar != (pos.lastPiv or 0):
                        fB = fPivs[-1]; pos.lastPiv = fB.bar
                        fRange, fBars = eng.angleWindow()
                        fCur = pos.safety if nl is None else nl
                        fBest = (close - fCur.priceAt(i)) * pos.dir
                        for fi, fAbar in enumerate(fCur.tapBars):
                            fAp = fCur.tapWick[fi]
                            if (fB.price - fAp) * pos.dir > 0 and fB.bar - fAbar >= eng.tapSpacing:
                                fc = TLine(P, pos.dir, fAbar, fAp, fCur.tapTimes[fi], fB.bar, fB.price, fB.t, born=i)
                                fd = (close - fc.priceAt(i)) * pos.dir
                                if fd > 0 and fd < fBest and (fc.slope() - fCur.slope()) * pos.dir > 0 and nz(fc.angleIn(fRange, fBars), 90.0) < P.safeMaxAng and eng.scan(fc, fAbar, i) is None:
                                    nl = fc; fBest = fd
                if nl is not None:
                    pos.safety = nl; nl.traded = True; moved = True; eng.log_lines[nl.id] = nl
                    if P.stopMode == 'MECH':
                        ns = tick(nl.priceAt(i + 4), pos.dir)
                        if (ns - pos.stop) * pos.dir > 0 and (close - ns) * pos.dir > 0: pos.stop = ns
                if moved:
                    pos.sBars.append(i); pos.sLines.append(pos.safety); pos.sStops.append(pos.stop)

        cands = []; late = []
        for k in range(len(armed) - 1, -1, -1):
            al = armed[k]
            if armed_mode == 'expire' and i - armedBar[k] > armed_expire:
                noTrade['armed expired'] += 1; armed.pop(k); armedWhy.pop(k); armedBar.pop(k); continue
            if (close - al.priceAt(i)) * -al.side >= P.breakBuf * atrV:
                cands.append(al); late.append(True); armed.pop(k); armedWhy.pop(k); armedBar.pop(k)
        for ln in eng.endedNow:
            if ln.endHow != 'broke': continue
            if ln.grade() != GRADE_APLUS: nB += 1; continue
            nBreaks += 1; cands.append(ln); late.append(False)
        for k, ln in enumerate(cands):
            d = -ln.side
            code, safe, stop, risk, target = f_check(i, ln, d, pos is None and (flatAtStart or ln.sameAs(reverseOn)), late[k], close, atrV, biasAll)
            events.append(dict(bar=i, line=ln.id, dir=d, late=late[k], code=code, break_bar=ln.endBar, bias=biasAll))
            if code == '':
                ln.traded = True; safe.traded = True
                pos = Trade(d, i, close, stop, target, risk, ln, safe); pos.late = late[k]; pos.biasAll = biasAll; pos.breakBar = ln.endBar
                pos.entryFill = close if fills == 'close' else (float(o[i + 1]) if i + 1 < n else close)
                nTraded += 1
                for j in range(len(armed) - 1, -1, -1):
                    if -armed[j].side == d:
                        noTrade['same move traded'] += 1; armed.pop(j); armedWhy.pop(j); armedBar.pop(j)
            elif armed_mode != 'off' and (late[k] or code in ('break buffer', 'against bias')):
                armed.append(ln); armedWhy.append(code); armedBar.append(armedBar_first.setdefault(ln.id, i) if armed_mode == 'expire' else i)
                if len(armed) > ARMED_CAP:
                    armed.pop(0); gone = armedWhy.pop(0); armedBar.pop(0); noTrade[gone] += 1
            else:
                noTrade[code] += 1
        barlog[i] = (biasAll, chartBias, 0 if pos is None else pos.dir, len(eng.bestSup), len(eng.bestRes))
        if verbose and (i + 1) % 1000 == 0: print(f'  {label} bar {i+1}/{n}  trades={len(trades)}  scans={eng.n_scan}  [{time.time()-t0:.0f}s]', flush=True)
    if pos is not None:      # still open at the end of the data: mark at the last close
        pos.exitBar = n - 1; pos.exitPrice = float(c[-1]); pos.exitWhy = 'open at end'; pos.exitFill = float(c[-1]); pos.exitFillBar = n - 1; trades.append(pos)

    dt = bars.datetime.values
    rows = []
    for tr in trades:
        pts = (tr.exitFill - tr.entryFill) * tr.dir; cost = (cost_fn or fut_costs)(tr.entryFill, tr.exitFill, tr.dir)
        rows.append(dict(entry_time=dt[tr.bar], dir=tr.dir, signal_close=tr.entry, entry_fill=tr.entryFill, stop0=tr.sStops[0], stop_last=tr.stop, target=tr.target, risk=tr.risk,
                         rr_planned=round((tr.target - tr.entry) * tr.dir / tr.risk, 2), late=tr.late, bars_after_break=tr.bar - tr.breakBar, bias=tr.biasAll,
                         action_id=tr.action.id, action_tA=pd.Timestamp(tr.action.tA, unit='ms'), action_taps=tr.action.taps(), action_angle=round(tr.action.angle, 1) if tr.action.angle == tr.action.angle else np.nan,
                         safety_id=tr.sLines[0].id, safety_taps=tr.sLines[0].taps(), n_trail=len(tr.sLines) - 1, half=tr.half, extended=tr.extended,
                         exit_time=dt[tr.exitBar], exit_fill_time=dt[tr.exitFillBar], exit_why=tr.exitWhy, exit_script=tr.exitPrice, exit_fill=tr.exitFill,
                         R_script=round((tr.exitPrice - tr.entry) * tr.dir / tr.risk, 3), pts_script=(tr.exitPrice - tr.entry) * tr.dir,
                         bars=tr.exitBar - tr.bar, pts=pts, gross=pts * LOT, cost=cost, net=pts * LOT - cost))
    T = pd.DataFrame(rows)
    if len(T): T['year'] = pd.to_datetime(T.entry_time).dt.year
    global _last_trades, _last_events; _last_trades = trades; _last_events = pd.DataFrame(events)
    info = dict(label=label, fills=fills, n_bars=n, n_aplus_breaks=nBreaks, n_b_breaks=nB, n_traded=nTraded, no_trade=dict(noTrade), armed_left=len(armed), scans=eng.n_scan, secs=round(time.time() - t0))
    return T, info, eng, barlog


def stats(T, label=''):
    if len(T) == 0: return dict(book=label, N=0)
    x = T.net; g = x[x > 0].sum(); b = -x[x < 0].sum(); eq = x.cumsum(); dd = (eq - eq.cummax()).min()
    yr = T.groupby('year').net.sum()
    return dict(book=label, N=len(T), win=round((T.pts > 0).mean(), 3), pts=round(T.pts.sum(), 1), avg_pts=round(T.pts.mean(), 1), sumR=round(T.R_script.sum(), 1), avgR=round(T.R_script.mean(), 2),
                gross=round(T.gross.sum()), cost=round(T.cost.sum()), net=round(x.sum()), PF=round(g / b, 2) if b > 0 else np.inf,
                t=round(x.mean() / (x.std(ddof=1) / np.sqrt(len(x))), 2) if len(x) > 1 else np.nan, maxDD=round(dd), worst=round(x.min()), best=round(x.max()),
                avg_bars=round(T.bars.mean(), 1), longs=int((T.dir == 1).sum()), years_pos=f'{int((yr > 0).sum())}/{len(yr)}', exits=T.exit_why.value_counts().to_dict())


if __name__ == '__main__':
    pd.set_option('display.width', 250); pd.set_option('display.max_columns', 60)
    B = load_bars(); P = Params()
    t0 = time.time()
    ctxs = contexts(P, B['4h'], B)
    print('contexts ready', f'[{time.time()-t0:.0f}s]', flush=True)
    T, info, eng, barlog = run(P, B['4h'], ctxs, fills='close', label='4H close-fills')
    print(json.dumps(info, indent=1, default=str))
    print(stats(T, '4H close fills'))
    print(T.to_string())
    T.to_csv('/home/claude/tt/trades_4h_close.csv', index=False)
