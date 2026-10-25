"""The fair-value weekly book with the monthly longs held across weeks (STRATEGY_ANALYSIS_TODO S109, S110). No chart; prints the trades.

The user's rule (2026-10-25): NIFTY = 2000 on 2000-01-01 at 10% a year is the fair value. The session before each weekly
expiry at 09:30: above the line, SELL 1 lot each of the next weekly's puts nearest 150 and 450 premium (strikes rounded to
100); below, the calls. The book holds 3 lots of a monthly option of the same right nearest 200 premium, on the first monthly
at least 18 days out. Marked hourly (09:30, 10:30 ... 14:30, 15:25). The week's P&L is the shorts (realized on rolled legs plus
open) plus the longs' move since the week's entry; its base is the margin per short lot x 2 plus the longs' value at the
week's entry.

  +3% / -6%     the whole book is closed, the shorts AND the longs (the user: "in the same strategy -6% or +3% is exit"); the
                next week buys new longs. --keep-longs-on-pct keeps the longs instead (S109's first run).
  next next day the session two sessions ahead is the sold expiry: in profit, the shorts are bought back and the longs kept;
                IN LOSS, the shorts are rolled - bought back and the SAME strikes sold on the next available weekly at that
                step's price - and the week goes on with its P&L carried (the user: "roll over to the same strikes in the next
                available weekly expiry if there is a loss in a week"). No candle at a rolled strike: the shorts are bought
                back ("roll_unavailable"). --no-loss-roll turns the roll off.
  the longs     not closed with the week: under 15 days to expiry they are sold and 3 lots of the next monthly (at least 18 days
                out, premium nearest 200) bought ("roll").
Order at each step: the week's exits, then the long roll, then a new week's entry. Build choices: when the line's side flips at
a week's entry the old right's longs are sold and the new right's bought ("side_flip"); a week whose short strikes are missing
is skipped (the longs stay); costs as the lab (0.5 point slippage a side, option charges, lot 65).

  python tools/cagr_book.py [FROM] [TO] [--keep-longs-on-pct] [--no-loss-roll]
         default 2025-05-14 2026-10-09 (the far strikes complete from the 2025-05-15 expiry)
"""
import os, sys, csv, datetime as D
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, HERE); os.chdir(HERE)
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np, core, store_reader

