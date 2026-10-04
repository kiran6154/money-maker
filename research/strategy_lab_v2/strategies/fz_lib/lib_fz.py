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

Two memory models (room_model), the rest of the module shared:
  bands    the base (Strategies 5, 6): zones as above; drift births while a sit lasts (drift_birth); never retired
  rooms    FZ v2 (Strategies 7, 8): a room is born only on the transition into a sit (birth_a_source 'none'), centred on
           the sit, visit 1 = the sit; a sit overlapping a live room by merge_overlap is a visit of that room (the live
           visit follows it); a sit overlapping a room already visited this session is a visit of that older room
           (same_session_overlap 'keep_older'; 'visited' = any close inside, or a sit of cluster_bars closes inside,
           session_visit_rule); a sit within band_half_width of a room sat in this session is not a birth and not a
           visit (adjacent_birth 'block_half_width', counted sits_near_room); live rooms never overlap (room_overlap: 'supersede' retires the rooms a new sit partly
           overlaps, 'clip' stops the new room at their edges); a room with no inside close in room_max_age_sessions
           sessions is retired on a session's first bar (never the ref band again, absorbs nothing, contains no price);
           ids '<letter> <mm-dd hh:mm>' (birth order in the session, birth bar)
  In either model a stay with fewer than visit_min_bars inside closes that ends by the leave rule is a touch: counted on
  the zone and the card (touches), not a visit (visit_n does not advance); and the close-form HUNT is 1..hunt_max_bars
  closes outside on one side, then a close back inside. defend_half 'away_half' (either model; base 'off') lets a defend
  TAKE through only when the SETUP close is in the half of the room away from the defended edge (above the mid for a
  long, below it for a short); otherwise the row falls through to WATCH with take_why defend_wrong_half. defend_direction
  'one_per_visit' (base 'any'): after a defend TAKE one way in a visit, a defend the other way in the same visit is WATCH
  with take_why defend_opposite_in_visit.
  Rooms only: room_edges 'sit_range' (base 'half_width') gives a room the min / max close of the sit that bore it, frozen
  at birth; absorb_rule 'mid_inside' (base 'overlap') absorbs a sit only into the live room containing its mid;
  same_day_replace 'replace' (base 'off'): a sit that is not absorbed and overlaps or touches a room born earlier the
  same session is born and retires that room (retired_by same_day_replace; a watch on it ends, reason room_replaced);
  'replace_unaccepted' does so only while that room has not had an ACCEPTED stay (accepted_at, set as of the close
  on which a stay of the room first reads ACCEPTED); an accepted same-day room keeps keep_older / adjacent_birth.

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
from bisect import bisect_left, bisect_right, insort

EPS = 1e-6       # float tolerance on inclusive band edges (prices sit on a 0.05 grid; mid +- half width is inexact)
READS = ("FIRST_PRINT", "ACCEPTED", "RECYCLE", "THIN", "HUNT", "REJECT", "LEAVE", "PENDING", "NEW")
BLOCK_READS = ("RECYCLE", "THIN", "HUNT", "REJECT")     # spec s3's BLOCK list, applied to the entered band (block_list)

CHOICES = dict(birth_a_source=("protected_level", "every_swing", "none"), birth_b=("band", "flag"),
               hunt_form=("close", "wick"), leave_far_side=("any", "block_list", "no_band"),
               fade_scope=("ref_band", "any_band"), edge_watch=("ref_band", "containing_band"),
               volume_base=("first", "previous"), reenter_fill=("confirm_bar",), room_model=("bands", "rooms"),
               room_overlap=("supersede", "clip"), same_session_overlap=("keep_older", "supersede"),
               session_visit_rule=("any_close", "sit"), adjacent_birth=("allow", "block_half_width"),
               defend_half=("off", "away_half"), room_edges=("half_width", "sit_range"),
               absorb_rule=("overlap", "mid_inside"), defend_direction=("any", "one_per_visit"),
               same_day_replace=("off", "replace", "replace_unaccepted"))
BAR_COUNTS = ("cluster_bars", "accept_bars", "first_print_min_bars", "hunt_max_bars", "leave_closes", "leave_ttl_bars",
              "fade_block_bars", "defend_window_bars", "open_bars", "open_quiet_bars", "open_sit_closes",
              "cancel_inside_bars", "control_draws", "visit_min_bars")
