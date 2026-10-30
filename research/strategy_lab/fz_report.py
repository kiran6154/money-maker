"""FZ reporting: what the gate did with Foundation's SETUPs, what that did to net, and whether it beats chance.

Pure functions (no files, no lab, no engine) over what lab.py hands in after the gate has run:
  ledger    fz.run()'s SETUP rows (i >= s0): one per Foundation SETUP with its card columns and gate
  watches   fz.run()'s watch log (opened in the window); counters = its stats; card = its per-bar card for the window
  units     priced positions, one per futures position with its option / futures legs summed (see units())
Nothing here feeds a gate decision. The Foundation outcome of a SETUP that FZ did not take is used only by the bridge,
the random control and the permutation test (evaluation M40 / M43), after fz.run() has finished.

Why a control at all: Foundation loses about as much per trade as it pays in charges and slippage, so any gate that
drops trades raises net whichever trades it drops. The bridge splits FZ-minus-Foundation into the avoided price move,
the avoided costs and the REENTER exit change; the session-matched random control asks whether FZ's net beats keeping
the same number of Foundation positions per session at random; the permutation p asks whether the Foundation trades FZ
kept differ from the ones it refused by more than a random split of the same trades would.
"""
import datetime, math, random, statistics
from collections import Counter
import fz

# sample-size conventions for every FZ table (evaluation M45). Reporting only: no trade depends on them.
PF_T_MIN, PF_T_OK = 10, 30          # n < 10: ledger only, no PF / t; 10 <= n < 30: 'indicative', printed with the CI
WEEKS_MIN, SESSIONS_MIN = 4, 10      # fewer weeks with a trade: no week stats; fewer active sessions: no Sharpe / Calmar
CI = 0.95                            # two-sided confidence of the t-based half-width on expectancy
GATES = ("TAKE", "REENTER", "WATCH", "BLOCK")


# ---------------------------------------------------------------- small helpers
def key(x):
    """JSON-safe table key: None -> 'none', booleans -> 'true' / 'false'."""
    return "none" if x is None else ("true" if x else "false") if isinstance(x, bool) else str(x)


def tally(xs):
    """{value: count}, most frequent first."""
    return dict(sorted(Counter(key(x) for x in xs).items(), key=lambda kv: (-kv[1], kv[0])))


def cross(rows, fa, fb, first=GATES):
    """{fa(row): {fb(row): count}}, the fa values in `first` order before any others."""
    out = {}
    for r in rows:
        a, b = key(fa(r)), key(fb(r))
        out.setdefault(a, {}); out[a][b] = out[a].get(b, 0) + 1
    return {k: out[k] for k in [x for x in first if x in out] + sorted(x for x in out if x not in first)}


def median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def rnd(x, k=2):
    return None if x is None else round(x, k)


def iso_week(day):
    y, w, _ = datetime.date.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


# ---------------------------------------------------------------- Student t quantile (stdlib only)
def _betacf(a, b, x):
    """Continued fraction of the regularised incomplete beta (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam, c, d = a + b, a + 1.0, a - 1.0, 1.0, 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (d if abs(d) > tiny else tiny); h = d
    for m in range(1, 300):
        m2 = 2 * m
        for aa in (m * (b - m) * x / ((qam + m2) * (a + m2)), -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))):
            d = 1.0 + aa * d; d = 1.0 / (d if abs(d) > tiny else tiny)
            c = 1.0 + aa / c; c = c if abs(c) > tiny else tiny
            h *= d * c
        if abs(d * c - 1.0) < 1e-14: break
    return h


def _ibeta(a, b, x):
    if x <= 0: return 0.0
    if x >= 1: return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1 - x))
    return front * _betacf(a, b, x) / a if x < (a + 1) / (a + b + 2) else 1.0 - front * _betacf(b, a, 1 - x) / b


def t_crit(df, conf=CI):
    """Two-sided critical value of Student's t with df degrees of freedom (bisection on the CDF)."""
    q = 1 - (1 - conf) / 2
    cdf = lambda t: 1 - 0.5 * _ibeta(df / 2.0, 0.5, df / (df + t * t))
    lo, hi = 0.0, 1e3
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) < q else (lo, mid)
    return (lo + hi) / 2


