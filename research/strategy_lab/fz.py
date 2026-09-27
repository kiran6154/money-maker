"""Foundation-Zone (FZ): band memory, a per-bar zone card, a gate on Foundation SETUPs and a re-entry watch.

Foundation (engine.py) finds structure (swings -> protected level -> CHoCH -> AVWAP pair -> SETUP) but has no memory of
price bands: time for it is "bars since the last CHoCH". FZ adds that memory without touching the engine:
  zones    bands of +-band_half_width born at protected levels (Birth A) and at cluster sits (Birth B); a candidate
           that overlaps an existing band is absorbed into it; nothing is ever deleted and band edges never move
  visits   one live visit at a time (the ref band). A visit ends only on leave_closes consecutive closes outside it on
           the same side; a single outside close, even one inside a neighbouring band, does not end it
  card     per bar, as of that bar and never rewritten: which band, which visit, bars and volume now vs the first (or
           previous) visit, and a read: LEAVE > HUNT > REJECT > FIRST_PRINT / ACCEPTED / THIN / RECYCLE > PENDING > NEW
  gate     at every Foundation SETUP: hard BLOCK (in_position, clock, open_pierce, hunt_fade, new), else TAKE on one of
           three branches (leave, first_print, defend), else WATCH a band, else BLOCK new. A branch-1 (LEAVE) TAKE of the
           band a watch waits on, in the watch's direction, is that watch's REENTER (evaluation M22); a first_print or
           defend TAKE stays Foundation's own position and leaves the watch as it is
  watch    WATCH -> ARMED -> REENTER on R1-R5 (a hold outside the band on closes, volume on the leave, and a Foundation
           SETUP in that direction on this bar or the previous one), with the cancel rules. R3 is read as an unbroken
           far-side run: a close back inside (or on the other side) breaks the run and the next far-side close re-arms the
           watch (R1 again), so the ledger carries armed_bars from the first arming and rearmed_bars from the latest

One live visit at a time wins over a return (the D01 tie-break): a close back inside the band just left ends its LEAVE
and sets the band's leave_failed flag (the card shows it as last_leave_failed while that band is the ref band), but it
re-opens a visit on that band only when no other band holds the live visit; otherwise the neighbour keeps the visit and
the bar is counted as leave_return_no_visit.

The module is pure and causal. It reads candles, a frozen view of engine.run() output (swings, setups, CHoCH levels,
protected level per bar) and the strategy file's `fz` thresholds; it never imports lab or engine and never sees a
trade's outcome. Positions are opened through the `open_position` callback, which answers only with the bar the position
ends on (so a later entry cannot overlap it) or a refusal reason. Every threshold comes from the strategy file: a
missing, unknown or ill-typed key raises; there are no defaults in code.

Conventions: all durations are bars, counted across the session break; clock rules compare the bar's open-time label
("HH:MM") with no_entry_from / open_window_until; band edges are inclusive; a visit inside at a session's last bar
continues at the next session's first bar (its bar count simply goes on). A visit's bars and volume are its inside
closes only: the outside closes of a one-close excursion and of a leave are not part of the sit.
"""
import re

EPS = 1e-6       # float tolerance on inclusive band edges (prices sit on a 0.05 grid; mid +- half width is inexact)
READS = ("FIRST_PRINT", "ACCEPTED", "RECYCLE", "THIN", "HUNT", "REJECT", "LEAVE", "PENDING", "NEW")
BLOCK_READS = ("RECYCLE", "THIN", "HUNT", "REJECT")     # spec s3's BLOCK list, applied to the entered band (block_list)

CHOICES = dict(birth_a_source=("protected_level", "every_swing"), birth_b=("band", "flag"), hunt_form=("close", "wick"),
               leave_far_side=("any", "block_list", "no_band"), fade_scope=("ref_band", "any_band"),
               edge_watch=("ref_band", "containing_band"), volume_base=("first", "previous"), reenter_fill=("confirm_bar",))
BAR_COUNTS = ("cluster_bars", "accept_bars", "first_print_min_bars", "hunt_max_bars", "leave_closes", "leave_ttl_bars",
              "fade_block_bars", "defend_window_bars", "open_bars", "open_quiet_bars", "open_sit_closes",
              "cancel_inside_bars", "control_draws")
NUMBERS = ("band_half_width", "cluster_width", "merge_overlap", "accept_vol_ratio", "thin_ratio", "hunt_burst", "reject_tol")
OPTIONAL = ("zone_max_age_sessions", "hunt_min_depth_atr")        # null allowed
CLOCKS = ("open_window_until", "no_entry_from")
TEXT = ("control_seed",)
KEYS = set(CHOICES) | set(BAR_COUNTS) | set(NUMBERS) | set(OPTIONAL) | set(CLOCKS) | set(TEXT)