H = core.family("cagr_hedge")
mod = core.load_strategies()["ST91"]; S = mod.SPEC["cagr"]
args = [a for a in sys.argv[1:] if not a.startswith("--")]
FRM = args[0] if len(args) > 0 else "2025-05-14"
TO = args[1] if len(args) > 1 else "2026-10-09"
EXIT_ALL = "--keep-longs-on-pct" not in sys.argv     # +3% / -6% exits everything, longs included
LOSS_ROLL = "--no-loss-roll" not in sys.argv         # a losing week's shorts roll to the same strikes on the next weekly
ctx = core.context(mod, "OPT_FUT_SIGNAL", "minute", "INDEX", None, FRM, TO)
LOT, DAY = mod.SPEC["lot_size"], core.DAY
sp = core.series("spot", "minute"); ss = core.sessions()
exps = sorted(e["expiry"] for e in store_reader.expiries())
monthly = sorted(e["expiry"] for e in store_reader.expiries() if e.get("monthly"))
steps = [core.hhmm_sec(x) for x in S["steps"]]; entry_t = core.hhmm_sec(S["entry_time"])
ser = lambda e, k, r, t0: H._series(e, k, r, core.dstr(t0 // DAY), e)
dd_ = lambda a, b: (D.date.fromisoformat(a) - D.date.fromisoformat(b)).days

legs, weeks, events = [], [], []                       # closed legs; one row per week; long buys / rolls / flips / exits
longs = None                                            # dict(right, exp, k, px, t, n)
shorts = None                                           # dict(right, exp, legs=[(k, px, t_in)], t, base, long_px, long_carry, realized, week, rolls)


def close(pos, right, exp, k, px0, t0, px1, t1, n, why, week=""):
    name = f"NIFTY {D.date.fromisoformat(exp):%d%b%y} {k} {right}".upper()
    rec = dict(position=pos, opt_type=right, kind="OPT", instrument=name, strike=k, expiry=exp, entry_time=t0, entry_px=px0,
               exit_time=t1, exit_px=px1, exit_reason=why, open=False, sl=None, lots=n, tranche=week, label="", stale=False)
    r = core.price_trade(ctx, rec); legs.append(r); return r["net"]


def buy_longs(right, day, tt):
    mon = next((e for e in monthly if dd_(e, day) >= S["monthly_min_days"]), None)
    got = H._pick(mon, right, day, tt, S["long_premium"], S) if mon else None
    return None if got is None else dict(right=right, exp=mon, k=got[0], px=got[1], t=tt, n=S["long_lots"])


def long_px(tt):
    return H._px(ser(longs["exp"], longs["k"], longs["right"], longs["t"]), tt)


def sell_longs(tt, p, why, note):
    global longs
    net = close("LONG", longs["right"], longs["exp"], longs["k"], longs["px"], longs["t"], p, tt, longs["n"], why)
    events.append((core.tstr(tt), why, f"{longs['exp']} {longs['k']} {longs['right']} @{p:.2f} {note}", net)); longs = None


def end_week(tt, sx, why, lp):
    """Buy the shorts back at sx and write the week's row."""
    global shorts
    w = weeks[shorts["week"] - 1]; sn = shorts["realized_net"]
    for (k, px0, t_in), p in zip(shorts["legs"], sx): sn += close("SHORT", shorts["right"], shorts["exp"], k, px0, t_in, p, tt, 1, why, f"W{shorts['week']}")
    long_move = shorts["long_carry"] + ((lp - shorts["long_px"]) * LOT * longs["n"] if longs and lp is not None else 0.0)
    w.update(exit=core.tstr(tt), why=why, last_exp=shorts["exp"], exit_shorts=" / ".join(f"{p:.2f}" for p in sx), short_net=sn, long_mtm=long_move,
             pct=shorts.get("pct"), rolls=shorts["rolls"])
    shorts = None


for d in ss[(ss >= core.dnum(FRM)) & (ss <= core.dnum(TO))]:
    d = int(d); day = core.dstr(d); j = int(np.searchsorted(ss, d))
    ahead2 = core.dstr(int(ss[j + 2])) if j + 2 < len(ss) else None
    cur = next((e for e in exps if e >= day), None)
    pre = cur and j + 1 < len(ss) and core.dstr(int(ss[j + 1])) == cur          # the session before the current weekly expiry
    for st in steps:
        tt = d * DAY + st
        # ---- 1. the week's exits (and the loss roll)
        if shorts and tt > shorts["t"]:
            sx = [H._px(ser(shorts["exp"], k, shorts["right"], t_in), tt) for k, _, t_in in shorts["legs"]]
            lp = long_px(tt) if longs else None
            if not (any(p is None for p in sx) or lp is None):
                open_pnl = sum((px0 - p) * LOT for (k, px0, _), p in zip(shorts["legs"], sx))
                pnl = shorts["realized"] + open_pnl + shorts["long_carry"] + (lp - shorts["long_px"]) * LOT * longs["n"]
                pct = 100 * pnl / shorts["base"]; shorts["pct"] = pct
                why = "target" if pct >= S["target_pct"] else "stop_loss" if pct <= -S["stop_pct"] else "short_expiry_near" if (ahead2 == shorts["exp"] or shorts["exp"] <= day) else None
                if why == "short_expiry_near" and LOSS_ROLL and pnl < 0:              # a losing week: the same strikes on the next weekly
                    nx2 = next((e for e in exps if e > shorts["exp"]), None)
                    p2s = [H._px(ser(nx2, k, shorts["right"], tt), tt) for k, _, _ in shorts["legs"]] if nx2 else [None]
                    if nx2 and all(p is not None for p in p2s):
                        for (k, px0, t_in), p in zip(shorts["legs"], sx):
                            shorts["realized"] += (px0 - p) * LOT
                            shorts["realized_net"] += close("SHORT", shorts["right"], shorts["exp"], k, px0, t_in, p, tt, 1, "rolled", f"W{shorts['week']}")
                        events.append((core.tstr(tt), "short roll", f"W{shorts['week']} {shorts['right']} " + " / ".join(f"{k} {shorts['exp'][5:]} @{p:.2f} → {nx2[5:]} @{p2:.2f}" for (k, _, _), p, p2 in zip(shorts["legs"], sx, p2s)) + f" (week {pct:+.1f}%)", None))
                        shorts["legs"] = [(k, p2, tt) for (k, _, _), p2 in zip(shorts["legs"], p2s)]; shorts["exp"] = nx2; shorts["rolls"] += 1
                        why = None
                    else: why = "roll_unavailable"
                if why:
                    end_week(tt, sx, why, lp)
                    if why in ("target", "stop_loss") and EXIT_ALL:      # +3% / -6% closes the whole book: the longs too
                        sell_longs(tt, lp, why, "sold with the week")
        # ---- 2. the longs: roll at 15 days
        if longs and dd_(longs["exp"], day) < S["long_exit_days"]:
            p = long_px(tt)
            nl = buy_longs(longs["right"], day, tt) if p is not None else None
            if p is not None and nl:
                old = dict(longs)
                net = close("LONG", longs["right"], longs["exp"], longs["k"], longs["px"], longs["t"], p, tt, longs["n"], "roll")
                events.append((core.tstr(tt), "roll", f"{old['exp']} {old['k']} {old['right']} @{p:.2f} → {nl['exp']} {nl['k']} @{nl['px']:.2f}", net))
                if shorts: shorts["long_carry"] += (p - shorts["long_px"]) * LOT * old["n"]; shorts["long_px"] = nl["px"]
                longs = nl
        # ---- 3. a new week at 09:30 on the pre-expiry session (not while a rolled week is still open)
        if pre and st == entry_t and not shorts:
            i = int(np.searchsorted(sp.t, tt))
            if i < len(sp) and sp.day[i] == d:
                idx = float(sp.o[i]); F = H.fair(day, S); right = "PE" if idx > F else "CE"
                nxt = next((e for e in exps if e > cur), None)
                if longs and longs["right"] != right:                                   # the line's side flipped: the hedge follows
                    p = long_px(tt)
                    if p is not None: sell_longs(tt, p, "side_flip", "sold")
                if not longs:
                    longs = buy_longs(right, day, tt)
                    if longs: events.append((core.tstr(tt), "buy", f"{longs['exp']} {longs['k']} {right} @{longs['px']:.2f} × {longs['n']} lots", None))
                picks = [H._pick(nxt, right, day, tt, prem, S) for prem in S["short_premiums"]] if nxt else [None]
                if any(g is None for g in picks) or not longs:
                    weeks.append(dict(week=len(weeks) + 1, entry=core.tstr(tt), side=right, index=idx, fair=F, skipped="no strike near " + "/".join(str(p) for p, g in zip(S["short_premiums"], picks) if g is None) if any(g is None for g in picks) else "no monthly"))
                else:
                    lp = long_px(tt)
                    base = S["margin_per_short_lot"] * len(picks) + lp * LOT * longs["n"]
                    shorts = dict(right=right, exp=nxt, legs=[(k, px, tt) for k, px in picks], t=tt, base=base, long_px=lp, long_carry=0.0,
                                  realized=0.0, realized_net=0.0, week=len(weeks) + 1, rolls=0)
                    weeks.append(dict(week=len(weeks) + 1, entry=core.tstr(tt), side=right, index=idx, fair=F, sold_exp=nxt,
                                      shorts=" / ".join(f"{k} @{px:.2f}" for k, px in picks), long=f"{longs['exp']} {longs['k']} @{lp:.2f}", base=base))
# ---- the data's end: close what is open at the last step
tt = int(ss[ss <= core.dnum(TO)][-1]) * DAY + steps[-1]
if shorts:
    sx = [H._px(ser(shorts["exp"], k, shorts["right"], t_in), tt) for k, _, t_in in shorts["legs"]]
    end_week(tt, sx, "data_end", long_px(tt) if longs else None)
if longs:
    sell_longs(tt, long_px(tt), "data_end", "sold")

# ---- print
f = lambda v: "" if v is None else f"{v:+,.0f}"
mode = ("longs closed at +3% / -6%" if EXIT_ALL else "longs kept at +3% / -6%") + (", a losing week's shorts rolled to the same strikes" if LOSS_ROLL else "")
print(f"Fair-value weekly book, longs held across weeks ({mode}) · {FRM} → {TO} · after costs (0.5 slippage a side, option charges, lot {LOT})\n")
print("| # | Entry (09:30) | Side | Index / fair | Sold weekly | Shorts sold (strike @ premium) | Long held | Rolls | Last weekly | Exit | Why | Bought back | Shorts net ₹ | Longs' move ₹ | Week % |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for w in weeks:
    if "skipped" in w:
        print(f"| {w['week']} | {w['entry'][:16]} | {w['side']} | {w['index']:,.0f} / {w['fair']:,.0f} | | skipped: {w['skipped']} | | | | | | | | | |"); continue
    print(f"| {w['week']} | {w['entry'][:16]} | {w['side']} | {w['index']:,.0f} / {w['fair']:,.0f} | {w['sold_exp']} | {w['shorts']} | {w['long']} | {w.get('rolls', '') or ''} | {w.get('last_exp', '') if w.get('rolls') else ''} | {w.get('exit', '')[:16]} | {w.get('why', '')} | {w.get('exit_shorts', '')} | {f(w.get('short_net'))} | {f(w.get('long_mtm'))} | {'' if w.get('pct') is None else format(w['pct'], '+.1f')} |")
print("\nBuys, rolls and exits of the long legs, and the short rolls:\n")
print("| When | Event | Detail | Realized ₹ (after costs) |"); print("|---|---|---|---|")
for t, k, s, net in events: print(f"| {t[:16]} | {k} | {s} | {f(net)} |")
SN = sum(l["net"] for l in legs if l["position"] == "SHORT"); LN = sum(l["net"] for l in legs if l["position"] == "LONG")
done = [w for w in weeks if "short_net" in w]
print(f"\nWeeks traded {len(done)}, skipped {sum(1 for w in weeks if 'skipped' in w)}; exits {dict((k, sum(1 for w in done if w['why'] == k)) for k in sorted({w['why'] for w in done}))}; weeks rolled {sum(1 for w in done if w.get('rolls'))} ({sum(w.get('rolls', 0) for w in done)} rolls)")
print(f"Shorts ₹{SN:+,.0f} over {sum(1 for l in legs if l['position'] == 'SHORT')} legs ({sum(1 for w in done if w['short_net'] > 0)} winning weeks) · longs ₹{LN:+,.0f} over {sum(1 for l in legs if l['position'] == 'LONG')} legs · total ₹{SN + LN:+,.0f}")
out = os.path.join(HERE, "results", "cagr_book_trades.csv")
with open(out, "w", newline="", encoding="utf-8") as fh:
    wr = csv.writer(fh); wr.writerow(["position", "instrument", "lots", "entry_time", "entry_px", "exit_time", "exit_px", "exit_reason", "week", "pts", "gross", "charges", "net"])
    for l in legs: wr.writerow([l["position"], l["instrument"], l["lots"], core.tstr(l["entry_time"]), l["entry_px"], core.tstr(l["exit_time"]), l["exit_px"], l["exit_reason"], l["tranche"], round(l["pts"], 2), round(l["gross"], 2), round(l["chg"]["total"], 2), round(l["net"], 2)])
print(f"\nEvery leg: {os.path.relpath(out, os.path.dirname(os.path.dirname(HERE)))}")
