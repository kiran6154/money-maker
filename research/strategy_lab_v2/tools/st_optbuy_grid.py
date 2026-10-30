"""tools/st_optbuy_grid.py - option BUYING on Supertrend flips, every combination asked (S158).

The user, 2026-10-28: "check all different combinations of options buy using Supertrend - different Supertrend configs,
different price range 500+, ATM, less than 50; both intraday and positional; till expiry; what if the premium becomes 2x;
not closing it at all ... all combinations".

Grid, fixed before the run:
  Signal  : Supertrend (hl2, Wilder ATR) on near-month futures, 09:15-aligned candles of 1 / 5 / 15 / 60 minutes, configs
            (ATR length, multiplier) = (7, 2), (10, 2), (10, 3), (14, 4) -> 16 signal sets. A flip up buys a CE, a flip down
            a PE, at the minute after the flip candle closes, entries 09:20 - 15:00, one position at a time per combination.
  Expiry  : the nearest expiry on or after the signal day (weekly from 2019; monthly-only before) - 0DTE on expiry days.
  Strike  : ATM  = the index at the signal minute rounded to 50
            P500 = the strike nearest ATM (in the money side) whose premium at the signal minute is >= 500
            P50  = the strike nearest ATM (out of the money side) whose premium at the signal minute is < 50 (and > 0)
            (premium = the option's last close at or before the signal minute, within 5 minutes)
  Exit    : I    intraday - the opposite flip or 15:20
            I2x  intraday, sell at 2x the entry premium if touched first
            P    positional - the opposite flip (carried overnight) or the expiry close
            P2x  positional, 2x first
            E    never closed - held to the expiry close, flips ignored
            E2x  held to expiry, but sold at 2x if touched
  Fills   : buy at the first option candle's open at / after the entry minute (within 5 minutes, else skipped); flip / 15:20
            exits at the first candle at / after the exit minute (else the last before); 2x at exactly 2x (or the open if it
            gapped above); expiry = the contract's last candle close. Lab option slippage (max(0.5, 0.5%)) and dated charges;
            1 lot of 65 throughout (lot sizes changed over the years; kept fixed so years compare).
  Report  : every combination: trades, win %, avg return on premium, PF 2018-22 / 2023-26 / 2026, net; then the best on
            2018-22 (>= 100 trades) read on 2023-26 without re-picking.
Expiries are independent (no position outlives its expiry), so the run walks expiry by expiry, one expiry's option data
in memory at a time.
"""
import os, sys, time, json
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
import pyarrow.dataset as pds
from numba import njit
import core, store_reader as S
import bandlab as BL
JF = BL.JF
f, MIN, cut, ses, year = BL.data()
LOT = 65
TFS = (1, 5, 15, 60)
CFG = ((7, 2.0), (10, 2.0), (10, 3.0), (14, 4.0))
MODES = ("ATM", "P500", "P50")
EXITS = ("I", "I2x", "P", "P2x", "E", "E2x")


@njit(cache=True)
def _st(h, l, c, n, m):
    out = np.zeros(len(h), np.int8)
    a = 0.0; s = 0.0; fu = 0.0; fl = 0.0; d = 1
    for i in range(len(h)):
        tr = h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        s += tr
        a = s / (i + 1) if i < n else (a * (n - 1) + tr) / n
        mid = (h[i] + l[i]) / 2; bu = mid + m * a; bl = mid - m * a
        if i == 0:
            fu, fl = bu, bl
        else:
            fu = bu if (bu < fu or c[i - 1] > fu) else fu
            fl = bl if (bl > fl or c[i - 1] < fl) else fl
            if d == 1 and c[i] < fl: d = -1
            elif d == -1 and c[i] > fu: d = 1
        out[i] = d
    return out


# ---------------------------------------------------------------- signals: (minute index of the flip, direction)
SIG = {}
for tf in TFS:
    B, last = BL.tf_bars(tf)
    for n_, m_ in CFG:
        d = _st(np.asarray(B.h, float), np.asarray(B.l, float), np.asarray(B.c, float), n_, m_)
        k = np.nonzero(d[1:] != d[:-1])[0] + 1
        SIG[(tf, n_, m_)] = (last[k].astype(np.int64), d[k].astype(np.int8))
FT = f.t.astype(np.int64)
DAYS = np.array([core.dstr(int(x)) for x in f.day])
sp = JF._store_bars("index"); SPT = sp.t.astype(np.int64); SPC = np.asarray(sp.c, float)
EXPS = sorted(e["expiry"] for e in S.expiries())


def expiry_of(day):
    j = np.searchsorted(EXPS, day)
    return EXPS[j] if j < len(EXPS) else None


def load_expiry(ex):
    paths = S._exp_files(ex)
    if not paths: return None
    df = pds.dataset(paths, format="parquet").to_table(columns=["datetime", "strike", "right", "open", "high", "close"]).to_pandas()
    if df.empty: return None
    df = S._session(df)
    df["t"] = df["datetime"].to_numpy().astype("datetime64[s]").astype("int64")
    df["right"] = df["right"].astype(str); df["strike"] = df["strike"].astype(int)
    df = df.drop(columns=["datetime"]).sort_values(["right", "strike", "t"]).drop_duplicates(["right", "strike", "t"], keep="last")
    C = {}
    for (r, k), g in df.groupby(["right", "strike"], sort=False):
        C[(r, k)] = (g["t"].to_numpy(np.int64), g["open"].to_numpy(float), g["high"].to_numpy(float), g["close"].to_numpy(float))
    C["_ks"] = {r: sorted(k for (r2, k) in C if r2 == r) for r in ("CE", "PE")}
    return C


