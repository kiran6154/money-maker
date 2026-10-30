"""Reinforcement learning over the Foundation SETUPs (entry_rule rl_v1): a journal of every trade and a learner that decides,
at each SETUP, whether to trade and how - the exit profile, the stop distance and the number of lots - and updates itself
after every closed trade.

What the learner is
  A contextual bandit with Bayesian linear regression per action (linear Thompson sampling). One decision per SETUP,
  from features known at the SETUP candle's close (time of day, ATR, distance from the two AVWAPs, trend flip, bars since
  the CHoCH, the day's CHoCH count, the session's results so far, recent form). Actions: skip, or (exit profile x stop x
  lots) from the strategy file's `rl` block; an intraday profile is not an option at or after its square-off time. It learns
  with full information: once a SETUP's candles have played out, the outcome of EVERY feasible action for that SETUP is
  known from the price data, so every action's model is updated - not only the one taken. Updates are applied strictly in
  time order: an outcome is used only once its exit candle has closed, so no decision sees the future (tests/test_rl.py
  checks this by truncation, at random candles and right after SETUP candles).
  Under full information the exploration term plays no learning role (every action's model updates on every SETUP); it
  only randomises near-ties and shrinks as 1/sqrt(updates), so after a few hundred SETUPs a decision is close to the argmax
  of 27 posterior means. That maximum is biased upward (the winner's curse): `pred` runs above the realised reward of the
  trades taken; the payload reports the gap and the correlation between pred and realised reward so it can be read.
  Lots are chosen by expected reward alone: there is no risk or drawdown term.

Rewards (the strategy file picks one; the three are run as separate strategies). Each is a per-lot value, clipped to +-10
per lot so one outlier cannot swamp a linear model, times the lots, so sizing stays learnable:
  net  net rupees after slippage and charges, per lot, in units of one lot's 50-point risk (lot_size x 50)
  r    the position's R multiple: net points per lot divided by the stop distance
  pf   as net, with losses weighted x1.5 (profit-factor oriented: fewer, cleaner trades)
  skip always earns 0.
  A loss is bounded by the stop (about 5 units at most), a trailing win is not, so the clip cuts the right tail only - most
  often on the multi-lot trailing arms; the payload counts the clipped outcomes per action.
  The reward of an action is its own outcome at that SETUP. The learner's BOOK holds one position per contract (the lab's
  strike lock), so a long-held action also costs the book the SETUPs it locks out - and that cost is in no reward. The
  learner is therefore biased toward the positional profiles relative to their value to the book; read the action mix
  beside the locked count (STRATEGY_ANALYSIS_TODO S51).

Learning window
  The learner starts empty at the FIRST session of the futures file (Oct 2021) and learns through every SETUP to the file's
  end, once per strategy; each backtest is a window cut from that one run (its decisions up to any date do not depend on
  later data). Inside a window the trades are scored, charted and journaled as `scored`; the SETUPs before it are the
  learning history. So a 2026 window is out-of-sample for the knowledge the learner starts it with, and the learner keeps
  learning during it, as it would live. Every book is valued at the window's last candle for lots still open there, and a
  month straddling the window's start is reported as two rows (learning, scored).

Yardsticks, reported beside the learner (every book holds one position per contract, like the learner):
  BASE book      the strategy file's first profile at stop 50 with the most lots - Strategy 9's rule - at every feasible
                 SETUP its own open position does not lock
  RANDOM books   `control_draws` (default 200) seeded books, each a uniformly random action per SETUP (skip is 1 of 28, so
                 they take almost every free SETUP, 2 lots on average); the learner's percentile among them is reported and
                 draw 0 is the journal's Random column. Beating them is necessary, not sufficient.
  PERMUTATIONS   `control_draws` matched controls: the learner's own decisions in the window, shuffled across the window's
                 SETUPs in time order (the same action multiset, so the same take rate and sizes; an action a SETUP cannot
                 take goes to the next free one). The learner's percentile among them, and the share at or above it, test
                 WHERE it chose to trade.
  SEED SPREAD    the learner run again from empty with `spread_seeds` (default 4 more seeds): the window net of each. Four
                 features and the lock depend on the learner's own path, so one seed is one path; the spread is the first
                 thing to read. The backtest windows are cuts of one run and nested, not independent checks.
  ORACLE         the best NET among the feasible actions per SETUP in hindsight, skip included, so never below 0 at a
                 SETUP; the maximum of 27 noisy outcomes summed - an upper bound, not a target to capture a share of.

v1 scope: near-month futures only (the Futures type); option types and a backtest's square-off override are refused with a
reason (each exit profile carries its own square-off). Costs, the strike lock and the fill rules are the lab's (lab.manage /
lab.price_trade); a contract whose candles end before its expiry date closes the lots at its last candle ('expiry').
Deterministic: fixed seeds in the strategy file.
"""
import bisect, hashlib, heapq, json, os
import numpy as np
import engine
import lab

