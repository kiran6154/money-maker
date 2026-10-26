"""tools/bandlab.py - the shared bench for the band -> structure research (STRATEGY_ANALYSIS_TODO S149).

The idea (the user, 2026-10-26): a band marks where the day is sideways; once price leaves it, trade the move - enter on
the band cross or on the first CHoCH / BOS that way, exit on structure, on a continuation indicator, or by switching the
exit to a higher timeframe once in profit. Every research bot uses THIS module, so they measure alike.

Data     NIFTY near-month futures, 1-minute, the download store (jilly._store_bars("fut"), 2018-01 - 2026-10-23); times
         are the lab's (IST read as UTC). A decision at a bar's close fills at the next 1-minute bar's open.
Costs    1 lot of 65; 0.5 pt slippage a side + futures charges by trade date (jilly._charges) - about 4 points a round
         trip in 2019, 5 in 2022, 8 in 2025, 15 from 2026-04 (STT).
Split    choose on 2018-22 (IS), read 2023-26 (OOS) and 2026 alone; never pick on OOS numbers.

bands(name) -> (up, lo) per 1-minute bar, known at that bar's close (NaN = no band yet):
  or15 / or30   the session's opening range of the first 15 / 30 minutes, from the minute it closes
  pdhl          the previous session's high / low
  jilly         Jilly's noise band UB(key) / LB(key) (Strategy 111's settings, no vol filter)
  vwap1 / vwap2 session VWAP (hlc3, futures volume) +/- 1 / 2 volume-weighted standard deviations, from 09:30
  ema5          Strategy 138's 5-minute EMA 50 +/- 3 x mean distance, from the last completed 5-minute bar
  don60         the highest high / lowest low of the previous 60 one-minute bars
structure(tf, mode) -> dict of 1-minute arrays (the structure engine, core.foundation, on tf-minute bars; an event on a tf
  bar is known at that bar's last minute): choch[i] / bos[i] in {-1, 0, +1} (the direction of a CHoCH / BOS confirmed at
  minute i), trend[i] (the side of the last event), swing_lo[i] / swing_hi[i] (the last confirmed swing low / high).
  tf 1 / 5 / 15; mode "touch" (Strategy 1) / "close" (Strategy 3).
simulate(...) -> list of trades (dict side, ei, xi, entry, exit, why); evaluate(trades) -> the stats.

    entry  "cross"         a close from inside the band to outside enters that way
           "cross_struct"  after such a cross (armed until a close back inside), the first `ev` event that way enters
           "struct_out"    any `ev` event that way while the close is outside the band on that side
           ev = "choch" / "bos" / "any" (on the entry structure, `etf`)
    exit   "choch"   the opposite CHoCH on the exit structure (`xtf`)
           "swing"   a close beyond the last confirmed swing low (long) / high (short) on the exit structure (a trail)
           "inside"  a close back inside the band
           "ema"     a close back through the 1-minute EMA(`ema_n`) - the continuation indicator
           "escalate" the opposite CHoCH on `xtf` until the trade is `esc_pts` points in profit (on closes), then the opposite
                     CHoCH on `esc_tf` (a higher timeframe) - let a working trade run
    stop   None, or "band": a close back beyond the far side of the band
    always flat at the 15:20 open; entries 09:30 - 14:30 (`first`, `last`, minutes from midnight); one position at a time;
    at most `max_day` entries a session.
"""
import os
import sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path: sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import core

JF = core.family("jilly")
PR = core.family("pinerules")
DAY = core.DAY
_D = {}


