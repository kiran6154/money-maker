"""The learner (rl.py) on real 5-minute candles and on hand-made cases:
  1. no look-ahead: cut the candles at random bars; every decision before the cut is the same as in the full run
  2. determinism: the same seed gives the same decisions
  3. learning: with known rewards the policy converges to the right action per context
  4. outcomes: lots are read off the max-lots outcome correctly; the learnable rule; the base arm is Strategy 9's rule

    python tests/test_rl.py
"""
import json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import engine, lab, rl  # noqa: E402

CFG = {"reward": "net", "seed": 7, "ridge": 1.0, "explore": 0.3, "stops_pts": [35, 50, 75], "lots": [1, 2, 3],
       "profiles": {"intraday 1R/2R trail 3R-1": {"scale_out": [{"lots": 1, "target_r": 1}, {"lots": 1, "target_r": 2}], "trail": {"start_r": 3, "lag_r": 1}, "square_off": "15:25"},
                    "positional trail 3R-2": {"scale_out": [], "trail": {"start_r": 3, "lag_r": 2}, "square_off": None},
                    "positional 2R/4R trail 4R-2": {"scale_out": [{"lots": 1, "target_r": 2}, {"lots": 1, "target_r": 4}], "trail": {"start_r": 4, "lag_r": 2}, "square_off": None}}}
fails = []
def check(name, got, want):
    if got != want: fails.append(f"{name}: got {str(got)[:300]}, want {str(want)[:300]}")


spec = dict(next(sp for _, sp in lab.load_strategies() if sp["code"] == "ST10"))
spec["rl"] = CFG; spec["rules"] = dict(spec["rules"], entry_rule="rl_v1")
row = next(x for x in lab.type_rows(spec) if x["variant"] == "FUT")
st = dict(row, timeframe="5minute", data_file=lab.FUT5, positions="BOTH", underlying="FUT")
cs = dict(json.load(open(lab.CHARGECFG, encoding="utf-8"))[st["charge_code"]], code=st["charge_code"])
P = dict(break_mode=st["break_mode"], choch_mode=st.get("choch_mode") or st["break_mode"], avwap_weight=st["avwap_weight"], sl_rule=st["sl_rule"])
bars, s0 = engine.load(lab.FUT5, "2026-05-01", "2026-09-25", 5)
n = len(bars["t"])
full = rl.simulate(st, cs, bars, CFG, P)
dec = lambda res: [(j["time"], j["decision"]) for j in res["journal"]]
full_dec = dec(full)
print(f"5m window: {n} bars, {len(full_dec)} setups, {len(full['trades'])} lot exits, learned updates {full['learned']}")