# ---------------------------------------------------------------- positions
def units(legs, lot, slippage_pts):
    """One record per position from lab's priced legs, which carry _entry (entry bar), _setup (the SETUP bar the position
    belongs to) and _gate (TAKE / REENTER / RAW). net and gross (after slippage, as lab's stats) and charges are summed
    over the legs; slip is the slippage paid (2 x slippage_pts x lot per leg), so gross + slip is the price move."""
    by = {}
    for x in legs:
        u = by.get(x["_entry"])
        if u is None:
            u = by[x["_entry"]] = dict(entry=x["_entry"], setup=x["_setup"], gate=x["_gate"], day=x["entry_time"][:10],
                                       exit_day=x["exit_time"][:10], legs=0, net=0.0, gross=0.0, charges=0.0, slip=0.0,
                                       open=False)
        u["legs"] += 1; u["net"] += x["net"]; u["gross"] += x["gross"]; u["charges"] += x["chg"]["total"]
        u["slip"] += 2 * slippage_pts * lot; u["open"] = u["open"] or bool(x["open"])
        u["exit_day"] = max(u["exit_day"], x["exit_time"][:10])
    return [by[k] for k in sorted(by)]


def book(us, lot):
    """Headline numbers of a set of positions with the honesty M45 asks for: per-trade and per-session t (sessions by entry
    day, over sessions with a position), weeks by exit day, net with and without positions still open at the data end,
    and the t-based CI half-width on expectancy in INR and in points (INR / lot)."""
    net = [u["net"] for u in us]; n = len(net)
    m = sum(net) / n if n else 0.0
    sd = statistics.stdev(net) if n > 1 else 0.0
    ses = {}
    for u in us: ses[u["day"]] = ses.get(u["day"], 0.0) + u["net"]
    sv = list(ses.values()); ssd = statistics.stdev(sv) if len(sv) > 1 else 0.0
    wins, loss = [v for v in net if v > 0], [v for v in net if v <= 0]
    ci = t_crit(n - 1) * sd / math.sqrt(n) if n > 1 else None
    return dict(n=n, net=round(sum(net), 2), mean=round(m, 2), sd=round(sd, 2), wins=len(wins),
                pf=round(sum(wins) / -sum(loss), 2) if loss and sum(loss) else None,
                t_trade=round(m / (sd / math.sqrt(n)), 2) if sd else None,
                t_session=round(statistics.mean(sv) / (ssd / math.sqrt(len(sv))), 2) if ssd else None,
                sessions=len(ses), weeks=len({iso_week(u["exit_day"]) for u in us}),
                open=sum(1 for u in us if u["open"]), net_ex_open=round(sum(u["net"] for u in us if not u["open"]), 2),
                ci_inr=rnd(ci), ci_pts=rnd(ci / lot) if ci is not None else None)


def sample_flags(n, sd, weeks_with_trades, active_sessions, lot):
    """Which headline numbers a table may print for a book of n positions (M45): PF / t not reported below PF_T_MIN,
    'indicative' with the CI below PF_T_OK; week stats need WEEKS_MIN weeks with a trade; Sharpe / Calmar need
    SESSIONS_MIN active sessions (sessions with at least one Foundation SETUP)."""
    ci = t_crit(n - 1) * sd / math.sqrt(n) if n > 1 else None
    return dict(n=n, pf_t="not reported" if n < PF_T_MIN else "indicative" if n < PF_T_OK else "ok",
                ci_inr=rnd(ci), ci_pts=rnd(ci / lot) if ci is not None else None,
                weeks="suppressed" if weeks_with_trades < WEEKS_MIN else "ok",
                sharpe="suppressed" if active_sessions < SESSIONS_MIN else "ok",
                rule=f"n < {PF_T_MIN}: ledger only, no PF / t; {PF_T_MIN} <= n < {PF_T_OK}: indicative, with the "
                     f"{int(CI * 100)}% CI on expectancy; weeks < {WEEKS_MIN}: no week stats; active sessions < "
                     f"{SESSIONS_MIN}: no Sharpe / Calmar")


