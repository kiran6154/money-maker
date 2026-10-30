"""C2C research, phases 1 and 3 (research programme 2026-09-29, ledger EXP-001 .. EXP-003).

Question A only: does the CHoCH retest signal (Strategy 25's entry, and its bullish mirror) predict the NIFTY move?
No option prices are used here. Frozen rules, no parameter is fitted:
  bearish: trend flipped down (engine flip), a swing high confirms at i, anchored VWAP - 50 < SH < VWAP + 50, i is not the
           flip candle, close[i] > session open x 0.994            -> short NIFTY from the open of candle i+1
  bullish: trend flipped up, a swing low confirms at i, VWAP - 50 < SL < VWAP + 50 (VWAP anchored at the trough the flip
           re-anchors at), not the flip candle, close[i] < session open x 1.006   -> long NIFTY from the open of i+1
  (the PCR rule is left out: no option OI before 2026)
Data: the long NIFTY 5-minute index file (2019-2026; agrees with Kite in 2026 - the Breeze index file used by the lab has
corrupt 15:20 candles, EXP-001). Engine: break and CHoCH by close, equal-weighted AVWAP (the index has no volume), one run
from 2020-10-01 so 2021 starts warm.

For every signal, direction-signed moves from the entry open: close-to-close move, MFE and MAE at 5 .. 240 minutes (cut at
the session's end), to the session's close, to the next session's close, and to the opposite flip. Control: for each signal,
entries at every candle of the same year with the same time of day (same direction); the signal's excess over that bucket's
mean, and a randomisation test (2,000 draws of one random same-bucket entry per signal).
Regimes (pre-registered before any result): a calendar month is bullish above +2 %, bearish below -2 %, else flat (first open
to last close); a year is labelled the same way at +-10 %.

    python studies/c2c/phase1_3.py      # writes studies/c2c/phase1_3.json and studies/c2c/signals.csv
Nothing here writes to the lab's results, database or strategy files.
"""
import csv, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
import engine  # noqa: E402

SRC = "D:/nifty/nifty50_5minute_2019-01-01_to_2026-09-26.csv"
START, WARM_FROM = "2021-01-01", "2020-10-01"
BAND, DAY_PCT = 50, 0.6
H_MIN = (5, 10, 15, 30, 60, 120, 240)
DRAWS, SEED = 2000, 20260929
OUT = os.path.dirname(os.path.abspath(__file__))


def load():
    rows = [r for r in csv.DictReader(open(SRC)) if r["datetime"] >= WARM_FROM and r["datetime"][11:16] <= "15:25"]
    return dict(t=[r["datetime"] for r in rows], o=[float(r["open"]) for r in rows], h=[float(r["high"]) for r in rows],
                l=[float(r["low"]) for r in rows], c=[float(r["close"]) for r in rows], v=[0.0] * len(rows))


def month_regimes(b):
    first, last = {}, {}
    for i, t in enumerate(b["t"]):
        first.setdefault(t[:7], b["o"][i]); last[t[:7]] = b["c"][i]
    ret = {m: last[m] / first[m] - 1 for m in first}
    lab = lambda x, th: "bullish" if x > th else "bearish" if x < -th else "flat"
    fy, ly = {}, {}
    for i, t in enumerate(b["t"]):
        fy.setdefault(t[:4], b["o"][i]); ly[t[:4]] = b["c"][i]
    yret = {y: ly[y] / fy[y] - 1 for y in fy}
    return ({m: (lab(r, 0.02), round(r * 100, 2)) for m, r in ret.items()},
            {y: (lab(r, 0.10), round(r * 100, 2)) for y, r in yret.items()})


