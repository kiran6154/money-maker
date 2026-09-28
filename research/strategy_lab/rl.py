"""Reinforcement learning over the Foundation SETUPs (entry_rule rl_v1): a journal of every trade and a learner that decides,
at each SETUP, whether to trade and how - the exit profile, the stop distance and the number of lots - and updates itself
after every closed trade.

What the learner is
  A contextual bandit with Bayesian linear regression per action (linear Thompson sampling). One decision per SETUP,
  from features known at the SETUP candle's close (time of day, ATR, distance from the two AVWAPs, trend flip, bars since
  the CHoCH, the day's CHoCH count, the session's results so far, recent form). Actions: skip, or (exit profile x stop x
  lots) from the strategy file's `rl` block. It learns with full information: once a SETUP's candles have played out, the
  outcome of EVERY action for that SETUP is known from the price data, so every action's model is updated - not only the
  one taken. Updates are applied strictly in time order: an outcome is used only once its exit candle has closed, so no
  decision sees the future (tests/test_rl.py checks this by truncation).

Rewards (the strategy file picks one; the three are run as separate strategies)
  net  net rupees after slippage and charges, in units of one lot's 50-point risk (lot_size x 50)
  r    net points per lot divided by the stop distance (an R multiple)
  pf   as net, with losses weighted x1.5 (profit-factor oriented: fewer, cleaner trades)
  skip always earns 0.

Learning window
  The learner starts empty at the FIRST session of the futures file (Oct 2021) and learns through every SETUP to the file's
  end, once per strategy; each backtest is a window cut from that one run (its decisions up to any date do not depend on
  later data). Inside a window the trades are scored, charted and journaled as `scored`; the SETUPs before it are the
  learning history. So a 2026 window is out-of-sample for the knowledge the learner starts it with, and the learner keeps
  learning during it, as it would live. A position still open at a window's end is valued at the window's last candle.

v1 scope: near-month futures only (the Futures type); option types are refused with a reason. Costs, the strike lock and
the fill rules are the lab's (lab.manage / lab.price_trade). Deterministic: a fixed seed in the strategy file.
"""
import bisect, json, os
import numpy as np
import engine
import lab

RULES = ("rl_v1",)
REWARDS = ("net", "r", "pf")
FEATURES = ("bias", "h0915", "h10", "h11", "h12", "h13", "h14", "dir_up", "flip", "atr_pct", "d_avwap_hi", "d_avwap_lo",
            "bars_since_choch", "entry_body", "range20", "chochs_today", "day_r", "form3", "consec_loss", "closed_today", "d_day_open")
FUT_WHY = "RL v1 decides on the near-month futures only; option types and index signals are not part of it yet"
MODULES = ("rl.py",)
_SIM = {}                    # one learning run per strategy row (key -> simulate result); the last one only


def rl_rule(st):
    return str(st.get("entry_rule") or "") in RULES


# ---------------------------------------------------------------- configuration (strategy file `rl` block)
def config_of(spec):
    """The strategy file's `rl` block, validated: reward, seed, ridge, explore, stops_pts, lots, profiles."""
    c = spec.get("rl")
    if not isinstance(c, dict): raise ValueError("entry_rule rl_v1 needs an 'rl' block")
    need = {"reward", "seed", "ridge", "explore", "stops_pts", "lots", "profiles"}
    if not need <= set(c) <= need | {"notes"}: raise ValueError(f"keys are {sorted(need)} (+ optional notes; got {sorted(c)})")
    if c["reward"] not in REWARDS: raise ValueError(f"reward must be one of {REWARDS}")
    if not isinstance(c["seed"], int): raise ValueError("seed must be an integer")
    if not (isinstance(c["ridge"], (int, float)) and c["ridge"] > 0): raise ValueError("ridge must be > 0")
    if not (isinstance(c["explore"], (int, float)) and c["explore"] >= 0): raise ValueError("explore must be >= 0")
    if not c["stops_pts"] or not all(isinstance(s, (int, float)) and s > 0 for s in c["stops_pts"]): raise ValueError("stops_pts: positive numbers")
    if not c["lots"] or not all(isinstance(k, int) and k >= 1 for k in c["lots"]): raise ValueError("lots: whole numbers >= 1")
    if not isinstance(c["profiles"], dict) or not c["profiles"]: raise ValueError("profiles: at least one exit profile")
    for name, p in c["profiles"].items():
        if set(p) != {"scale_out", "trail", "square_off"}: raise ValueError(f"profile {name!r}: keys are scale_out, trail, square_off")
        if any(so.get("lots") != 1 or "target_r" not in so for so in p["scale_out"]):
            raise ValueError(f"profile {name!r}: each scale_out tranche is {{\"lots\": 1, \"target_r\": R}} (v1 sizes by whole lots)")
        lab.position_of({"position": dict(lots=max(c["lots"]), exit="position", stop={"futures_pts": 50, "option_pct": 5},
                                          scale_out=p["scale_out"], trail=p["trail"], square_off=p["square_off"])})
    return c


