"""c2c.py (entry_rule c2c_v1, Strategies 25-28): the exit walk on synthetic put candles, and no look-ahead on real data -
a window cut at an earlier date gives the same trades for every position that closed before the cut.

    python tests/test_c2c.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import c2c, lab  # noqa: E402

fails = []
def check(name, got, want):
    if got != want: fails.append(f"{name}: got {got}, want {want}")


def series(rows):
    """rows: (time, o, h, l, c) -> a lab.Series."""
    return lab.Series.from_cols(([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows], [r[3] for r in rows],
                                 [r[4] for r in rows], [0.0] * len(rows)))


def cfg(fill, pcr=None):
    return dict(band_pts=50, day_drop_pct=0.6, pcr=pcr, stop_pct=5, trail_pts=5, stop_fill=fill,
                ladder=dict(time="15:15", profit_pct=40, loss_pct=2), max_open=1)


D0 = "2026-07-01 "
def tm(hm): return D0 + hm + ":00"

# stop: entry 100, stop 95. Close mode ignores a wick to 90 and exits on a close at 94; touch mode exits at 95 on the wick.
s = series([(tm("10:00"), 100, 100, 99, 100), (tm("10:05"), 100, 100, 90, 97), (tm("10:10"), 97, 97, 93, 94)])   # never above the entry: no trail
check("close stop", c2c.hold(s, 0, 100, cfg("close"), [], tm("09:55"), lambda T: None, 2)[:3], (2, 94, "stop_loss"))
check("touch stop", c2c.hold(s, 0, 100, cfg("touch"), [], tm("09:55"), lambda T: None, 2)[:3], (1, 95.0, "stop_loss"))
# touch: a candle opening below the stop fills at its open
s = series([(tm("10:00"), 100, 100, 99, 100), (tm("10:05"), 92, 93, 91, 92)])
check("touch gap", c2c.hold(s, 0, 100, cfg("touch"), [], tm("09:55"), lambda T: None, 1)[:3], (1, 92, "stop_loss"))
# a high of 101 on the entry candle is a gain: touch mode trails to 96 at once
s = series([(tm("10:00"), 100, 101, 99, 100), (tm("10:05"), 100, 100, 95.5, 97)])
check("touch early trail", c2c.hold(s, 0, 100, cfg("touch"), [], tm("09:55"), lambda T: None, 1)[:3], (1, 96, "trail_stop"))
# trail: peak close 120 -> stop 115; a close at 114 exits as a trail stop (close mode); touch uses the high 125 -> stop 120
s = series([(tm("10:00"), 100, 125, 100, 120), (tm("10:05"), 120, 121, 114, 114)])
check("close trail", c2c.hold(s, 0, 100, cfg("close"), [], tm("09:55"), lambda T: None, 1)[:3], (1, 114, "trail_stop"))
check("touch trail", c2c.hold(s, 0, 100, cfg("touch"), [], tm("09:55"), lambda T: None, 1)[:3], (1, 120, "trail_stop"))
# a bullish flip at 10:05 exits at that candle's close; a flip at or before the signal candle does not
s = series([(tm("10:00"), 100, 101, 99, 100), (tm("10:05"), 100, 101, 99, 101), (tm("10:10"), 101, 102, 100, 101)])
check("choch exit", c2c.hold(s, 0, 100, cfg("close"), [tm("09:50"), tm("10:05")], tm("09:55"), lambda T: None, 2)[:3], (1, 101, "choch"))
# ladder at 15:15: profit > 40 % exits; a flat position carries; with PCR rules a PCR above 0.95 exits
s = series([(tm("15:10"), 100, 101, 99, 100), (tm("15:15"), 100, 100.5, 99.5, 100), (tm("15:20"), 100, 100.5, 99.5, 100)])
check("ladder carry", c2c.hold(s, 0, 100, cfg("close"), [], tm("15:05"), lambda T: None, 2)[2:4], ("open", True))
P = dict(entry_max=1.3, exit_above=0.95, window_pts=300, min_strikes=9)
check("ladder pcr", c2c.hold(s, 0, 100, cfg("close", P), [], tm("15:05"), lambda T: 1.0, 2)[:3], (1, 100, "ladder_pcr"))
check("ladder pcr NA", c2c.hold(s, 0, 100, cfg("close", P), [], tm("15:05"), lambda T: None, 2)[2], "open")
s = series([(tm("15:10"), 100, 101, 99, 100), (tm("15:15"), 100, 101, 99, 97.5)])
check("ladder loss", c2c.hold(s, 0, 100, cfg("close"), [], tm("15:05"), lambda T: None, 1)[:3], (1, 97.5, "ladder_loss"))
# entered after 15:15: no ladder that session (the 15:20 candle is down 2.5 % but carries)
s = series([(tm("15:20"), 100, 100.5, 97, 97.5), (tm("15:25"), 97.5, 98, 97, 97.5)])
check("ladder after entry", c2c.hold(s, 0, 100, cfg("close"), [], tm("15:15"), lambda T: None, 1)[2], "open")

# no look-ahead on real data: ST25 index signals, a window cut at an earlier date
db = lab.connect()
row = db.execute("select * from strategy where code='ST25_FB'").fetchone()
if row is None:
    fails.append("ST25_FB not in strategy_lab.db: run python lab.py ST25 first")
else:
    st = dict(row)
    cs = dict(db.execute("select * from charge_schedule where code=?", (st["charge_code"],)).fetchone())
    def run(to):
        stp = dict(st, data_file=lab.tf_file("fut", "5minute"), spot_file=lab.tf_file("spot", "5minute"), underlying="INDEX",
                   signal_file=lab.tf_file("spot", "5minute"), date_from="2026-06-23", date_to=to, period="test", positions="BOTH")
        return c2c.run_variant(stp, cs)["M-ITM1"]["trades"]
    full, cut = run("2026-09-14"), run("2026-08-05")
    key = lambda x: (x["instrument"], x["entry_time"], x["entry_px"], x["exit_time"], x["exit_px"], x["exit_reason"])
    closed = [key(x) for x in full if x["exit_time"] < "2026-08-05 15:30:00"]
    check("truncation", [key(x) for x in cut if not x["open"]], closed)
    if not closed: fails.append("truncation: no closed trades before the cut (the check is empty)")

print("\n".join(fails) if fails else "OK - c2c exits and no look-ahead")
sys.exit(1 if fails else 0)
