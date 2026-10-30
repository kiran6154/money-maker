"""tools/bandlab_oi.py - research bot 6 ("open interest") on the band -> structure bench (tools/bandlab.py, S149).

Question: does OPEN INTEREST give a better sideways band, a better entry trigger, or a better filter?

Builds (causal - a value at minute t uses prints at or before t of the same session; cached under cache/bandlab_oi/):
  fut_oi   the near-month futures OI on every 1-minute bar of the bench series (joined by datetime and contract expiry)
  opt5     per session and 5-minute bucket (09:15-09:19 = bucket 0, known at its last minute) for the nearest option expiry
           >= the day: spot (index close), the call wall (highest CE OI strike in (spot, spot+300]) and put wall (highest PE
           OI strike in [spot-300, spot)), sum CE / PE OI over strikes within 300 of the ATM, and how many strikes had OI
  Regular option files only (the *.wide files with far strikes are skipped).
Features (1-minute arrays aligned with BL.data()[0]):
  regime15 / regime30  futures price vs OI change over 15 / 30 minutes on 5-minute snapshots: +1 long build-up,
                       +2 short covering, -1 short build-up, -2 long unwinding (0 = unknown)
  pcr, pcr_ma (20 x 5-minute SMA, same session), dpe15 / dpe30 = change in PE OI - change in CE OI (window sums)
  the OI-wall band "oiwall" = (call wall, put wall) + the futures basis at that bucket (walls are index strikes)
Tests: python tools/bandlab_oi.py build | run   ->  results/bandlab/oi.md, results/bandlab/oi_grid.csv
"""
import os
import sys
import glob
import time
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
if HERE not in sys.path: sys.path.insert(0, HERE)
import numpy as np
import pandas as pd
import bandlab as BL
import core

ROOT = "D:/nifty_data"
CDIR = os.path.join(HERE, "cache", "bandlab_oi")
RES = os.path.join(HERE, "results", "bandlab")
DAY = 86400
NB = 75                     # 5-minute buckets 09:15 .. 15:29


# ---------------------------------------------------------------- builds
def build_fut_oi():
    p = os.path.join(CDIR, "fut_oi.npy")
    if os.path.exists(p): return np.load(p)
    f = BL.data()[0]
    files = sorted(glob.glob(os.path.join(ROOT, "futures", "1minute", "*", "*.parquet")))
    parts = []
    for x in files:
        d = pd.read_parquet(x, columns=["datetime", "open_interest", "expiry"])
        parts.append(d)
    df = pd.concat(parts, ignore_index=True)
    df["t"] = df["datetime"].to_numpy().astype("datetime64[s]").astype("int64")
    df["e"] = pd.to_datetime(df["expiry"]).dt.strftime("%Y-%m-%d")
    df = df.drop_duplicates(["t", "e"], keep="last")
    key = pd.DataFrame({"t": f.t, "e": f.extra["expiry"].astype(str)})
    m = key.merge(df[["t", "e", "open_interest"]], on=["t", "e"], how="left")
    oi = m["open_interest"].to_numpy(float)
    oi[oi <= 0] = np.nan
    os.makedirs(CDIR, exist_ok=True); np.save(p, oi)
    return oi


def _expiries():
    out = []
    for d in glob.glob(os.path.join(ROOT, "options", "1minute", "*", "*")):
        e = os.path.basename(d)
        if os.path.isdir(d) and len(e) == 10 and glob.glob(os.path.join(d, "*.parquet")): out.append(e)
    return sorted(out)


def _index_close():
    files = sorted(glob.glob(os.path.join(ROOT, "index", "1minute", "*", "*.parquet")))
    df = pd.concat([pd.read_parquet(x, columns=["datetime", "close"]) for x in files], ignore_index=True)
    t = df["datetime"].to_numpy().astype("datetime64[s]").astype("int64")
    df = pd.DataFrame({"t": t, "c": df["close"].to_numpy(float)}).drop_duplicates("t", keep="last").sort_values("t")
    df["day"] = df.t // DAY; df["MIN"] = (df.t % DAY) // 60
    df = df[(df.MIN >= 555) & (df.MIN <= 929)]
    df["b"] = (df.MIN - 555) // 5
    g = df.groupby(["day", "b"])["c"].last()
    return g