def arms_of(cfg):
    """[('skip',)] + [(profile name, stop pts, lots)] in a fixed order."""
    return [("skip",)] + [(p, s, k) for p in cfg["profiles"] for s in cfg["stops_pts"] for k in cfg["lots"]]


def arm_label(a):
    return "skip" if a[0] == "skip" else f"{a[0]} · stop {a[1]:g} · {a[2]} lot{'s' if a[2] > 1 else ''}"


def position_for(cfg, st, profile, stop, lots):
    """A lab position block: the profile's tranches, one lot each, for `lots` lots (fewer lots drop the last targets)."""
    p = cfg["profiles"][profile]
    so = p["scale_out"][:max(0, lots - 1)]
    return dict(lots=lots, lock=lab.position_cfg(st)["lock"], exit="position", stop={"futures_pts": stop, "option_pct": 5},
                scale_out=so, trail=p["trail"], square_off=p["square_off"], reverse=None)


# ---------------------------------------------------------------- features
def atr_arr(bars, n=14):
    h, l, c = bars["h"], bars["l"], bars["c"]
    out, a = [], 0.0
    for i in range(len(c)):
        tr = h[i] - l[i] if i == 0 else max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
        a = tr if i == 0 else (a * (n - 1) + tr) / n if i >= n else (a * i + tr) / (i + 1)
        out.append(a)
    return out


def hour_bucket(t):
    hm = t[11:16]
    return 0 if hm < "10:00" else 1 if hm < "11:00" else 2 if hm < "12:00" else 3 if hm < "13:00" else 4 if hm < "14:00" else 5


class State:
    """What the learner may know at a SETUP: the session's closed results and recent form (from the trades it took)."""

    def __init__(self):
        self.closed = []                 # (exit_time, reward) of the learner's own closed trades, time-ordered

    def features(self, bars, r, x, atr, day_open, chochs_today, e):
        t, o, c = bars["t"], bars["o"], bars["c"]
        k0 = x["entry"]; up = x["dir"] == "up"; sg = 1 if up else -1
        a = atr[k0] or 1e-9
        av = r["av"]
        avH = av(e["hi"]["bar"], k0) if e and e["hi"] else c[k0]
        avL = av(e["lo"]["bar"], k0) if e and e["lo"] else c[k0]
        lo20 = min(bars["l"][max(0, k0 - 19):k0 + 1]); hi20 = max(bars["h"][max(0, k0 - 19):k0 + 1])
        past = [z for z in self.closed if z[0] <= t[k0]]
        today = [n for (xt, n) in past if xt[:10] == t[k0][:10]]
        recent = [n for (_, n) in past][-3:]
        consec = 0
        for (_, n) in reversed(past):
            if n < 0: consec += 1
            else: break
        f = [1.0] + [1.0 if hour_bucket(t[k0]) == i else 0.0 for i in range(6)]
        f += [1.0 if up else 0.0, 1.0 if (e and e.get("flip")) else 0.0, min(a / c[k0] * 1000, 5.0),
              max(-5.0, min(5.0, sg * (c[k0] - avH) / a)), max(-5.0, min(5.0, sg * (c[k0] - avL) / a)),
              min((k0 - x["choch"]) / 20, 3.0), max(-3.0, min(3.0, sg * (c[k0] - o[k0]) / a)), min((hi20 - lo20) / a / 5, 5.0),
              min(chochs_today / 10, 3.0), max(-5.0, min(5.0, sum(today))), float(sum(1 if n > 0 else -1 for n in recent)),
              min(consec, 6) / 3, min(len(today), 10) / 5, max(-5.0, min(5.0, sg * (c[k0] - day_open) / a / 5))]
        return np.array(f, dtype=float)


