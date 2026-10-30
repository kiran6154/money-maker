"""Every spec §0 study on the current store, reported per §2.9 against the spec's headline numbers.

    python -m nifty_bt.books          -> results/nifty_bt/books/{summary.csv, report.md, <book>.csv}

Books (1 lot of 75 per leg, CE and PE legs, 2018-01 -> 2026-10-19):
  §12.2  Supertrend-swing CHoCH / BOS grid (p100, p500up x 5m / 15m x ST(10,3) / (4,3) x positional / intraday x trail /
         trail+lock50 x CHoCH / CHoCH+BOS x no filter / chop); per (pick, mode, side) the book with the best 2018-22 net
  §6.6   p100 SELL (15m ST(4,3) + 5m confirm, ST exit, lock50 / ₹50) + BUY (same, lock -> expiry); §6.3 1m confirm, ST exit
  §6.4-5 the same rules on p500up (deep ITM, illiquid)
  §12.4  pivot CHoCH -> ST confirm (15m: SELL ST(10,3), BUY ST(4,3), CHoCH + BOS)
  §12.5  intraday 5m-confirm grid (p100 / p500up x 5m / 15m premium ST x (4,3) / (10,3) x ST / chandelier / EMA20 exit x
         lock none / 20 / 40 x filter none / daily / chop), best 2018-22 book per (pick, side)
  §12.6  dual Supertrend intraday (p100, 3m / 5m, pairs (10,4)/(5,2) and (14,4)/(7,2), caps 1 / 2 / none)
  §12.3  1-min ST swings, 5-min signals (p100, ST(4,3) / (10,4))
  §12.7  lot scaling + compounding on p500up positional SELL + BUY (₹1 slippage)
  §5.5   per-trade hedge on the p100 SELL book;  §12.8 late entry on p100 BUY;  §4.7 day-type score at 12:00
"""
import os, time, json
import numpy as np, pandas as pd
from . import data, chain, engine as E, research as R, filters as F, report as RP

NEXP = int(os.environ.get("NBT_NEXP", "0"))                     # smoke test: only the last N expiries, separate output
OUT = os.path.join(chain.CACHE, "books" + (f"_test{NEXP}" if NEXP else ""))
SPEC = {   # spec headline net (₹) to compare
    "§6.6 p100 SELL (G3 rules)": 792410, "§6.6 p100 BUY (G4 rules)": 947207, "§6.6 p100 SELL + BUY": 1740000,
    "§6.3 p100 SELL 1m confirm -> ST up": 784000, "§12.2 p100 positional SELL + BUY": 1483000,
    "§12.2 p500up positional SELL + BUY": 4136000, "§12.2 p100 intraday SELL + BUY": 426000,
    "§12.4 p100 15m CHoCH -> ST SELL + BUY": 1518000, "§12.5 intraday portfolio (4 legs)": 857000,
    "§6.4 p500up SELL lock (ST(4,3) + 5m)": 1518000, "§6.5 p500up BUY lock -> expiry": 1420000,
}


def _families(P):
    out = {}
    for pick in ("p100", "p500up"):
        q = P[P.pick == pick]
        out[pick] = (q.groupby(["expiry", "strike", "right"]).date.apply(set).to_dict(), q.groupby(["expiry", "strike", "right"]).date.min().to_dict())
    return out


