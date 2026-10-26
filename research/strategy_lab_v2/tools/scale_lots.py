"""tools/scale_lots.py - compounding lot sizing on a lab strategy's saved trades (the user, 2026-10-26: "the CHoCH to CHoCH pdf
should scale: say we have invested for 2 lots, trade 1 lot; if the profit is 2 times, trade 2 lots, and so on").

    python tools/scale_lots.py ST147 all-data_5m_idx M-ITM1 [ST148 ...]

Rule "step" (as read): starting capital C0 = the cost of 2 lots at the first trade (2 x its entry premium x the lot size);
  lots = max(1, floor(equity / C0)) - 1 lot until equity reaches 2 x C0, 2 lots until 3 x C0, ... (never below 1 lot);
  trading stops when equity cannot pay for 1 lot of the next trade.
Rule "premium": lots = max(1, floor(equity / (2 x this trade's entry premium x the lot size))) - the same "capital for 2,
  trade 1" read on every trade's own premium.
A trade's rupee result = its saved 1-lot net x lots (charges scale with lots; the flat brokerage is over-counted slightly).
Trades are taken in entry order; a trade's lots are fixed from the equity at its entry (closed trades only).
"""
import os, sys, json
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
from collections import defaultdict


def load(code, run, choice):
    j = json.load(open(os.path.join("results", code, run, "OPT_FUT_SIGNAL", f"{choice}.json"), encoding="utf-8"))
    C = {k: i for i, k in enumerate(j["cols"])}
    T = sorted(j["trades"], key=lambda r: r[C["entry_time"]])
    return [dict(t=r[C["entry_time"]], x=r[C["exit_time"]], px=float(r[C["entry_px"]]), net=float(r[C["net"]])) for r in T], 65


def scale(T, lot, rule, topup=False):
    """topup: when equity cannot pay one lot of the next put, money is added to bring it back to 2 lots' worth at that
    premium (the starting rule); lots then count whole multiples of ALL the money put in (step rule)."""
    C0 = 2 * T[0]["px"] * lot
    eq, out, peak, dd, ruin, inv = C0, [], C0, 0.0, None, C0
    for tr in T:
        if eq < tr["px"] * lot:
            if not topup: ruin = tr["t"]; break
            add = 2 * tr["px"] * lot - eq; inv += add; eq += add; peak = max(peak, eq)
            out.append(dict(tr, lots=0, eq=eq, added=add, inv=inv))
        n = max(1, int(eq // inv)) if rule == "step" else max(1, int(eq // (2 * tr["px"] * lot)))
        eq += tr["net"] * n; peak = max(peak, eq); dd = min(dd, eq - peak)
        out.append(dict(tr, lots=n, eq=eq, added=0.0, inv=inv))
    return (C0, eq, dd, ruin, out) if not topup else (C0, eq, dd, inv, out)


if __name__ == "__main__":
    args = sys.argv[1:]
    for k in range(0, len(args), 3):
        code, run, ch = args[k:k + 3]
        T, lot = load(code, run, ch)
        flat = sum(t["net"] for t in T)
        print(f"\n#### {code} {run} {ch}: {len(T)} trades, {T[0]['t'][:10]} - {T[-1]['t'][:10]}, 1 lot flat: net {flat:+,.0f}")
        print("| Sizing | Start capital ₹ | End equity ₹ | Return | Max lots | Max drawdown ₹ | Stopped (could not pay 1 lot) |\n|---|---|---|---|---|---|---|")
        res = {}
        for rule in ("step", "premium"):
            C0, eq, dd, ruin, out = scale(T, lot, rule); res[rule] = out
            print(f"| {rule} | {C0:,.0f} | {eq:,.0f} | {(eq / C0 - 1) * 100:+.0f}% | {max(o['lots'] for o in out)} | {dd:,.0f} | {ruin or '-'} |")
        C0 = 2 * T[0]["px"] * lot
        print(f"| 1 lot flat (no scaling) | {C0:,.0f} | {C0 + flat:,.0f} | {flat / C0 * 100:+.0f}% | 1 | | |")
        yr = defaultdict(lambda: [0.0, 0, 0])
        for o in res["step"]: y = o["t"][:4]; yr[y][0] += o["net"] * o["lots"]; yr[y][1] = max(yr[y][1], o["lots"]); yr[y][2] = o["eq"]
        print("step rule by year (net ₹, max lots, equity at year end):", {y: (round(v[0]), v[1], round(v[2])) for y, v in sorted(yr.items())})
