"""S177 - S176's cumulative ATM dOI regime on BOS buys (the user, 2026-10-30: "try same with BOS").

S176 filtered the Supertrend / CHoCH-BOS BUY books; G2 (ST152) buys on CHoCH only. Here the BUY trades entered on a BOS,
from the same nifty_bt candidates (results/nifty_bt/books/cand_swing.parquet, every Supertrend-segment CHoCH / BOS on the
p100 contract), positional with the trail + lock50, one open trade per leg (nifty_bt.engine.sequence):
    A  15m ST(4,3) BOS             - G2's rules with BOS instead of CHoCH (the like-for-like book)
    B  15m ST(4,3) CHoCH + BOS     - G2 with both
    C  5m ST(4,3) BOS, D 5m ST(10,3) BOS - the larger BOS samples
    E  15m pivot CHoCH -> ST(10,3) confirm, the BOS buys (S12.4 book, results/nifty_bt/books)
Regime, "with / neutral / against" and the summary exactly as tools/oi_regime.py (read from its minutes.parquet).

    python tools/oi_regime_bos.py      (from research/strategy_lab_v2; run tools/oi_regime.py first)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, pandas as pd
from nifty_bt import engine as E
from oi_regime import OUT, RES, summ


def tag(T, key):
    T = T.copy(); T["date"] = pd.to_datetime(T.sig).dt.normalize()
    T["tod"] = (pd.to_datetime(T.sig).dt.hour * 60 + pd.to_datetime(T.sig).dt.minute - 1).clip(lower=555)
    T["regime"] = key.regime.reindex(list(zip(T.date, T.tod))).values
    T["fit"] = np.where(T.regime.isna(), "no OI data", np.where(T.regime == "neutral", "neutral",
               np.where(((T.right == "CE") & (T.regime == "bullish")) | ((T.right == "PE") & (T.regime == "bearish")), "with regime", "against regime")))
    return T


if __name__ == "__main__":
    pd.set_option("display.width", 230); pd.set_option("display.max_rows", 200)
    key = pd.read_parquet(os.path.join(OUT, "minutes.parquet")).set_index(["date", "tod"])
    c = pd.read_parquet(os.path.join(RES, "books", "cand_swing.parquet"))
    c = c[(c.pick == "p100") & (c.side == 1) & (c["mode"] == "positional") & (c.lock == "trail+lock50")]
    books = {
        "A 15m ST(4,3) BOS": c[(c.st == "15m ST(4,3)") & (c.kind == "BOS")],
        "B 15m ST(4,3) CHoCH + BOS": c[c.st == "15m ST(4,3)"],
        "C 5m ST(4,3) BOS": c[(c.st == "5m ST(4,3)") & (c.kind == "BOS")],
        "D 5m ST(10,3) BOS": c[(c.st == "5m ST(10,3)") & (c.kind == "BOS")],
    }
    books = {k: E.sequence(v.reset_index(drop=True)) for k, v in books.items()}
    s4 = pd.read_csv(os.path.join(RES, "books", "S12.4_p100_15m_CHoCH_-_ST_SELL_+_BUY.csv"), parse_dates=["sig", "entry_time", "exit_time"])
    books["E 15m pivot CHoCH->ST BOS"] = s4[(s4.side == 1) & (s4.kind == "BOS")]
    g2 = pd.read_csv(os.path.join(RES, "golden", "G2.csv"), parse_dates=["sig", "entry_time", "exit_time"])
    books["(ref) G2 15m ST(4,3) CHoCH"] = g2
    rows, allT = [], []
    for name, T in books.items():
        T = tag(T, key); allT.append(T.assign(book=name))
        rows.append(dict(book=name, take="all", **summ(T)))
        for k in ("with regime", "neutral", "against regime"):
            rows.append(dict(book=name, take=k, **summ(T[T.fit == k])))
    S = pd.DataFrame(rows); S.to_csv(os.path.join(OUT, "bos_books.csv"), index=False); print(S.to_string(index=False))
    A = pd.concat(allT); A.to_parquet(os.path.join(OUT, "bos_trades.parquet"))
    op = key.spot.groupby(level=0).transform("first"); mv = (key.spot - op)
    A["mv"] = mv.reindex(list(zip(A.date, A.tod))).values
    A["price_with"] = np.where(A.right == "CE", A.mv > 0, A.mv < 0)
    pf = lambda s: round(s[s > 0].sum() / max(-s[s < 0].sum(), 1), 2)
    print("\nBOS books A, C, D, E pooled: price since open with the trade x regime (trades, PF, net):")
    P = A[A.book.str[0].isin(list("ACDE"))]
    for (pw, f), h in P.groupby(["price_with", "fit"]): print(f"   {'price with' if pw else 'price against':<13} {f:<15} {len(h):>5} {pf(h.net):>6} {round(h.net.sum()):>12,}")
