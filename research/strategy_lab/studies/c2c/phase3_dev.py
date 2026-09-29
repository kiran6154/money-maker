"""C2C research, phase 3 on the development years only (ledger EXP-003): the signal edge on NIFTY under two regime
definitions, because the engine's own regime freezes when run continuously (EXP-001 A3). The user (2026-09-29): test both,
freeze none yet, on development data; validation (2024) and blind (2025-2026) data are not loaded at all.

  R-A  rolling memory: each session's structure is rebuilt from the previous MEMORY sessions plus the session itself
       (the lab's per-backtest warm-up, made daily); the engine is unchanged
  R-B  flip on the level break: no AVWAP condition anywhere in the regime - every opposite swing of the trend is a
       protected-level candidate (engine: only swings beyond the anchored AVWAP) and a close through the protected level
       flips the trend (engine: also through the AVWAP). A study-local copy of engine.run with those two lines changed, run
       continuously from 2020-10-01 (engine.py untouched). The AVWAP still anchors the retest band.
       (A first attempt changed only the flip line and was identical to the engine: with close breaks every CHoCH already
       flips; the freeze comes from the candidate rule.)

Everything else is EXP-002's frozen rule and measurement (see phase1_3.py): bearish = swing-high retest within 50 pts of
the peak-anchored AVWAP, bullish = the mirror, day filter 0.6 %, entry at the next candle's open, direction-signed moves,
same-year same-time-of-day control, 2,000-draw randomisation. Also reported per definition: flips per year and the longest
regime, the first thing to read (a frozen regime makes the rest meaningless).

    python studies/c2c/phase3_dev.py        # writes studies/c2c/phase3_dev.json
"""
import csv, json, os, sys, types
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
import engine  # noqa: E402

SRC = "D:/nifty/nifty50_5minute_2019-01-01_to_2026-09-26.csv"
WARM_FROM, START, END = "2020-10-01", "2021-01-01", "2023-12-31"      # END seals validation and blind data
BAND, DAY_PCT, MEMORY = 50, 0.6, 5
H_MIN = (5, 10, 15, 30, 60, 120, 240)
DRAWS, SEED = 2000, 20260929
P = dict(break_mode="close", choch_mode="close", avwap_weight="equal", sl_rule="none")
OUT = os.path.dirname(os.path.abspath(__file__))


def level_break_engine():
    """engine.run with the flip condition reduced to the level break (R-B). Refuses if the source line is not found."""
    src = open(os.path.join(HERE, "engine.py"), encoding="utf-8").read()
    old = "                flip = (trend == 1 and ch_below(i, v)) or (trend == -1 and ch_above(i, v))\n"
    assert src.count(old) == 1, "engine.py flip line changed; update phase3_dev.py"
    m = types.ModuleType("engine_rb")
    q_old = '        return (s["k"] == "L" and s["p"] < a) if trend == 1 else (s["k"] == "H" and s["p"] > a)\n'
    assert src.count(q_old) == 1, "engine.py qualifies() changed; update phase3_dev.py"
    # no AVWAP anywhere in the regime: every opposite swing of the trend is a protected-level candidate, and its break flips
    src = src.replace(old, "                flip = True\n").replace(q_old, '        return s["k"] == ("L" if trend == 1 else "H")\n')
    exec(compile(src, "engine_rb", "exec"), m.__dict__)
    return m


def load():
    rows = [r for r in csv.DictReader(open(SRC)) if WARM_FROM <= r["datetime"][:10] <= END and r["datetime"][11:16] <= "15:25"]
    return dict(t=[r["datetime"] for r in rows], o=[float(r["open"]) for r in rows], h=[float(r["high"]) for r in rows],
                l=[float(r["low"]) for r in rows], c=[float(r["close"]) for r in rows], v=[0.0] * len(rows))


def signals_from(r, bars, off, keep_day=None):
    """Signals of one engine run over bars (global index = local + off); only on keep_day when given. Also the flips."""
    t, c = bars["t"], bars["c"]
    n = len(t)
    first_open = {}
    for i in range(n): first_open.setdefault(t[i][:10], bars["o"][i])
    flips = {e["i"]: e for e in r["chs"] if e["flip"]}
    reg, cur = [None] * n, (0, None, None)
    for i in range(n):
        e = flips.get(i)
        if e: cur = (-1, i, e["hi"]["bar"]) if e["dir"] == "down" else (1, i, e["lo"]["bar"])
        reg[i] = cur
    out = []
    for sw in r["sw"]:
        i = sw["conf"]
        if i + 1 >= n or t[i] < START or (keep_day and t[i][:10] != keep_day): continue
        want = -1 if sw["k"] == "H" else 1
        rg, fi, anchor = reg[i]
        if rg != want or fi == i: continue
        av = r["av"](anchor, i)
        if not (av - BAND < sw["p"] < av + BAND): continue
        d0 = first_open[t[i][:10]]
        if want == -1 and not c[i] > d0 * (1 - DAY_PCT / 100): continue
        if want == 1 and not c[i] < d0 * (1 + DAY_PCT / 100): continue
        out.append(dict(i=i + off, dir=want, time=t[i], dist_av=round(sw["p"] - av, 2), bars_since_flip=i - fi))
    fl = [(t[k], flips[k]["dir"]) for k in flips if not keep_day or t[k][:10] == keep_day]
    return out, fl