NUMBERS = ("band_half_width", "cluster_width", "merge_overlap", "accept_vol_ratio", "thin_ratio", "hunt_burst", "reject_tol")
OPTIONAL = ("zone_max_age_sessions", "hunt_min_depth_atr", "room_max_age_sessions")        # null allowed
CLOCKS = ("open_window_until", "no_entry_from")
TEXT = ("control_seed",)
BOOLS = ("drift_birth",)
KEYS = set(CHOICES) | set(BAR_COUNTS) | set(NUMBERS) | set(OPTIONAL) | set(CLOCKS) | set(TEXT) | set(BOOLS)


def room_letters(k):
    """Birth order within a session as letters: 0 -> A, 25 -> Z, 26 -> AA, 27 -> AB ..."""
    s, k = "", k + 1
    while k:
        k, r = divmod(k - 1, 26); s = chr(65 + r) + s
    return s


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
    for k in BOOLS:
        if not isinstance(cfg[k], bool): raise ValueError(f"fz {k} = {cfg[k]!r}: must be true or false")
    if cfg["room_max_age_sessions"] is not None and cfg["room_max_age_sessions"] < 0:
        raise ValueError("fz room_max_age_sessions: must be >= 0 or null")
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

    ROOMS, VMIN, AGE = g["room_model"] == "rooms", g["visit_min_bars"], g["room_max_age_sessions"]
    zones, byid, alive = [], {}, []      # every zone ever born; by id; the ones not retired (all of them under bands)
    # v2: the live zones indexed by lo and by mid (sorted (key, seq)), so the per-bar "bands containing this close" and
    # target() look at the zones near a price instead of every zone ever born; candidates are then tested with the exact
    # v1 expressions and taken in birth (seq) order, i.e. the order of `alive`
    lo_ix, mid_ix, by_seq, wmax = [], [], {}, [0.0]
    def ix_add(z):
        insort(lo_ix, (z["lo"], z["seq"])); insort(mid_ix, (z["mid"], z["seq"])); by_seq[z["seq"]] = z
        wmax[0] = max(wmax[0], z["hi"] - z["lo"])
    def ix_del(z):
        del lo_ix[bisect_left(lo_ix, (z["lo"], z["seq"]))]; del mid_ix[bisect_left(mid_ix, (z["mid"], z["seq"]))]
        del by_seq[z["seq"]]
    def near_lo(a, b):
        """Live zones with lo in [a, b] (a superset; callers apply the exact test), in birth order."""
        return sorted((by_seq[q] for _, q in lo_ix[bisect_left(lo_ix, (a, -1)):bisect_right(lo_ix, (b, float("inf")))]),
                      key=lambda z: z["seq"])
    def near_mid(a, b):
        return [by_seq[q] for _, q in mid_ix[bisect_left(mid_ix, (a, -1)):bisect_right(mid_ix, (b, float("inf")))]]
    born_in = {}                         # rooms: births per session (the room letter)
    ref, orun, oside = None, 0, None     # band with the live visit; consecutive closes outside it and their side
    leave = None                         # the LEAVE of the band most recently left, while it lives
    watch, pos = None, None
    card, rows, decisions, reasons, watches = [], {}, [], {}, []
    stash = {}                           # REENTER decided in the watch step on a SETUP bar, for that bar's gate
    absorbed = [None]                    # the zone that absorbed the last candidate birth() refused
    replaced = [set()]                   # rooms: ids of same-day rooms the last candidate replaces (same_day_replace)

    # ---------------------------------------------------------------- helpers
    def inside(z, x): return z["lo"] - EPS <= x <= z["hi"] + EPS
    def edir(j): return None if j == 0 else ("up" if c[j] > c[j - 1] else "down")
    def add(V, j): V["bars"] += 1; V["vol"] += v[j]; V["vol_na"] = V["vol_na"] or na[j]
    def sit(V): return None if V is None or V["vol_na"] or not V["bars"] else V["vol"] / V["bars"]
    def nearest(zs, x): return min(zs, key=lambda z: (abs(z["mid"] - x), z["seq"])) if zs else None

    def visit(z, j):
        """A new stay; its number counts the earlier stays that were not touches (as-of: it is a visit while it lasts)."""
        V = dict(n=1 + sum(1 for W in z["visits"] if not W.get("touch")), start=j, end=None, ended_by=None, bars=0,
                 vol=0.0, vol_na=False, entry_dir=edir(j))
        z["visits"].append(V); add(V, j)
        return V

    def end_stay(z, V, j, how):
        """End stay V of zone z at bar j. A stay ended by the leave rule with fewer than visit_min_bars inside closes is a
        touch: it keeps its record (flag `touch`) but does not advance the zone's visit count."""
        V.update(end=j, ended_by=how)
        if how == "left" and V["bars"] < VMIN:
            V["touch"] = True; z["touches"] += 1; j >= s0 and inc("touches")

    def first_of(z):
        """The zone's first visit (its first stay that is not a touch)."""
        return next((W for W in z["visits"] if not W.get("touch")), None)

    def prev_of(z, V):
        """The visit before V (number V.n - 1, not a touch), or None."""
        return next((W for W in reversed(z["visits"]) if W["n"] == V["n"] - 1 and not W.get("touch") and W is not V), None)

    def visited_today(z, i):
        """Room z counts as visited this session (before bar i) under session_visit_rule: any_close = a close inside it
        this session; sit = a run of at least cluster_bars consecutive same-session closes inside it this session (the
        sit that bore it counts)."""
        return (z["sat_sess"] if g["session_visit_rule"] == "sit" else z["last_in"]) == sess[i]

    def room_fit(mid, i, rng=None):
        """Rooms: (lo, hi, absorber, overlapped, near, how) for a candidate sit at bar i, in this order. The candidate's
        band is mid +- band_half_width (room_edges = half_width) or the sit's own close range `rng` (sit_range; a
        candidate without a sit, i.e. a swing birth, keeps mid +- band_half_width).
          absorber  absorb_rule = overlap: a live room overlapping the band by >= merge_overlap x the candidate's width
                    (largest overlap, then nearest mid, then the older room); absorb_rule = mid_inside: the live room
                    containing the candidate's mid (nearest mid, then the older room)  -> how = 'merge'
                    then, with same_session_overlap = keep_older, a live room visited this session (visited_today) that
                    the band overlaps by any amount: the older room keeps its edges, the sit is a visit  -> how = 'older'
          near      with adjacent_birth = block_half_width, a live room visited this session whose edge is within a
                    distance of the band (overlapping or not): band_half_width (half_width) or that room's own half-range
                    (sit_range): no birth and no visit
          same_day_replace = replace (checked after the absorb rule, before keep_older / adjacent_birth): the live rooms
                    born earlier this session that the band overlaps or touches (gap <= 0) are not protected by
                    keep_older / adjacent_birth; the sit is born and replaces them (their ids go to replaced[0]; birth()
                    retires them with retired_by = same_day_replace). Rooms born on earlier days keep both protections
          else a new room at lo..hi; `overlapped` are the live rooms it partly overlaps, retired under room_overlap =
          supersede (the new room keeps its edges); under clip the new room's edges stop at theirs instead (how =
          'clipped' when they moved)."""
        sr = g["room_edges"] == "sit_range" and rng is not None
        lo, hi = rng if sr else (mid - HW, mid + HW)
        ovl = lambda z: round(min(hi, z["hi"]) - max(lo, z["lo"]), 6)
        key = lambda z: (ovl(z), -abs(z["mid"] - mid), -z["seq"])
        replaced[0] = set()
        if g["absorb_rule"] == "mid_inside":
            best = [z for z in alive if inside(z, mid)]
            if best: return None, None, min(best, key=lambda z: (abs(z["mid"] - mid), z["seq"])), [], None, "merge"
        else:
            need = g["merge_overlap"] * ((hi - lo) if sr else 2 * HW) - EPS
            best = [z for z in alive if ovl(z) >= need]
            if best: return None, None, max(best, key=key), [], None, "merge"
        repl = []
        if g["same_day_replace"] in ("replace", "replace_unaccepted"):
            repl = [z for z in alive if sess[z["birth_bar"]] == sess[i] and max(lo - z["hi"], z["lo"] - hi) <= EPS
                    and (g["same_day_replace"] == "replace" or z["accepted_at"] is None)]
        over = [z for z in alive if ovl(z) > EPS and z not in repl]
        if g["same_session_overlap"] == "keep_older":
            today = [z for z in over if visited_today(z, i)]
            if today: return None, None, max(today, key=key), [], None, "older"
        if g["adjacent_birth"] == "block_half_width":
            dist = (lambda z: (z["hi"] - z["lo"]) / 2) if g["room_edges"] == "sit_range" else (lambda z: HW)
            near = [z for z in alive if z not in repl and visited_today(z, i)
                    and max(lo - z["hi"], z["lo"] - hi) <= dist(z) + EPS]
            if near: return None, None, None, [], min(near, key=lambda z: (abs(z["mid"] - mid), z["seq"])), None
        how = None
        if g["room_overlap"] == "clip":
            for z in over:
                if z["mid"] < mid: lo = z["hi"]
                else: hi = z["lo"]
            how = "clipped" if over else None
            over = []
        replaced[0] = {z["id"] for z in repl}
        return lo, hi, None, over + repl, None, how

    def retire(z, i, why):
        """Retire zone z at bar i (room_max_age_sessions: 'retired'; a superseding sit: 'superseded'): never the ref band
        again, absorbs nothing, contains no price. A LEAVE still live on it ends."""
        nonlocal leave
        z["retired_bar"] = i; z["retired_by"] = why; alive.remove(z); ix_del(z); i >= s0 and inc(f"rooms_{why}")
        if leave is not None and leave["zone"] is z: leave = None; inc("leave_end_retired")

    def target(mid):
        """Zone a candidate centred at `mid` is absorbed into: overlap >= merge_overlap of the width, largest overlap
        first (equal widths: nearest mid), then the older zone."""
        need, best = g["merge_overlap"] * 2 * HW - EPS, None
        r_ = 2 * HW - need + 1e-3                          # |mid - z.mid| beyond this cannot reach `need`
        for z in near_mid(mid - r_, mid + r_):
            ov = round(2 * HW - abs(z["mid"] - mid), 6)
            if ov >= need and (best is None or (ov, -z["seq"]) > best[0]): best = ((ov, -z["seq"]), z)
        return best and best[1]

    def birth(kind, mid, origin, i, zid, back, count_merge=True, rng=None):
        """New zone (or None when absorbed; absorbed[0] is then the absorbing zone). Its visit history is replayed with
        the zone-local visit rule over the closes before bar i: from the start of the run of inside closes containing
        `origin` when `back` and that close is inside, else from `origin`. Returns (zone, the replayed visit if still
        open, its outside run, its side). Rooms: named '<letter> <mm-dd hh:mm>' (the letter = birth order within the
        session, the time = the birth bar); the live rooms it overlaps are superseded or it is clipped (room_overlap)."""
        near = how = None
        if ROOMS: lo_, hi_, z0, over, near, how = room_fit(mid, i, rng)
        else: z0 = target(mid)
        absorbed[0] = z0
        if near is not None:                               # adjacent_birth: a sit next to a room sat in today
            i >= s0 and inc("sits_near_room")
            return None
        if z0 is not None:
            if count_merge: z0["merges"] += 1; inc(f"merges_{kind}")
            if how == "older": i >= s0 and inc("sits_kept_by_older")   # same_session_overlap, not the absorb rule
            return None
        if ROOMS:
            k = born_in.get(sess[i], 0); born_in[sess[i]] = k + 1
            zid = f"{room_letters(k)} {t[i][5:10]} {t[i][11:16]}"
            lo, hi = round(lo_, 4), round(hi_, 4)
            mid = round((lo + hi) / 2, 4)
            if how == "clipped": i >= s0 and inc("rooms_clipped")
            for z_ in over:
                if z_["id"] in replaced[0]:
                    retire(z_, i, "same_day_replace")
                    if watch is not None and watch["band"]["id"] == z_["id"]: end_watch("room_replaced", i)
                else: retire(z_, i, "superseded")
        else:
            mid = round(mid, 4)                            # edges frozen at birth (float noise trimmed; EPS covers it)
            lo, hi = round(mid - HW, 4), round(mid + HW, 4)
        z = dict(id=zid, kind=kind, lo=lo, hi=hi, mid=mid, origin_bar=origin, birth_bar=i,
                 born_ts=t[i], merges=0, visits=[], seq=len(zones), hunt_at=None, hunt_dir=None, reject_at=None,
                 reject_dir=None, leave_failed=False, today=-1, today_in=0, touches=0, retired_bar=None, retired_by=None,
                 last_in=sess[i], sat_sess=sess[i] if kind == "B" else -1, run_sess=-1, in_run=0, in_last=-2, accepted_at=None)
        zones.append(z); byid[zid] = z; alive.append(z); ix_add(z)
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
                if run >= LC: end_stay(z, V, j, "left"); V, run, sd = None, 0, None
        return z, V, run, sd

    def base_of(z, V):
        """Visit the volume ratio compares against: the first visit, or the previous one (volume_base)."""
        if g["volume_base"] == "first": return first_of(z)
        return prev_of(z, V) if V["n"] >= 2 else None

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
        whose last visit ended in an earlier session and that has fewer than open_sit_closes closes inside today
        (retired rooms have no edges)."""
        if not (sbar[k] < g["open_bars"] and hm[k] < g["open_window_until"]): return False
        for z in alive:
            if not z["visits"] or z["visits"][-1].get("end") is None: continue
            if sess[z["visits"][-1].get("end")] >= sess[k]: continue
            if z["today"] == sess[k] and z["today_in"] >= g["open_sit_closes"]: continue
            if l[k] - EPS <= z["lo"] <= h[k] + EPS or l[k] - EPS <= z["hi"] <= h[k] + EPS: return True
        return False

    def fade(k, S):
        """S would chase a HUNT: a HUNT in S's direction completed within fade_block_bars, same session, on the ref band
        or the band just left (fade_scope ref_band) or on any band (any_band)."""
        zs = alive if g["fade_scope"] == "any_band" else [z for z in (ref, leave and leave["zone"]) if z is not None]
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
            if not defend(ref, V, k, S): row["take_why"] = "accepted_no_defend"
            elif g["defend_half"] == "away_half" and not (c[k] > ref["mid"] if S == "up" else c[k] < ref["mid"]):
                row["take_why"] = "defend_wrong_half"          # the close is not in the half away from the defended edge
            elif g["defend_direction"] == "one_per_visit" and V.get("defend_dir") not in (None, S):
                row["take_why"] = "defend_opposite_in_visit"   # this visit already had a defend TAKE the other way
            else: return "defend", ref
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
            if branch == "defend" and g["defend_direction"] == "one_per_visit":
                z["visits"][-1]["defend_dir"] = S              # the gate's decision, whether or not a position opens
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
        # -- retirement (room_max_age_sessions): on a session's first bar, a zone with no inside close in the last that
        #    many sessions is retired: never the ref band again, absorbs nothing, contains no price. The zone holding the
        #    live visit is kept.
        if AGE is not None and i > 0 and sbar[i] == 0:
            for z in [z for z in alive if z is not ref and sess[i] - z["last_in"] > AGE]: retire(z, i, "retired")
        # -- births: A (protected level, or every swing as a diagnostic) before B (cluster sit)
        new_sw = []
        while sp < len(swings) and swings[sp][3] <= i:
            latest[swings[sp][2]] = swings[sp]; new_sw.append(swings[sp]); sp += 1
        cands = []                                         # (kind, mid, origin, id, scan back, count a merge)
        if g["birth_a_source"] == "every_swing":
            cands = [("A", s[2], s[1], "A" + t[s[3]], True, True) for s in new_sw]
        elif g["birth_a_source"] == "protected_level" and prot[i] is not None and (i == 0 or prot[i] != prot[i - 1]):
            s = latest.get(prot[i])
            if s is not None and s not in born:            # a revert to an already-born swing is not a birth
                born.add(s); cands = [("A", s[2], s[1], "A" + t[s[3]], True, True)]
        cond = False
        if i >= N - 1 and sess[i - N + 1] == sess[i]:
            win = c[i - N + 1:i + 1]; hi_, lo_ = max(win), min(win)
            cond = hi_ - lo_ <= CW + EPS
        if cond and g["birth_b"] == "band":
            # a candidate on the transition into the sit; while the sit lasts, only a drift the memory cannot absorb
            # (drift_birth), which the room model does not use
            if not cond_prev: cands.append(("B", (hi_ + lo_) / 2, i - N + 1, "B" + t[i], False, True))
            elif g["drift_birth"] and not (any(room_fit((hi_ + lo_) / 2, i, (lo_, hi_))[2::2]) if ROOMS else target((hi_ + lo_) / 2)):
                cands.append(("B", (hi_ + lo_) / 2, i - N + 1, "B" + t[i], False, False))
        drift = cond and cond_prev
        cond_prev = cond
        prefer = None                                      # rooms: the live room a sit was absorbed into (it takes the visit)
        for kind, mid, origin, zid, back, count in cands:
            got = birth(kind, mid, origin, i, zid, back, count_merge=count, rng=(lo_, hi_) if kind == "B" else None)
            if got is not None and kind == "B" and drift: inc("births_B_drift")
            if got is None and ROOMS and kind == "B" and count:
                Z = absorbed[0]                            # a sit inside a live room is a visit of that room
                if Z is not None and Z is not ref and inside(Z, x):
                    if ref is not None:
                        end_stay(ref, ref["visits"][-1], i - 1, "sit_moved"); i >= s0 and inc("visit_ends_sit_moved")
                        ref, orun, oside = None, 0, None
                    prefer = Z
            if got is None or got[1] is None: continue
            z, V, run, sd = got
            if ref is None: ref, orun, oside = z, run, sd    # open ground: the replayed visit is the live one
            elif ROOMS:                                    # the room the market sits in now holds the live visit
                end_stay(ref, ref["visits"][-1], i - 1, "sit_moved"); i >= s0 and inc("visit_ends_sit_moved")
                ref, orun, oside = z, run, sd
            else: V.update(end=i - 1, ended_by="ref_live"); inc("backfill_cut_ref_live")   # one live visit at a time
        if ref is not None and ref["retired_bar"] is not None:  # superseded with no room taking the visit over
            end_stay(ref, ref["visits"][-1], i - 1, "superseded"); ref, orun, oside = None, 0, None

        # -- bands containing this close; today's inside counts (open guard); the session of the last inside close; the
        #    run of consecutive same-session inside closes and the session of the last sit (session_visit_rule = sit)
        #    (v2: in_run is kept lazily - v1 reset it to 0 on every live zone not containing the close; here a zone's
        #    run continues only when it also held the previous bar's close, which is the same number)
        inz = []
        for z in near_lo(x - wmax[0] - 1e-3, x + 1e-3):
            if inside(z, x):
                inz.append(z); z["last_in"] = sess[i]
                if z["today"] != sess[i]: z["today"], z["today_in"] = sess[i], 0
                z["today_in"] += 1
                run0 = z["in_run"] if z["in_last"] == i - 1 else 0
                z["in_run"] = run0 + 1 if z["run_sess"] == sess[i] else 1; z["run_sess"] = sess[i]; z["in_last"] = i
                if z["in_run"] >= N: z["sat_sess"] = sess[i]

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
                    end_stay(ref, V, i, "left"); r1 = i - orun + 1
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
            z = returned if returned is not None else prefer if prefer is not None else nearest(inz, x)
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
            if g["hunt_form"] == "close":                  # 1..hunt_max_bars closes out on one side, then back in
                if prev_ref is z and 1 <= prev_orun <= g["hunt_max_bars"]: pierce = (prev_oside, i - prev_orun)
            elif i > 0 and inside(z, c[i - 1]) and max(up_d, dn_d) > EPS \
                    and max(up_d, dn_d) >= g["hunt_min_depth_atr"] * atr[i] - EPS:
                pierce = ("up" if up_d >= dn_d else "down", i)                           # wick pierce, closes inside
            if pierce is not None and i - pierce[1] <= g["hunt_max_bars"]:
                pb = range(pierce[1], i) if g["hunt_form"] == "close" else (i,)         # the outside bars (the poke)
                m = pre[1] / pre[0] if (prev_ref is z and pre and pre[0] and not pre[2]) else None
                if m is None or any(na[b] for b in pb) or max(v[b] for b in pb) >= g["hunt_burst"] * m:   # burst; NA skips
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
        if V is not None and orun == 0 and ref["accepted_at"] is None and inside_read(ref, V) == "ACCEPTED":
            ref["accepted_at"] = i                         # as of this close: the room has had an ACCEPTED stay
        zin = ref if (ref is not None and orun == 0) else nearest(inz, x)
        F = first_of(ref) if ref is not None else None
        P = prev_of(ref, V) if ref is not None else None
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
                  first_clock_lived=(V["bars"] >= g["accept_bars"]) if read == "FIRST_PRINT" else None,
                  touches=ref["touches"] if ref is not None else None)
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
                 birth_bar=z["birth_bar"], born_ts=z["born_ts"], merges=z["merges"], visits=[dict(V) for V in z["visits"]],
                 touches=z["touches"], retired_bar=z["retired_bar"], retired_by=z["retired_by"])
            for z in zones]
    wout = [dict(opened_at=w["opened_at"], band_id=w["band"]["id"], dir=w["dir"], kind=w["kind"],
                 opened_by_read=w["opened_by"], setup_i=w["setup_i"], outcome=w["outcome"], outcome_bar=w["outcome_bar"],
                 armed_at=w["first_armed_at"], last_armed_at=w["armed_at"]) for w in watches]
    return dict(card=card, zones=zout, ledger=ledger, watches=wout, decisions=decisions, reasons=reasons, stats=stats)