# ---------------------------------------------------------------- Foundation -> FZ
def bridge(raw, fzu):
    """Foundation net to FZ net in four lines (M43), over positions priced the same way (same choice, same costs):
        Foundation net
      + avoided price move of the Foundation positions FZ holds no counterpart of (minus their gross before slippage)
      + avoided charges and slippage of those positions
      + REENTER exit delta: a REENTER on a SETUP Foundation traded replaces that trade (its net minus Foundation's);
        a REENTER with no Foundation trade of its own (engine-skipped SETUP, or one already counted) adds its whole net
      = FZ net (asserted).
    A TAKE is Foundation's own position (same entry, same exit): it is kept, not bridged. Cost savings are reported,
    never counted as edge: they are what any gate that drops trades collects."""
    rby = {u["entry"]: u for u in raw}
    used = {u["entry"] for u in fzu if u["gate"] == "TAKE" and u["entry"] in rby}
    delta = new = 0.0; n_delta = n_new = 0
    for u in fzu:
        if u["gate"] != "REENTER": continue
        b = rby.get(u["setup"]) if u["setup"] not in used else None
        if b is not None: used.add(u["setup"]); delta += u["net"] - b["net"]; n_delta += 1
        else: new += u["net"]; n_new += 1
    avoided = [u for u in raw if u["entry"] not in used]
    price, cost = -sum(u["gross"] + u["slip"] for u in avoided), sum(u["charges"] + u["slip"] for u in avoided)
    raw_net, fz_net = sum(u["net"] for u in raw), sum(u["net"] for u in fzu)
    total = raw_net + price + cost + delta + new
    assert abs(total - fz_net) < 0.01 + 1e-9 * abs(raw_net), f"FZ bridge does not close: {total} vs {fz_net}"
    lines = [dict(key="raw_net", label="Foundation net", n=len(raw), value=round(raw_net, 2)),
             dict(key="avoided_price", label="avoided price move of Foundation positions FZ did not hold", n=len(avoided),
                  value=round(price, 2)),
             dict(key="avoided_cost", label="avoided charges + slippage of those positions", n=len(avoided),
                  value=round(cost, 2)),
             dict(key="reenter_delta", label="REENTER vs Foundation's exit of the same SETUP", n=n_delta, value=round(delta, 2)),
             dict(key="reenter_new", label="REENTER with no Foundation position of its own", n=n_new, value=round(new, 2)),
             dict(key="fz_net", label="FZ net", n=len(fzu), value=round(fz_net, 2))]
    return dict(lines=lines, kept=len(used) - n_delta, replaced=n_delta, avoided=len(avoided),
                selection=round(price + delta + new, 2), costs=round(cost, 2))


def random_control(raw, fzu, draws, seed, tag):
    """Session-matched random gate: every draw keeps, in each session, as many Foundation positions (drawn without
    replacement) as FZ held that session, and sums their net. Returns the 5 / 50 / 95 percentiles of the draws, FZ's
    percentile among them (ties count half) and p_beat = P(draw >= FZ net) with the +1 correction. Draw d is seeded
    with random.Random(f"{seed}|{tag}|{k}|{d}"), k = FZ's position count, so every number reproduces. A session where FZ
    held more positions than Foundation had (a REENTER on an engine-skipped SETUP) is capped and counted."""
    pool = {}
    for u in raw: pool.setdefault(u["day"], []).append(u["net"])
    want = Counter(u["day"] for u in fzu)
    plan = [(want[d], pool.get(d, [])) for d in sorted(want)]
    k = sum(want.values()); capped = sum(max(0, kk - len(p)) for kk, p in plan)
    nets = []
    for d in range(draws):
        rng = random.Random(f"{seed}|{tag}|{k}|{d}")
        nets.append(sum(sum(rng.sample(p, min(kk, len(p)))) for kk, p in plan))
    fz_net = sum(u["net"] for u in fzu)
    s = sorted(nets)
    q = lambda p: round(s[min(len(s) - 1, int(round(p * (len(s) - 1))))], 2)
    below, same = sum(1 for v in nets if v < fz_net - 1e-9), sum(1 for v in nets if abs(v - fz_net) <= 1e-9)
    return dict(scheme="session-matched: per session, as many Foundation positions drawn at random as FZ held",
                seed=f"{seed}|{tag}|{k}|<draw>", draws=draws, k=k, capped=capped, p5=q(0.05), p50=q(0.5), p95=q(0.95),
                fz_net=round(fz_net, 2), fz_pct=round(100.0 * (below + 0.5 * same) / draws, 1),
                p_beat=round((1 + sum(1 for v in nets if v >= fz_net - 1e-9)) / (draws + 1), 4))