# ---------------------------------------------------------------- the policy
class LinTS:
    """Bayesian linear regression per arm (ridge prior), Thompson sampling for the decision. Arm 0 (skip) is a fixed 0."""

    def __init__(self, n_arms, d, ridge, explore, seed):
        self.A = [np.eye(d) * ridge for _ in range(n_arms)]
        self.b = [np.zeros(d) for _ in range(n_arms)]
        self.explore, self.rng, self.n = explore, np.random.RandomState(seed), [0] * n_arms

    def means(self, x):
        return np.array([0.0] + [float(x @ np.linalg.solve(self.A[a], self.b[a])) for a in range(1, len(self.A))])

    def choose(self, x):
        vals = [0.0]
        for a in range(1, len(self.A)):
            Ainv = np.linalg.inv(self.A[a])
            mu = Ainv @ self.b[a]
            theta = mu + self.explore * np.linalg.cholesky(Ainv + 1e-12 * np.eye(len(mu))) @ self.rng.standard_normal(len(mu))
            vals.append(float(x @ theta))
        return int(np.argmax(vals)), vals

    def update(self, a, x, reward):
        self.A[a] += np.outer(x, x); self.b[a] += reward * x; self.n[a] += 1

    def weights(self):
        return [np.linalg.solve(self.A[a], self.b[a]).round(4).tolist() for a in range(len(self.A))]


def reward_of(cfg, st, stop, lots, tranches):
    """The reward of one action's outcome (its tranches, priced), in the strategy's reward version."""
    net = sum(tr["net"] for tr in tranches)
    if cfg["reward"] == "r":
        val = net / (st["lot_size"] * stop * lots)
    else:
        val = net / (st["lot_size"] * 50)
        if cfg["reward"] == "pf" and val < 0: val *= 1.5
    return max(-10.0, min(10.0, val))


# ---------------------------------------------------------------- outcomes of every action for one SETUP
def outcomes(cfg, st, cs, rec, bars, cap, expiry):
    """{(profile, stop): [priced max-lots tranches]} for one SETUP, computed once per profile x stop; lots are read off them."""
    t, o, h, l, c = bars["t"], bars["o"], bars["h"], bars["l"], bars["c"]
    out = {}
    kmax = max(cfg["lots"])
    for p in cfg["profiles"]:
        for s in cfg["stops_pts"]:
            stp = dict(st, position_json=json.dumps(position_for(cfg, st, p, s, kmax), sort_keys=True))
            trs = lab.manage(stp, rec, t, o, h, l, c, cap, expiry)
            for tr in trs:
                lab.excursion(t, h, l, tr, rec["position"] == "LONG"); lab.price_trade(stp, cs, tr)
            out[(p, s)] = trs
    return out


def tranches_for(cfg, st, cs, base_trs, profile, lots):
    """The tranches an action with `lots` lots takes from the max-lots outcome: the first lots-1 targets (one lot each) and
    the trailing rest with the remaining lots. Each lot's exit is independent of the others in lab.manage, so this is exact."""
    targets = [tr for tr in base_trs if not tr["tranche"].startswith("rest")]
    rest = [tr for tr in base_trs if tr["tranche"].startswith("rest")]
    if not cfg["profiles"][profile]["scale_out"]:                    # one tranche of `lots` lots
        return [lab.price_trade(st, cs, dict(rest[0], lots=lots))] if rest else []
    picked = [dict(tr) for tr in targets[:max(0, lots - 1)]]
    left = lots - len(picked)
    if rest and left > 0: picked.append(lab.price_trade(st, cs, dict(rest[0], lots=left)))
    return picked


def learnable(trs, tl):
    """An outcome can be learned from once every lot has closed for a reason that does not depend on where the data ends."""
    if not trs or any(tr["open"] for tr in trs): return False
    return all(tr["exit_reason"] in ("stop_loss", "trail_stop") or tr["exit_reason"].startswith("target") or tr["exit_time"] < tl[-1]
               for tr in trs)


