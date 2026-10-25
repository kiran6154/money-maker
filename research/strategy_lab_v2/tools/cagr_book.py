"""The fair-value weekly book with the monthly longs held across weeks (STRATEGY_ANALYSIS_TODO S109). No chart; prints the trades.

The user's rule (2026-10-25): NIFTY = 2000 on 2000-01-01 at 10% a year is the fair value. The session before each weekly
expiry at 09:30: above the line, SELL 1 lot each of the next weekly's puts nearest 150 and 450 premium (strikes rounded to
100); below, the calls. The book holds 3 lots of a monthly option of the same right nearest 200 premium, on the first monthly
at least 18 days out. Marked hourly (09:30, 10:30 ... 14:30, 15:25). The week's shorts are bought back at the first step where
the week's P&L - the shorts plus the longs' move since the week's entry - is +3% or -6% of the base (margin per short lot x 2
plus the longs' value at the week's entry), or the session two sessions ahead is the sold expiry. The longs are NOT closed
with the week (the user's answer: keep them across weeks): when they have under 15 days to expiry they are sold and 3 lots of
the next monthly (at least 18 days out, premium nearest 200) bought ("roll"). Build choices: when the line's side flips at a
week's entry, the longs of the old right are sold and the new right's bought ("side_flip"); a week whose short strikes are
missing is skipped (the longs stay); costs as the lab (0.5 point slippage a side, option charges, lot 65).

  python tools/cagr_book.py [FROM] [TO]       default 2025-05-14 2026-10-09 (the far strikes complete from the 2025-05-15 expiry)
"""
import os, sys, csv, datetime as D
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE); os.chdir(HERE)
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, core, store_reader

H = core.family("cagr_hedge")
mod = core.load_strategies()["ST91"]; S = mod.SPEC["cagr"]
FRM = sys.argv[1] if len(sys.argv) > 1 else "2025-05-14"
TO = sys.argv[2] if len(sys.argv) > 2 else "2026-10-09"
ctx = core.context(mod, "OPT_FUT_SIGNAL", "minute", "INDEX", None, FRM, TO)
LOT, DAY = mod.SPEC["lot_size"], core.DAY
sp = core.series("spot", "minute"); ss = core.sessions()
exps = sorted(e["expiry"] for e in store_reader.expiries())
monthly = sorted(e["expiry"] for e in store_reader.expiries() if e.get("monthly"))
steps = [core.hhmm_sec(x) for x in S["steps"]]; entry_t = core.hhmm_sec(S["entry_time"])
ser = lambda e, k, r, d0: H._series(e, k, r, d0, e)
dd_ = lambda a, b: (D.date.fromisoformat(a) - D.date.fromisoformat(b)).days

legs, weeks, events = [], [], []                       # closed legs; one row per week; long rolls / flips
longs = None                                            # dict(right, exp, k, px, t, n)
shorts = None                                           # dict(right, exp, legs=[(k, px)], t, base, long_ref)


def close(pos, right, exp, k, px0, t0, px1, t1, n, why, week=""):
    name = f"NIFTY {D.date.fromisoformat(exp):%d%b%y} {k} {right}".upper()
    rec = dict(position=pos, opt_type=right, kind="OPT", instrument=name, strike=k, expiry=exp, entry_time=t0, entry_px=px0,
               exit_time=t1, exit_px=px1, exit_reason=why, open=False, sl=None, lots=n, tranche=week, label="", stale=False)
    r = core.price_trade(ctx, rec); legs.append(r); return r["net"]


def buy_longs(right, day, tt):
    mon = next((e for e in monthly if dd_(e, day) >= S["monthly_min_days"]), None)
    got = H._pick(mon, right, day, tt, S["long_premium"], S) if mon else None
    return None if got is None else dict(right=right, exp=mon, k=got[0], px=got[1], t=tt, n=S["long_lots"])