def permutation_p(kept, blocked, draws, seed, tag):
    """Kept vs refused Foundation trades: the difference of their mean net and a two-sided permutation p (labels shuffled
    `draws` times with random.Random(f"{seed}|{tag}|perm"), +1 corrected). kept = Foundation's trades on the SETUPs FZ held
    a position on (a TAKE, or a REENTER on that SETUP, on its own bar or later), blocked = Foundation's other trades: the
    split is by what FZ traded, not by the gate as of the SETUP bar."""
    out = dict(kept_n=len(kept), blocked_n=len(blocked), kept_mean=rnd(statistics.mean(kept)) if kept else None,
               blocked_mean=rnd(statistics.mean(blocked)) if blocked else None, diff=None, p=None, draws=draws)
    if not kept or not blocked: return out
    obs = statistics.mean(kept) - statistics.mean(blocked)
    pooled, nk = list(kept) + list(blocked), len(kept)
    rng, hits = random.Random(f"{seed}|{tag}|perm"), 0
    for _ in range(draws):
        rng.shuffle(pooled)
        d = sum(pooled[:nk]) / nk - sum(pooled[nk:]) / (len(pooled) - nk)
        hits += abs(d) >= abs(obs) - 1e-9
    return dict(out, diff=round(obs, 2), p=round((1 + hits) / (1 + draws), 4))