# ---------------------------------------------------------------- the run
def simulate(st, cs, bars, cfg, p_engine):
    """Walk every SETUP of `bars` in time order: decide, trade, journal, learn. Returns everything (no window): trades,
    journal rows, refused SETUPs, the engine result, the arms and the policy."""
    r = engine.run(bars, p_engine)
    t, c = bars["t"], bars["c"]
    atr = atr_arr(bars, st["atr_period"] or 14)
    contracts, clast = lab.fut_contracts()
    arms = arms_of(cfg)
    policy = LinTS(len(arms), len(FEATURES), cfg["ridge"], cfg["explore"], cfg["seed"])
    ctrl_rng = np.random.RandomState(cfg["seed"] + 1)      # the control: a uniformly random action per SETUP (skip included)
    state, lock = State(), lab.StrikeLock(st)
    chs_by_i = {e["i"]: e for e in r["chs"]}
    queue, seq = [], 0                          # (exit_time, seq, arm index, features, reward): applied in time order
    trades, journal, skipped = [], [], []
    day_open, cur_day = None, None
    ch_days = {}
    for e in r["chs"]: ch_days.setdefault(t[e["i"]][:10], []).append(e["i"])
    first = list(cfg["profiles"])[0]
    base_arm = next((i for i, a in enumerate(arms) if a[0] == first and a[1] == 50 and a[2] == max(cfg["lots"])), None)

    def flush(upto):
        while queue and queue[0][0] <= upto:
            _, _, a, x, rw = queue.pop(0); policy.update(a, x, rw)

    for x in sorted(r["trades"], key=lambda z: z["entry"]):
        k0 = x["entry"]; te = t[k0]; day = te[:10]
        if day != cur_day:
            cur_day, day_open = day, bars["o"][bisect.bisect_left(t, f"{day} 00:00:00")]
        chochs_today = sum(1 for i in ch_days.get(day, []) if i <= k0)
        flush(te)
        e = chs_by_i.get(x["choch"])
        feats = state.features(bars, r, x, atr, day_open, chochs_today, e)
        bull = x["dir"] == "up"
        c_, e_ = contracts.get(te, ("NIFTY FUT", None))
        cap = t[-1]
        if e_ and c_ in clast: cap = min(cap, clast[c_])
        rec = dict(dir=x["dir"], signal="BULLISH" if bull else "BEARISH", position="LONG" if bull else "SHORT", opt_type="FUT",
                   kind="FUT", instrument=c_, strike=None, expiry=e_, choch_time=t[x["choch"]], entry_time=te, exit_time=te,
                   exit_reason="open", open=True, sl=None, entry_px=c[k0], exit_px=None, und_entry=None, und_exit=None)
        outs = outcomes(cfg, st, cs, rec, bars, cap, e_)
        per_arm = {}                            # arm -> (tranches, reward, net, learnable)
        for ai, a in enumerate(arms):
            if a[0] == "skip": per_arm[ai] = ([], 0.0, 0.0, True); continue
            trs = tranches_for(cfg, st, cs, outs[(a[0], a[1])], a[0], a[2])
            rw = reward_of(cfg, st, a[1], a[2], trs) if trs else 0.0
            ok = learnable(trs, t)
            per_arm[ai] = (trs, rw, sum(tr["net"] for tr in trs), ok)
            if ok:
                seq += 1; queue.append((max(tr["exit_time"] for tr in trs), seq, ai, feats, rw))
        queue.sort(key=lambda q: (q[0], q[1]))
        best_i = max(per_arm, key=lambda i: per_arm[i][1])
        oracle = per_arm[best_i][2]
        base_net = per_arm[base_arm][2] if base_arm is not None else 0.0
        ci = int(ctrl_rng.randint(len(arms)))              # drawn for every SETUP, so the control sequence is fixed by the seed
        held = lock.held(c_, te)
        means = policy.means(feats)
        row = dict(time=te, dir=x["dir"], hour=te[11:16], atr_pct=round(float(feats[9]) / 10, 3), d_hi=round(float(feats[10]), 2),
                   d_lo=round(float(feats[11]), 2), day_r=round(float(feats[16]), 2), form3=int(feats[17]), consec_loss=int(round(feats[18] * 3)),
                   base_net=round(base_net, 2), oracle_net=round(oracle, 2), oracle_arm=arm_label(arms[best_i]),
                   control_net=round(per_arm[ci][2], 2), control_arm=arm_label(arms[ci]),
                   pred_base=round(float(means[base_arm]), 3) if base_arm is not None else None)
        if held:
            row.update(decision="locked", pred=None, net=0.0, reward=0.0); journal.append(row)
            skipped.append(dict(entry_time=te, position=rec["position"], dir=x["dir"], why=f"strike locked: {c_} open until {held}"))
            continue
        ai, vals = policy.choose(feats)
        a = arms[ai]
        row.update(decision=arm_label(a), pred=round(float(means[ai]), 3))
        if a[0] == "skip":
            row.update(net=0.0, reward=0.0); journal.append(row)
            skipped.append(dict(entry_time=te, position=rec["position"], dir=x["dir"], why="learner skipped")); continue
        trs, rw, net, ok = per_arm[ai]
        row.update(net=round(net, 2), reward=round(rw, 3)); journal.append(row)
        end = max(tr["exit_time"] for tr in trs)
        lock.hold(c_, end)
        if ok: state.closed.append((end, rw))
        for tr in trs:
            trades.append(dict(tr, arm=arm_label(a), pred=round(float(means[ai]), 3)))
    flush(t[-1])
    return dict(engine=r, bars=bars, trades=trades, skipped=skipped, journal=journal, arms=arms, policy=policy, learned=sum(policy.n[1:]))