def candidates(log=print):
    P = pd.read_parquet(os.path.join(chain.CACHE, "picks.parquet"))
    fam = _families(P); cand = {k: [] for k in ("swing", "sell", "buy", "chochst", "intra", "dual", "s1m5m")}
    frames = {k: [] for k in cand}
    exps = sorted(set(e for f in fam.values() for (e, _, _) in f[0])); t0 = time.time()
    if NEXP: exps = exps[-NEXP:]
    for n, e in enumerate(exps):
        keys = {pk: [(k, r) for (e2, k, r) in fam[pk][0] if e2 == e] for pk in fam}
        X = data.read_expiry(e, strikes={k for v in keys.values() for k, _ in v})
        if X is None: continue
        G = {(int(k), r): g.reset_index(drop=True) for (k, r), g in X.groupby(["strike", "right"])}
        for pk, (wd, first) in fam.items():
            for k, r in keys[pk]:
                g = G.get((k, r))
                if g is None: continue
                C = E.Contract(e, k, r, g, wd[(e, k, r)], first[(e, k, r)])
                if not C.ok(): continue
                tag = lambda xs: [dict(x, pick=pk) for x in xs]
                for tf in (5, 15):
                    for p, m in ((10, 3.0), (4, 3.0)):
                        cand["swing"] += tag(E.stswing(C, tf, p, m, ("positional", "intraday"), ("trail", "trail+lock50")))
                cand["sell"] += tag(E.conf_sell(C, 4, 3.0, ("1m", "5m"), ("st_up",), ("none", "tgt50", "exp")))
                cand["buy"] += tag(E.conf_buy(C, 4, 3.0, ("5m",), ("st_dn",), ("normal", "lock_exp", "lock_2x")))
                for p, m in ((10, 3.0), (4, 3.0)): cand["chochst"] += tag(E.chochst(C, 15, 2, p, m))
                for d in (-1, 1):
                    for tf in (5, 15):
                        for p, m in ((4, 3.0), (10, 3.0)):
                            cand["intra"] += tag(E.intraday(C, d, tf, p, m, ("5m",), ("st", "chandelier", "ema20"), ("none", "lock20", "lock40")))
                if pk == "p100":
                    for tf in (3, 5):
                        for sl, fa in (((10, 4.0), (5, 2.0)), ((14, 4.0), (7, 2.0))): cand["dual"] += R.dual_st(C, tf, sl, fa)
                    for p, m in ((4, 3.0), (10, 4.0)): cand["s1m5m"] += tag(R.stswing_1m5m(C, p, m))
        for k, v in cand.items():                                   # compact per expiry (memory: the machine is shared)
            if v:
                df = pd.DataFrame(v)
                for c in df.columns:
                    if df[c].dtype == object and c not in ("sig",): df[c] = df[c].astype("category")
                frames[k].append(df); cand[k] = []
        if n % 25 == 0: log(f"{n}/{len(exps)} {e} " + " ".join(f"{k}:{sum(map(len, v))}" for k, v in frames.items()) + f" {time.time() - t0:.0f}s")
    out = {}
    for k, v in frames.items():
        df = pd.concat(v, ignore_index=True)
        for c in df.columns:
            if isinstance(df[c].dtype, pd.CategoricalDtype): df[c] = df[c].astype(str) if c not in ("entry_time", "exit_time") else df[c]
        out[k] = df
    return out


def best_train(books, keys):
    """the book with the best 2018-22 net among `keys` (pre-registered choice, read on 2023-26 without re-picking)."""
    return max(keys, key=lambda k: books[k][books[k].year <= 2022].net.sum() if len(books[k]) else -1e18)


def cached_candidates(log=print):
    """candidates are saved per study after the expiry pass (it takes ~40 minutes); delete OUT/cand_*.parquet to rebuild."""
    fs = {k: os.path.join(OUT, f"cand_{k}.parquet") for k in ("swing", "sell", "buy", "chochst", "intra", "dual", "s1m5m")}
    if all(os.path.exists(f) for f in fs.values()): return {k: pd.read_parquet(f) for k, f in fs.items()}
    C = candidates(log)
    for k, f in fs.items(): C[k].to_parquet(f)
    return C