def _one_expiry(e, prev, spot):
    """Rows (day, b, spot, cw, pw, cwoi, pwoi, sce, spe, nce, npe, nwin) for the days this expiry is the nearest one."""
    d0 = (pd.Timestamp(prev) + pd.Timedelta(days=1)).strftime("%Y-%m-%d") if prev else "0000"
    files = []
    for p in sorted(glob.glob(os.path.join(ROOT, "options", "1minute", e[:4], e, "*.parquet"))):
        n = os.path.basename(p)
        if ".wide" in n: continue
        n = n.replace(".partial", "").replace(".parquet", "")
        a, z = n.split("__") if "__" in n else ("0000", n)
        if z >= d0 and a <= e: files.append(p)
    if not files: return None
    df = pd.concat([pd.read_parquet(p, columns=["datetime", "strike", "right", "open_interest"]) for p in files], ignore_index=True)
    t = df["datetime"].to_numpy().astype("datetime64[s]").astype("int64")
    day = t // DAY; MIN = (t % DAY) // 60
    lo_day = (pd.Timestamp(prev).value // 10**9) // DAY if prev else -1
    hi_day = (pd.Timestamp(e).value // 10**9) // DAY
    m = (day > lo_day) & (day <= hi_day) & (MIN >= 555) & (MIN <= 929)
    df = pd.DataFrame({"t": t[m], "day": day[m], "b": (MIN[m] - 555) // 5, "k": df["strike"].to_numpy()[m],
                       "r": (df["right"].astype(str).to_numpy()[m] == "PE").astype(np.int8), "oi": df["open_interest"].to_numpy(float)[m]})
    del t, day, MIN
    df = df.sort_values("t").drop_duplicates(["t", "k", "r"], keep="last")
    last = df.groupby(["day", "b", "r", "k"])["oi"].last()
    rows = []
    for dy, g in last.groupby(level=0):
        g = g.droplevel(0)
        K = np.array(sorted(g.index.get_level_values(2).unique()), float)
        mats = []
        for r in (0, 1):
            try: s = g.xs(r, level=1)
            except KeyError: s = pd.Series(dtype=float, index=pd.MultiIndex.from_arrays([[], []]))
            M = s.unstack(level=1).reindex(index=range(NB), columns=K).ffill().to_numpy(float) if len(s) else np.full((NB, len(K)), np.nan)
            mats.append(M)
        CE, PE = mats
        try: sp = spot.loc[dy].reindex(range(NB)).ffill().to_numpy(float)
        except KeyError: continue
        for b in range(NB):
            s0 = sp[b]
            if not np.isfinite(s0): continue
            ce, pe = CE[b], PE[b]
            atm = round(s0 / 50) * 50
            w = np.abs(K - atm) <= 300
            up_m = (K > s0) & (K <= s0 + 300) & np.isfinite(ce)
            dn_m = (K < s0) & (K >= s0 - 300) & np.isfinite(pe)
            cw = K[up_m][np.argmax(ce[up_m])] if up_m.any() else np.nan
            cwoi = ce[up_m].max() if up_m.any() else np.nan
            pw = K[dn_m][np.argmax(pe[dn_m])] if dn_m.any() else np.nan
            pwoi = pe[dn_m].max() if dn_m.any() else np.nan
            rows.append((dy, b, s0, cw, pw, cwoi, pwoi, np.nansum(ce[w]), np.nansum(pe[w]), int(np.isfinite(ce[w]).sum()),
                         int(np.isfinite(pe[w]).sum()), int(w.sum())))
    return rows


def build_opt5():
    p = os.path.join(CDIR, "opt5.parquet")
    if os.path.exists(p): return pd.read_parquet(p)
    os.makedirs(CDIR, exist_ok=True)
    spot = _index_close()
    ex = _expiries(); allrows = []
    t0 = time.time()
    for j, e in enumerate(ex):
        cp = os.path.join(CDIR, f"exp_{e}.parquet")
        if os.path.exists(cp): allrows.append(pd.read_parquet(cp)); continue
        rows = _one_expiry(e, ex[j - 1] if j else None, spot)
        d = pd.DataFrame(rows or [], columns=["day", "b", "spot", "cw", "pw", "cwoi", "pwoi", "sce", "spe", "nce", "npe", "nwin"])
        d["expiry"] = e
        d.to_parquet(cp); allrows.append(d)
        print(e, len(d), f"{time.time() - t0:.0f}s", flush=True)
    df = pd.concat(allrows, ignore_index=True).drop_duplicates(["day", "b"], keep="first").sort_values(["day", "b"])
    df.to_parquet(p)
    return df


# ---------------------------------------------------------------- features on the 1-minute series
def features():
    if ("oi", "F") in BL._D: return BL._D[("oi", "F")]
    f, MIN, cut, ses, year = BL.data(); n = len(f.t)
    foi = build_fut_oi(); O = build_opt5()
    b1 = np.clip((MIN - 555) // 5, 0, NB - 1)
    is_end = ((MIN - 555) % 5 == 4) | (np.r_[ses[1:] != ses[:-1], True])       # last minute of a bucket (or session)
    # futures 5-minute snapshots: close and OI at each bucket's last available minute, same session
    F = {}
    snap = pd.DataFrame({"day": f.day, "b": b1, "c": f.c, "oi": foi}).groupby(["day", "b"]).last()
    snap["oi"] = snap.groupby(level=0)["oi"].ffill()
    for L, k in ((15, 3), (30, 6)):
        dc = snap.groupby(level=0)["c"].diff(k); do = snap.groupby(level=0)["oi"].diff(k)
        reg = np.where((dc > 0) & (do > 0), 1, np.where((dc > 0) & (do < 0), 2, np.where((dc < 0) & (do > 0), -1, np.where((dc < 0) & (do < 0), -2, 0))))
        snap[f"reg{L}"] = reg; snap[f"doi{L}"] = do
    O = O.set_index(["day", "b"])
    O["pcr"] = O.spe / O.sce.replace(0, np.nan)
    O.loc[(O.nce < 3) | (O.npe < 3), "pcr"] = np.nan
    O["pcr_ma"] = O.groupby(level=0)["pcr"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    for L, k in ((15, 3), (30, 6)):
        O[f"dpe{L}"] = O.groupby(level=0)["spe"].diff(k) - O.groupby(level=0)["sce"].diff(k)
        O.loc[(O.nce < 3) | (O.npe < 3), f"dpe{L}"] = np.nan
        O[f"dpcr{L}"] = O.groupby(level=0)["pcr"].diff(k)
    J = snap.join(O, how="left")
    # map to 1-minute: value of bucket b known from its last minute; earlier minutes of b see bucket b-1
    key = pd.MultiIndex.from_arrays([f.day, b1])
    V = J.reindex(key)
    out = {}
    for col in ("reg15", "reg30", "doi15", "doi30", "pcr", "pcr_ma", "dpe15", "dpe30", "dpcr15", "dpcr30", "cw", "pw", "spot", "c", "nce", "npe", "nwin"):
        a = V[col].to_numpy(float).copy()
        a[~is_end] = np.nan
        s = pd.Series(a); a = s.groupby(ses).ffill().to_numpy()
        out[col] = a
    out["basis"] = out["c"] - out["spot"]
    for c_ in ("reg15", "reg30"): out[c_] = np.nan_to_num(out[c_]).astype(np.int8)
    out["bucket_end"] = is_end
    BL._D[("oi", "F")] = out
    up = out["cw"] + out["basis"]; lo = out["pw"] + out["basis"]
    BL._D[("band", "oiwall")] = (up, lo)
    return out


# ---------------------------------------------------------------- the walk (BL.simulate + a filter and a signal entry)
def simulate(band=None, entry="cross", ev="any", etf=1, emode="touch", exit="choch", xtf=1, xmode="touch",
             esc_pts=20.0, esc_tf=5, first=570, last=870, max_day=1, allow=None, sig=None):
    """allow: int8 per minute, bit 1 = a long may enter, bit 2 = a short may enter (None = all).
    sig: int8 per minute in {-1, 0, +1} - an OI crossover at that minute's close; with sig the band is not used:
         entry "cross" enters on the signal, "cross_struct" arms on it (disarmed by the opposite signal / the session end)
         and enters on the first `ev` event that way."""
    f, MIN, cut, ses, year = BL.data(); n = len(f.t)
    if sig is None: up, lo = BL.bands(band)
    E = BL.structure(etf, emode); X = BL.structure(xtf, xmode); H = BL.structure(esc_tf, xmode) if exit == "escalate" else None
    ee = {"choch": E["choch"], "bos": E["bos"], "any": np.where(E["choch"] != 0, E["choch"], E["bos"])}[ev]
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
                if exit == "choch" and X["choch"][i] == -pos: why = "choch"
                elif exit == "escalate":
                    if not esc and pos * (ci - epx) >= esc_pts: esc = True
                    if (H if esc else X)["choch"][i] == -pos: why = "esc_choch" if esc else "choch"
            if why:
                j = i if (last_bar and why == "eod") else i + 1
                out.append((pos, e, j, epx, (c[i] if j == i else o[j]), why)); pos = 0
            continue
        if sig is not None:
            if sig[i]: armed = sig[i]
            if MIN[i] < first or MIN[i] > last or taken >= max_day or ses[i + 1] != s_: continue
            if entry == "cross": s = sig[i]
            else: s = armed if (armed and ee[i] == armed) else 0
        else:
            if MIN[i] < first or MIN[i] > last or taken >= max_day or ses[i + 1] != s_ or not np.isfinite(up[i]) or not np.isfinite(up[i - 1]):
                continue
            ci, cp = c[i], c[i - 1]
            crossed = 1 if (cp <= up[i - 1] and ci > up[i]) else -1 if (cp >= lo[i - 1] and ci < lo[i]) else 0
            if entry == "cross":
                s = crossed
            else:
                if crossed: armed = crossed
                if armed and lo[i] <= ci <= up[i]: armed = 0
                s = armed if (armed and ee[i] == armed) else 0
        if s and allow is not None and not (allow[i] & (1 if s > 0 else 2)): s = 0
        if s:
            pos, e, epx, esc, taken, armed = s, i + 1, o[i + 1], False, taken + 1, 0
    return out


def stats(tr, label, **kw):
    r = BL.evaluate(tr, label)
    r.update(kw)
    if not tr: return r
    f, MIN, cut, ses, year = BL.data()
    a = np.array([x[1] for x in tr]); g = np.array([x[0] * (x[4] - x[3]) for x in tr])
    chg = np.array([BL.JF._charges(core.dstr(int(f.day[i])), "FUT", f.o[i], f.o[i], 65)["total"] / 65 for i in a]) + 1.0
    yy = year[a]
    for nm, m in (("A", yy <= 2022), ("B", yy >= 2023), ("26", yy == 2026)):
        r[f"gross{nm}"] = float(g[m].mean()) if m.any() else np.nan
        r[f"cost{nm}"] = float(chg[m].mean()) if m.any() else np.nan
    r["n26"] = int((yy == 2026).sum())
    return r


# ---------------------------------------------------------------- filters
def filters(F):
    """allow arrays (bit 1 long, bit 2 short), defined before looking at any result (see oi.md for the IS read)."""
    def ls(lmask, smask):
        return (np.where(lmask, 1, 0) | np.where(smask, 2, 0)).astype(np.int8)
    r15, r30 = F["reg15"], F["reg30"]
    pcr, dpcr30, dpe30, dpe15, doi30 = F["pcr"], F["dpcr30"], F["dpe30"], F["dpe15"], F["doi30"]
    with np.errstate(invalid="ignore"):
        return {
            "buildup30": ls(r30 == 1, r30 == -1),                         # fresh positions that way (OI up)
            "cover30": ls(r30 == 2, r30 == -2),                           # short covering / long unwinding (OI down)
            "buildup15": ls(r15 == 1, r15 == -1),
            "oi_up30": ls(doi30 > 0, doi30 > 0),                          # futures OI rising, either side
            "oi_dn30": ls(doi30 < 0, doi30 < 0),
            "pcr_rise30": ls(dpcr30 > 0, dpcr30 < 0),                     # PCR moving with the trade
            "pcr_lvl": ls(pcr > 1, pcr < 1),
            "dpe30": ls(dpe30 > 0, dpe30 < 0),                            # puts written faster than calls -> long
            "dpe15": ls(dpe15 > 0, dpe15 < 0),
            "dpe30_contra": ls(dpe30 < 0, dpe30 > 0),
        }


def crossings(F):
    f, MIN, cut, ses, year = BL.data()
    end = F["bucket_end"]
    def cross(x, y):
        s = np.zeros(len(x), np.int8)
        idx = np.nonzero(end)[0]
        xv, yv = x[idx], (y[idx] if hasattr(y, "__len__") else np.full(len(idx), y))
        same = ses[idx][1:] == ses[idx][:-1]
        d0, d1 = xv[:-1] - yv[:-1], xv[1:] - yv[1:]
        with np.errstate(invalid="ignore"):
            up = same & (d0 <= 0) & (d1 > 0); dn = same & (d0 >= 0) & (d1 < 0)
        s[idx[1:][up]] = 1; s[idx[1:][dn]] = -1
        return s
    return {"pcr_x_ma": cross(F["pcr"], F["pcr_ma"]), "pcr_x_1": cross(F["pcr"], 1.0),
            "dpe15_x0": cross(F["dpe15"], 0.0), "dpe30_x0": cross(F["dpe30"], 0.0)}


EXITS = (dict(exit="choch", xtf=5), dict(exit="escalate", xtf=1, esc_tf=15, esc_pts=20.0))
ENTRIES = (dict(entry="cross"), dict(entry="cross_struct", ev="any", etf=1), dict(entry="cross_struct", ev="any", etf=5))


def _lab(d):
    return " ".join(f"{k}={v}" for k, v in d.items())


def coverage(F):
    f, MIN, cut, ses, year = BL.data()
    O = build_opt5(); foi = build_fut_oi()
    O["year"] = [int(core.dstr(int(d))[:4]) for d in O.day]
    days = pd.Series(f.day).groupby(year).nunique()
    rows = []
    for y in sorted(set(year)):
        m = year == y; o = O[O.year == y]
        nb = days[y] * NB
        rows.append(dict(year=y, sessions=int(days[y]), fut_oi_known=f"{np.isfinite(foi[m]).mean() * 100:.0f}%",
                         opt_sessions=int(o.day.nunique()), buckets_na=f"{(1 - len(o.dropna(subset=['cw', 'pw'])) / nb) * 100:.0f}%",
                         pcr_na=f"{(1 - ((o.nce >= 3) & (o.npe >= 3)).sum() / nb) * 100:.0f}%",
                         strikes_ce=f"{o.nce.mean():.1f}/{o.nwin.mean():.0f}", strikes_pe=f"{o.npe.mean():.1f}",
                         wall_width=f"{(o.cw - o.pw).median():.0f}", expiries=int(o.expiry.nunique())))
    return pd.DataFrame(rows)


def run():
    t0 = time.time()
    F = features(); print("features", f"{time.time() - t0:.0f}s", flush=True)
    rows = []
    def go(tr, **kw):
        r = stats(tr, kw.pop("label"), **kw); rows.append(r)
        print(r["label"], r.get("n"), round(r.get("pfA", 0), 2) if r.get("n") else "", round(r.get("pfB", 0), 2) if r.get("n") else "", f"{time.time() - t0:.0f}s", flush=True)
    # 1. the OI-wall band
    for en in ENTRIES:
        for xx in EXITS:
            go(simulate("oiwall", **en, **xx), label=f"oiwall {_lab(en)} | {_lab(xx)}", test="band", band="oiwall", filt="none")
    # reference bands, unfiltered + filtered
    FL = filters(F)
    for b in ("or15", "jilly", "vwap2"):
        for en in ENTRIES:
            for xx in EXITS:
                go(simulate(b, **en, **xx), label=f"{b} {_lab(en)} | {_lab(xx)} | none", test="filter", band=b, filt="none")
                for fn, al in FL.items():
                    go(simulate(b, **en, **xx, allow=al), label=f"{b} {_lab(en)} | {_lab(xx)} | {fn}", test="filter", band=b, filt=fn)
    # 3. OI crossovers as entries
    for sn, sg in crossings(F).items():
        for en in ENTRIES:
            for xx in EXITS:
                go(simulate(None, **en, **xx, sig=sg), label=f"{sn} {_lab(en)} | {_lab(xx)}", test="xover", band=sn, filt="none")
    df = pd.DataFrame(rows)
    df["exits"] = df["exits"].astype(str)
    os.makedirs(RES, exist_ok=True)
    df.to_csv(os.path.join(RES, "oi_grid.csv"), index=False)
    coverage(F).to_csv(os.path.join(CDIR, "coverage.csv"), index=False)
    print("done", f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "build":
        oi = build_fut_oi(); print("fut oi known", np.isfinite(oi).mean())
        O = build_opt5(); print(len(O))
    elif cmd == "cov":
        print(coverage(features()).to_string())
    else:
        run()
