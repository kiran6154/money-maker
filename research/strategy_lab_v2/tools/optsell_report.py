"""tools/optsell_report.py - the 15-minute option-selling books (strategies/optsell15.py) summarised like the hand-off specs:
the Strategy 11 family table (2 slots, fixed gate, clean universe unless given) and the Rainbow Book by year.

    python tools/optsell_report.py s11      every variant x K (the spec's section 6 table) + the golden trades
    python tools/optsell_report.py rb       the Rainbow Book as specified / spot-scaled (regular strike files, and with .wide)
"""
import os
import sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np
import pandas as pd
import core

F = core.family("optsell15")


def stats(B, tcol="exit_t"):
    if not len(B): return dict(n=0)
    B = B.sort_values(tcol); eq = B.net.cumsum(); dd = float((eq.cummax() - eq).max())
    y = pd.to_datetime(B[tcol]).dt.year
    t = B.net.mean() / (B.net.std(ddof=1) / np.sqrt(len(B))) if len(B) > 2 else np.nan
    out = dict(n=len(B), net=B.net.sum(), win=100 * (B.net > 0).mean(), dd=dd, worst=B.net.min(), t=t)
    if "worst_mtm" in B: out["mtm"] = B.worst_mtm.min()
    out["by_year"] = {int(k): round(float(v)) for k, v in B.net.groupby(y).sum().items()}
    return out


def s11():
    D = F.s11_candidates()
    print(f"candidates: {len(D)} rows over {D.exp.nunique()} monthly expiries\n")
    print("| Variant | K | Trades | Net ₹ | Win % | Closed DD ₹ | Worst open MTM ₹ | t | 2018-23 ₹ | 2024-26 ₹ |\n|---|---|---|---|---|---|---|---|---|---|")
    for (var, K) in sorted(set(zip(D["var"], D["K"]))):
        B = F.s11_book(var, K)
        s = stats(B)
        if not s["n"]: print(f"| {var} | {K} | 0 |"); continue
        a = sum(v for y, v in s["by_year"].items() if y <= 2023); b = sum(v for y, v in s["by_year"].items() if y >= 2024)
        print(f"| {var} | {K or ''} | {s['n']} | {s['net']:+,.0f} | {s['win']:.0f} | {s['dd']:,.0f} | {s['mtm']:,.0f} | {s['t']:.2f} | {a:+,.0f} | {b:+,.0f} |")
    for var, K in (("A_s11", 0),):
        for slots in (1,):
            s = stats(F.s11_book(var, K, slots=slots)); print(f"\n{var} with {slots} slot: {s['n']} trades, net {s['net']:+,.0f}, by year {s['by_year']}")
        s = stats(F.s11_book(var, K, universe="spec")); print(f"{var}, universe 'spec' (no 250-point limit): {s['n']} trades, net {s['net']:+,.0f}")
        s = stats(F.s11_book(var, K, gate="scaled")); print(f"{var}, scaled gate: {s['n']} trades, net {s['net']:+,.0f}")
    B = F.s11_book("A_s11", 0)
    print("\nA_s11 by year:", stats(B)["by_year"])
    g = D[(D["var"] == "A_s11") & (((D.exp == "2024-07-25") & (D.strike == 23850) & (D.side == "CE")) | ((D.exp == "2026-03-30") & (D.strike == 24600) & (D.side == "PE")))]
    print("\ngolden trades (A_s11 candidates):")
    print(g[["exp", "strike", "side", "entry_t", "fill", "exit_t", "exit_px", "reason", "net"]].to_string(index=False))


def rb():
    for scaled in (False, True):
        for wide in (False, True):
            B = F.rb_book(scaled, wide)
            if B.empty: print(scaled, wide, "no trades"); continue
            y = pd.to_datetime(B.fill_t).dt.year
            print(f"\n#### Rainbow Book · {'spot-scaled' if scaled else 'as specified'} · {'regular + wide strikes' if wide else 'regular strikes'}: {len(B)} trades, net {B.net.sum():+,.0f}")
            print("| Year | Trades | Win % | Net ₹ | Worst ₹ | RBW_X / BE / EXP |\n|---|---|---|---|---|---|")
            for yy, g in B.groupby(y):
                ex = g.reason.value_counts()
                print(f"| {yy} | {len(g)} | {100 * (g.net > 0).mean():.0f} | {g.net.sum():+,.0f} | {g.net.min():+,.0f} | {ex.get('RBW_X', 0)} / {ex.get('BE', 0)} / {ex.get('EXP', 0)} |")
            a = B[y <= 2023]; b = B[(y >= 2024) & (y <= 2025)]
            print(f"2018-23: {len(a)} trades {a.net.sum():+,.0f} · 2024-25: {len(b)} trades {b.net.sum():+,.0f} · 2026: {(y == 2026).sum()} trades {B[y == 2026].net.sum():+,.0f}")


if __name__ == "__main__":
    {"s11": s11, "rb": rb}[sys.argv[1]]()