def learned_run(st, cs):
    """The one learning run of this strategy row over the whole futures file (cached; the last one only)."""
    f = st["data_file"]
    key = (st["code"], st["timeframe"], f, os.path.getsize(f), int(os.path.getmtime(f)), st["rl_json"], st["position_json"],
           st["lot_size"], st["slippage_pts"], json.dumps(cs, sort_keys=True, default=str))
    if key not in _SIM:
        _SIM.clear()
        bars, _ = engine.load(f, "2000-01-01", "2099-12-31", 0)
        p = dict(break_mode=st["break_mode"], choch_mode=st.get("choch_mode") or st["break_mode"], avwap_weight=st["avwap_weight"], sl_rule=st["sl_rule"])
        _SIM[key] = simulate(st, cs, bars, json.loads(st["rl_json"]), p)
    return _SIM[key]


def cut_open(tr, bars, i_end, st, cs):
    """A lot still open at the window's last candle i_end: valued there and marked open (what a run ending there would show)."""
    tr = dict(tr, exit_time=bars["t"][i_end], exit_px=bars["c"][i_end], exit_reason="open", open=True)
    lab.excursion(bars["t"], bars["h"], bars["l"], tr, tr["position"] == "LONG")
    return lab.price_trade(st, cs, tr)


def run_variant(st, cs):
    """Lab-shaped result for an RL futures row: {'-': dict(trades, skipped, signals, charts, rl)} for the window
    st['date_from'] .. st['date_to'], cut from the strategy's one learning run."""
    if st["variant"] != "FUT" or (st.get("underlying") or "FUT") != "FUT":
        return {"-": dict(trades=[], skipped=[dict(why=FUT_WHY)], signals=[], charts=[])}
    cfg = json.loads(st["rl_json"])
    res = learned_run(st, cs)
    bars, r, t = res["bars"], res["engine"], res["bars"]["t"]
    d0, d1 = f"{st['date_from']} 00:00:00", f"{st['date_to']} 23:59:59"
    s0 = bisect.bisect_left(t, d0); i_end = bisect.bisect_right(t, d1) - 1
    if s0 > i_end: return {"-": dict(trades=[], skipped=[dict(why="no candles in the window")], signals=[], charts=[])}
    t_end = t[i_end]
    trades = [tr if tr["exit_time"] <= t_end else cut_open(tr, bars, i_end, st, cs)
              for tr in res["trades"] if d0 <= tr["entry_time"] <= t_end]
    skipped = [k for k in res["skipped"] if d0 <= k["entry_time"] <= t_end]
    signals = [dict(time=t[e["i"]], dir=e["dir"], flipped=e["flip"], lvl=e["lvl"], av=e["av"],
                    hi=(t[e["hi"]["bar"]], e["hi"]["p"]) if e["hi"] else None, lo=(t[e["lo"]["bar"]], e["lo"]["p"]) if e["lo"] else None)
               for e in r["chs"] if s0 <= e["i"] <= i_end]
    setup_at = {x["ch"]: t[x["i"]] for x in r["setups"]}
    for sgl, e in zip(signals, [e for e in r["chs"] if s0 <= e["i"] <= i_end]): sgl["setup"] = setup_at.get(e["i"])
    marks = []
    for tr in trades:
        j0 = bisect.bisect_right(t, tr["entry_time"]) - 1; jx = bisect.bisect_right(t, tr["exit_time"]) - 1
        marks.append([lab.ts(t[j0]), tr["entry_px"], lab.ts(t[jx]), tr["exit_px"], tr["dir"], round(tr["pts"], 2), tr["open"], tr["sl"],
                      tr["exit_reason"], tr["position"] + (f" · {tr['tranche']}" if tr["tranche"] else ""), tr["dir"]])
    day_span = {}
    for i in range(s0, i_end + 1): day_span.setdefault(t[i][:10], [i, i])[1] = i
    charts = []
    for d, (i0, i1) in day_span.items():
        lo, hi = lab.ts(t[i0]), lab.ts(t[i1])
        mk = [m for m in marks if m[0] <= hi and m[2] >= lo]
        n = len({m[0] for m in mk if lo <= m[0] <= hi}); pnl = sum(m[5] for m in mk if lo <= m[0] <= hi)
        charts.append(dict(lab.chart(bars, r, i0, i1, mk), day=d, kind="signal",
                           label=f"{d} · futures" + (f" · {n} position{'s' * (n > 1)} · {pnl:+.1f} pts" if n else "")))
    J = [dict(j, scored=d0 <= j["time"] <= t_end) for j in res["journal"] if j["time"] <= t_end]
    sc = [j for j in J if j["scored"]]; W = [j for j in J if not j["scored"]]
    taken = [j for j in sc if j["decision"] not in ("skip", "locked")]
    months = {}
    for j in J:
        m = months.setdefault(j["time"][:7], dict(month=j["time"][:7], scored=j["scored"], setups=0, taken=0, locked=0, rl_net=0.0, base_net=0.0,
                                                  oracle_net=0.0, control_net=0.0))
        m["setups"] += 1; m["taken"] += j["decision"] not in ("skip", "locked"); m["locked"] += j["decision"] == "locked"
        m["rl_net"] += j["net"]; m["base_net"] += j["base_net"]; m["oracle_net"] += j["oracle_net"]; m["control_net"] += j["control_net"]
    mix = {}
    for j in taken: mix[j["decision"]] = mix.get(j["decision"], 0) + 1
    Wt = res["policy"].weights()
    payload = dict(reward=cfg["reward"], seed=cfg["seed"], arms=[arm_label(a) for a in res["arms"]], features=list(FEATURES),
                   learned_updates=res["learned"], learn_from=t[0][:10], scored_from=st["date_from"], scored_to=st["date_to"],
                   summary=dict(setups=len(sc), taken=len(taken), skipped=sum(1 for j in sc if j["decision"] == "skip"),
                                locked=sum(1 for j in sc if j["decision"] == "locked"),
                                rl_net=round(sum(tr["net"] for tr in trades), 2), base_net=round(sum(j["base_net"] for j in sc), 2),
                                oracle_net=round(sum(j["oracle_net"] for j in sc), 2), control_net=round(sum(j["control_net"] for j in sc), 2),
                                warmup_setups=len(W), warmup_rl_net=round(sum(j["net"] for j in W), 2),
                                warmup_base_net=round(sum(j["base_net"] for j in W), 2), warmup_control_net=round(sum(j["control_net"] for j in W), 2)),
                   action_mix=sorted(mix.items(), key=lambda kv: -kv[1]),
                   months=[dict(m, **{k: round(m[k], 2) for k in ("rl_net", "base_net", "oracle_net", "control_net")}) for m in months.values()],
                   notes=cfg.get("notes"),
                   weights={arm_label(a): Wt[i] for i, a in enumerate(res["arms"]) if i > 0 and res["policy"].n[i]},
                   journal=J, base_arm=f"{first_profile(cfg)} · stop 50 · {max(cfg['lots'])} lots (Strategy 9's rule)")
    return {"-": dict(trades=trades, skipped=skipped, signals=signals, charts=charts, rl=payload)}


def first_profile(cfg):
    return list(cfg["profiles"])[0]