# 1. no look-ahead
random.seed(11)
for cut in sorted(random.sample(range(n // 3, n - 20), 4)):
    part = {k: v[:cut] for k, v in bars.items()}
    res = rl.simulate(st, cs, part, CFG, P)
    upto = bars["t"][cut - 1]
    a = [d for d in full_dec if d[0] < upto]
    b = [d for d in dec(res) if d[0] < upto]
    check(f"no look-ahead (cut {cut} = {upto})", b, a)

# 1b. one-candle peeks: random cuts rarely land next to a SETUP, so also cut right after 8 SETUP candles - the decision taken on
#     the cut candle itself must match the full run (a feature or update that peeked one bar ahead would differ here)
random.seed(5)
setups = sorted(full["engine"]["trades"], key=lambda z: z["entry"])
for x in random.sample(setups[5:], 8):
    cut = x["entry"] + 1
    part = {k: v[:cut] for k, v in bars.items()}
    res = rl.simulate(st, cs, part, CFG, P)
    upto = bars["t"][cut - 1]
    check(f"decision on the cut candle ({upto})", [d for d in dec(res) if d[0] <= upto], [d for d in full_dec if d[0] <= upto])

# 2. determinism
again = rl.simulate(st, cs, bars, CFG, P)
check("determinism", dec(again), full_dec)

# 3. the policy learns known rewards
pol = rl.LinTS(4, 2, 1.0, 0.3, 3)
rng = np.random.RandomState(1)
for _ in range(400):
    x = np.array([1.0, rng.choice([-1.0, 1.0])])
    pol.update(1, x, 1.0); pol.update(2, x, -1.0); pol.update(3, x, 2.0 if x[1] > 0 else -2.0)
pick = lambda x: sum(1 for _ in range(50) if pol.choose(np.array([1.0, x]))[0] == (3 if x > 0 else 1)) / 50
check("learns context +1 -> arm 3", pick(1.0) >= 0.8, True)
check("learns context -1 -> arm 1", pick(-1.0) >= 0.8, True)
check("skip when all negative", rl.LinTS(3, 2, 1.0, 0.0, 0).choose(np.array([1.0, 0.0]))[0], 0)

# 4. outcomes and lots
arms = rl.arms_of(CFG)
check("arms", len(arms), 1 + 3 * 3 * 3)
check("base arm = first profile · stop 50 · 3 lots", arms[[i for i, a in enumerate(arms) if a != ("skip",) and a[0] == list(CFG["profiles"])[0] and a[1] == 50 and a[2] == 3][0]],
      ("intraday 1R/2R trail 3R-1", 50, 3))
t = ["2026-08-03 09:%02d:00" % m for m in range(20, 30)]
mk = lambda o, h, l, c: (o, h, l, c)
rows = [mk(100, 100, 100, 100), mk(101, 151, 100, 150), mk(150, 201, 149, 200), mk(200, 251, 199, 250), mk(250, 251, 240, 241),
        mk(241, 242, 200, 201), mk(201, 202, 199, 200), mk(200, 201, 199, 200), mk(200, 201, 199, 200), mk(200, 201, 199, 200)]
b2 = dict(t=t, o=[r[0] for r in rows], h=[r[1] for r in rows], l=[r[2] for r in rows], c=[r[3] for r in rows], v=[0] * 10)
rec = dict(dir="up", signal="BULLISH", position="LONG", opt_type="FUT", kind="FUT", instrument="X", strike=None, expiry=None,
           choch_time=t[0], entry_time=t[0], exit_time=t[0], exit_reason="open", open=True, sl=None, entry_px=100.0, exit_px=None,
           und_entry=None, und_exit=None)
outs = rl.outcomes(CFG, st, cs, rec, b2, t[-1], None)
p0 = outs[("intraday 1R/2R trail 3R-1", 50)]
check("3-lot tranches", [(x["tranche"], x["exit_px"]) for x in p0], [("T1 1R", 150.0), ("T2 2R", 200.0), ("rest (trail)", 200.0)])
t2 = rl.tranches_for(CFG, st, cs, p0, "intraday 1R/2R trail 3R-1", 2)
check("2 lots = T1 + rest", [(x["tranche"], x["lots"]) for x in t2], [("T1 1R", 1), ("rest (trail)", 1)])
t1 = rl.tranches_for(CFG, st, cs, p0, "intraday 1R/2R trail 3R-1", 1)
check("1 lot = rest only", [(x["tranche"], x["lots"]) for x in t1], [("rest (trail)", 1)])
p1 = outs[("positional trail 3R-2", 50)]
t13 = rl.tranches_for(CFG, st, cs, p1, "positional trail 3R-2", 3); t11 = rl.tranches_for(CFG, st, cs, p1, "positional trail 3R-2", 1)
check("all-lot trail: 3 lots one tranche", (len(t13), t13[0]["lots"]), (1, 3))
check("all-lot trail: net scales with lots (gross)", round(t13[0]["gross"] / t11[0]["gross"], 6), 3.0)
check("learnable: closed by a stop", rl.learnable(t1, t), True)
open_tr = [dict(t1[0], open=True, exit_reason="open", exit_time=t[-1])]
check("not learnable: open at the end", rl.learnable(open_tr, t), False)
eod_end = [dict(t1[0], open=False, exit_reason="eod", exit_time=t[-1])]
check("not learnable: eod on the last bar", rl.learnable(eod_end, t), False)
check("reward net units", round(rl.reward_of(dict(CFG, reward="net"), st, 50, 1, t1), 4), round(t1[0]["net"] / (st["lot_size"] * 50), 4))
check("reward pf weights losses", rl.reward_of(dict(CFG, reward="pf"), st, 50, 1, [dict(t1[0], net=-3250.0)]), -1.5)
# 5. sizing stays learnable: the R reward of 3 lots is about 3x that of 1 lot (charges per order make it a little more), and the
#    clip is per lot (3 lots of +20 per lot -> +30, not +10); an intraday profile is not an option at / after its square-off
r1, r3 = rl.reward_of(dict(CFG, reward="r"), st, 50, 1, t11), rl.reward_of(dict(CFG, reward="r"), st, 50, 3, t13)
check("r reward scales with lots", 2.9 <= r3 / r1 <= 3.1, True)
check("clip per lot", rl.reward_of(dict(CFG, reward="net"), st, 50, 3, [dict(t13[0], net=3 * 20 * st["lot_size"] * 50)]), 30.0)
feas = rl.feasible_arms(CFG, arms, "2026-08-03 15:26:00")
check("intraday arms infeasible after square-off", [rl.arm_label(a) for a, f in zip(arms, feas) if not f],
      [rl.arm_label(a) for a in arms if a[0] == "intraday 1R/2R trail 3R-1"])
check("all arms feasible mid-day", all(rl.feasible_arms(CFG, arms, "2026-08-03 11:00:00")), True)
pol2 = rl.LinTS(4, 2, 1.0, 0.0, 0); pol2.update(1, np.array([1.0, 0.0]), 5.0); pol2.update(2, np.array([1.0, 0.0]), 3.0)
check("choose respects the mask", pol2.choose(np.array([1.0, 0.0]), [True, False, True, True])[0], 2)
check("base arm = first profile · stop 50 · max lots", rl.arm_label(arms[rl.base_arm_of(CFG, arms)]), "intraday 1R/2R trail 3R-1 · stop 50 · 3 lots")
for bad in (dict(CFG, stops_pts=[35, 75]), dict(CFG, profiles={"p": {"scale_out": [{"lots": 1, "target_r": 1}, {"lots": 1, "target_r": 2}, {"lots": 1, "target_r": 3}], "trail": {"start_r": 4, "lag_r": 1}, "square_off": None}})):
    try: rl.config_of({"rl": bad}); fails.append(f"config accepted {list(bad)[:1]}")
    except ValueError: pass
# the full 5m run: the base and control books never hold two positions at once (their taken SETUPs are separated by their exits)
jb = [j for j in full["journal"] if j["base_taken"]]
check("base book has taken SETUPs", len(jb) > 10, True)
check("no infeasible intraday base after 15:25", any(j["base_taken"] and j["hour"] >= "15:25" for j in full["journal"]), False)
# 6. a window of the run: every book cut at the window's last candle and the tiles, the month rows and the trades agree;
#    the seed spread, the random books and the matched permutations are the sizes the config says
WP = rl.window_payload(full, st, cs, CFG, "2026-08-12", "2026-09-04")
W, S = WP["rl"], WP["rl"]["summary"]
check("window trades sum to the learner tile", round(sum(x["net"] for x in WP["trades"]), 2), S["rl_net"])
scored_m = [m for m in W["months"] if m["scored"]]
for k in ("rl_net", "base_net", "control_net"):
    check(f"scored month rows sum to the tile ({k})", round(sum(m[k] for m in scored_m), 2), S[k])
check("a straddling month is two rows", [(m["month"], m["scored"]) for m in W["months"] if m["month"] == "2026-08"], [("2026-08", False), ("2026-08", True)])
check("month keys unique", len({(m["month"], m["scored"]) for m in W["months"]}), len(W["months"]))
check("seed spread: the primary seed first, with the tile's net", (W["seeds"]["runs"][0]["seed"], W["seeds"]["runs"][0]["net"], len(W["seeds"]["runs"])), (CFG["seed"], S["rl_net"], 5))
check("random books: 200 draws, draw 0 is the journal's Random column", (W["random"]["draws"], W["random"]["draw0"]), (200, S["control_net"]))
check("random percentile in range", 0 <= W["random"]["learner_pct"] <= 100, True)
check("permutations: the learner's free-SETUP decisions, 200 shuffles", (W["permutation"]["actions"], W["permutation"]["n"]), (S["taken"] + S["skipped"], 200))
check("prediction pairs bounded by taken", W["prediction"]["taken_n"] <= S["taken"], True)
check("feature sd per feature, bias constant", (len(W["feature_sd"]), W["feature_sd"][0]), (len(rl.FEATURES), 0.0))
check("clipped outcomes bounded", 0 <= S["clipped"] <= S["outcomes"], True)
check("locked + taken + skipped = scored SETUPs", S["taken"] + S["skipped"] + S["locked"], S["setups"])
# 7. a contract whose candles end before its expiry date closes at its last candle; at the data's end the calendar expiry stands
tl = ["2022-03-01 09:15:00", "2026-09-25 15:25:00"]
check("contract end before expiry = its last candle", rl.contract_end(tl, "MAR22", "2022-03-31", {"MAR22": "2022-03-28 15:25:00"}), ("2022-03-28 15:25:00", "2022-03-28"))
check("contract end at the data end keeps the expiry", rl.contract_end(tl, "SEP26", "2026-09-29", {"SEP26": "2026-09-25 15:25:00"}), ("2026-09-25 15:25:00", "2026-09-29"))
for bad in (dict(CFG, spread_seeds=[7, 11]), dict(CFG, control_draws=0)):
    try: rl.config_of({"rl": bad}); fails.append(f"config accepted {[k for k in bad if k not in CFG]}")
    except ValueError: pass
check("default spread seeds", rl.spread_seeds_of(CFG), [1007, 2007, 3007, 4007])
print(chr(10).join(fails) if fails else "OK - rl (no look-ahead on 4 random cuts + 8 SETUP-candle cuts, determinism, learning, outcomes, books, window, spread, controls)")
sys.exit(1 if fails else 0)