def prem_at(C, key, ts):
    g = C.get(key)
    if g is None: return None
    j = int(np.searchsorted(g[0], ts, side="right")) - 1
    if j < 0 or ts - g[0][j] > 300: return None
    return g[3][j]


def pick(C, mode, right, atm, ts):
    if mode == "ATM": return atm if (right, atm) in C else None
    ks = C["_ks"][right]
    if mode == "P500":       # in the money side, nearest ATM with premium >= 500
        cand = [k for k in ks if (k <= atm if right == "CE" else k >= atm)]
        cand.sort(key=lambda k: abs(k - atm))
        for k in cand:
            p = prem_at(C, (right, k), ts)
            if p is not None and p >= 500: return k
        return None
    cand = [k for k in ks if (k >= atm if right == "CE" else k <= atm)]      # P50: out of the money side
    cand.sort(key=lambda k: abs(k - atm))
    for k in cand:
        p = prem_at(C, (right, k), ts)
        if p is not None and 0 < p < 50: return k
    return None


def first_at(g, ts, strict):
    j = int(np.searchsorted(g[0], ts))
    if j >= len(g[0]): return (len(g[0]) - 1) if not strict else None
    if strict and g[0][j] - ts > 300: return None
    return j


def sim_expiry(ex, C, sigs_by_set, res):
    """sigs_by_set: set -> list of (flip minute index, dir) for signal days that map to this expiry (time order)."""
    for sk, sigs in sigs_by_set.items():
        fl_idx = np.array([s[0] for s in sigs], np.int64)
        for mode in MODES:
            # entry per signal for this mode (shared by all exits)
            ent = []
            for q, (i, d) in enumerate(sigs):
                if i + 1 >= len(FT) or DAYS[i + 1] != DAYS[i]: ent.append(None); continue
                mm = MIN[i + 1]
                if mm < 560 or mm > 900: ent.append(None); continue
                si = int(np.searchsorted(SPT, FT[i]))
                if si >= len(SPT) or abs(SPT[si] - FT[i]) > 120: ent.append(None); continue
                atm = int(round(SPC[si] / 50) * 50); right = "CE" if d > 0 else "PE"
                k = pick(C, mode, right, atm, int(FT[i]))
                if k is None: ent.append(None); continue
                g = C[(right, k)]; j = first_at(g, int(FT[i + 1]), True)
                if j is None: ent.append(None); continue
                ent.append((g, j, right, k))
            for ex_rule in EXITS:
                busy = -1
                for q, (i, d) in enumerate(sigs):
                    e = ent[q]
                    if e is None or FT[i + 1] <= busy: continue
                    g, j, right, k = e; t0 = g[0][j]; px = g[1][j]
                    day = DAYS[i]
                    # the exit time by rule (before the 2x check)
                    if ex_rule in ("E", "E2x"):
                        tx = None                                                  # expiry close
                    else:
                        nx = q + 1
                        tflip = int(FT[sigs[nx][0] + 1]) if nx < len(sigs) and sigs[nx][0] + 1 < len(FT) else None
                        if ex_rule in ("I", "I2x"):
                            eod = int(t0 - t0 % 86400 + 920 * 60)
                            tx = min(tflip, eod) if tflip is not None and DAYS[sigs[nx][0]] == day else eod
                        else:
                            tx = tflip                                              # None -> expiry close
                    if tx is None: jx = len(g[0]) - 1; xp = g[3][jx]; why = "expiry"
                    else:
                        jx = first_at(g, tx, False); xp = g[1][jx]; why = "flip/eod"
                    if ex_rule.endswith("2x"):
                        tgt = 2 * px; hit = np.nonzero(g[2][j:jx + 1] >= tgt)[0]
                        if len(hit):
                            jh = j + int(hit[0]); jx = jh; why = "2x"
                            xp = g[1][jh] if g[1][jh] >= tgt and jh > j else tgt
                    rec = dict(position="LONG", entry_time=int(t0), exit_time=int(g[0][jx]), entry_px=float(px), exit_px=float(xp))
                    JF._price({"lot_size": LOT}, rec, "OPT")
                    busy = int(g[0][jx])
                    res.append((sk[0], sk[1], sk[2], mode, ex_rule, int(day[:4]), day, float(px), float(rec["net"]), why))


if __name__ == "__main__":
    t_start = time.time()
    # signals grouped by expiry
    by_exp = {}
    for sk, (idx, dr) in SIG.items():
        for i, d in zip(idx, dr):
            if i + 1 >= len(FT): continue
            ex = expiry_of(DAYS[i])
            if ex is None: continue
            by_exp.setdefault(ex, {}).setdefault(sk, []).append((int(i), int(d)))
    res = []
    ex_list = sorted(by_exp)
    if os.environ.get("NEXP"): ex_list = ex_list[-int(os.environ["NEXP"]):]
    for n_done, ex in enumerate(ex_list):
        C = load_expiry(ex)
        if C: sim_expiry(ex, C, by_exp[ex], res)
        del C
        if n_done % 40 == 0: print(f"{n_done}/{len(ex_list)} expiries, {len(res)} trades, {time.time() - t_start:.0f}s", flush=True)
    R = pd.DataFrame(res, columns=["tf", "atr", "mult", "mode", "exit", "yy", "day", "prem", "net", "why"])
    os.makedirs("results/optbuy_grid", exist_ok=True)
    R.to_parquet("results/optbuy_grid/trades.parquet" if not os.environ.get("NEXP") else "results/optbuy_grid/test.parquet")
    print(f"done {len(R)} trades in {time.time() - t_start:.0f}s")