def main():
    b = load()
    r = engine.run(b, dict(break_mode="close", choch_mode="close", avwap_weight="equal", sl_rule="none"))
    t, o, h, l, c = (np.array(b[k]) if k != "t" else b[k] for k in "tohlc")
    n = len(t)
    day = [x[:10] for x in t]
    # session bounds
    last_of = np.zeros(n, dtype=int); first_open = {}
    s = 0
    for i in range(n):
        if i == n - 1 or day[i + 1] != day[i]:
            last_of[s:i + 1] = i; s = i + 1
        first_open.setdefault(day[i], o[i])
    reg = [(0, None, None)] * n
    cur = (0, None, None)
    flips = {e["i"]: e for e in r["chs"] if e["flip"]}
    for i in range(n):
        e = flips.get(i)
        if e: cur = (-1, i, e["hi"]["bar"]) if e["dir"] == "down" else (1, i, e["lo"]["bar"])
        reg[i] = cur
    flip_i = sorted(flips)
    # ATR(14) of 5-minute candles, value known at the close of i
    tr = np.maximum(h - l, np.maximum(abs(h - np.roll(c, 1)), abs(l - np.roll(c, 1)))); tr[0] = h[0] - l[0]
    atr = np.zeros(n); a = tr[0]
    for i in range(n):
        a = tr[:i + 1].mean() if i < 14 else (a * 13 + tr[i]) / 14; atr[i] = a

    # ---- signals
    sig = []
    for sw in sorted(r["sw"], key=lambda z: z["conf"]):
        i = sw["conf"]
        if t[i] < START or i + 1 >= n: continue
        want = -1 if sw["k"] == "H" else 1
        rg, fi, anchor = reg[i]
        if rg != want or fi == i: continue
        av = r["av"](anchor, i)
        if not (av - BAND < sw["p"] < av + BAND): continue
        d0 = first_open[day[i]]
        if want == -1 and not c[i] > d0 * (1 - DAY_PCT / 100): continue
        if want == 1 and not c[i] < d0 * (1 + DAY_PCT / 100): continue
        e = flips[fi]
        sig.append(dict(i=i, dir=want, time=t[i], entry_time=t[i + 1], entry=float(o[i + 1]), open_print=day[i + 1] != day[i],
                        swing=sw["p"], avwap=round(av, 2), dist_av=round(sw["p"] - av, 2), atr=round(float(atr[i]), 2),
                        bars_since_flip=i - fi, break_size=round(abs(c[fi] - e["lvl"]), 2), day_ret=round((c[i] / d0 - 1) * 100, 3)))

    # ---- forward moves, direction-signed, for any entry index e (vectorised over arrays of entries)
    def fwd(E, D):
        E, D = np.asarray(E), np.asarray(D)
        L = last_of[E]; e0 = o[E]; out = {}
        mx, mn = h[E].copy(), l[E].copy()
        m_needed = {hm // 5: hm for hm in H_MIN}
        for m in range(1, max(m_needed) + 1):
            k = np.minimum(E + m - 1, L)
            mx = np.maximum(mx, h[k]); mn = np.minimum(mn, l[k])
            if m in m_needed:
                hm = m_needed[m]
                out[f"move_{hm}"] = D * (c[k] - e0)
                out[f"mfe_{hm}"] = np.where(D > 0, mx - e0, e0 - mn)
                out[f"mae_{hm}"] = np.where(D > 0, mn - e0, e0 - mx)
                out[f"cut_{hm}"] = (E + m - 1 > L)
        out["move_eod"] = D * (c[L] - e0)
        nxt = np.minimum(L + 1, n - 1); nl = last_of[nxt]
        out["move_next"] = np.where(L + 1 < n, D * (c[nl] - e0), np.nan)
        return out

    E = [x["i"] + 1 for x in sig]; Dn = [x["dir"] for x in sig]
    F = fwd(E, Dn)
    # to the opposite flip (the baseline's structural exit), on the underlying
    for j, x in enumerate(sig):
        nf = next((k for k in flip_i if k > x["i"] and flips[k]["dir"] == ("up" if x["dir"] < 0 else "down")), None)
        x["to_flip_bars"] = (nf - x["i"] - 1) if nf is not None else None
        x["move_to_flip"] = round(float(x["dir"] * (c[nf] - x["entry"])), 2) if nf is not None else None
        for k, v in F.items(): x[k] = (bool(v[j]) if k.startswith("cut") else (None if np.isnan(v[j]) else round(float(v[j]), 2)))

    # ---- matched control: every candle of the same year and time of day as an entry
    allE = np.array([i for i in range(1, n) if t[i] >= START and day[i] == day[i - 1]])   # no 09:15 print (entry after a candle of the same session)
    ctl = {d: fwd(allE, np.full(len(allE), d)) for d in (-1, 1)}
    bucket = {}
    for j, e in enumerate(allE): bucket.setdefault((t[e][:4], t[e][11:16]), []).append(j)
    rng = np.random.default_rng(SEED)
    keys = [f"move_{hm}" for hm in H_MIN] + ["move_eod"]
    for x in sig:
        bj = bucket.get((x["entry_time"][:4], x["entry_time"][11:16]))
        x["bucket_n"] = len(bj) if bj else 0
        for k in keys:
            x[f"ctl_{k}"] = round(float(np.nanmean(ctl[x["dir"]][k][bj])), 3) if bj else None

    months, years = month_regimes(b)
    for x in sig:
        x["month_regime"] = months[x["time"][:7]][0]; x["year_regime"] = years[x["time"][:4]][0]

    def summary(xs, label):
        """Question A numbers for a set of signals (entries on the 09:15 print excluded from the control comparison)."""
        out = dict(label=label, n=len(xs))
        if not xs: return out
        use = [x for x in xs if not x["open_print"] and x["bucket_n"]]
        for k in keys + ["move_next", "move_to_flip"]:
            v = np.array([x[k] for x in xs if x[k] is not None], float)
            if len(v): out[k] = dict(mean=round(v.mean(), 2), median=round(float(np.median(v)), 2), hit=round((v > 0).mean() * 100, 1))
        for hm in H_MIN:
            out[f"mfe_{hm}"] = round(float(np.mean([x[f"mfe_{hm}"] for x in xs])), 2)
            out[f"mae_{hm}"] = round(float(np.mean([x[f"mae_{hm}"] for x in xs])), 2)
        # excess over the matched control, t-stat and randomisation percentile
        for k in keys:
            ex = np.array([x[k] - x[f"ctl_{k}"] for x in use])
            if len(ex) < 2: continue
            obs = np.mean([x[k] for x in use])
            draws = np.zeros(DRAWS)
            for x in use:
                bj = bucket[(x["entry_time"][:4], x["entry_time"][11:16])]
                draws += ctl[x["dir"]][k][rng.choice(bj, DRAWS)]
            draws /= len(use)
            out[f"excess_{k}"] = dict(n=len(ex), mean=round(ex.mean(), 2), t=round(ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex))), 2),
                                      p_random=round(float((draws >= obs).mean()), 4))
        out["to_flip_bars_median"] = float(np.median([x["to_flip_bars"] for x in xs if x["to_flip_bars"] is not None]))
        out["open_print_entries"] = sum(x["open_print"] for x in xs)
        return out

    res = dict(source=SRC, start=START, band=BAND, day_pct=DAY_PCT, draws=DRAWS, seed=SEED,
               months={m: v for m, v in months.items() if m >= "2021"}, years={y: v for y, v in years.items() if y >= "2021"}, tables={})
    for side, dv in (("bearish", -1), ("bullish", 1), ("both", 0)):
        xs = [x for x in sig if dv == 0 or x["dir"] == dv]
        T = res["tables"][side] = {"all": summary(xs, "all")}
        for y in sorted({x["time"][:4] for x in xs}): T[y] = summary([x for x in xs if x["time"][:4] == y], y)
        for g in ("bullish", "bearish", "flat"): T["month_" + g] = summary([x for x in xs if x["month_regime"] == g], "month " + g)
        for per, (a, z) in (("dev_2021_2023", ("2021", "2023")), ("val_2024", ("2024", "2024")), ("oos_2025_2026", ("2025", "2026"))):
            T[per] = summary([x for x in xs if a <= x["time"][:4] <= z], per)
    json.dump(res, open(os.path.join(OUT, "phase1_3.json"), "w"), indent=1)
    cols = list(sig[0].keys())
    with open(os.path.join(OUT, "signals.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(sig)
    print(f"{len(sig)} signals ({sum(x['dir'] < 0 for x in sig)} bearish, {sum(x['dir'] > 0 for x in sig)} bullish); wrote phase1_3.json, signals.csv")


if __name__ == "__main__":
    main()