def run_ra(b):
    days = sorted({x[:10] for x in b["t"]})
    idx = {}
    for i, x in enumerate(b["t"]): idx.setdefault(x[:10], [i, i])[1] = i
    sig, fl = [], []
    for k, d in enumerate(days):
        if d < START: continue
        a = idx[days[max(0, k - MEMORY)]][0]; z = idx[d][1]
        w = {q: b[q][a:z + 1] for q in "tohlcv"}
        r = engine.run(w, P)
        s_, f_ = signals_from(r, w, a, keep_day=d)
        sig += s_; fl += f_
    return sig, fl


def run_rb(b):
    r = level_break_engine().run(b, P)
    return signals_from(r, b, 0)


def regime_stats(fl):
    ts = sorted(fl)
    import datetime as D
    per_year = {}
    for x, _ in ts: per_year[x[:4]] = per_year.get(x[:4], 0) + 1
    gaps = [((D.datetime.fromisoformat(ts[k + 1][0]) - D.datetime.fromisoformat(ts[k][0])).days, ts[k][0][:10]) for k in range(len(ts) - 1)]
    return dict(flips_per_year=per_year, longest_regimes_days=sorted(gaps)[-3:])


def measure(b, sig):
    t = b["t"]; o, h, l, c = (np.array(b[k]) for k in "ohlc"); n = len(t)
    day = [x[:10] for x in t]
    last_of = np.zeros(n, dtype=int); s = 0
    for i in range(n):
        if i == n - 1 or day[i + 1] != day[i]: last_of[s:i + 1] = i; s = i + 1

    def fwd(E, D):
        E, D = np.asarray(E), np.asarray(D); L = last_of[E]; e0 = o[E]; out = {}
        mx, mn = h[E].copy(), l[E].copy(); need = {hm // 5: hm for hm in H_MIN}
        for m in range(1, max(need) + 1):
            k = np.minimum(E + m - 1, L); mx = np.maximum(mx, h[k]); mn = np.minimum(mn, l[k])
            if m in need:
                hm = need[m]; out[f"move_{hm}"] = D * (c[k] - e0)
                out[f"mfe_{hm}"] = np.where(D > 0, mx - e0, e0 - mn); out[f"mae_{hm}"] = np.where(D > 0, mn - e0, e0 - mx)
        out["move_eod"] = D * (c[L] - e0)
        return out

    sig = [x for x in sig if x["i"] + 1 < n]
    for x in sig: x["open_print"] = day[x["i"] + 1] != day[x["i"]]; x["entry_time"] = t[x["i"] + 1]
    F = fwd([x["i"] + 1 for x in sig], [x["dir"] for x in sig])
    for j, x in enumerate(sig):
        for k, v in F.items(): x[k] = float(v[j])
    allE = np.array([i for i in range(1, n) if t[i] >= START and day[i] == day[i - 1]])
    ctl = {d: fwd(allE, np.full(len(allE), d)) for d in (-1, 1)}
    bucket = {}
    for j, e in enumerate(allE): bucket.setdefault((t[e][:4], t[e][11:16]), []).append(j)
    rng = np.random.default_rng(SEED)
    keys = [f"move_{hm}" for hm in H_MIN] + ["move_eod"]

    def summary(xs):
        out = dict(n=len(xs), open_print=sum(x["open_print"] for x in xs))
        use = [x for x in xs if not x["open_print"] and (x["entry_time"][:4], x["entry_time"][11:16]) in bucket]
        for k in keys:
            v = np.array([x[k] for x in xs])
            if not len(v): continue
            out[k] = dict(mean=round(v.mean(), 2), median=round(float(np.median(v)), 2), hit=round((v > 0).mean() * 100, 1))
            if len(use) < 2: continue
            ctl_mean = np.array([ctl[x["dir"]][k][bucket[(x["entry_time"][:4], x["entry_time"][11:16])]].mean() for x in use])
            ex = np.array([x[k] for x in use]) - ctl_mean
            draws = np.zeros(DRAWS)
            for x in use: draws += ctl[x["dir"]][k][rng.choice(bucket[(x["entry_time"][:4], x["entry_time"][11:16])], DRAWS)]
            draws /= len(use)
            out[k].update(excess=round(ex.mean(), 2), t=round(ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex))), 2),
                          p_random=round(float((draws >= np.mean([x[k] for x in use])).mean()), 4))
        for hm in (15, 60, 240):
            out[f"mfe_{hm}"] = round(float(np.mean([x[f"mfe_{hm}"] for x in xs])), 2) if xs else None
            out[f"mae_{hm}"] = round(float(np.mean([x[f"mae_{hm}"] for x in xs])), 2) if xs else None
        return out

    T = {}
    for side, dv in (("bearish", -1), ("bullish", 1)):
        xs = [x for x in sig if x["dir"] == dv]
        T[side] = {"2021-2023": summary(xs), **{y: summary([x for x in xs if x["time"][:4] == y]) for y in ("2021", "2022", "2023")}}
    return T


def main():
    b = load()
    assert max(b["t"]) <= END + " 23:59:59"
    res = dict(source=SRC, end=END, memory=MEMORY, band=BAND, day_pct=DAY_PCT, draws=DRAWS, seed=SEED, defs={})
    for name, fn in (("R-A rolling memory", run_ra), ("R-B level-break flip", run_rb)):
        sig, fl = fn(b)
        res["defs"][name] = dict(regime=regime_stats(fl), tables=measure(b, sig))
        print(name, len(sig), "signals", res["defs"][name]["regime"])
    json.dump(res, open(os.path.join(OUT, "phase3_dev.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