def check(cfg):
    """Refuse a threshold set with a missing or unknown key or a value of the wrong kind; returns cfg unchanged."""
    missing, unknown = sorted(KEYS - set(cfg)), sorted(set(cfg) - KEYS)
    if missing or unknown:
        raise ValueError(f"fz thresholds: missing {missing}, unknown {unknown}")
    num = lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)
    for k, allowed in CHOICES.items():
        if cfg[k] not in allowed: raise ValueError(f"fz {k} = {cfg[k]!r}: must be one of {allowed}")
    for k in BAR_COUNTS:
        if not (isinstance(cfg[k], int) and not isinstance(cfg[k], bool) and cfg[k] >= 1):
            raise ValueError(f"fz {k} = {cfg[k]!r}: must be a whole number of bars >= 1")
    for k in NUMBERS:
        if not num(cfg[k]) or cfg[k] < 0: raise ValueError(f"fz {k} = {cfg[k]!r}: must be a number >= 0")
    for k in OPTIONAL:
        if cfg[k] is not None and not num(cfg[k]): raise ValueError(f"fz {k} = {cfg[k]!r}: must be a number or null")
    for k in CLOCKS:
        if not (isinstance(cfg[k], str) and re.fullmatch(r"\d\d:\d\d", cfg[k])): raise ValueError(f"fz {k}: must be 'HH:MM'")
    if not isinstance(cfg["control_seed"], str): raise ValueError("fz control_seed: must be text")
    if cfg["hunt_form"] == "wick" and cfg["hunt_min_depth_atr"] is None:
        raise ValueError("fz hunt_form 'wick' needs hunt_min_depth_atr")
    return cfg


def thresholds(block):
    """{key: value} from a strategy file's fz[<timeframe>] block. Every entry must be an object carrying a value and a
    non-empty source (where the number came from: spec / decision / evaluation id); the key set must be complete."""
    if not isinstance(block, dict): raise ValueError("fz block must be an object of {key: {value, source, statistic}}")
    for k, e in block.items():
        if not isinstance(e, dict) or "value" not in e or not str(e.get("source") or "").strip():
            raise ValueError(f"fz key {k}: needs a value and a source")
    return check({k: e["value"] for k, e in block.items()})