RULES = ("rl_v1",)
REWARDS = ("net", "r", "pf")
FEATURES = ("bias", "h0915", "h10", "h11", "h12", "h13", "h14", "dir_up", "flip", "atr_pct", "d_avwap_hi", "d_avwap_lo",
            "bars_since_choch", "entry_body", "range20", "chochs_today", "day_r", "form3", "consec_loss", "closed_today", "d_day_open")
PATH_FEATURES = ("day_r", "form3", "consec_loss", "closed_today")   # filled from the book's own closed trades at decision time
FUT_WHY = "RL v1 decides on the near-month futures only; option types and index signals are not part of it yet"
SQUARE_OFF_WHY = "the learner's exit profiles carry their own square-off; a backtest cannot override it"
MODULES = ("rl.py",)
BASE_STOP = 50               # the base book's stop (Strategy 9's rule); the strategy file's stops must include it
CLIP = 10.0                  # reward clip per lot
SPREAD_SEEDS = 4             # extra learning runs for the seed spread when the file names none (seed + 1000 k)
CONTROL_DRAWS = 200          # random books and matched permutations when the file names no count
_SIM = {}                    # one learning run per strategy row (key -> simulate result); the last one only


def rl_rule(st):
    return str(st.get("entry_rule") or "") in RULES


