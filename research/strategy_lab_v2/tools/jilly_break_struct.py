"""tools/jilly_break_struct.py - "once Jilly's noise band breaks it is not a sideways day; then trade Strategy 1 / 2 / 3 or plain
CHoCH / BOS on 1- and 5-minute candles" (the user, 2026-10-26; STRATEGY_ANALYSIS_TODO S149).

The day's confirmation = the FIRST 1-minute close of the near-month future outside Jilly's noise band (UB(key) / LB(key),
Strategy 111's settings without the volatility filter) between 09:30 and 14:00 - just the band, none of Jilly's other
conditions (opening range + ATR buffer, VWAP, the volatility rank). Then jilly_ext.trades_of's structure trading for the
rest of the day, unchanged (Strategies 114 - 118's engine): plain = every CHoCH / BOS after the confirmation enters at the next
open, out at the next CHoCH against it, the last swing as the stop, or 15:20; setup = Strategy 1 / 2 / 3's SETUP trades.
`sides`: "jilly" = only the break's direction, "both" = reversals too. For comparison, the same with Jilly's full signal as
the confirmation (= Strategies 114 - 118). Futures, 1 lot, the lab's costs (jilly._price).
"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); os.chdir(HERE); sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, core
JX = core.family("jilly_ext"); JF = core.family("jilly")
_orig_engine = JF.engine


def band_break_engine(J):
    """jilly.engine with each session's 'signal' replaced by the first close outside the noise band (09:30 - 14:00)."""
    f, keyv, E = _orig_engine(dict(J, filter=False))
    E2 = []
    for r in E:
        r2 = dict(r, signal=None)
        if "UB" in r:
            a, z = r["a"], r["z"]
            for i in range(a, z - 1):
                k = int(keyv[i])
                if k < 16: continue
                if k > 286: break
                if f.c[i] > r["UB"][k - 1]: r2.update(signal=1, i=i); break
                if f.c[i] < r["LB"][k - 1]: r2.update(signal=-1, i=i); break
        E2.append(r2)
    return f, keyv, E2


def trades(X, confirm):
    JX._J.engine = band_break_engine if confirm == "band" else _orig_engine
    try:
        f, T = JX.trades_of(X)
    finally:
        JX._J.engine = _orig_engine
    out = []
    for day, d, ei, xi, xp, why, stop, lab, fill, oei, oxi in T:
        rec = dict(position="LONG" if d > 0 else "SHORT", entry_time=int(f.t[ei]), exit_time=int(f.t[xi]), entry_px=fill, exit_px=xp, why=why, label=lab)
        out.append(JF._price({"lot_size": 65}, rec, "FUT"))
    return out


def pf(x):
    w = sum(v for v in x if v > 0); l = -sum(v for v in x if v <= 0); return w / l if l else float("inf")


R = lambda b, c: {"break_mode": b, "choch_mode": c, "avwap_weight": "volume", "sl_rule": "prev_swing"}
SYS = {
    "plain CHoCH/BOS 1m": dict(mode="plain", minutes=1, warm=2, rules=R("touch", "touch")),
    "plain CHoCH/BOS 5m": dict(mode="plain", minutes=5, warm=4, rules=R("touch", "touch")),
    "Strategy 1 SETUP (1m)": dict(mode="setup", minutes=1, warm=2, rules=R("touch", "touch")),
    "Strategy 2 SETUP (5m)": dict(mode="setup", minutes=5, warm=4, rules=dict(R("touch", "touch"), sl_rule="choch_candle")),
    "Strategy 3 SETUP (1m, CHoCH on close)": dict(mode="setup", minutes=1, warm=2, rules=R("touch", "close")),
}
if __name__ == "__main__":
    Y = lambda t: core.tstr(t["entry_time"])[:4]
    print("| Confirmation | Structure trades | Sides | Trades | Gross pts / trade | Win % | PF 2018-22 | PF 2023-26 | PF 2026 | Net 2018-22 ₹ | Net 2023-26 ₹ | Net 2026 ₹ | Long / short ₹ |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for confirm in ("band", "jilly"):
        for nm, X in SYS.items():
            for sides in ("jilly", "both"):
                T = trades(dict(X, sides=sides), confirm)
                if not T: continue
                n = [t["net"] for t in T]; g = np.mean([t["pts"] + 1.0 for t in T])
                A = [t["net"] for t in T if Y(t) <= "2022"]; B = [t["net"] for t in T if Y(t) >= "2023"]; Z = [t["net"] for t in T if Y(t) == "2026"]
                L = sum(t["net"] for t in T if t["position"] == "LONG"); S = sum(t["net"] for t in T if t["position"] == "SHORT")
                print(f"| {'noise-band break' if confirm == 'band' else 'Jilly full signal'} | {nm} | {'break side only' if sides == 'jilly' else 'both'} | {len(T)} | {g:+.2f} | "
                      f"{100 * np.mean([v > 0 for v in n]):.0f} | {pf(A):.2f} | {pf(B):.2f} | {pf(Z):.2f} | {sum(A):+,.0f} | {sum(B):+,.0f} | {sum(Z):+,.0f} | {L:+,.0f} / {S:+,.0f} |", flush=True)