# ---------------------------------------------------------------- the gate itself
def crosstabs(ledger, watches, trades, counters, card, sessions, cfg):
    """What the gate did over one window (evaluation M46 / B23), as JSON-ready tables:
      gate x read (BLOCK split by reason, WATCH rows that fell through a refused LEAVE listed by reason), gate by hour bin
      (the clock edges are the strategy's open_window_until / no_entry_from), by visit_n (1, 2, 3, 4+), by direction and
      by zone kind; watch kinds and outcomes, armed_expired by reason with the median bars armed; the counters decisions
      4 and 8 promised (ACCEPTED on a revisit, ARMED-expired); R4 evaluated / failed / NA; ACCEPTED on time only (volume
      NA); first_vol_na; branch-1 TAKEs split by what lies on the far side, and how many branch-1 TAKEs each
      leave_far_side option admits (static, from entered_read: a real rerun would also move positions and watches);
      REENTER exits and fills; active sessions (>= 1 Foundation SETUP) and the dormant stretches between them.
    ledger / watches / trades / card cover the window only (i >= s0); sessions are the window's session dates.
    The gate tables count each SETUP by how it ended (outcome_gate: a WATCH or BLOCK row whose SETUP a later REENTER used
    counts as REENTER, so REENTER rows match REENTER positions); gates_at_setup keeps the gate as of the SETUP bar, and the
    WATCH-after-a-refused-LEAVE reasons are read at the SETUP bar too."""
    L = ledger
    ow, nf = cfg["open_window_until"], cfg["no_entry_from"]
    def hour(r):
        hm = r["time"][11:16]
        return "<" + ow if hm < ow else ">=" + nf if hm >= nf else hm[:2]
    def vbin(v): return None if v is None else str(v) if v < 4 else "4+"
    gate = lambda r: r.get("outcome_gate") or r["gate"]
    free = lambda r: r["entered_zone_id"] is None
    C = [r for r in L if r["branch"] == "leave" or r["block_reason"] in ("leave_into_recycle", "leave_into_band")]
    b1 = [r for r in L if r["branch"] == "leave"]
    inb = [r for r in b1 if not free(r)]
    W = watches
    exp = [w for w in W if (w["outcome"] or "").startswith("armed_expired:")]
    act = sorted({r["time"][:10] for r in L})
    dormant, run = [], []
    for d in list(sessions) + [None]:
        if d is not None and d not in act: run.append(d); continue
        if run: dormant.append([run[0], run[-1], len(run)]); run = []
    RE = [x for x in trades if x["gate"] == "REENTER"]
    nb = counters.get("bars_shown", len(card)) or 1
    pct = lambda k: round(100.0 * counters.get(k, 0) / nb, 1)
    return dict(
        setups=len(L), gates={g: sum(1 for r in L if gate(r) == g) for g in GATES},
        gates_at_setup={g: sum(1 for r in L if r["gate"] == g) for g in GATES},
        gate_read=cross(L, gate, lambda r: r["read"]),
        block_read=cross([r for r in L if gate(r) == "BLOCK"], lambda r: r["block_reason"], lambda r: r["read"], ()),
        watch_reason=tally(r["block_reason"] for r in L if r["gate"] == "WATCH" and r["block_reason"]),
        branches=cross([r for r in L if r["branch"]], gate, lambda r: r["branch"]),
        take_why=tally(r["take_why"] for r in L if r["take_why"]),
        by_hour=cross(L, hour, gate, ["<" + ow] + [f"{h:02d}" for h in range(9, 16)] + [">=" + nf]),
        by_visit=cross(L, lambda r: vbin(r["visit_n"]), gate, ("1", "2", "3", "4+", "none")),
        by_dir=cross(L, lambda r: r["dir"], gate, ("up", "down")),
        by_zone_kind=cross(L, lambda r: r["zone_kind"], gate, ("A", "B", "none")),
        reads_at_setup=tally(r["read"] for r in L), visit_n_median=median(r["visit_n"] for r in L),
        accepted_revisit=dict(setups=sum(1 for r in L if r["read"] == "ACCEPTED" and (r["visit_n"] or 0) >= 2),
                              bars=sum(1 for c in card if c["read"] == "ACCEPTED" and (c["visit_n"] or 0) >= 2)),
        accepted_time_only=sum(1 for r in L if r["read"] == "ACCEPTED" and (r["vol_na"] or r["first_vol_na"])),
        vol_na=sum(1 for r in L if r["vol_na"]), first_vol_na=sum(1 for r in L if r["first_vol_na"]),
        r4=dict(bars_evaluated=counters.get("r4_bars_evaluated", 0), bars_fail=counters.get("r4_bars_fail", 0),
                bars_na=counters.get("r4_bars_na", 0),
                leave_setups=tally(r["leave_vol_ok"] for r in L if r["read"] == "LEAVE")),
        leave_far_side=dict(seeded=cfg["leave_far_side"], any=len(C),
                            block_list=sum(1 for r in C if free(r) or r["entered_read"] not in fz.BLOCK_READS),
                            no_band=sum(1 for r in C if free(r))),
        branch1=dict(n=len(b1), far_side_no_band=len(b1) - len(inb), far_side_in_band=len(inb),
                     in_band_visit_n=tally(vbin(r["entered_visit_n"]) for r in inb),
                     in_band_visit_n_median=median(r["entered_visit_n"] for r in inb),
                     in_band_entered_read=tally(r["entered_read"] for r in inb)),
        watches=dict(opened=len(W), kinds=tally(w["kind"] for w in W), outcomes=tally(w["outcome"] for w in W),
                     armed=sum(1 for w in W if w["armed_at"] is not None),
                     armed_expired=tally(w["outcome"].split(":", 1)[1] for w in exp),
                     # bars armed before an armed watch expired: from its first R1 (armed_bars) and from its latest
                     # (rearmed_bars: a close back inside breaks the far-side run and the next far close re-arms)
                     armed_bars_median=median(w["outcome_bar"] - w["armed_at"] for w in exp),
                     rearmed_bars_median=median(w["outcome_bar"] - w["last_armed_at"] for w in exp),
                     rearmed=sum(1 for w in W if w["armed_at"] is not None and w["last_armed_at"] != w["armed_at"]),
                     no_same_dir_setup=counters.get("no_same_dir_setup", 0), clock_1520=counters.get("clock_1520", 0),
                     reenter_refused=counters.get("reenter_refused", 0),
                     reenter_in_position=counters.get("reenter_in_position", 0)),
        positions=dict(TAKE=sum(1 for x in trades if x["gate"] == "TAKE"), REENTER=len(RE),
                       reenter_exits=tally(x["exit_reason"] for x in RE), reenter_fill=tally(x["fill_used"] for x in RE),
                       reenter_sl_bar=tally(x.get("sl_bar") for x in RE),
                       reenter_sl_in_band=sum(1 for x in RE if x.get("sl_in_band")),
                       reenter_converted_take=sum(1 for r in L if r["gate"] == "REENTER" and r["branch"] != "watch"),
                       take_refused=counters.get("take_refused", 0)),
        active_sessions=len(act), sessions=len(sessions), dormant=dormant,
        card=dict(bars=nb, inside_pct=pct("bars_inside"), ref_live_pct=pct("bars_ref_live"),
                  reads={r: pct("read_" + r) for r in fz.READS},
                  leave_return_no_visit=counters.get("leave_return_no_visit", 0),
                  zones_since_memory_start=counters.get("zones"),
                  births_in_window=dict(A=counters.get("births_A_shown", 0), B=counters.get("births_B_shown", 0)),
                  since_memory_start=dict(births_A=counters.get("births_A", 0), births_B=counters.get("births_B", 0),
                                          births_B_drift=counters.get("births_B_drift", 0),
                                          merges_A=counters.get("merges_A", 0), merges_B=counters.get("merges_B", 0))))
