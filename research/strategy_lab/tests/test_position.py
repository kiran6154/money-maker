"""Position handling in lab.py on hand-made candles with known answers: managed exits (lab.manage: stop, R targets, the
1R-ladder trail, fills on a session's first candle, the backtest end, option R), scale-out (lab.tranches), the strike lock
(exit before entry on the same candle) and the default block (the position unchanged).

    python tests/test_position.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab  # noqa: E402

MANAGED = {"lots": 3, "lock": "strike", "exit": "position", "stop": {"futures_pts": 10, "option_pct": 5},
           "scale_out": [{"lots": 1, "target_r": 1}, {"lots": 1, "target_r": 2}], "trail": {"start_r": 3, "lag_r": 1}}


def st(pos):
    return {"position_json": json.dumps(lab.position_of({"position": pos}))}


def bars(day, rows, start=9 * 60 + 20):
    """rows of (open, high, low, close), one minute apart from 09:20 on `day`."""
    t = [f"{day} {(start + i) // 60:02d}:{(start + i) % 60:02d}:00" for i in range(len(rows))]
    return t, [r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows]


def rec(pos, e, t0, kind="FUT"):
    return dict(position=pos, entry_px=e, entry_time=t0, exit_time=t0, kind=kind, exit_reason="open", open=True, sl=None)


def by(parts):
    return {p["tranche"]: (p["exit_px"], p["exit_reason"]) for p in parts}


fails = []
def check(name, got, want):
    if got != want: fails.append(f"{name}: got {got}, want {want}")


# 1. long future, R = 10: T1 at 110, T2 at 120; 3R (130) then 4R (140) move the stop to 120 then 130; a fall hits 130
t, o, h, l, c = bars("2026-08-03", [(100, 100, 100, 100), (101, 111, 101, 110), (110, 121, 109, 120), (120, 131, 119, 130),
                                    (130, 141, 129, 140), (139, 139, 125, 126)])
parts = lab.manage(st(MANAGED), rec("LONG", 100, t[0]), t, o, h, l, c, t[-1])
check("long ladder", by(parts), {"T1 1R": (110, "target 1R"), "T2 2R": (120, "target 2R"), "rest (trail)": (130, "trail_stop")})
check("long lots", sorted(p["lots"] for p in parts), [1, 1, 1])
check("long initial sl", {p["sl"] for p in parts}, {90})

# 2. short mirror: stop 110, targets 90 / 80
t, o, h, l, c = bars("2026-08-03", [(100, 100, 100, 100), (99, 99, 89, 90), (90, 91, 79, 80), (80, 81, 69, 70), (70, 85, 70, 84)])
parts = lab.manage(st(MANAGED), rec("SHORT", 100, t[0]), t, o, h, l, c, t[-1])
check("short ladder", by(parts), {"T1 1R": (90, "target 1R"), "T2 2R": (80, "target 2R"), "rest (trail)": (80, "trail_stop")})

# 3. stop and target on the same candle: the stop is taken first, for every lot
t, o, h, l, c = bars("2026-08-03", [(100, 100, 100, 100), (100, 112, 88, 95)])
parts = lab.manage(st(MANAGED), rec("LONG", 100, t[0]), t, o, h, l, c, t[-1])
check("stop first", set(by(parts).values()), {(90, "stop_loss")})

# 4. gap through the stop mid-session fills at the open (worse than the stop)
t, o, h, l, c = bars("2026-08-03", [(100, 100, 100, 100), (85, 86, 84, 85)])
parts = lab.manage(st(MANAGED), rec("LONG", 100, t[0]), t, o, h, l, c, t[-1])
check("gap stop", set(by(parts).values()), {(85, "stop_loss")})

# 5. a session's first candle: a target counts only if the close is still beyond it (at that close); a stop fills at the close
t1, o1, h1, l1, c1 = bars("2026-08-03", [(100, 100, 100, 100)], start=15 * 60 + 29)
t2, o2, h2, l2, c2 = bars("2026-08-04", [(115, 116, 104, 105), (105, 106, 104, 105)], start=9 * 60 + 15)
T, O, H, L, C = t1 + t2, o1 + o2, h1 + h2, l1 + l2, c1 + c2
parts = lab.manage(st(MANAGED), rec("LONG", 100, T[0]), T, O, H, L, C, T[-1])
check("first-candle target not filled", [p["exit_reason"] for p in parts], ["open", "open", "open"])
t2b, o2b, h2b, l2b, c2b = bars("2026-08-04", [(115, 116, 110, 112)], start=9 * 60 + 15)
parts = lab.manage(st(MANAGED), rec("LONG", 100, T[0]), t1 + t2b, o1 + o2b, h1 + h2b, l1 + l2b, c1 + c2b, t2b[-1])
check("first-candle target at close", by(parts)["T1 1R"], (112, "target 1R"))
t2c, o2c, h2c, l2c, c2c = bars("2026-08-04", [(80, 95, 78, 93)], start=9 * 60 + 15)
parts = lab.manage(st(MANAGED), rec("LONG", 100, T[0]), t1 + t2c, o1 + o2c, h1 + h2c, l1 + l2c, c1 + c2c, t2c[-1])
check("first-candle stop at close", set(by(parts).values()), {(93, "stop_loss")})

# 6. still open at the backtest end: valued at the last candle, marked open; at a contract's end: 'expiry', not open
t, o, h, l, c = bars("2026-08-03", [(100, 100, 100, 100), (101, 104, 99, 104)])    # below 1R for both kinds
parts = lab.manage(st(MANAGED), rec("LONG", 100, t[0]), t, o, h, l, c, t[-1])
check("open at end", {(p["exit_px"], p["exit_reason"], p["open"]) for p in parts}, {(104, "open", True)})
parts = lab.manage(st(MANAGED), rec("LONG", 100, t[0], kind="OPT"), t, o, h, l, c, t[-1], expiry="2026-08-03")
check("expiry", {(p["exit_reason"], p["open"]) for p in parts}, {("expiry", False)})
parts = lab.manage(st(MANAGED), rec("LONG", 100, t[0]), t, o, h, l, c, t[-1], expiry="2026-08-10")
check("data end before expiry stays open", {(p["exit_reason"], p["open"]) for p in parts}, {("open", True)})

# 7. options: R = 5% of the entry premium (200 -> 10)
t, o, h, l, c = bars("2026-08-03", [(200, 200, 200, 200), (200, 211, 199, 210), (210, 210, 189, 190)])
parts = lab.manage(st(MANAGED), rec("LONG", 200, t[0], kind="OPT"), t, o, h, l, c, t[-1])
check("option R", by(parts), {"T1 1R": (210, "target 1R"), "T2 2R": (190, "stop_loss"), "rest (trail)": (190, "stop_loss")})

# 8. scale-out on the strategy's exit (lab.tranches): 2 lots, one out at +10, the rest with the strategy exit
t, o, h, l, c = bars("2026-08-03", [(100, 100, 100, 100), (101, 111, 100, 108), (108, 109, 104, 105)])
r0 = dict(rec("LONG", 100, t[0]), exit_time=t[-1], exit_px=105, exit_reason="next_choch", open=False)
parts = lab.tranches(st({"lots": 2, "scale_out": [{"lots": 1, "target_pts": 10}]}), r0, t, o, h, l, c)
check("scale-out", by(parts), {"T1 +10": (110, "target 10"), "rest": (105, "next_choch")})
check("default block", lab.tranches(st({}), r0, t, o, h, l, c), [dict(r0, lots=1, tranche="")])

# 9. strike lock: locked until the exit, free on the exit candle itself, per instrument; lock "none" never holds
L = lab.StrikeLock(st({}))
L.hold("NIFTY 25AUG26 24000 CE", "2026-08-03 10:00:00")
check("lock before exit", L.held("NIFTY 25AUG26 24000 CE", "2026-08-03 09:59:00"), "2026-08-03 10:00:00")
check("lock exit bar", L.held("NIFTY 25AUG26 24000 CE", "2026-08-03 10:00:00"), None)
check("lock other strike", L.held("NIFTY 25AUG26 24050 CE", "2026-08-03 09:59:00"), None)
N = lab.StrikeLock(st({"lock": "none"})); N.hold("X", "2026-08-03 10:00:00")
check("lock none", N.held("X", "2026-08-03 09:00:00"), None)

# 10. validation refuses a managed exit without a stop, and targets in R without a stop
for bad in ({"exit": "position"}, {"scale_out": [{"lots": 1, "target_r": 1}], "lots": 2}, {"lots": 1, "scale_out": [{"lots": 2, "target_pts": 5}]}):
    try: lab.position_of({"position": bad}); fails.append(f"validation accepted {bad}")
    except ValueError: pass

# 11. intraday square-off: managed lots still open at 15:25 close at that candle (reason eod); an entry at/after 15:25 is refused;
#     on the strategy's exit, a position past 15:25 is cut there
EOD = dict(MANAGED, square_off="15:25")
t, o, h, l, c = bars("2026-08-03", [(100, 100, 100, 100), (101, 104, 99, 103), (103, 105, 101, 104)], start=15 * 60 + 23)
parts = lab.manage(st(EOD), rec("LONG", 100, t[0]), t, o, h, l, c, t[-1])
check("eod managed", {(p["exit_time"][11:16], p["exit_reason"], p["open"]) for p in parts}, {("15:25", "eod", False)})
r1 = dict(rec("LONG", 100, "2026-08-03 15:20:00"), exit_time="2026-08-04 10:00:00", exit_px=90, exit_reason="next_choch", open=False)
tt = ["2026-08-03 15:20:00", "2026-08-03 15:25:00", "2026-08-04 09:15:00", "2026-08-04 10:00:00"]
check("eod cut", (lab.eod_cut(st(EOD), r1, tt, [100, 101, 97, 90]), r1["exit_time"], r1["exit_px"], r1["exit_reason"]),
      (True, "2026-08-03 15:25:00", 101, "eod"))
check("eod late entry", lab.eod_cut(st(EOD), dict(r1, entry_time="2026-08-03 15:25:00"), tt, [100, 101, 97, 90]), False)
check("no square-off", lab.eod_cut(st({}), dict(r1), tt, [100, 101, 97, 90]), True)
for bad in ({"square_off": "9:30"}, {"square_off": "15:45"}, {"square_off": 1525}):
    try: lab.position_of({"position": bad}); fails.append(f"validation accepted {bad}")
    except ValueError: pass

# 12. stop and reverse: an initial-stop exit opens the opposite position at the stop fill (a trail stop does not); once per signal
#     (max 1); not at or after the square-off; the reversed lots carry reversal = 1 and a REV tranche label
SAR = dict(MANAGED, reverse={"trigger": "initial_stop", "max": 1})
t, o, h, l, c = bars("2026-08-03", [(100, 100, 100, 100), (99, 100, 89, 90), (90, 91, 79, 80), (80, 81, 69, 70)])
parts = lab.manage(st(SAR), rec("LONG", 100, t[0]), t, o, h, l, c, t[-1])
rv = lab.reversal_of(st(SAR), parts, 0)
check("sar trigger", rv, (t[1], 90))
r2 = lab.flip(rec("LONG", 100, t[0]), rv[0], rv[1], 0)
check("sar flip", (r2["position"], r2["entry_px"], r2["entry_time"], r2["reversal"]), ("SHORT", 90, t[1], 1))
p2 = [lab.rev_tag(p) for p in lab.manage(st(SAR), r2, t, o, h, l, c, t[-1])]
check("sar reversed lots", by(p2), {"REV T1 1R": (80, "target 1R"), "REV T2 2R": (70, "target 2R"), "REV rest (trail)": (70, "open")})
check("sar max 1", lab.reversal_of(st(SAR), [dict(p, exit_reason="stop_loss") for p in p2], 1), None)
t, o, h, l, c = bars("2026-08-03", [(100, 100, 100, 100), (101, 111, 101, 110), (110, 121, 109, 120), (120, 131, 119, 130), (130, 141, 129, 140), (139, 139, 125, 126)])
check("no reverse on trail", lab.reversal_of(st(SAR), lab.manage(st(SAR), rec("LONG", 100, t[0]), t, o, h, l, c, t[-1]), 0), None)
late = [dict(exit_reason="stop_loss", exit_time="2026-08-03 15:26:00", exit_px=90)]
check("no reverse after square-off", lab.reversal_of(st(dict(SAR, square_off="15:25")), late, 0), None)
check("no reverse when off", lab.reversal_of(st(MANAGED), [dict(late[0], exit_time="2026-08-03 10:00:00")], 0), None)
for bad in ({"reverse": {"trigger": "any", "max": 1}, "exit": "position", "stop": {"futures_pts": 10, "option_pct": 5}},
            {"reverse": {"trigger": "initial_stop", "max": 1}}):
    try: lab.position_of({"position": bad}); fails.append(f"validation accepted {bad}")
    except ValueError: pass

print("\n".join(fails) if fails else "OK - position handling (12 groups)")
sys.exit(1 if fails else 0)