def run(log=print):
    os.makedirs(OUT, exist_ok=True); C = cached_candidates(log); B = {}; rows = []
    def add(name, T):
        B[name] = T; s = RP.stats(T, name)
        if name in SPEC: s["spec_net"] = SPEC[name]; s["vs_spec"] = f"{(s['net'] / SPEC[name] - 1) * 100:+.0f}%"
        rows.append(s); T.to_csv(os.path.join(OUT, name.replace(" ", "_").replace("/", "-").replace("§", "S").replace(">", "") + ".csv"), index=False)
    # §12.2 grid
    S = C["swing"]; S["f_chop"] = F.chop_ok(S.sig, S.side, S.right); grid = {}
    for (pk, side, st, mode, lock), x0 in S.groupby(["pick", "side", "st", "mode", "lock"]):
        for sigs in ("CHoCH", "CHoCH+BOS"):
            x1 = x0 if sigs == "CHoCH+BOS" else x0[x0.kind == "CHoCH"]
            for filt in ("none", "chop"):
                grid[(pk, side, st, sigs, mode, lock, filt)] = E.sequence((x1 if filt == "none" else x1[x1.f_chop]).reset_index(drop=True))
    both = sum(1 for T in grid.values() if T[T.year <= 2022].net.sum() > 0 and T[T.year >= 2023].net.sum() > 0)
    log(f"§12.2 grid: {both}/{len(grid)} books positive in both halves (spec 218/256)")
    add("§12.2 G1 rules: p100 positional SELL 5m ST(4,3) CHoCH+BOS lock50", grid[("p100", -1, "5m ST(4,3)", "CHoCH+BOS", "positional", "trail+lock50", "none")])
    add("§12.2 G2 rules: p100 positional BUY 15m ST(4,3) CHoCH lock50", grid[("p100", 1, "15m ST(4,3)", "CHoCH", "positional", "trail+lock50", "none")])
    for pk in ("p100", "p500up"):
        for mode in ("positional", "intraday"):
            legs = [grid[best_train(grid, [k for k in grid if k[0] == pk and k[4] == mode and k[1] == sd])] for sd in (-1, 1)]
            add(f"§12.2 {pk} {mode} SELL + BUY", pd.concat(legs).sort_values("exit_time"))
    # §6.3 / §6.6 / §6.4-5
    sell, buy = C["sell"], C["buy"]
    q = lambda x, **kw: E.sequence(x[np.logical_and.reduce([x[k] == v for k, v in kw.items()])].reset_index(drop=True))
    add("§6.3 p100 SELL 1m confirm -> ST up", q(sell, pick="p100", conf="1m", lock="none"))
    s66, b66 = q(sell, pick="p100", conf="5m", lock="tgt50"), q(buy, pick="p100", conf="5m", lock="lock_exp")
    add("§6.6 p100 SELL (G3 rules)", s66); add("§6.6 p100 BUY (G4 rules)", b66); add("§6.6 p100 SELL + BUY", pd.concat([s66, b66]).sort_values("exit_time"))
    s5, b5 = q(sell, pick="p500up", conf="5m", lock="tgt50"), q(buy, pick="p500up", conf="5m", lock="lock_exp")
    add("§6.4 p500up SELL lock (ST(4,3) + 5m)", s5); add("§6.5 p500up BUY lock -> expiry", b5)
    # §12.4
    ch = C["chochst"]
    cs = q(ch, pick="p100", side=-1, st="15m CHoCH → ST(10,3) confirm"); cb = q(ch, pick="p100", side=1, st="15m CHoCH → ST(4,3) confirm")
    add("§12.4 p100 15m CHoCH -> ST SELL + BUY", pd.concat([cs, cb]).sort_values("exit_time"))
    # §12.5
    I5 = C["intra"]; I5["f_chop"] = F.chop_ok(I5.sig, I5.side, I5.right); I5["f_daily"] = F.daily_ok(I5.sig, I5.side, I5.right); ig = {}
    for (pk, side, st, ex, lk), x0 in I5.groupby(["pick", "side", "st", "exit_rule", "lock"]):
        for filt in ("none", "daily", "chop"):
            ig[(pk, side, st, ex, lk, filt)] = E.sequence((x0 if filt == "none" else x0[x0[f"f_{filt}"]]).reset_index(drop=True))
    both5 = sum(1 for T in ig.values() if T[T.year <= 2022].net.sum() > 0 and T[T.year >= 2023].net.sum() > 0)
    log(f"§12.5 5m-confirm grid: {both5}/{len(ig)} positive in both halves")
    legs = [ig[best_train(ig, [k for k in ig if k[0] == pk and k[1] == sd])] for pk in ("p100", "p500up") for sd in (-1, 1)]
    add("§12.5 intraday portfolio (4 legs)", pd.concat(legs).sort_values("exit_time"))
    # §12.6 dual ST
    D = C["dual"]; dg = {}
    for (side, tf, pair, ent, ex), x0 in D.groupby(["side", "tf", "pair", "entry_rule", "exit_rule"]):
        for cap in (1, 2, None): dg[(side, tf, pair, ent, ex, cap)] = R.sequence_capped(x0.reset_index(drop=True), cap)
    for sd, nm in ((-1, "SELL"), (1, "BUY")):
        k = best_train(dg, [k for k in dg if k[0] == sd]); add(f"§12.6 dual ST {nm} best on 2018-22 {k[1:]}", dg[k])
    # §12.3
    s15 = C["s1m5m"]
    for p_ in ("1m ST(4,3) swings · 5m signals", "1m ST(10,4) swings · 5m signals"):
        add(f"§12.3 p100 SELL + BUY {p_}", q(s15, st=p_))
    # §12.7
    port = pd.concat([s5.assign(side=-1), b5.assign(side=1)]).sort_values("exit_time").reset_index(drop=True)
    cap = RP.capital_per_lot(port, slip=1.0); comp = {}
    for nm, pol in (("fixed 1 lot", RP.Fixed), ("double, never reduce", RP.DoubleUp), ("double / halve", RP.DoubleUpDown), ("add 1 lot", RP.AddOne)):
        _, comp[nm] = RP.compound(port, pol(cap, 10), slip=1.0)
    # §5.5 hedge, §12.8 late entry, §4.7 day type
    hz = R.hedge(s66, chain.chain_0919(), data.read_expiry)
    hedge = {f"₹{t}": dict(naked=round(hz.net_naked.sum()), hedged=round(hz[f"net_h{t}"].sum())) for t in (5, 10, 20)}
    S_ = pd.DataFrame(rows); S_.to_csv(os.path.join(OUT, "summary.csv"), index=False)
    extra = dict(swing_grid_both_positive=f"{both}/{len(grid)}", intraday_grid_both_positive=f"{both5}/{len(ig)}",
                 capital_per_lot_p500up_slip1=round(cap), compounding=comp, hedge_p100_sell=hedge)
    json.dump(extra, open(os.path.join(OUT, "extra.json"), "w"), indent=1, default=str)
    return S_, extra


if __name__ == "__main__":
    S_, extra = run(lambda s: print(s, flush=True))
    pd.set_option("display.width", 250); pd.set_option("display.max_colwidth", 70)
    print(S_.drop(columns=["by_year"]).to_string(index=False)); print(json.dumps(extra, indent=1, default=str))