def run(bars, view, cfg, tf_min, s0, open_position):
    """Zone card, zones, SETUP ledger, watches and positions for one candle series.

    bars           t/o/h/l/c/v lists (engine format) plus fm_na (volume not usable on that bar: not the front month, or
                   zero volume) and atr14 (Wilder ATR on these bars), both per bar
    view           frozen engine output: swings [(kind, bar, price, conf)] in confirmation order, setups [(bar, dir,
                   choch_bar)], chs [(bar, dir, level)], prot [protected level or None per bar]
    cfg            thresholds (see check); tf_min is the bar length in minutes (recorded only). zone_max_age_sessions
                   never changes the card: zones are never deleted, an age only hides a zone from the chart view (lab);
                   control_draws / control_seed belong to the report (random-gate control), not to this module
    s0             first shown bar: every bar from 0 is processed (memory starts at the first candle), the ledger and
                   the counters cover bars >= s0
    open_position  callback(kind 'TAKE'|'REENTER', entry_bar, dir, setup_bar, band) -> the bar the position ends on,
                   or None / a short reason when the entry is refused. It is the only way a position opens.

    Returns dict(card, zones, ledger, watches, decisions, reasons, stats)."""
    g = check(cfg)
    t, o, h, l, c, v = (bars[k] for k in "tohlcv")
    na, atr = bars["fm_na"], bars["atr14"]
    n = len(t)
    HW, LC = g["band_half_width"], g["leave_closes"]
    hm = [x[11:16] for x in t]
    sess, sbar, gap = [0] * n, [0] * n, [None] * n            # session number, bar in session, open gap vs prior close
    for i in range(1, n):
        if t[i][:10] != t[i - 1][:10]: sess[i], sbar[i], gap[i] = sess[i - 1] + 1, 0, round(c[i] - c[i - 1], 2)
        else: sess[i], sbar[i], gap[i] = sess[i - 1], sbar[i - 1] + 1, gap[i - 1]
    swings = view["swings"]; prot = view["prot"]
    setup_at = {i: (d, ch) for i, d, ch in view["setups"]}
    level_at = {i: lvl for i, d, lvl in view["chs"]}

    stats = {}
    def inc(k, by=1): stats[k] = stats.get(k, 0) + by

    zones, byid = [], {}
    ref, orun, oside = None, 0, None     # band with the live visit; consecutive closes outside it and their side
    leave = None                         # the LEAVE of the band most recently left, while it lives
    watch, pos = None, None
    card, rows, decisions, reasons, watches = [], {}, [], {}, []
    stash = {}                           # REENTER decided in the watch step on a SETUP bar, for that bar's gate

    # ---------------------------------------------------------------- helpers
    def inside(z, x): return z["lo"] - EPS <= x <= z["hi"] + EPS
    def edir(j): return None if j == 0 else ("up" if c[j] > c[j - 1] else "down")
    def add(V, j): V["bars"] += 1; V["vol"] += v[j]; V["vol_na"] = V["vol_na"] or na[j]
    def sit(V): return None if V is None or V["vol_na"] or not V["bars"] else V["vol"] / V["bars"]
    def nearest(zs, x): return min(zs, key=lambda z: (abs(z["mid"] - x), z["seq"])) if zs else None

    def visit(z, j):
        V = dict(n=len(z["visits"]) + 1, start=j, end=None, ended_by=None, bars=0, vol=0.0, vol_na=False, entry_dir=edir(j))
        z["visits"].append(V); add(V, j)
        return V

    def target(mid):
        """Zone a candidate centred at `mid` is absorbed into: overlap >= merge_overlap of the width, largest overlap
        first (equal widths: nearest mid), then the older zone."""
        need, best = g["merge_overlap"] * 2 * HW - EPS, None
        for z in zones:
            ov = round(2 * HW - abs(z["mid"] - mid), 6)
            if ov >= need and (best is None or (ov, -z["seq"]) > best[0]): best = ((ov, -z["seq"]), z)
        return best and best[1]

    def birth(kind, mid, origin, i, zid, back, count_merge=True):
        """New zone (or None when absorbed). Its visit history is replayed with the zone-local visit rule over the closes
        before bar i: from the start of the run of inside closes containing `origin` when `back` and that close is
        inside, else from `origin`. Returns (zone, the replayed visit if still open, its outside run, its side)."""
        z0 = target(mid)
        if z0 is not None:
            if count_merge: z0["merges"] += 1; inc(f"merges_{kind}")
            return None
        mid = round(mid, 4)                                # edges frozen at birth (float noise trimmed; EPS covers it)
        z = dict(id=zid, kind=kind, lo=round(mid - HW, 4), hi=round(mid + HW, 4), mid=mid, origin_bar=origin, birth_bar=i,
                 born_ts=t[i], merges=0, visits=[], seq=len(zones), hunt_at=None, hunt_dir=None, reject_at=None,
                 reject_dir=None, leave_failed=False, today=-1, today_in=0)
        zones.append(z); byid[zid] = z
        inc(f"births_{kind}"); i >= s0 and inc(f"births_{kind}_shown")
        j0 = origin
        if back and inside(z, c[origin]):
            while j0 > 0 and inside(z, c[j0 - 1]): j0 -= 1
        V, run, sd = None, 0, None
        for j in range(j0, i):
            if inside(z, c[j]):
                if V is None: V = visit(z, j)
                else: add(V, j)
                run, sd = 0, None
            elif V is not None:
                s_ = "up" if c[j] > z["hi"] else "down"
                run, sd = (run + 1, sd) if s_ == sd else (1, s_)
                if run >= LC: V.update(end=j, ended_by="left"); V, run, sd = None, 0, None
        return z, V, run, sd

    def base_of(z, V):
        """Visit the volume ratio compares against: the first visit, or the previous one (volume_base)."""
        if g["volume_base"] == "first": return z["visits"][0]
        return z["visits"][V["n"] - 2] if V["n"] >= 2 else None

    def inside_read(z, V):
        """FIRST_PRINT / ACCEPTED / THIN / RECYCLE of visit V of zone z. Volume NA (either side) makes ACCEPTED time-only
        and THIN unavailable. A visit with live volume has only front-month bars (fm_na folds front_month == 0 in), so
        two live sides are always the same volume regime and a cross-regime ratio is NA by construction."""
        if V["n"] == 1: return "FIRST_PRINT"
        B = base_of(z, V)
        live = not V["vol_na"] and B is not None and not B["vol_na"]
        if V["bars"] >= g["accept_bars"] and (not live or V["vol"] >= g["accept_vol_ratio"] * B["vol"]): return "ACCEPTED"
        if live and V["vol"] < g["thin_ratio"] * B["vol"]: return "THIN"
        return "RECYCLE"

    def zone_read(z, k):
        """Read of zone z at bar k as if it were the ref band (LEAVE and PENDING aside): its edge event on this bar, else
        the inside read of its live or most recent visit (a never-visited band would open visit 1: FIRST_PRINT)."""
        if z["hunt_at"] == k: return "HUNT"
        if z["reject_at"] == k: return "REJECT"
        return inside_read(z, z["visits"][-1]) if z["visits"] else "FIRST_PRINT"

    def snap(z):
        """Band snapshot a WATCH or a position pins: edges, mid and the per-bar volume of its live or most recent sit."""
        V = z["visits"][-1] if z["visits"] else None
        m = sit(V)
        return dict(id=z["id"], kind=z["kind"], lo=z["lo"], hi=z["hi"], mid=z["mid"], sit_mean=m, vol_na=m is None)

    def in_pos(k): return pos is not None and pos["entry"] <= k < pos["exit"]

    def opened(res): return isinstance(res, int) and not isinstance(res, bool)

    def open_pierce(k):
        """First open_bars of the session (and before open_window_until): the bar's range crosses an edge of a band
        whose last visit ended in an earlier session and that has fewer than open_sit_closes closes inside today."""
        if not (sbar[k] < g["open_bars"] and hm[k] < g["open_window_until"]): return False
        for z in zones:
            if not z["visits"] or z["visits"][-1].get("end") is None: continue
            if sess[z["visits"][-1].get("end")] >= sess[k]: continue
            if z["today"] == sess[k] and z["today_in"] >= g["open_sit_closes"]: continue
            if l[k] - EPS <= z["lo"] <= h[k] + EPS or l[k] - EPS <= z["hi"] <= h[k] + EPS: return True
        return False

    def fade(k, S):
        """S would chase a HUNT: a HUNT in S's direction completed within fade_block_bars, same session, on the ref band
        or the band just left (fade_scope ref_band) or on any band (any_band)."""
        zs = zones if g["fade_scope"] == "any_band" else [z for z in (ref, leave and leave["zone"]) if z is not None]
        return any(z["hunt_at"] is not None and z["hunt_dir"] == S and 0 <= k - z["hunt_at"] <= g["fade_block_bars"]
                   and sess[z["hunt_at"]] == sess[k] for z in zs)

    def defend(z, V, k, S):
        """ACCEPTED band defended: a HUNT or REJECT in this visit within defend_window_bars at the edge S points away
        from (a low-edge event for a long, a high-edge event for a short)."""
        away = "down" if S == "up" else "up"
        return any(at is not None and d == away and at >= V["start"] and k - at <= g["defend_window_bars"]
                   for at, d in ((z["hunt_at"], z["hunt_dir"]), (z["reject_at"], z["reject_dir"])))

    def end_watch(reason, j):
        nonlocal watch
        w = watch
        out = reason if reason in ("reenter", "replaced") else ("armed_expired:" if w["armed"] else "cancelled:") + reason
        w.update(outcome=out, outcome_bar=j)
        if w["armed"] and w["r14"] and reason != "reenter" and w["opened_at"] >= s0: inc("no_same_dir_setup")
        if w["setup_i"] in rows: rows[w["setup_i"]]["watch_outcome"] = out
        watch = None

    def open_watch(k, S, z, kind, row, armed):
        nonlocal watch
        if watch is not None: end_watch("replaced", k)
        watch = dict(band=snap(z), dir=S, kind=kind, opened_at=k, opened_by=row["read"], setup_i=k, armed=armed,
                     armed_at=k if armed else None, first_armed_at=k if armed else None, run=1 if armed else 0,
                     far_vol=v[k] if armed else 0.0, far_na=na[k] if armed else False,
                     in_run=1 if inside(z, c[k]) else 0, opp_run=0, r14=False, outcome=None, outcome_bar=None)
        watches.append(watch)
        row.update(gate="WATCH", watch_kind=kind, watch_band_id=z["id"])

    def open_reenter(j, si, w, why):
        """REENTER at bar j's close on the watch's pinned band, with SETUP si as R5 (or as the converted TAKE)."""
        nonlocal pos
        B, up = w["band"], w["dir"] == "up"
        res = open_position("REENTER", j, w["dir"], si, dict(B))
        if not opened(res):
            if j >= s0: inc("reenter_refused"); inc(f"reenter_refused_{res or 'refused'}")
            fill = dict(reenter_reason=f"refused:{res or 'refused'}", refused=res or "refused")
            if si in rows: rows[si].update(fill)
            elif si == j: stash[j] = dict(fill, ok=False)
            return False
        # outcome_gate: the SETUP ended as a REENTER even when its own gate (as of its bar) was WATCH or BLOCK
        fill = dict(fill_bar=j, fill_used="setup_close" if j == si else "reenter_close", fill_delay_bars=j - si,
                    edge_dist_pts=round(c[j] - B["hi"] if up else B["lo"] - c[j], 2),
                    armed_bars=j - w["first_armed_at"] if w["first_armed_at"] is not None else None,
                    rearmed_bars=j - w["armed_at"] if w["armed_at"] is not None else None, reenter_reason=why,
                    outcome_gate="REENTER")
        pos = dict(kind="REENTER", entry=j, exit=res, dir=w["dir"], setup_i=si)
        decisions.append(("REENTER", j, w["dir"], si, dict(B)))
        reasons[j] = (why, fill["fill_used"])
        if si in rows: rows[si].update(fill)
        elif si == j: stash[j] = dict(fill, ok=True)
        if watch is w: end_watch("reenter", j)
        return True

    def watch_step(j):
        """Cancel checks, then R1-R5 on bar j's close; REENTER on the first bar where all hold and the clock allows."""
        w, B = watch, watch["band"]
        up = w["dir"] == "up"
        if sbar[j] == 0: return end_watch("session_end", j)
        x = c[j]
        ins = B["lo"] - EPS <= x <= B["hi"] + EPS
        far = x > B["hi"] + EPS if up else x < B["lo"] - EPS
        opp = x < B["lo"] - EPS if up else x > B["hi"] + EPS
        w["opp_run"] = w["opp_run"] + 1 if opp else 0
        w["in_run"] = w["in_run"] + 1 if ins else 0
        if w["opp_run"] >= LC: return end_watch("opposite_leave", j)
        if w["armed"] and w["in_run"] >= g["cancel_inside_bars"]: return end_watch("back_inside", j)
        if far:                                            # R1 (a fresh one after any close back in re-arms here)
            if w["run"] == 0:
                w.update(armed=True, armed_at=j, far_vol=0.0, far_na=False)
                if w["first_armed_at"] is None: w["first_armed_at"] = j
            w["run"] += 1; w["far_vol"] += v[j]; w["far_na"] = w["far_na"] or na[j]
        else:
            w["run"] = 0
        r2 = w["run"] >= LC                                # R2; R3 holds by construction on an unbroken far-side run
        r4 = None if (not w["run"] or w["far_na"] or B["sit_mean"] is None) else w["far_vol"] / w["run"] >= B["sit_mean"]
        w["r14"] = r2 and r4 is not False
        if r2 and j >= s0:
            inc("r4_bars_evaluated") if r4 is not None else inc("r4_bars_na")
            if r4 is False: inc("r4_bars_fail")
        if not w["r14"]: return
        if setup_at.get(j, (None,))[0] == w["dir"]: si = j                              # R5 on this bar
        elif sbar[j] > 0 and setup_at.get(j - 1, (None,))[0] == w["dir"]: si = j - 1     # ... or the prior bar
        else: return
        if hm[j] >= g["no_entry_from"]: j >= s0 and inc("clock_1520"); return
        if in_pos(j): j >= s0 and inc("reenter_in_position"); return
        open_reenter(j, si, w, w["kind"].lower())

    def take_branch(k, S, row, cd):
        """(branch, band) of the first TAKE branch that holds, else (None, None) with the reason on the row."""
        read = cd["read"]
        if read == "LEAVE":
            X, E = leave["zone"], byid.get(cd["in_id"])
            if S != leave["side"]: why = "leave_against"
            elif cd["leave_vol_ok"] is False: why = "leave_vol_fail"
            elif leave["kind"] == "gap" and sbar[k] < g["open_quiet_bars"]: why = "leave_gap_quiet"
            elif g["leave_far_side"] == "block_list" and E is not None and row["entered_read"] in BLOCK_READS:
                why = row["block_reason"] = "leave_into_recycle"
            elif g["leave_far_side"] == "no_band" and E is not None: why = row["block_reason"] = "leave_into_band"
            else: return "leave", X
            row["take_why"] = why
            return None, None
        V = ref["visits"][-1] if ref is not None else None
        if read == "FIRST_PRINT":
            if V["bars"] < g["first_print_min_bars"]: row["take_why"] = "first_print_young"
            elif S != V["entry_dir"]: row["take_why"] = "first_print_against"
            else: return "first_print", ref
        elif read == "ACCEPTED":
            if defend(ref, V, k, S): return "defend", ref
            row["take_why"] = "accepted_no_defend"
        return None, None

    def gate(k, S, row, cd):
        """TAKE / WATCH / BLOCK / REENTER for the Foundation SETUP at bar k in direction S."""
        nonlocal pos
        st_ = stash.pop(k, None)
        if st_ is not None and st_.pop("ok"):              # the watch step already re-entered on this SETUP
            row.update(gate="REENTER", branch="watch", **st_); return
        if st_ is not None: row.update(st_)                # a refused REENTER on this bar; gate the SETUP as usual
        why = ("in_position" if in_pos(k) else "clock" if hm[k] >= g["no_entry_from"] else "open_pierce" if open_pierce(k)
               else "hunt_fade" if fade(k, S) else "new" if cd["read"] == "NEW" else None)
        if why:
            row.update(gate="BLOCK", block_reason=why); return
        branch, z = take_branch(k, S, row, cd)
        if branch:
            if branch == "leave" and watch is not None and watch["band"]["id"] == z["id"] and watch["dir"] == S:
                row.update(gate="REENTER", branch=branch)          # a LEAVE of the watched band the watched way (M22)
                open_reenter(k, k, watch, f"take_on_watch:{branch}"); return
            row.update(gate="TAKE", branch=branch)
            res = open_position("TAKE", k, S, k, snap(z))
            if not opened(res):
                row.update(refused=res or "refused"); k >= s0 and inc("take_refused"); return
            pos = dict(kind="TAKE", entry=k, exit=res, dir=S, setup_i=k)
            decisions.append(("TAKE", k, S, k, snap(z)))
            row.update(fill_bar=k, fill_used="setup_close", fill_delay_bars=0)
            if watch is not None and watch["dir"] != S: end_watch("opposite_take", k)
            return
        if g["edge_watch"] == "ref_band" and cd["read"] == "PENDING" and k > 0 and inside(ref, c[k - 1]) and S == oside:
            return open_watch(k, S, ref, "WATCH_EDGE", row, armed=True)   # first close beyond: R1 already true
        zc = byid.get(cd["in_id"])
        if zc is not None: return open_watch(k, S, zc, "WATCH", row, armed=False)
        row.update(gate="BLOCK", block_reason="new")

    # ---------------------------------------------------------------- the bar loop
    N, CW = g["cluster_bars"], g["cluster_width"]
    born, latest, sp, cond_prev = set(), {}, 0, False
    for i in range(n):
        x = c[i]
        # -- births: A (protected level, or every swing as a diagnostic) before B (cluster sit)
        new_sw = []
        while sp < len(swings) and swings[sp][3] <= i:
            latest[swings[sp][2]] = swings[sp]; new_sw.append(swings[sp]); sp += 1
        cands = []                                         # (kind, mid, origin, id, scan back, count a merge)
        if g["birth_a_source"] == "every_swing":
            cands = [("A", s[2], s[1], "A" + t[s[3]], True, True) for s in new_sw]
        elif prot[i] is not None and (i == 0 or prot[i] != prot[i - 1]):
            s = latest.get(prot[i])
            if s is not None and s not in born:            # a revert to an already-born swing is not a birth
                born.add(s); cands = [("A", s[2], s[1], "A" + t[s[3]], True, True)]
        cond = False
        if i >= N - 1 and sess[i - N + 1] == sess[i]:
            win = c[i - N + 1:i + 1]; hi_, lo_ = max(win), min(win)
            cond = hi_ - lo_ <= CW + EPS
        if cond and g["birth_b"] == "band":
            # a candidate on the transition into the sit; while the sit lasts, only a drift the memory cannot absorb
            if not cond_prev: cands.append(("B", (hi_ + lo_) / 2, i - N + 1, "B" + t[i], False, True))
            elif target((hi_ + lo_) / 2) is None: cands.append(("B", (hi_ + lo_) / 2, i - N + 1, "B" + t[i], False, False))
        drift = cond and cond_prev
        cond_prev = cond
        for kind, mid, origin, zid, back, count in cands:
            got = birth(kind, mid, origin, i, zid, back, count_merge=count)
            if got is not None and kind == "B" and drift: inc("births_B_drift")
            if got is None or got[1] is None: continue
            z, V, run, sd = got
            if ref is None: ref, orun, oside = z, run, sd    # open ground: the replayed visit is the live one
            else: V.update(end=i - 1, ended_by="ref_live"); inc("backfill_cut_ref_live")   # one live visit at a time

        # -- bands containing this close; today's inside counts (open guard)
        inz = []
        for z in zones:
            if inside(z, x):
                inz.append(z)
                if z["today"] != sess[i]: z["today"], z["today_in"] = sess[i], 0
                z["today_in"] += 1

        # -- the live visit: continue, count an outside close, or end on the leave_closes-th and start a LEAVE
        prev_ref, prev_orun, prev_oside = ref, orun, oside
        pre = None
        if ref is not None:
            V = ref["visits"][-1]; pre = (V["bars"], V["vol"], V["vol_na"])
            if inside(ref, x):
                orun, oside = 0, None; add(V, i)
            else:
                sd = "up" if x > ref["hi"] else "down"
                orun, oside = (orun + 1, sd) if sd == oside else (1, sd)
                if orun >= LC:
                    V.update(end=i, ended_by="left"); r1 = i - orun + 1
                    ref["leave_failed"] = False                   # this leave has not failed (yet)
                    if leave is not None: inc("leave_end_replaced")
                    leave = dict(zone=ref, bar=i, side=sd, r1=r1, far_vol=sum(v[r1:i + 1]), far_n=orun,
                                 far_na=any(na[r1:i + 1]), sit=sit(V), kind="gap" if 0 in sbar[r1:i + 1] else "normal")
                    ref, orun, oside = None, 0, None
                    i >= s0 and inc("visit_ends_left")
        # -- the LEAVE lives leave_ttl_bars bars while no close is back inside the band and none crosses its mid
        returned = None
        if leave is not None and leave["bar"] < i:
            X, up = leave["zone"], leave["side"] == "up"
            if inside(X, x):
                X["leave_failed"] = True; returned = X; leave = None; inc("leave_end_returned")
            elif (x < X["mid"]) if up else (x > X["mid"]):
                leave = None; inc("leave_end_mid")
            elif i - leave["bar"] >= g["leave_ttl_bars"]:
                leave = None; inc("leave_end_expired")
            else:
                leave["far_vol"] += v[i]; leave["far_n"] += 1; leave["far_na"] = leave["far_na"] or na[i]
                if sbar[i] == 0: leave["kind"] = "gap"
        # -- no live visit: the band containing the close opens one (a return into the band just left takes it back)
        if ref is None:
            z = returned if returned is not None else nearest(inz, x)
            if z is not None:
                visit(z, i); ref, orun, oside = z, 0, None
                i >= s0 and inc("visits_opened")
        if returned is not None and ref is not returned and i >= s0:
            inc("leave_return_no_visit")                   # back inside the band just left, but a neighbour holds the visit

        # -- edge events on the ref band (read on the reclaim / tag bar only)
        ev_h = ev_r = None; wick = None
        if ref is not None and orun == 0:
            z = ref
            up_d, dn_d = h[i] - z["hi"], z["lo"] - l[i]
            wick = round(max(up_d, dn_d, 0.0), 2)
            pierce = None
            if g["hunt_form"] == "close":
                if prev_ref is z and prev_orun == 1: pierce = (prev_oside, i - 1)        # one close out, back in
            elif i > 0 and inside(z, c[i - 1]) and max(up_d, dn_d) > EPS \
                    and max(up_d, dn_d) >= g["hunt_min_depth_atr"] * atr[i] - EPS:
                pierce = ("up" if up_d >= dn_d else "down", i)                           # wick pierce, closes inside
            if pierce is not None and i - pierce[1] <= g["hunt_max_bars"]:
                pb = pierce[1]
                m = pre[1] / pre[0] if (prev_ref is z and pre and pre[0] and not pre[2]) else None
                if m is None or na[pb] or v[pb] >= g["hunt_burst"] * m:                  # burst, skipped when NA
                    ev_h = pierce[0]; z["hunt_at"], z["hunt_dir"] = i, ev_h
                else:
                    i >= s0 and inc("hunt_no_burst")
            if ev_h is None and i > 0 and inside(z, c[i - 1]):
                tol = g["reject_tol"]
                qh, ql = -tol - EPS <= up_d <= tol + EPS, -tol - EPS <= dn_d <= tol + EPS
                if (qh or ql) and abs(x - z["mid"]) < abs(o[i] - z["mid"]) - EPS:
                    ev_r = ("up" if up_d >= dn_d else "down") if (qh and ql) else ("up" if qh else "down")
                    z["reject_at"], z["reject_dir"] = i, ev_r

        # -- the card
        V = ref["visits"][-1] if ref is not None else None
        if leave is not None: read = "LEAVE"
        elif ev_h: read = "HUNT"
        elif ev_r: read = "REJECT"
        elif V is not None and orun == 0: read = inside_read(ref, V)
        elif V is not None: read = "PENDING"
        else: read = "NEW"
        zin = ref if (ref is not None and orun == 0) else nearest(inz, x)
        F = ref["visits"][0] if ref is not None else None
        P = ref["visits"][-2] if ref is not None and len(ref["visits"]) > 1 else None
        lv_ok = None
        if leave is not None and not leave["far_na"] and leave["sit"] is not None:
            lv_ok = leave["far_vol"] / leave["far_n"] >= leave["sit"]
        cd = dict(zone_id=ref and ref["id"], visit_n=V and V["n"], this_bars=V and V["bars"],
                  this_vol=V and V["vol"], vol_na=V["vol_na"] if V else na[i],
                  first_bars=F and F["bars"], first_vol=F and F["vol"], first_vol_na=F["vol_na"] if F else None,
                  read=read, left_id=leave and leave["zone"]["id"], out_run=orun if ref is not None else None,
                  out_side=oside, session_bar=sbar[i], gap_pts=gap[i], wick_depth=wick,
                  last_hunt_at=ref and ref["hunt_at"], last_hunt_dir=ref and ref["hunt_dir"],
                  last_reject_at=ref and ref["reject_at"], last_reject_dir=ref and ref["reject_dir"],
                  cluster_sit=cond, prev_bars=P and P["bars"], prev_vol=P and P["vol"],
                  last_leave_failed=ref["leave_failed"] if ref is not None else None,
                  in_id=zin and zin["id"], leave_side=leave and leave["side"], leave_vol_ok=lv_ok,
                  leave_kind=leave and leave["kind"],
                  first_clock_lived=(V["bars"] >= g["accept_bars"]) if read == "FIRST_PRINT" else None)
        card.append(cd)

        # -- the watch (before the gate), then the gate on a Foundation SETUP at this bar
        if watch is not None and watch["opened_at"] < i: watch_step(i)
        if i in setup_at:
            S, ch = setup_at[i]
            lvl = level_at.get(ch)
            row = dict(i=i, time=t[i], dir=S, choch_i=ch, zone_id=cd["zone_id"], zone_kind=ref and ref["kind"],
                       band_lo=ref and ref["lo"], band_hi=ref and ref["hi"], visit_n=cd["visit_n"],
                       this_bars=cd["this_bars"], this_vol=cd["this_vol"], first_bars=cd["first_bars"],
                       first_vol=cd["first_vol"], vol_na=cd["vol_na"], first_vol_na=cd["first_vol_na"], read=read,
                       left_id=cd["left_id"], session_bar=sbar[i], in_id=cd["in_id"],
                       level_in_band=(ref["lo"] - EPS <= lvl <= ref["hi"] + EPS) if (ref is not None and lvl is not None) else None,
                       gate=None, outcome_gate=None, block_reason=None, branch=None, take_why=None, refused=None,
                       entered_zone_id=None, entered_visit_n=None, entered_read=None, leave_vol_ok=None, leave_kind=None,
                       watch_kind=None, watch_band_id=None, watch_outcome=None, reenter_reason=None, fill_used=None,
                       fill_bar=None, fill_delay_bars=None, edge_dist_pts=None, armed_bars=None, rearmed_bars=None,
                       sl_bar=None)
            if read == "LEAVE":
                E = byid.get(cd["in_id"])
                row.update(leave_vol_ok=lv_ok, leave_kind=leave["kind"], entered_zone_id=E and E["id"],
                           entered_visit_n=E["visits"][-1]["n"] if (E is not None and E["visits"]) else (0 if E else None),
                           entered_read=zone_read(E, i) if E is not None else None)
            rows[i] = row
            gate(i, S, row, cd)

    # ---------------------------------------------------------------- outputs
    if watch is not None: watch.update(outcome="active", outcome_bar=n - 1)
    for w in watches:
        if w["setup_i"] in rows and w["outcome"]: rows[w["setup_i"]]["watch_outcome"] = w["outcome"]
    for r in rows.values():          # gate = as of the SETUP bar (what truncation checks); outcome_gate = how the SETUP ended
        r["outcome_gate"] = r["outcome_gate"] or r["gate"]
    ledger = [rows[i] for i in sorted(rows) if i >= s0]
    for i in range(s0, n):
        inc(f"read_{card[i]['read']}")
        if card[i]["in_id"] is not None: inc("bars_inside")
        if card[i]["zone_id"] is not None: inc("bars_ref_live")
    stats["bars_shown"] = n - s0
    for r in ledger:
        inc(f"gate_{r['gate']}"); inc(f"gate_read_{r['gate']}:{r['read']}"); inc(f"outcome_gate_{r['outcome_gate']}")
        if r["block_reason"]: inc(f"block_{r['gate']}:{r['block_reason']}")
        if r["branch"]: inc(f"branch_{r['gate']}:{r['branch']}")
        if r["take_why"]: inc(f"take_why_{r['take_why']}")
    for w in watches:
        if w["opened_at"] >= s0: inc(f"watch_{w['kind']}"); inc(f"watch_outcome_{w['outcome']}")
    for kind, e, d, si, b in decisions:
        if e >= s0: inc(f"positions_{kind}")
    stats.update(tf_min=tf_min, zones=len(zones), s0=s0)
    zout = [dict(id=z["id"], kind=z["kind"], lo=z["lo"], hi=z["hi"], mid=z["mid"], origin_bar=z["origin_bar"],
                 birth_bar=z["birth_bar"], born_ts=z["born_ts"], merges=z["merges"], visits=[dict(V) for V in z["visits"]])
            for z in zones]
    wout = [dict(opened_at=w["opened_at"], band_id=w["band"]["id"], dir=w["dir"], kind=w["kind"],
                 opened_by_read=w["opened_by"], setup_i=w["setup_i"], outcome=w["outcome"], outcome_bar=w["outcome_bar"],
                 armed_at=w["first_armed_at"], last_armed_at=w["armed_at"]) for w in watches]
    return dict(card=card, zones=zout, ledger=ledger, watches=wout, decisions=decisions, reasons=reasons, stats=stats)
