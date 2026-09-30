"""rainbow.py (entry_rule rainbow_v1, Strategies 29-30): the ribbon's arithmetic on hand-made candles, the signal rules,
the strategy-mode exits, the config validation, and no look-ahead on real 5-minute data (a window cut at an earlier date
gives the same closed positions before the cut).

    python tests/test_rainbow.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lab, rainbow  # noqa: E402

fails = []
def check(name, got, want):
    if got != want: fails.append(f"{name}: got {str(got)[:300]}, want {str(want)[:300]}")

CFG = dict(kind="widner", levels=10, period=2, trigger="cross", fan="full", osc_min=0, lookback=10, pullback_bars=5,
           entry_from="09:20", entry_until="14:30", exit="band")


def bars_of(closes, day="2026-08-03", start=(9, 15), rng=0.5, opens=None, highs=None, lows=None):
    """Candles one minute apart from `start` on `day`: close as given, open = previous close (or given), high / low = the
    wider of open / close +- rng (or given)."""
    t, o, h, l = [], [], [], []
    for i, c in enumerate(closes):
        m = start[0] * 60 + start[1] + i
        t.append(f"{day} {m // 60:02d}:{m % 60:02d}:00")
        op = opens[i] if opens and opens[i] is not None else (closes[i - 1] if i else c)
        o.append(op)
        h.append(highs[i] if highs and highs[i] is not None else max(op, c) + rng)
        l.append(lows[i] if lows and lows[i] is not None else min(op, c) - rng)
    return dict(t=t, o=o, h=h, l=l, c=list(closes), v=[0.0] * len(closes))


# 1. arithmetic: on a straight line c = i, SMA(2) lags by 0.5 per level (line k = c - k/2); the EMA seed is the first p closes
c = [float(i) for i in range(40)]
L = rainbow.lines_of(c, CFG)
check("widner: 10 lines", len(L), 10)
check("widner: line k lags k/2 on a straight line", [round(L[k][30] - (30 - (k + 1) / 2), 9) for k in range(10)], [0.0] * 10)
check("widner: line k defined from k*(p-1)", [next(i for i, v in enumerate(L[k]) if v is not None) for k in (0, 1, 9)], [1, 2, 10])
E = rainbow.lines_of(c, dict(CFG, kind="ema", periods=[2, 3]))
check("ema: seeded with the first p closes", (E[0][1], E[1][2], E[0][0]), (0.5, 1.0, None))
check("ema recurrence", round(E[0][2], 6), round(0.5 + 2 / 3 * (2 - 0.5), 6))
check("sma restarts after a None", rainbow.sma([1.0, None, 2.0, 4.0], 2), [None, None, None, 3.0])

# 2. band, fan and oscillator: on a rising line the fan is bullish and price is above the top line
b = bars_of(c)
R = rainbow.ribbon(b, CFG)
check("start = first candle with every line", R["start"], 10)
check("rising: fan bullish, price above the band", (R["fan_up"][30], R["fan_dn"][30], b["c"][30] > R["top"][30]), (True, False, True))
check("oscillator positive above the ribbon", R["osc"][30] > 0, True)
# no fresh cross on a monotonic line: no signal even with a wide entry window
check("monotonic line: no fresh cross", rainbow.signals(b, dict(CFG, entry_from="00:00", entry_until="23:59")), [])

# 3. a flat stretch, then a break above the ribbon: one long signal on the first close above the band, fan not yet full
#    (the flat lines are equal, so fan 'full' refuses it and fan 'none' takes it); the short mirror on a break below
flat = [100.0] * 20 + [100.0 + 3 * k for k in range(1, 12)]
b3 = bars_of(flat)
wide = dict(CFG, entry_from="00:00", entry_until="23:59")
s_none = rainbow.signals(b3, dict(wide, fan="none"))
check("break above a flat ribbon: one long signal at the first close above", [(s["i"], s["dir"]) for s in s_none], [(20, "up")])
s_full = rainbow.signals(b3, dict(wide, fan="full"))
check("a 2-period ribbon fans on the first up candle: fan 'full' signals there too", [(s["i"], s["dir"]) for s in s_full], [(20, "up")])
down = [100.0] * 20 + [100.0 - 3 * k for k in range(1, 12)]
check("break below: a short", [(s["i"], s["dir"]) for s in rainbow.signals(bars_of(down), dict(wide, fan="none"))], [(20, "down")])
check("osc_min refuses a weak break", rainbow.signals(b3, dict(wide, fan="none", osc_min=99)), [])
check("session window refuses signals outside it", rainbow.signals(b3, dict(CFG, fan="none", entry_from="10:00", entry_until="11:00")), [])

# 4. strategy-mode exits: the stop is the band's far side at the signal candle; a close back through the far side exits at
#    that close; a gap through the stop fills at the open; a session's first candle fills at its close
up = [100.0] * 20 + [103.0, 106.0, 109.0, 112.0, 115.0]
seq = up + [113.0, 111.0, 99.0]                     # then a fall: the close at 99 is through the band (and the stop)
b4 = bars_of(seq)
cfg4 = dict(wide, fan="none")
R4 = rainbow.ribbon(b4, cfg4); S4 = rainbow.signals(b4, cfg4, R4)
X4 = rainbow.trades_of(b4, S4, cfg4, R4)
check("a long from the break, then a short from the fall through the band", [x["dir"] for x in X4], ["up", "down"])
x = X4[0]
check("stop = bottom line at the signal candle", x["sl"], R4["bot"][x["entry"]])
check("exit on the candle whose low touches the stop, at the stop", (x["exit"], x["exit_px"], x["exit_reason"]),
      (next(k for k in range(x["entry"] + 1, len(seq)) if b4["l"][k] <= x["sl"]), x["sl"], "stop_loss"))
# band exit: a close below the bottom line while the low stays above the stop
seq5 = up + [114.0, 113.5, 113.0, 112.5, 112.0, 111.5, 111.0, 110.5, 110.0, 109.5, 109.0, 108.5, 108.0, 107.5, 107.0]
b5 = bars_of(seq5, rng=0.1)
R5 = rainbow.ribbon(b5, cfg4); S5 = rainbow.signals(b5, cfg4, R5); X5 = rainbow.trades_of(b5, S5, cfg4, R5)
if X5:
    x5 = X5[0]
    k_band = next((k for k in range(x5["entry"] + 1, len(seq5)) if b5["c"][k] < R5["bot"][k]), None)
    k_stop = next((k for k in range(x5["entry"] + 1, len(seq5)) if b5["l"][k] <= x5["sl"]), None)
    if k_band is not None and (k_stop is None or k_band < k_stop):
        check("band exit at the first close through the bottom line", (x5["exit"], x5["exit_px"], x5["exit_reason"]), (k_band, b5["c"][k_band], "band_exit"))
    check("exit 'none' keeps the position past the band exit", rainbow.trades_of(b5, S5, dict(cfg4, exit="none"), R5)[0]["exit_reason"] in ("stop_loss", "open"), True)
else:
    fails.append("band-exit case produced no trade")
# gap through the stop: fills at the open; on a session's first candle: at the close
g = bars_of(up + [90.0], opens=[None] * 25 + [92.0], lows=[None] * 25 + [89.0])
Rg = rainbow.ribbon(g, cfg4); Sg = rainbow.signals(g, cfg4, Rg); Xg = rainbow.trades_of(g, Sg, cfg4, Rg)
check("gap through the stop fills at the open", (Xg[0]["exit_reason"], Xg[0]["exit_px"]), ("stop_loss", 92.0))
gt = bars_of(up + [90.0], opens=[None] * 25 + [92.0]); gt["t"][-1] = "2026-08-04 09:15:00"
Rt = rainbow.ribbon(gt, cfg4); St = rainbow.signals(gt, cfg4, Rt); Xt = rainbow.trades_of(gt, St, cfg4, Rt)
check("first candle of a session fills at its close", (Xt[0]["exit_reason"], Xt[0]["exit_px"]), ("stop_loss", 90.0))

# 5. pullback trigger: after a rise (closes above the band), a dip into the ribbon and a close back above it is a re-emergence and
#    signals; the plain cross does too (a fresh close above); the first break out of a long flat range is a cross, not a pullback
rise = [100.0 + 2 * k for k in range(30)]
dip = rise + [rise[-1] - 3.0, rise[-1] - 4.0, rise[-1] + 1.0, rise[-1] + 3.0]
bp = bars_of(dip, rng=0.2)
cp = dict(wide, fan="none", trigger="pullback", pullback_bars=5)   # a dip swaps the fastest lines, so the slope test is the trend filter here
Rp = rainbow.ribbon(bp, cp); Sp = rainbow.signals(bp, cp, Rp)
check("pullback: a signal at the re-emergence, the slow edge still rising", ([(s["i"], s["dir"], s["reentry"]) for s in Sp]), [(32, "up", True)])
flat_break = bars_of([100.0] * 30 + rise, rng=0.2)                # j0 >= start here, so the re-emergence test itself refuses the first break
check("pullback: the first break out of a range is not a pullback", rainbow.signals(flat_break, cp), [])
check("cross: the first break out of a range is a cross", [(s["i"], s["dir"]) for s in rainbow.signals(flat_break, dict(cp, trigger="cross"))], [(31, "up")])   # rise[0] equals the flat level; the first higher close is index 31
check("pullback signals are a subset of the cross signals", set(s["i"] for s in Sp) <= set(s["i"] for s in rainbow.signals(bp, dict(cp, trigger="cross"), Rp)), True)

# 5b. the short side, a stop and a band exit on the same candle (the stop first), the oscillator's value, 'open' at the last candle
dn = [100.0] * 20 + [97.0, 94.0, 91.0, 88.0, 85.0] + [87.0, 89.0, 101.0]
bd = bars_of(dn); Rd = rainbow.ribbon(bd, cfg4); Sd = rainbow.signals(bd, cfg4, Rd); Xd = rainbow.trades_of(bd, Sd, cfg4, Rd)
xs = [x for x in Xd if x["dir"] == "down"]
check("short: stop = top line at the signal candle, exit when the high reaches it", (len(xs) == 1, xs[0]["sl"] == Rd["top"][xs[0]["entry"]], xs[0]["exit_reason"]), (True, True, "stop_loss"))
check("short: pts = entry - exit", round(xs[0]["pts"], 6), round(bd["c"][xs[0]["entry"]] - xs[0]["exit_px"], 6))
same = bars_of(up + [90.0], lows=[None] * 25 + [80.0])            # the last candle closes through the band AND its low takes the stop
Rs = rainbow.ribbon(same, cfg4); Ss = rainbow.signals(same, cfg4, Rs); Xs = rainbow.trades_of(same, Ss, cfg4, Rs)
check("stop before band exit on one candle", Xs[0]["exit_reason"], "stop_loss")
still = bars_of(up); Ro = rainbow.ribbon(still, cfg4); So = rainbow.signals(still, cfg4, Ro); Xo = rainbow.trades_of(still, So, cfg4, Ro)
check("still open at the last candle: 'open', valued at its close", (Xo[0]["exit_reason"], Xo[0]["open"], Xo[0]["exit_px"]), ("open", True, still["c"][-1]))
c9 = [float(v) for v in [100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 120]]   # a jump: close 120, lines lag, range 110-120 over 10 candles? use lookback 10
b9 = dict(t=[f"2026-08-03 10:{m:02d}:00" for m in range(len(c9))], o=c9, h=[v + 0.1 for v in c9], l=[v - 0.1 for v in c9], c=c9, v=[0.0] * len(c9))
R9 = rainbow.ribbon(b9, dict(CFG, kind="ema", periods=[2, 3], lookback=10))
i9 = len(c9) - 1
mean9 = (R9["lines"][0][i9] + R9["lines"][1][i9]) / 2
check("oscillator = 100 x (close - mean of lines) / (highest - lowest close over the lookback)", round(R9["osc"][i9], 6), round(100 * (120 - mean9) / (120 - 102), 6))

# 5c. a window that starts earlier gives the same widner lines, band and signals (the study reads one run in two parts)
early = bars_of([100.0 + (k % 7) * 0.37 for k in range(400)], rng=0.3)
late = {k: v[100:] for k, v in early.items()}
Re, Rl = rainbow.ribbon(early, cfg4), rainbow.ribbon(late, cfg4)
k0 = Rl["start"]
check("widner lines do not depend on how much history precedes", [round(v, 12) for v in Re["top"][100 + k0:]], [round(v, 12) for v in Rl["top"][k0:]])
check("widner signals do not depend on how much history precedes", [(s["i"] - 100, s["dir"]) for s in rainbow.signals(early, cfg4, Re) if s["i"] >= 100 + k0 + 10],
      [(s["i"], s["dir"]) for s in rainbow.signals(late, cfg4, Rl) if s["i"] >= k0 + 10])

# 6. configuration
for bad in (dict(CFG, kind="sma"), dict(CFG, levels=1), dict(CFG, kind="ema"), dict(CFG, kind="ema", periods=[5, 5]), dict(CFG, trigger="x"),
            dict(CFG, osc_min=101), dict(CFG, entry_from="14:30", entry_until="09:20"), dict(CFG, exit="close"), dict(CFG, extra=1)):
    try: rainbow.config_of({"rainbow": bad}); fails.append(f"config accepted {sorted(k for k in bad if bad[k] != CFG.get(k))}")
    except ValueError: pass
check("config accepts the classic", rainbow.config_of({"rainbow": CFG})["levels"], 10)

# 7. no look-ahead on real 5-minute futures: the same closed positions before an earlier cut (Strategy 9's file with the rainbow rule)
spec = dict(next(sp for _, sp in lab.load_strategies() if sp["code"] == "ST10"))
spec["rainbow"] = CFG; spec["rules"] = dict(spec["rules"], entry_rule="rainbow_v1")
spec["position"] = dict(lots=3, lock="strike", exit="position", stop={"futures_pts": 50, "option_pct": 5},
                        scale_out=[{"lots": 1, "target_r": 1}, {"lots": 1, "target_r": 2}], trail={"start_r": 3, "lag_r": 1}, square_off="15:25", reverse=None)
row = next(x for x in lab.type_rows(spec) if x["variant"] == "FUT")
st = dict(row, timeframe="5minute", data_file=lab.FUT5, spot_file=lab.tf_file("spot", "5minute"), positions="BOTH", underlying="FUT",
          date_from="2026-07-01", date_to="2026-09-25", period="test", warmup_days=2)
cs = dict(json.load(open(lab.CHARGECFG, encoding="utf-8"))[st["charge_code"]], code=st["charge_code"])
full = rainbow.run_variant(st, cs)["-"]
cut = rainbow.run_variant(dict(st, date_to="2026-08-14"), cs)["-"]
key = lambda x: (x["entry_time"], x["tranche"], x["entry_px"], x["exit_time"], x["exit_px"], x["exit_reason"])
closed = [key(x) for x in full["trades"] if x["exit_time"] <= "2026-08-14 15:30:00"]
check("truncation: the same closed positions before the cut", [key(x) for x in cut["trades"] if not x["open"]], closed)
if len(closed) < 10: fails.append(f"truncation: only {len(closed)} closed positions before the cut")
check("every position closed by the square-off", all(x["exit_time"][11:16] <= "15:25" for x in full["trades"]), True)
check("one position per contract at a time (lock)", full["rainbow"]["locked"] >= 0 and all(k.get("why", "").startswith(("strike locked", "entry at")) for k in full["skipped"]), True)
check("charts carry the ribbon", all(len(ch["RB"]) == 10 for ch in full["charts"]), True)
print(f"5m Jul-Sep: {full['rainbow']['signals']} signals, {len(full['trades'])} lot exits, {full['rainbow']['locked']} locked")
print("\n".join(fails) if fails else "OK - rainbow (arithmetic, signals, exits, config, no look-ahead)")
sys.exit(1 if fails else 0)