def data():
    if "f" in _D: return _D["f"]
    f = JF._store_bars("fut")
    MIN = ((f.t % DAY) // 60).astype(np.int64)
    cut = np.concatenate([[0], np.nonzero(np.diff(f.day))[0] + 1, [len(f.t)]])
    ses = np.zeros(len(f.t), np.int64)
    for s, (a, z) in enumerate(zip(cut[:-1], cut[1:])): ses[a:z] = s
    year = np.array([int(core.dstr(int(d))[:4]) for d in f.day]) if "year" not in _D else _D["year"]
    _D["f"] = (f, MIN, cut, ses, year)
    return _D["f"]


# ---------------------------------------------------------------- bands
def bands(name):
    key = ("band", name)
    if key in _D: return _D[key]
    f, MIN, cut, ses, year = data(); n = len(f.t)
    up = np.full(n, np.nan); lo = np.full(n, np.nan)
    if name in ("or15", "or30"):
        N = 15 if name == "or15" else 30
        for a, z in zip(cut[:-1], cut[1:]):
            m = (MIN[a:z] >= 555) & (MIN[a:z] < 555 + N)
            if not m.any(): continue
            hi, lw = f.h[a:z][m].max(), f.l[a:z][m].min()
            k = a + int(np.argmax(MIN[a:z] >= 555 + N - 1)) if (MIN[a:z] >= 555 + N - 1).any() else z
            up[k:z], lo[k:z] = hi, lw
    elif name == "pdhl":
        prev = None
        for a, z in zip(cut[:-1], cut[1:]):
            if prev is not None: up[a:z], lo[a:z] = prev
            prev = (f.h[a:z].max(), f.l[a:z].min())
    elif name == "jilly":
        J = dict(core.load_strategies()["ST111"].SPEC["jilly"], filter=False)
        ff, keyv, E = JF.engine(J)
        for r in E:
            if "UB" not in r: continue
            a, z = r["a"], r["z"]; kk = np.clip(keyv[a:z], 1, 375) - 1
            up[a:z], lo[a:z] = r["UB"][kk], r["LB"][kk]
    elif name in ("vwap1", "vwap2"):
        k = 1.0 if name == "vwap1" else 2.0
        hlc3 = (f.h + f.l + f.c) / 3
        for a, z in zip(cut[:-1], cut[1:]):
            v = f.v[a:z]; cv = np.cumsum(v)
            if cv[-1] <= 0: continue
            with np.errstate(all="ignore"):
                vw = np.cumsum(hlc3[a:z] * v) / cv; sd = np.sqrt(np.maximum(np.cumsum(hlc3[a:z] ** 2 * v) / cv - vw ** 2, 0))
            ok = (MIN[a:z] >= 570) & (cv > 0)
            up[a:z] = np.where(ok, vw + k * sd, np.nan); lo[a:z] = np.where(ok, vw - k * sd, np.nan)
    elif name == "ema5":
        q0, q1, c5, ema, u5, l5 = PR.ema_bars(dict(ema=50, mult=3.0, dlen=20))
        last = np.full(n, -1)
        last[q1] = np.arange(len(q1))                           # a 5-minute bar is known at its last minute
        last = np.maximum.accumulate(last)
        ok = last >= 0
        up[ok], lo[ok] = u5[last[ok]], l5[last[ok]]
    elif name == "don60":
        s = pd.Series(f.h); up[:] = s.rolling(60).max().shift(1).values
        s = pd.Series(f.l); lo[:] = s.rolling(60).min().shift(1).values
    else:
        raise ValueError(name)
    _D[key] = (up, lo)
    return _D[key]


BANDS = ("or15", "or30", "pdhl", "jilly", "vwap1", "vwap2", "ema5", "don60")


# ---------------------------------------------------------------- structure
def tf_bars(tf):
    """(Bars of tf-minute candles, 09:15-aligned per session; the index of each candle's last 1-minute bar)."""
    f, MIN, cut, ses, year = data()
    if tf == 1: return core.Bars(f.t, f.o, f.h, f.l, f.c, f.v), np.arange(len(f.t))
    b = f.day * 1000 + (MIN - 555) // tf
    cb = np.concatenate([[0], np.nonzero(np.diff(b))[0] + 1, [len(f.t)]]); q0, q1 = cb[:-1], cb[1:] - 1
    B = core.Bars(f.t[q0], f.o[q0], np.maximum.reduceat(f.h, q0), np.minimum.reduceat(f.l, q0), f.c[q1], np.add.reduceat(f.v, q0))
    return B, q1


def structure(tf=1, mode="touch"):
    key = ("st", tf, mode)
    if key in _D: return _D[key]
    f, MIN, cut, ses, year = data(); n = len(f.t)
    B, last = tf_bars(tf)
    eng = core.foundation(B, {"break_mode": mode, "choch_mode": mode, "avwap_weight": "volume", "sl_rule": "none"})
    choch = np.zeros(n, np.int8); bos = np.zeros(n, np.int8)
    for j in range(len(eng.ei)):
        i = int(last[int(eng.ei[j])])
        (choch if int(eng.ek[j]) == 1 else bos)[i] = int(eng.ed[j])
    ev = np.where(choch != 0, choch, bos).astype(np.int8)
    tr = np.zeros(n, np.int8); cur = 0
    nz = np.nonzero(ev)[0]
    trend = np.zeros(n, np.int8)
    if len(nz):
        idx = np.zeros(n, np.int64); idx[nz] = nz; idx = np.maximum.accumulate(idx)
        trend = np.where(np.maximum.accumulate(np.where(ev != 0, np.arange(n), 0)) > 0, ev[idx], 0).astype(np.int8)
    sw_lo = np.full(n, np.nan); sw_hi = np.full(n, np.nan)
    sk, sp, sc = np.asarray(eng.sk), np.asarray(eng.sp, float), np.asarray(eng.sc)
    for arr, side in ((sw_lo, -1), (sw_hi, 1)):
        m = sk == side
        at = last[sc[m].astype(np.int64)]; px = sp[m]
        o_ = np.argsort(at, kind="stable"); at, px = at[o_], px[o_]
        tmp = np.full(n, np.nan); tmp[at] = px
        arr[:] = pd.Series(tmp).ffill().values
    _D[key] = dict(choch=choch, bos=bos, trend=trend, swing_lo=sw_lo, swing_hi=sw_hi)
    return _D[key]


def ema1(n_):
    key = ("ema", n_)
    if key not in _D:
        f = data()[0]; _D[key] = pd.Series(f.c).ewm(alpha=2 / (n_ + 1), adjust=False).mean().values
    return _D[key]


# ---------------------------------------------------------------- the walk
def simulate(band, entry="cross", ev="any", etf=1, emode="touch", exit="choch", xtf=1, xmode="touch", stop=None,
             ema_n=20, esc_pts=20.0, esc_tf=5, first=570, last=870, max_day=1):
    f, MIN, cut, ses, year = data(); n = len(f.t)
    up, lo = bands(band)
    E = structure(etf, emode); X = structure(xtf, xmode); H = structure(esc_tf, xmode) if exit == "escalate" else None
    ee = {"choch": E["choch"], "bos": E["bos"], "any": np.where(E["choch"] != 0, E["choch"], E["bos"])}[ev]
    em = ema1(ema_n) if exit == "ema" else None
    c, o = f.c, f.o
    out = []; pos = 0; armed = 0; taken = 0; cur_s = -1
    for i in range(1, n - 1):
        s_ = ses[i]
        if s_ != cur_s: cur_s, taken, armed = s_, 0, 0
        if pos:
            last_bar = ses[i + 1] != s_
            why = None
            if last_bar or MIN[i + 1] >= 920: why = "eod"
            else:
                ci = c[i]
                if stop == "band" and np.isfinite(up[i]) and ((pos > 0 and ci < lo[i]) or (pos < 0 and ci > up[i])): why = "band_stop"
                elif exit == "choch" and X["choch"][i] == -pos: why = "choch"
                elif exit == "swing":
                    lvl = X["swing_lo"][i] if pos > 0 else X["swing_hi"][i]
                    if np.isfinite(lvl) and ((pos > 0 and ci < lvl) or (pos < 0 and ci > lvl)): why = "swing"
                elif exit == "inside" and np.isfinite(up[i]) and ((pos > 0 and ci <= up[i]) or (pos < 0 and ci >= lo[i])): why = "inside"
                elif exit == "ema" and ((pos > 0 and ci < em[i]) or (pos < 0 and ci > em[i])): why = "ema"
                elif exit == "escalate":
                    if not esc and pos * (ci - epx) >= esc_pts: esc = True
                    if (H if esc else X)["choch"][i] == -pos: why = "esc_choch" if esc else "choch"
            if why:
                j = i if (last_bar and why == "eod") else i + 1
                out.append((pos, e, j, epx, (c[i] if j == i else o[j]), why)); pos = 0
            continue
        if MIN[i] < first or MIN[i] > last or taken >= max_day or ses[i + 1] != s_ or not np.isfinite(up[i]) or not np.isfinite(up[i - 1]):
            continue
        ci, cp = c[i], c[i - 1]
        crossed = 1 if (cp <= up[i - 1] and ci > up[i]) else -1 if (cp >= lo[i - 1] and ci < lo[i]) else 0
        if entry == "cross":
            s = crossed
        elif entry == "cross_struct":
            if crossed: armed = crossed
            if armed and lo[i] <= ci <= up[i]: armed = 0
            s = armed if (armed and ee[i] == armed) else 0
        else:  # struct_out
            s = ee[i] if (ee[i] and ((ee[i] > 0 and ci > up[i]) or (ee[i] < 0 and ci < lo[i]))) else 0
        if s:
            pos, e, epx, esc, taken, armed = s, i + 1, o[i + 1], False, taken + 1, 0
    return out


def evaluate(tr, label=""):
    f, MIN, cut, ses, year = data()
    if not tr: return dict(label=label, n=0)
    a = np.array([x[1] for x in tr]); pts = np.array([x[0] * (x[4] - x[3]) for x in tr]) - 1.0
    chg = np.array([JF._charges(core.dstr(int(f.day[i])), "FUT", f.o[i], f.o[i], 65)["total"] / 65 for i in a])
    net = (pts - chg) * 65; yy = year[a]
    def pf(x):
        w = x[x > 0].sum(); l = -x[x <= 0].sum(); return float(w / l) if l else float("inf")
    def dd(x):
        eq = np.cumsum(x); return float((eq - np.maximum.accumulate(eq)).min()) if len(x) else 0.0
    A, B, Z = yy <= 2022, yy >= 2023, yy == 2026
    why = pd.Series([x[5] for x in tr]).value_counts().to_dict()
    hold = float(np.mean([x[2] - x[1] for x in tr]))
    return dict(label=label, n=len(tr), nA=int(A.sum()), nB=int(B.sum()), gross_pts=float((pts + 1.0).mean()), hold_min=hold,
                pf=pf(net), pfA=pf(net[A]), pfB=pf(net[B]), pf26=pf(net[Z]), net=float(net.sum()), netA=float(net[A].sum()),
                netB=float(net[B].sum()), net26=float(net[Z].sum()), ddA=dd(net[A]), ddB=dd(net[B]), win=float((net > 0).mean() * 100),
                long_net=float(net[np.array([x[0] > 0 for x in tr])].sum()), exits=why)


if __name__ == "__main__":
    import time
    t0 = time.time()
    for b in BANDS:
        up, lo = bands(b); print(b, "known on", f"{np.isfinite(up).mean() * 100:.0f}% of minutes", f"{time.time() - t0:.0f}s")
    for tf in (1, 5, 15): structure(tf, "touch")
    print("structure", f"{time.time() - t0:.0f}s")
    r = evaluate(simulate("or15", entry="cross", exit="choch"), "or15 cross / 1m choch")
    print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}, f"{time.time() - t0:.0f}s")