for d in ss[(ss >= core.dnum(FRM)) & (ss <= core.dnum(TO))]:
    d = int(d); day = core.dstr(d); j = int(np.searchsorted(ss, d))
    ahead2 = core.dstr(int(ss[j + 2])) if j + 2 < len(ss) else None
    cur = next((e for e in exps if e >= day), None)
    pre = cur and j + 1 < len(ss) and core.dstr(int(ss[j + 1])) == cur          # the session before the current weekly expiry
    for st in steps:
        tt = d * DAY + st
        # ---- the longs: roll at 15 days
        if longs and dd_(longs["exp"], day) < S["long_exit_days"]:
            p = H._px(ser(longs["exp"], longs["k"], longs["right"], core.dstr(longs["t"] // DAY)), tt)
            nl = buy_longs(longs["right"], day, tt) if p is not None else None
            if p is not None and nl:
                net = close("LONG", longs["right"], longs["exp"], longs["k"], longs["px"], longs["t"], p, tt, longs["n"], "roll")
                events.append((core.tstr(tt), "roll", f"{longs['exp']} {longs['k']} {longs['right']} @{p:.2f} → {nl['exp']} {nl['k']} @{nl['px']:.2f}", net))
                if shorts: shorts["long_carry"] = shorts.get("long_carry", 0.0) + (p - shorts["long_px"]) * LOT * longs["n"]; shorts["long_px"] = nl["px"]
                longs = nl
        # ---- a new week at 09:30 on the pre-expiry session
        if pre and st == entry_t and not shorts:
            i = int(np.searchsorted(sp.t, tt))
            if i < len(sp) and sp.day[i] == d:
                idx = float(sp.o[i]); F = H.fair(day, S); right = "PE" if idx > F else "CE"
                nxt = next((e for e in exps if e > cur), None)
                if longs and longs["right"] != right:                                   # the line's side flipped: the hedge follows
                    p = H._px(ser(longs["exp"], longs["k"], longs["right"], core.dstr(longs["t"] // DAY)), tt)
                    if p is not None:
                        net = close("LONG", longs["right"], longs["exp"], longs["k"], longs["px"], longs["t"], p, tt, longs["n"], "side_flip")
                        events.append((core.tstr(tt), "side_flip", f"{longs['exp']} {longs['k']} {longs['right']} @{p:.2f} sold", net)); longs = None
                if not longs:
                    longs = buy_longs(right, day, tt)
                    if longs: events.append((core.tstr(tt), "buy", f"{longs['exp']} {longs['k']} {right} @{longs['px']:.2f} × {longs['n']} lots", 0.0))
                picks = [H._pick(nxt, right, day, tt, prem, S) for prem in S["short_premiums"]] if nxt else [None]
                if any(g is None for g in picks) or not longs:
                    weeks.append(dict(week=len(weeks) + 1, entry=core.tstr(tt), side=right, index=idx, fair=F, skipped="no strike near " + "/".join(str(p) for p, g in zip(S["short_premiums"], picks) if g is None) if any(g is None for g in picks) else "no monthly"))
                else:
                    lp = H._px(ser(longs["exp"], longs["k"], right, core.dstr(longs["t"] // DAY)), tt)
                    base = S["margin_per_short_lot"] * len(picks) + lp * LOT * longs["n"]
                    shorts = dict(right=right, exp=nxt, legs=[(k, px) for k, px in picks], t=tt, base=base, long_px=lp, long_carry=0.0,
                                  week=len(weeks) + 1, idx=idx, F=F)
                    weeks.append(dict(week=len(weeks) + 1, entry=core.tstr(tt), side=right, index=idx, fair=F, sold_exp=nxt,
                                      shorts=" / ".join(f"{k} @{px:.2f}" for k, px in picks), long=f"{longs['exp']} {longs['k']} @{lp:.2f}", base=base))
                continue
        # ---- the week's exits
        if shorts and tt > shorts["t"]:
            sx = [H._px(ser(shorts["exp"], k, shorts["right"], core.dstr(shorts["t"] // DAY)), tt) for k, _ in shorts["legs"]]
            lp = H._px(ser(longs["exp"], longs["k"], longs["right"], core.dstr(longs["t"] // DAY)), tt) if longs else None
            if any(p is None for p in sx) or lp is None: continue
            pnl = sum((px0 - p) * LOT for (k, px0), p in zip(shorts["legs"], sx)) + shorts["long_carry"] + (lp - shorts["long_px"]) * LOT * longs["n"]
            pct = 100 * pnl / shorts["base"]
            why = "target" if pct >= S["target_pct"] else "stop_loss" if pct <= -S["stop_pct"] else "short_expiry_near" if (ahead2 == shorts["exp"] or shorts["exp"] <= day) else None
            if why:
                w = weeks[shorts["week"] - 1]; sn = 0.0
                for (k, px0), p in zip(shorts["legs"], sx): sn += close("SHORT", shorts["right"], shorts["exp"], k, px0, shorts["t"], p, tt, 1, why, f"W{shorts['week']}")
                long_move = shorts["long_carry"] + (lp - shorts["long_px"]) * LOT * longs["n"]
                w.update(exit=core.tstr(tt), why=why, exit_shorts=" / ".join(f"{p:.2f}" for p in sx), short_net=sn, long_mtm=long_move, pct=pct)
                shorts = None
# ---- the data's end: close what is open at the last step
tt = int(ss[ss <= core.dnum(TO)][-1]) * DAY + steps[-1]
if shorts:
    w = weeks[shorts["week"] - 1]; sx = [H._px(ser(shorts["exp"], k, shorts["right"], core.dstr(shorts["t"] // DAY)), tt) for k, _ in shorts["legs"]]
    sn = sum(close("SHORT", shorts["right"], shorts["exp"], k, px0, shorts["t"], p, tt, 1, "data_end", f"W{shorts['week']}") for (k, px0), p in zip(shorts["legs"], sx))
    w.update(exit=core.tstr(tt), why="data_end", exit_shorts=" / ".join(f"{p:.2f}" for p in sx), short_net=sn, long_mtm=0.0, pct=None)
if longs:
    p = H._px(ser(longs["exp"], longs["k"], longs["right"], core.dstr(longs["t"] // DAY)), tt)
    net = close("LONG", longs["right"], longs["exp"], longs["k"], longs["px"], longs["t"], p, tt, longs["n"], "data_end")
    events.append((core.tstr(tt), "data_end", f"{longs['exp']} {longs['k']} {longs['right']} @{p:.2f} sold", net))

# ---- print
f = lambda v: "" if v is None else f"{v:+,.0f}"
print(f"Fair-value weekly book, longs held across weeks · {FRM} → {TO} · after costs (0.5 slippage a side, option charges, lot {LOT})\n")
print("| # | Entry (09:30) | Side | Index / fair | Sold weekly | Shorts sold (strike @ premium) | Long held | Exit | Why | Shorts bought back | Shorts net ₹ | Longs' move that week ₹ | Week % |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for w in weeks:
    if "skipped" in w:
        print(f"| {w['week']} | {w['entry'][:16]} | {w['side']} | {w['index']:,.0f} / {w['fair']:,.0f} | | skipped: {w['skipped']} | | | | | | | |"); continue
    print(f"| {w['week']} | {w['entry'][:16]} | {w['side']} | {w['index']:,.0f} / {w['fair']:,.0f} | {w['sold_exp']} | {w['shorts']} | {w['long']} | {w.get('exit', '')[:16]} | {w.get('why', '')} | {w.get('exit_shorts', '')} | {f(w.get('short_net'))} | {f(w.get('long_mtm'))} | {'' if w.get('pct') is None else format(w['pct'], '+.1f')} |")
print("\nLong legs (bought, rolled at 15 days, flipped with the side):\n")
print("| When | Event | Detail | Realized ₹ (after costs) |"); print("|---|---|---|---|")
for t, k, s, net in events: print(f"| {t[:16]} | {k} | {s} | {'' if k == 'buy' else f(net)} |")
SN = sum(l["net"] for l in legs if l["position"] == "SHORT"); LN = sum(l["net"] for l in legs if l["position"] == "LONG")
done = [w for w in weeks if "short_net" in w]
print(f"\nWeeks traded {len(done)}, skipped {sum(1 for w in weeks if 'skipped' in w)}; exits {dict((k, sum(1 for w in done if w['why'] == k)) for k in sorted({w['why'] for w in done}))}")
print(f"Shorts ₹{SN:+,.0f} over {sum(1 for l in legs if l['position'] == 'SHORT')} legs ({sum(1 for w in done if w['short_net'] > 0)} winning weeks) · longs ₹{LN:+,.0f} over {sum(1 for l in legs if l['position'] == 'LONG')} legs · total ₹{SN + LN:+,.0f}")
out = os.path.join(HERE, "results", "cagr_book_trades.csv")
with open(out, "w", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh); wr.writerow(["position", "instrument", "lots", "entry_time", "entry_px", "exit_time", "exit_px", "exit_reason", "week", "pts", "gross", "charges", "net"])
    for l in legs: wr.writerow([l["position"], l["instrument"], l["lots"], core.tstr(l["entry_time"]), l["entry_px"], core.tstr(l["exit_time"]), l["exit_px"], l["exit_reason"], l["tranche"], round(l["pts"], 2), round(l["gross"], 2), round(l["chg"]["total"], 2), round(l["net"], 2)])
print(f"\nEvery leg: {os.path.relpath(out, os.path.dirname(os.path.dirname(HERE)))}")
