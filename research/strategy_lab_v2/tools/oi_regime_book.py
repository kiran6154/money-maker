"""S179a - S178's 1-minute Supertrend-segment books with the dOI regime as tradable trade lists for the dashboard
(the user, 2026-10-30: "create previous as strategy") - ST160 / ST161 read them through strategies/handoff.py.

S178 sequenced every candidate first (one open trade per leg) and then kept the "with regime" ones, so an against-regime
trade that was never taken still blocked the leg while it would have been open. A strategy cannot do that: here the regime
is the entry rule - candidates against the regime or neutral at the signal minute are dropped, then the survivors are
sequenced. Both numbers are printed.
    ST160  1m ST(4,3)  CHoCH + BOS, with the regime
    ST161  1m ST(10,3) BOS, with the regime
Writes results/nifty_bt/books/<name>.csv (the handoff loader's format).

    python tools/oi_regime_book.py      (from research/strategy_lab_v2; run tools/oi_regime_bos1m.py first)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
import pandas as pd
from nifty_bt import engine as E
from oi_regime import OUT, RES, summ
from oi_regime_bos import tag

BOOKS = {"ST160": ("1m ST(4,3)", ("CHoCH", "BOS"), "1m_ST4-3_CHoCH_BOS_with_regime"),
         "ST161": ("1m ST(10,3)", ("BOS",), "1m_ST10-3_BOS_with_regime")}

if __name__ == "__main__":
    pd.set_option("display.width", 230)
    key = pd.read_parquet(os.path.join(OUT, "minutes.parquet")).set_index(["date", "tod"])
    c = tag(pd.read_parquet(os.path.join(OUT, "cand_1m.parquet")), key)
    rows = []
    for code, (st, kinds, fn) in BOOKS.items():
        x = c[(c.st == st) & c.kind.isin(kinds)]
        after = E.sequence(x.drop(columns=["regime", "fit", "date", "tod"]).reset_index(drop=True))
        after = tag(after, key); after = after[after.fit == "with regime"]
        T = E.sequence(x[x.fit == "with regime"].reset_index(drop=True))
        rows.append(dict(book=code, how="S178: sequence, then filter", **summ(after)))
        rows.append(dict(book=code, how="filter, then sequence (the strategy)", **summ(T)))
        cols = ["side", "st", "kind", "mode", "lock", "right", "sig", "entry_time", "exit_time", "entry", "stop0", "exit", "why", "net",
                "expiry", "strike", "year", "regime"]
        T[cols].to_csv(os.path.join(RES, "books", fn + ".csv"), index=False)
    print(pd.DataFrame(rows).to_string(index=False))