def code_hash():
    """sha1[:16] of the learner's modules (line endings normalised): the code a learner result comes from."""
    h = hashlib.sha1()
    for f in MODULES: h.update(open(os.path.join(lab.HERE, f), "rb").read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


# ---------------------------------------------------------------- configuration (strategy file `rl` block)
def config_of(spec):
    """The strategy file's `rl` block, validated: reward, seed, ridge, explore, stops_pts, lots, profiles (+ optional notes,
    spread_seeds, control_draws)."""
    c = spec.get("rl")
    if not isinstance(c, dict): raise ValueError("entry_rule rl_v1 needs an 'rl' block")
    need = {"reward", "seed", "ridge", "explore", "stops_pts", "lots", "profiles"}
    opt = {"notes", "spread_seeds", "control_draws"}
    if not need <= set(c) <= need | opt: raise ValueError(f"keys are {sorted(need)} (+ optional {sorted(opt)}; got {sorted(c)})")
    if c["reward"] not in REWARDS: raise ValueError(f"reward must be one of {REWARDS}")
    if not isinstance(c["seed"], int): raise ValueError("seed must be an integer")
    if not (isinstance(c["ridge"], (int, float)) and c["ridge"] > 0): raise ValueError("ridge must be > 0")
    if not (isinstance(c["explore"], (int, float)) and c["explore"] >= 0): raise ValueError("explore must be >= 0")
    if not c["stops_pts"] or not all(isinstance(s, (int, float)) and s > 0 for s in c["stops_pts"]): raise ValueError("stops_pts: positive numbers")
    if BASE_STOP not in c["stops_pts"]: raise ValueError(f"stops_pts must include {BASE_STOP} (the base book's stop)")
    if not c["lots"] or not all(isinstance(k, int) and k >= 1 for k in c["lots"]): raise ValueError("lots: whole numbers >= 1")
    if not isinstance(c["profiles"], dict) or not c["profiles"]: raise ValueError("profiles: at least one exit profile (the first is the base)")
    for name, p in c["profiles"].items():
        if set(p) != {"scale_out", "trail", "square_off"}: raise ValueError(f"profile {name!r}: keys are scale_out, trail, square_off")
        if any(so.get("lots") != 1 or "target_r" not in so for so in p["scale_out"]):
            raise ValueError(f"profile {name!r}: each scale_out tranche is {{\"lots\": 1, \"target_r\": R}} (v1 sizes by whole lots)")
        if len(p["scale_out"]) >= max(c["lots"]):
            raise ValueError(f"profile {name!r}: {len(p['scale_out'])} targets need more than {max(c['lots'])} lots (one lot must trail)")
        lab.position_of({"position": dict(lots=max(c["lots"]), exit="position", stop={"futures_pts": BASE_STOP, "option_pct": 5},
                                          scale_out=p["scale_out"], trail=p["trail"], square_off=p["square_off"])})
    ss = c.get("spread_seeds", [])
    if not (isinstance(ss, list) and all(isinstance(s, int) for s in ss) and c["seed"] not in ss and len(set(ss)) == len(ss)):
        raise ValueError("spread_seeds: a list of distinct integer seeds other than seed")
    if not (isinstance(c.get("control_draws", CONTROL_DRAWS), int) and c.get("control_draws", CONTROL_DRAWS) >= 1):
        raise ValueError("control_draws: a whole number >= 1")
    return c


def spread_seeds_of(cfg):
    return list(cfg.get("spread_seeds") or [cfg["seed"] + 1000 * k for k in range(1, SPREAD_SEEDS + 1)])


def draws_of(cfg):
    return int(cfg.get("control_draws") or CONTROL_DRAWS)


def arms_of(cfg):
    """[('skip',)] + [(profile name, stop pts, lots)] in a fixed order (profiles in file order)."""
    return [("skip",)] + [(p, s, k) for p in cfg["profiles"] for s in cfg["stops_pts"] for k in cfg["lots"]]


def arm_label(a):
    return "skip" if a[0] == "skip" else f"{a[0]} · stop {a[1]:g} · {a[2]} lot{'s' if a[2] > 1 else ''}"


def base_arm_of(cfg, arms):
    first = list(cfg["profiles"])[0]
    return next(i for i, a in enumerate(arms) if a[0] == first and a[1] == BASE_STOP and a[2] == max(cfg["lots"]))


def feasible_arms(cfg, arms, entry_time):
    """Which actions exist at this SETUP: an intraday profile cannot be entered at or after its square-off time."""
    hm = entry_time[11:16]
    ok = {p: v["square_off"] is None or hm < v["square_off"] for p, v in cfg["profiles"].items()}
    return [a[0] == "skip" or ok[a[0]] for a in arms]


def position_for(cfg, st, profile, stop, lots):
    """A lab position block: the profile's tranches, one lot each, for `lots` lots (fewer lots drop the last targets)."""
    p = cfg["profiles"][profile]
    so = p["scale_out"][:max(0, lots - 1)]
    return dict(lots=lots, lock=lab.position_cfg(st)["lock"], exit="position", stop={"futures_pts": stop, "option_pct": 5},
                scale_out=so, trail=p["trail"], square_off=p["square_off"], reverse=None)


def contract_end(tl, c, expiry, clast):
    """(cap, expiry) for a position on contract `c`: the contract's last candle in the data when it comes before the data's
    end - a roll, where lots still open close as 'expiry' even if the calendar expiry is later (MAR22 ends 2022-03-28 in the
    file, expiry 03-31) - else the data's end with the calendar expiry (a position still open there stays open unless the
    expiry date is reached)."""
    if expiry and c in clast and clast[c] < tl[-1]: return clast[c], min(expiry, clast[c][:10])
    return tl[-1], expiry


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


def static_features(bars, r, x, atr, day_open, chochs_today, e):
    """The features known at the SETUP candle's close that do not depend on the book's own trades; the PATH_FEATURES slots
    (day_r, form3, consec_loss, closed_today) are 0 here and filled by State.fill at decision time."""
    t, o, c = bars["t"], bars["o"], bars["c"]
    k0 = x["entry"]; up = x["dir"] == "up"; sg = 1 if up else -1
    a = atr[k0] or 1e-9
    av = r["av"]
    avH = av(e["hi"]["bar"], k0) if e and e["hi"] else c[k0]
    avL = av(e["lo"]["bar"], k0) if e and e["lo"] else c[k0]
    lo20 = min(bars["l"][max(0, k0 - 19):k0 + 1]); hi20 = max(bars["h"][max(0, k0 - 19):k0 + 1])
    f = [1.0] + [1.0 if hour_bucket(t[k0]) == i else 0.0 for i in range(6)]
    f += [1.0 if up else 0.0, 1.0 if (e and e.get("flip")) else 0.0, min(a / c[k0] * 1000, 5.0),
          max(-5.0, min(5.0, sg * (c[k0] - avH) / a)), max(-5.0, min(5.0, sg * (c[k0] - avL) / a)),
          min((k0 - x["choch"]) / 20, 3.0), max(-3.0, min(3.0, sg * (c[k0] - o[k0]) / a)), min((hi20 - lo20) / a / 5, 5.0),
          min(chochs_today / 10, 3.0), 0.0, 0.0, 0.0, 0.0, max(-5.0, min(5.0, sg * (c[k0] - day_open) / a / 5))]
    return np.array(f, dtype=float)


class State:
    """What a book may know at a SETUP about its own trades: the session's closed results and recent form, as per-lot R
    multiples (net points per lot / stop) whatever the reward version. Closed trades are kept in exit-time order."""

    def __init__(self):
        self.closed, self.ends = [], []           # (exit_time, per-lot R), and the exit times for bisecting

    def add(self, end, plr):
        i = bisect.bisect_right(self.ends, end); self.ends.insert(i, end); self.closed.insert(i, (end, plr))

    def fill(self, f, now):
        """`f` (static features) with the PATH_FEATURES set from the trades closed at or before `now`: the day's closed
        result in R (clipped +-5), form over the last three (+1 / -1 each), losses in a row (/3, at most 6), closed today (/5)."""
        k = bisect.bisect_right(self.ends, now)
        day, today, j = now[:10], [], k - 1
        while j >= 0 and self.closed[j][0][:10] == day: today.append(self.closed[j][1]); j -= 1
        today.reverse()
        recent = [n for (_, n) in self.closed[max(0, k - 3):k]]
        consec, j = 0, k - 1
        while j >= 0 and self.closed[j][1] < 0: consec += 1; j -= 1
        g = f.copy()
        g[16] = max(-5.0, min(5.0, sum(today))); g[17] = float(sum(1 if n > 0 else -1 for n in recent))
        g[18] = min(consec, 6) / 3; g[19] = min(len(today), 10) / 5
        return g


# ---------------------------------------------------------------- the policy
class LinTS:
    """Bayesian linear regression per arm (ridge prior), Thompson sampling for the decision. Arm 0 (skip) is a fixed 0."""

    def __init__(self, n_arms, d, ridge, explore, seed):
        self.A = [np.eye(d) * ridge for _ in range(n_arms)]
        self.b = [np.zeros(d) for _ in range(n_arms)]
        self.explore, self.rng, self.n = explore, np.random.RandomState(seed), [0] * n_arms

    def means(self, x):
        return np.array([0.0] + [float(x @ np.linalg.solve(self.A[a], self.b[a])) for a in range(1, len(self.A))])

    def choose(self, x, feasible=None):
        """The arm with the highest sampled value among the feasible ones (skip, value 0, is always feasible). One Gaussian
        draw per arm on every call, feasible or not, so the random sequence does not depend on the mask."""
        vals = [0.0]
        for a in range(1, len(self.A)):
            Ainv = np.linalg.inv(self.A[a])
            mu = Ainv @ self.b[a]
            theta = mu + self.explore * np.linalg.cholesky(Ainv + 1e-12 * np.eye(len(mu))) @ self.rng.standard_normal(len(mu))
            v = float(x @ theta)
            vals.append(v if feasible is None or feasible[a] else float("-inf"))
        return int(np.argmax(vals)), vals

    def update(self, a, x, reward):
        self.A[a] += np.outer(x, x); self.b[a] += reward * x; self.n[a] += 1

    def weights(self):
        return [np.linalg.solve(self.A[a], self.b[a]).round(4).tolist() for a in range(len(self.A))]


def per_lot_r(st, stop, lots, tranches):
    """Net points per lot divided by the stop distance: the position's R multiple per lot."""
    return sum(tr["net"] for tr in tranches) / (st["lot_size"] * stop * lots)


def per_lot_value(cfg, st, stop, lots, tranches):
    """The unclipped per-lot value an outcome is rewarded on: R for reward `r`, else net per lot in 50-point-risk units."""
    net = sum(tr["net"] for tr in tranches)
    return net / (st["lot_size"] * stop * lots) if cfg["reward"] == "r" else net / (st["lot_size"] * BASE_STOP * lots)


def reward_of(cfg, st, stop, lots, tranches):
    """The reward of one action's outcome (its tranches, priced): a per-lot value clipped to +-CLIP, times the lots."""
    per_lot = max(-CLIP, min(CLIP, per_lot_value(cfg, st, stop, lots, tranches)))
    if cfg["reward"] == "pf" and per_lot < 0: per_lot *= 1.5
    return per_lot * lots


# ---------------------------------------------------------------- outcomes of every action for one SETUP
def outcomes(cfg, st, cs, rec, bars, cap, expiry, profiles=None):
    """{(profile, stop): [priced max-lots tranches]} for one SETUP, computed once per profile x stop; lots are read off them."""
    t, o, h, l, c = bars["t"], bars["o"], bars["h"], bars["l"], bars["c"]
    out = {}
    kmax = max(cfg["lots"])
    for p in (profiles if profiles is not None else cfg["profiles"]):
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


# ---------------------------------------------------------------- the SETUP table: every action's outcome, seed-free
def setups(st, cs, bars, cfg, p_engine, r=None):
    """Every SETUP of `bars` in time order with the outcome of every action - nothing here depends on a seed or a book.
    Yields rows dict(n, i, time, dir, contract, expiry, f, feasible, per_arm, full, oracle, clipped) where
      per_arm[a] = (reward, net, end, still_open, learnable, per-lot R, meta), meta = ((exit_time, entry_px, lots, position,
      net), ...) per tranche - what a window cut needs; skip and infeasible arms are (0, 0, SETUP time, False, False, 0, ())
      full[a]    = the priced tranches (the caller drops them once used)
      oracle     = the arm with the best net (skip = 0 among them), clipped = the arms whose per-lot value the clip cut."""
    r = engine.run(bars, p_engine) if r is None else r
    t, c = bars["t"], bars["c"]
    atr = atr_arr(bars, st["atr_period"] or 14)
    contracts, clast = lab.fut_contracts()
    arms = arms_of(cfg)
    chs_by_i = {e["i"]: e for e in r["chs"]}
    ch_days = {}
    for e in r["chs"]: ch_days.setdefault(t[e["i"]][:10], []).append(e["i"])
    day_open, cur_day = None, None
    for n, x in enumerate(sorted(r["trades"], key=lambda z: z["entry"])):
        k0 = x["entry"]; te = t[k0]; day = te[:10]
        if day != cur_day:
            cur_day, day_open = day, bars["o"][bisect.bisect_left(t, f"{day} 00:00:00")]
        chochs_today = sum(1 for i in ch_days.get(day, []) if i <= k0)
        f = static_features(bars, r, x, atr, day_open, chochs_today, chs_by_i.get(x["choch"]))
        bull = x["dir"] == "up"
        c_, e_ = contracts.get(te, ("NIFTY FUT", None))
        cap, e_end = contract_end(t, c_, e_, clast)
        rec = dict(dir=x["dir"], signal="BULLISH" if bull else "BEARISH", position="LONG" if bull else "SHORT", opt_type="FUT",
                   kind="FUT", instrument=c_, strike=None, expiry=e_, choch_time=t[x["choch"]], entry_time=te, exit_time=te,
                   exit_reason="open", open=True, sl=None, entry_px=c[k0], exit_px=None, und_entry=None, und_exit=None)
        feasible = feasible_arms(cfg, arms, te)
        profiles = [p for p in cfg["profiles"] if any(feasible[i] for i, a in enumerate(arms) if a[0] == p)]
        outs = outcomes(cfg, st, cs, rec, bars, cap, e_end, profiles)
        per_arm, full, clipped = [], [], []
        none = (0.0, 0.0, te, False, False, 0.0, ())
        for ai, a in enumerate(arms):
            trs = tranches_for(cfg, st, cs, outs[(a[0], a[1])], a[0], a[2]) if a[0] != "skip" and feasible[ai] else []
            if not trs:
                per_arm.append(none); full.append([]); continue
            if abs(per_lot_value(cfg, st, a[1], a[2], trs)) > CLIP: clipped.append(ai)
            per_arm.append((reward_of(cfg, st, a[1], a[2], trs), sum(tr["net"] for tr in trs), max(tr["exit_time"] for tr in trs),
                            any(tr["open"] for tr in trs), learnable(trs, t), per_lot_r(st, a[1], a[2], trs),
                            tuple((tr["exit_time"], tr["entry_px"], tr["lots"], tr["position"], tr["net"]) for tr in trs)))
            full.append(trs)
        best = max((i for i in range(len(arms)) if feasible[i]), key=lambda i: per_arm[i][1])   # best NET in hindsight, skip = 0
        yield dict(n=n, i=k0, time=te, dir=x["dir"], contract=c_, expiry=e_, f=f, feasible=feasible, per_arm=per_arm, full=full,
                   oracle=best, clipped=tuple(clipped))


# ---------------------------------------------------------------- books
def walk(rows, cfg, st, arms, decide, learn=False, seed=None, on_row=None):
    """Run one book over the SETUP rows in time order: one position per contract (the lab's strike lock), an action per
    free SETUP from decide(row, feats, policy), and - when the book learns - every learnable outcome queued to its policy
    and applied in exit-time order, never before its exit candle. Returns (decisions: arm index per row, -1 = locked;
    policy or None)."""
    policy = LinTS(len(arms), len(FEATURES), cfg["ridge"], cfg["explore"], seed) if learn else None
    state, lock, queue, seq, out = State(), lab.StrikeLock(st), [], 0, []
    for row in rows:
        now = row["time"]
        if learn:
            while queue and queue[0][0] <= now:
                _, _, a, x, rw = heapq.heappop(queue); policy.update(a, x, rw)
        feats = state.fill(row["f"], now)
        if learn:
            for ai, pa in enumerate(row["per_arm"]):
                if pa[4]: seq += 1; heapq.heappush(queue, (pa[2], seq, ai, feats, pa[0]))
        held = lock.held(row["contract"], now)
        ai = -1 if held else decide(row, feats, policy)
        if on_row: on_row(row, feats, policy, ai, held)
        out.append(ai)
        if ai > 0:
            pa = row["per_arm"][ai]
            lock.hold(row["contract"], pa[2], pa[3])
            if pa[4]: state.add(pa[2], pa[5])
    if learn:
        while queue:
            _, _, a, x, rw = heapq.heappop(queue); policy.update(a, x, rw)
    return out, policy


def learner_decide(row, feats, policy):
    return policy.choose(feats, row["feasible"])[0]


def random_walk(T, cfg, st, arms, d):
    """Random book d: a uniformly random action per SETUP (skip included) drawn for every SETUP from seed + 1 + d, so the
    sequence is fixed by the seed whatever the lock does; an action not available at a SETUP is a skip."""
    rng = np.random.RandomState(cfg["seed"] + 1 + d)
    pick = rng.randint(len(arms), size=len(T)) if T else []
    return walk(T, cfg, st, arms, lambda row, f, p: int(pick[row["n"]]) if row["feasible"][pick[row["n"]]] else 0)[0]


def simulate(st, cs, bars, cfg, p_engine, extras=True):
    """The learning run over `bars` (no window): the SETUP table, the learner's decisions, trades and journal, the base
    book, the random books and the seed-spread runs (extras=False: one random book, no extra seeds - for tests)."""
    r = engine.run(bars, p_engine)
    arms = arms_of(cfg); base_arm = base_arm_of(cfg, arms)
    T, trades, view = [], [], []

    def on_row(row, feats, policy, ai, held):
        means = policy.means(feats)
        if ai > 0:
            for tr in row["full"][ai]: trades.append(dict(tr, arm=arm_label(arms[ai]), pred=round(float(means[ai]), 3)))
        view.append((feats, means, held)); row.pop("full"); T.append(row)

    dec, policy = walk(setups(st, cs, bars, cfg, p_engine, r), cfg, st, arms, learner_decide, learn=True, seed=cfg["seed"], on_row=on_row)
    base_dec, _ = walk(T, cfg, st, arms, lambda row, f, p: base_arm if row["feasible"][base_arm] else 0)
    draws = [random_walk(T, cfg, st, arms, d) for d in range(draws_of(cfg) if extras else 1)]
    seeds = {s: walk(T, cfg, st, arms, learner_decide, learn=True, seed=s)[0] for s in (spread_seeds_of(cfg) if extras else [])}
    journal, skipped = [], []
    for n, row in enumerate(T):
        feats, means, held = view[n]; ai = dec[n]; pa = row["per_arm"]; bi, ci = base_dec[n], draws[0][n]
        pos = "LONG" if row["dir"] == "up" else "SHORT"
        j = dict(time=row["time"], dir=row["dir"], hour=row["time"][11:16], atr_pct=round(float(feats[9]) / 10, 3), d_hi=round(float(feats[10]), 2),
                 d_lo=round(float(feats[11]), 2), day_r=round(float(feats[16]), 2), form3=int(feats[17]), consec_loss=int(round(feats[18] * 3)),
                 base_net=round(pa[bi][1], 2) if bi > 0 else 0.0, base_taken=bi > 0,
                 oracle_net=round(pa[row["oracle"]][1], 2), oracle_arm=arm_label(arms[row["oracle"]]),
                 control_net=round(pa[ci][1], 2) if ci > 0 else 0.0, control_taken=ci > 0, control_arm="locked" if ci < 0 else arm_label(arms[ci]),
                 feasible=sum(row["feasible"]) - 1, pred_base=round(float(means[base_arm]), 3))
        if ai < 0:
            j.update(decision="locked", pred=None, net=0.0, reward=0.0)
            skipped.append(dict(entry_time=row["time"], position=pos, dir=row["dir"], why=f"strike locked: {row['contract']} open until {held}"))
        elif ai == 0:
            j.update(decision="skip", pred=round(float(means[0]), 3), net=0.0, reward=0.0)
            skipped.append(dict(entry_time=row["time"], position=pos, dir=row["dir"], why="learner skipped"))
        else:
            j.update(decision=arm_label(arms[ai]), pred=round(float(means[ai]), 3), net=round(pa[ai][1], 2), reward=round(pa[ai][0], 3))
        journal.append(j)
    return dict(engine=r, bars=bars, cfg=cfg, trades=trades, skipped=skipped, journal=journal, arms=arms, base_arm=base_arm, policy=policy,
                learned=sum(policy.n[1:]), table=T, dec=dec, base_dec=base_dec, draws=draws, seeds=seeds, view=view)


def learned_run(st, cs):
    """The one learning run of this strategy row over the whole futures file (cached; the last one only)."""
    f = st["data_file"]
    p = dict(break_mode=st["break_mode"], choch_mode=st.get("choch_mode") or st["break_mode"], avwap_weight=st["avwap_weight"], sl_rule=st["sl_rule"])
    key = (st["code"], st["timeframe"], f, os.path.getsize(f), int(os.path.getmtime(f)), st["rl_json"], lab.position_cfg(st)["lock"],
           st["lot_size"], st["slippage_pts"], st["atr_period"], json.dumps(p, sort_keys=True), json.dumps(cs, sort_keys=True, default=str))
    if key not in _SIM:
        _SIM.clear()
        bars, _ = engine.load(f, "2000-01-01", "2099-12-31", 0)
        _SIM[key] = simulate(st, cs, bars, json.loads(st["rl_json"]), p)
    return _SIM[key]


# ---------------------------------------------------------------- a window of the run
def cut_open(tr, bars, i_end, st, cs):
    """A lot still open at the window's last candle i_end: valued there and marked open (what a run ending there would show)."""
    tr = dict(tr, exit_time=bars["t"][i_end], exit_px=bars["c"][i_end], exit_reason="open", open=True)
    lab.excursion(bars["t"], bars["h"], bars["l"], tr, tr["position"] == "LONG")
    return lab.price_trade(st, cs, tr)


def cut_net(st, cs, bars, i_end, meta):
    """The net of an outcome (its tranche meta) valued at the window's last candle: tranches exiting later are re-priced there."""
    t_end = bars["t"][i_end]
    return sum(nt if xt <= t_end else lab.price_trade(st, cs, dict(position=pos, entry_px=ep, exit_px=bars["c"][i_end], lots=lots, kind="FUT"))["net"]
               for xt, ep, lots, pos, nt in meta)


def pct_rank(v, xs):
    """Percentile of v among xs: the share below plus half the ties, in percent."""
    return round(100 * (sum(1 for x in xs if x < v) + 0.5 * sum(1 for x in xs if x == v)) / len(xs), 1) if xs else None


def permutation_test(res, st, cfg, rows_in, d0, net_of, n_perm):
    """Matched controls: the learner's decisions at the window's free SETUPs (skips included), shuffled and replayed over
    the window's SETUPs in time order under the same lock, starting from the learner's lock state at the window's start; an
    action the SETUP cannot take goes to the next free SETUP that can. Returns (net per permutation, actions left unplaced
    per permutation, number of actions)."""
    T, dec = res["table"], res["dec"]
    acts = [dec[n] for n in rows_in if dec[n] >= 0]
    holds = []
    for n in range(rows_in[0] if rows_in else 0):
        if dec[n] > 0:
            pa = T[n]["per_arm"][dec[n]]
            if pa[2] >= d0: holds.append((T[n]["contract"], pa[2], pa[3]))
    nets, left = [], []
    for p in range(n_perm if acts else 0):
        rng = np.random.RandomState(cfg["seed"] + 5000 + p)
        pool = [acts[i] for i in rng.permutation(len(acts))]
        lock = lab.StrikeLock(st)
        for h in holds: lock.hold(*h)
        net = 0.0
        for n in rows_in:
            row = T[n]
            if lock.held(row["contract"], row["time"]): continue
            k = next((k for k, a in enumerate(pool) if row["feasible"][a]), None)
            if k is None: continue
            a = pool.pop(k)
            if a > 0:
                pa = row["per_arm"][a]; lock.hold(row["contract"], pa[2], pa[3]); net += net_of(n, a)
        nets.append(round(net, 2)); left.append(len(pool))
    return nets, left, len(acts)


def _stats(xs):
    return dict(mean=round(float(np.mean(xs)), 2) if xs else None, sd=round(float(np.std(xs, ddof=1)), 2) if len(xs) > 1 else None,
                min=min(xs) if xs else None, max=max(xs) if xs else None)


def window_payload(res, st, cs, cfg, date_from, date_to):
    """Lab-shaped result (trades, skipped, signals, charts, rl) for the window date_from .. date_to of a learning run; every
    book is valued at the window's last candle. None when the window has no candles."""
    bars, r, t, T = res["bars"], res["engine"], res["bars"]["t"], res["table"]
    arms, dec, view = res["arms"], res["dec"], res["view"]
    d0, d1 = f"{date_from} 00:00:00", f"{date_to} 23:59:59"
    s0 = bisect.bisect_left(t, d0); i_end = bisect.bisect_right(t, d1) - 1
    if s0 > i_end: return None
    t_end = t[i_end]
    net_of = lambda n, ai: round(cut_net(st, cs, bars, i_end, T[n]["per_arm"][ai][6]), 2) if ai > 0 else 0.0
    rows_in = [n for n, row in enumerate(T) if d0 <= row["time"] <= t_end]
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
    # journal rows up to the window's end, every book cut there (a SETUP whose lots were cut carries the cut value)
    J = []
    for n, j in enumerate(res["journal"]):
        if j["time"] > t_end: break
        J.append(dict(j, scored=d0 <= j["time"], net=net_of(n, dec[n]), base_net=net_of(n, res["base_dec"][n]), control_net=net_of(n, res["draws"][0][n])))
    sc = [j for j in J if j["scored"]]; W = [j for j in J if not j["scored"]]
    taken = [j for j in sc if j["decision"] not in ("skip", "locked")]
    rl_net = round(sum(j["net"] for j in sc), 2)
    months, order = {}, []
    for j in J:
        key = (j["time"][:7], j["scored"])
        if key not in months:
            months[key] = dict(month=key[0], scored=key[1], setups=0, taken=0, locked=0, rl_net=0.0, base_net=0.0, oracle_net=0.0, control_net=0.0)
            order.append(key)
        m = months[key]
        m["setups"] += 1; m["taken"] += j["decision"] not in ("skip", "locked"); m["locked"] += j["decision"] == "locked"
        m["rl_net"] += j["net"]; m["base_net"] += j["base_net"]; m["oracle_net"] += j["oracle_net"]; m["control_net"] += j["control_net"]
    mix = {}
    for j in taken: mix[j["decision"]] = mix.get(j["decision"], 0) + 1
    # the seed spread: the same learner from empty on other seeds, this window's net of each
    runs = [dict(seed=s, net=round(sum(net_of(n, sd[n]) for n in rows_in), 2), taken=sum(1 for n in rows_in if sd[n] > 0),
                 skipped=sum(1 for n in rows_in if sd[n] == 0), locked=sum(1 for n in rows_in if sd[n] < 0))
            for s, sd in [(cfg["seed"], dec)] + list(res["seeds"].items())]
    sn = [x["net"] for x in runs]
    spread = dict(runs=runs, positive=sum(1 for v in sn if v > 0), **_stats(sn))
    # the random books and the learner's percentile among them
    dn = [round(sum(net_of(n, dd[n]) for n in rows_in), 2) for dd in res["draws"]]
    random_ = dict(draws=len(dn), learner_pct=pct_rank(rl_net, dn), below=sum(1 for v in dn if v < rl_net), draw0=dn[0],
                   p5=round(float(np.percentile(dn, 5)), 2), p95=round(float(np.percentile(dn, 95)), 2),
                   take_rate=round(float(np.mean([sum(1 for n in rows_in if dd[n] > 0) / len(rows_in) for dd in res["draws"]])), 3) if rows_in else None,
                   **_stats(dn))
    # the matched permutations
    pn, left, n_acts = permutation_test(res, st, cfg, rows_in, d0, net_of, draws_of(cfg))
    perm = dict(n=len(pn), actions=n_acts, learner_pct=pct_rank(rl_net, pn), p_ge=round(sum(1 for v in pn if v >= rl_net) / len(pn), 3) if pn else None,
                unplaced_mean=round(float(np.mean(left)), 2) if left else None, **_stats(pn))
    # what the learner predicted against what happened (learnable outcomes only)
    tp = [(float(view[n][1][dec[n]]), T[n]["per_arm"][dec[n]][0]) for n in rows_in if dec[n] > 0 and T[n]["per_arm"][dec[n]][4]]
    ap = [(float(view[n][1][a]), pa[0]) for n in rows_in for a, pa in enumerate(T[n]["per_arm"]) if a > 0 and pa[4] and T[n]["feasible"][a]]

    def corr(ps):
        if len(ps) < 3: return None
        x, y = np.array([p for p, _ in ps]), np.array([q for _, q in ps])
        return round(float(np.corrcoef(x, y)[0, 1]), 3) if x.std() > 0 and y.std() > 0 else None

    pred = dict(taken_n=len(tp), taken_corr=corr(tp), taken_gap=round(float(np.mean([p - q for p, q in tp])), 3) if tp else None,
                all_n=len(ap), all_corr=corr(ap))
    fsd = np.std([view[n][0] for n in rows_in], axis=0).round(3).tolist() if rows_in else [0.0] * len(FEATURES)
    clip_by = {}
    for n in rows_in:
        for a in T[n]["clipped"]: clip_by[arm_label(arms[a])] = clip_by.get(arm_label(arms[a]), 0) + 1
    outcomes_n = sum(sum(1 for a in range(1, len(arms)) if T[n]["feasible"][a]) for n in rows_in)
    xs = [net_of(n, dec[n]) for n in rows_in if dec[n] > 0]
    tstat = round(float(np.mean(xs) / (np.std(xs, ddof=1) / np.sqrt(len(xs)))), 2) if len(xs) > 1 and np.std(xs, ddof=1) > 0 else None
    Wt = res["policy"].weights()
    payload = dict(reward=cfg["reward"], seed=cfg["seed"], arms=[arm_label(a) for a in arms], features=list(FEATURES), feature_sd=fsd,
                   learned_updates=res["learned"], learn_from=t[0][:10], scored_from=date_from, scored_to=date_to,
                   summary=dict(setups=len(sc), taken=len(taken), skipped=sum(1 for j in sc if j["decision"] == "skip"),
                                locked=sum(1 for j in sc if j["decision"] == "locked"),
                                rl_net=rl_net, rl_t=tstat, base_net=round(sum(j["base_net"] for j in sc), 2),
                                oracle_net=round(sum(j["oracle_net"] for j in sc), 2), control_net=round(sum(j["control_net"] for j in sc), 2),
                                base_taken=sum(1 for j in sc if j["base_taken"]), control_taken=sum(1 for j in sc if j["control_taken"]),
                                warmup_setups=len(W), warmup_rl_net=round(sum(j["net"] for j in W), 2),
                                warmup_base_net=round(sum(j["base_net"] for j in W), 2), warmup_control_net=round(sum(j["control_net"] for j in W), 2),
                                clipped=sum(clip_by.values()), outcomes=outcomes_n),
                   action_mix=sorted(mix.items(), key=lambda kv: -kv[1]),
                   months=[dict(months[k], **{f: round(months[k][f], 2) for f in ("rl_net", "base_net", "oracle_net", "control_net")}) for k in order],
                   notes=cfg.get("notes"),
                   weights={arm_label(a): Wt[i] for i, a in enumerate(arms) if i > 0 and res["policy"].n[i]},
                   journal=J, base_arm=f"{arm_label(arms[res['base_arm']])} (Strategy 9's rule), run as its own book",
                   seeds=spread, random=random_, permutation=perm, prediction=pred,
                   clipped_by_arm=sorted(clip_by.items(), key=lambda kv: -kv[1]),
                   books="every book (learner, base, random) holds one position per contract (the lab's strike lock); an intraday profile "
                         "is not available at or after its square-off time; every book is valued at the window's last candle for positions "
                         "still open there; a month straddling the window's start is two rows (learning, scored); the oracle is the best net "
                         "per SETUP in hindsight, never below 0, and ignores the lock")
    return dict(trades=trades, skipped=skipped, signals=signals, charts=charts, rl=payload)


def run_variant(st, cs):
    """Lab-shaped result for an RL futures row: {'-': dict(trades, skipped, signals, charts, rl)} for the window
    st['date_from'] .. st['date_to'], cut from the strategy's one learning run."""
    if st["variant"] != "FUT" or (st.get("underlying") or "FUT") != "FUT":
        return {"-": dict(trades=[], skipped=[dict(why=FUT_WHY)], signals=[], charts=[])}
    cfg = json.loads(st["rl_json"])
    out = window_payload(learned_run(st, cs), st, cs, cfg, st["date_from"], st["date_to"])
    return {"-": out or dict(trades=[], skipped=[dict(why="no candles in the window")], signals=[], charts=[])}
