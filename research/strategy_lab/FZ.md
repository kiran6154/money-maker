# How the Foundation-Zone gate (Strategies 5 and 6) is built

> **v2 (Strategies 7 and 8): rooms instead of bands.** Sections 1–18 describe the first build, now tagged *FZ base*
> (`room_model = "bands"`, Strategies 5 and 6, unchanged bit for bit). Section 19 describes the room model that Strategies 7 and 8
> run through the same card, gate and watch code.

This is the builder's view of FZ: what each module does, the exact rules as coded, how the lab runs and stores it, what the dashboard shows, what the tests guarantee, and what is still a user decision. The user-level summary is the *FZ* section of [`README.md`](README.md); the evaluation that produced the design is `FZ_reevaluation_2026-09-27.md` (session scratchpad; its decision ids M01–M47, C01–C08, D01–D11 are what the `source` tags in the strategy files point at).

Everything below describes the code on disk on 2026-09-27: `fz.py`, `fz_exec.py`, `fz_report.py`, `strategies/strategy_5.json`, `strategies/strategy_6.json`, the FZ parts of `lab.py` and `dashboard.tpl`, `tests/test_fz_parity.py` and the FZ cases in `tests/test_truncation.py`. `engine.py` was not changed.

---

## 1. What FZ is, in one paragraph

Foundation (`engine.py`) finds structure: swings, a protected level, a change of character (CHoCH), an AVWAP pair, a SETUP candle. It has no memory of price bands: for it, time is "bars since the last CHoCH". FZ adds that memory on top, without touching the engine. It keeps a set of 20-point price bands (zones), knows which band price is living in and for how long (a visit), speaks a one-word **read** for every bar (FIRST_PRINT, ACCEPTED, RECYCLE, THIN, HUNT, REJECT, LEAVE, PENDING, NEW), and at every Foundation SETUP decides **TAKE** (Foundation's own trade), **WATCH** (no trade now, wait for a leave of the band), **BLOCK** (no trade, no watch) or, from a watch, **REENTER** (a new position after a confirmed leave, with an extra exit when price reclaims the band). Strategy 5 is Strategy 1's rules (1 minute, previous-swing stop) through this gate; Strategy 6 is Strategy 2's rules (5 minutes, CHoCH-candle stop) through the same gate with 5-minute thresholds.

---

## 2. Architecture and the information rule

```
strategies/strategy_5.json ──► lab.load_strategies (validates entry_rule fz_v1 + fz block) ──► strategy row (fz_json)
                                                                                                    │
engine.load ──► bars ──► engine.run ──► r (swings, events, chs, prot, setups, trades)               │
                  │                        │                                                        │
                  │                        ├─ fz_exec.view(r): frozen view (swings, setups, chs, prot) ─────┐
                  │                        │                                                                │
                  ├─ fm_na per bar (front_month == 0 or volume == 0), atr14 (Wilder, futures bars)          │
                  ▼                        ▼                                                                ▼
              fz.run(bars, view, cfg, tf_min, s0, open_position) ──── card / zones / ledger / watches / decisions / stats
                  ▲                                                           │
                  │ exit bar or refusal reason only                           │
              fz_exec.opener(bars, r, sl_rule, touch)  ◄── TAKE: engine trade's exit; REENTER: fz_exec.simulate()
                                                                              │
              fz_exec.build_trades ──► FZ trade list in engine shape (TAKE = engine trade copied, REENTER = simulate())
                                                                              │
              lab.run_variant prices legs per choice (futures / options via futures) ──► fz_payload
                                                                              │
              fz_report: units, book, bridge, random_control, permutation_p, crosstabs, sample_flags
                                                                              │
              web/<code>/<run>/<choice>/summary.json['fz'], c<k>.json (Z, ZONES), fz_setup table,
              results/summary.json (fz_* columns), results/fz_setups.csv, results/fz_ledger.csv, dashboard.html
```

The one rule that shapes the module boundaries: **the gate may never learn how a ticket ended.** `fz.py` reads candles, the frozen engine view and the thresholds. It never imports `engine` or `lab`, never sees `exit_px`, `exit_reason`, `pts`, `net`, `mfe`, `mae`, a swing's `broken` flag or a CHoCH window's `end`. The only way it opens a position is the `open_position` callback, which answers with the bar the position ends on (so a later entry cannot overlap it) or a short refusal reason. `fz_exec.py` sees trade outcomes and prices nothing; `lab.py` prices; `fz_report.py` uses the Foundation outcome of refused SETUPs only after the gate has run, and only for diagnostics (the bridge, the random control, the permutation test). `tests/test_fz_parity.py` enforces the rule with a token scan of `fz.py` and by checking that the card is identical whether or not positions are opened.

---

## 3. The strategy files

`strategy_5.json` is `strategy_1.json` with `rules.entry_rule = "fz_v1"`, its own code, name and description, the 5-minute sibling backtest removed (it would be refused), the Unseen backtest note changed to say the window is not out of sample for FZ, and an `fz` block keyed by the design timeframe. `strategy_6.json` is the same on `strategy_2.json` (`sl_rule: choch_candle`, warm-up 5). The files carry five backtests each: All data (default), Design period (26 Aug–25 Sep), Unseen test (8 Jul–25 Aug), 1M, 3M (3M is refused on this tape for lack of data). A `position` block (`lots`, `lock`, `scale_out`) sits after `capital` with default values; it belongs to the lab's position-lock work, not to FZ.

### 3.1 The `fz` block

```json
"fz": { "minute": { "<key>": { "value": ..., "source": "spec:s2 | decision:n | evaluation:M-id", "statistic": "...", "note": "..." }, ... } }
```

`fz.thresholds()` reduces the block to `{key: value}` after checking that every key is an object with a `value` and a non-empty `source`; `fz.check()` then refuses a missing key, an unknown key, a wrong type or an out-of-range value. There are no defaults in code: 39 keys (the 33 below plus the six room-model keys of §19), all required in all four files. `load_strategies()` also refuses an `fz` block on a `setup_v1` file (it would be stored and hashed but never applied) and an `fz_v1` file without a block for its design timeframe.

| key | ST5 (1 min) | ST6 (5 min) | meaning |
|---|---|---|---|
| `band_half_width` | 10 | 10 | a zone is mid ± this; every zone is 20 points wide |
| `birth_a_source` | protected_level | protected_level | Birth A at protected levels (`every_swing` is a diagnostic alternative) |
| `birth_b` | band | band | cluster sits become zones (`flag` would only mark the card) |
| `cluster_bars` | 10 | 6 | closes in the cluster window |
| `cluster_width` | 20 | 20 | max − min of those closes |
| `merge_overlap` | 0.5 | 0.5 | a candidate overlapping a zone by at least half the width is absorbed |
| `zone_max_age_sessions` | null | null | chart view only: hide a band not visited for this many sessions; never deletes |
| `accept_bars` | 10 | 2 | bars a visit needs to read ACCEPTED |
| `accept_vol_ratio` | 0.8 | 0.8 | this visit's volume ≥ ratio × base visit's volume |
| `thin_ratio` | 0.5 | 0.5 | below this ratio a revisit reads THIN |
| `first_print_min_bars` | 3 | 3 | a FIRST_PRINT TAKE needs a visit at least this old |
| `hunt_form` | close | wick | 1 min: one close outside then back inside; 5 min: a wick pierce with closes inside |
| `hunt_max_bars` | 3 | 1 | bars between the pierce and the reclaim (inert under both forms, kept as the spec's number) |
| `hunt_min_depth_atr` | null | 0.5 | wick form only: pierce depth ≥ this × ATR14 |
| `hunt_burst` | 1.5 | 1.5 | pierce-bar volume ≥ this × the sit's per-bar mean; skipped when volume is NA |
| `reject_tol` | 2 | 2 | REJECT: wick within ± this of an edge |
| `leave_closes` | 2 | 2 | consecutive same-side closes outside that end a visit; also R2 |
| `leave_ttl_bars` | 15 | 3 | how long a LEAVE stays readable on the band just left |
| `leave_far_side` | block_list | block_list | what a LEAVE may enter: `any`, `block_list`, `no_band` (see §8) |
| `fade_block_bars` | 15 | 3 | BLOCK a SETUP that chases a HUNT completed within this many bars |
| `fade_scope` | ref_band | ref_band | which bands the fade block looks at (`any_band` alternative) |
| `defend_window_bars` | 15 | 3 | a defend TAKE needs a HUNT/REJECT at the opposite edge within this window |
| `open_bars` | 10 | 2 | the open guard applies on the first this-many bars of a session |
| `open_quiet_bars` | 10 | 2 | a gap LEAVE cannot TAKE before this many bars into the session |
| `open_sit_closes` | 3 | 3 | the open guard fires on a band with fewer than this many closes inside today |
| `open_window_until` | 09:25 | 09:25 | open guard clock (bar open time) |
| `no_entry_from` | 15:20 | 15:20 | no new TAKE or REENTER from this bar open time on |
| `cancel_inside_bars` | 5 | 1 | an ARMED watch is cancelled after this many consecutive closes back inside |
| `edge_watch` | ref_band | ref_band | a breakout-bar SETUP watches the band just left (`containing_band` alternative) |
| `volume_base` | first | first | volume ratios compare with the first visit (`previous` alternative) |
| `reenter_fill` | confirm_bar | confirm_bar | REENTER fills on the bar R1–R5 all hold |
| `control_draws` | 2000 | 2000 | random-control and permutation draws (report only) |
| `control_seed` | fz | fz | seed prefix (report only) |

The `source` tags say where each number came from; the `statistic` field records the tape statistic it was read from when it was not in the spec. Changing a value is an edit of the file; the lab's cache key hashes the row, so the affected FZ rows recompute on the next run (about five minutes) and nothing else does.

---

## 4. Zones: the band memory

A zone is an immutable band `[mid − half_width, mid + half_width]` with an id, a kind (A or B), an origin bar, a birth bar, a merge counter, a visit list and the edge-event memory (`hunt_at/dir`, `reject_at/dir`, `leave_failed`). Edges are inclusive with a float tolerance (`EPS = 1e-6`). Zones are never deleted and edges never move.

**Birth A, protected levels.** On every bar, the swings confirmed by that bar are added to a `latest` map keyed by price. When `prot[i]` (the engine's protected level per bar) takes a new value, the swing at that price is the candidate: mid = the swing price, origin = the swing bar, id = `A` + the swing's confirmation timestamp. A swing is born at most once; a revert of the protected level to an already-born swing is not a birth. With `birth_a_source = every_swing` every confirmed swing is a candidate instead (diagnostic only; not seeded).

**Birth B, cluster sits.** The condition on bar i: the last `cluster_bars` closes are in the same session and their range is at most `cluster_width`. On the transition into that state (false on i−1, true on i) the candidate is mid = (max + min)/2, origin = the window's first bar, id = `B` + the bar timestamp. While the condition stays true, a new candidate is raised only when the drifted mid cannot be absorbed by any zone (a *drift birth*, counted separately and not counted as a merge). With `birth_b = flag` no zone is born; the card only carries `cluster_sit`.

**Merge, absorb.** A candidate whose overlap with an existing zone is at least `merge_overlap` × width is absorbed into the zone with the largest overlap (equal overlap: nearest mid, then the older zone). The survivor is unchanged in every way; the candidate leaves only a merge count. Birth A candidates are processed before Birth B on the same bar.

**Visit backfill at birth.** A new zone replays its own visit history over the closes before its birth bar, using the visit rule of §5 on that zone alone: from the start of the run of consecutive inside closes that contains the origin (Birth A, when the origin close is inside), otherwise from the origin. Only past bars are read, so this is truncation-safe; cards written for earlier bars are never changed. If the replayed visit is still open at birth and another band already holds the live visit, the replayed visit is closed at bar i−1 with `ended_by = ref_live` (one live visit at a time); in open ground it becomes the live visit.

**No ageing.** `zone_max_age_sessions` never changes the card. A number there only hides a band not visited for that many sessions from the chart's nearest-band fill (lab side).

---

## 5. Visits, the ref band, PENDING and LEAVE

**One live visit at a time.** The zone holding the live visit is the *ref band*. A visit ends only on the `leave_closes`-th consecutive close outside the band on the same side (`ended_by = left`). A single outside close does not end it, even when that close is inside a neighbouring band; the card reads PENDING on such a bar. The outside run (`out_run`, `out_side`) resets on a close back inside and restarts at 1 on a close on the other side. A visit's `bars` and `vol` count its inside closes only.

**When a visit ends,** the leave is recorded on the band left: its side, the R1 bar, the far-side volume and bar count, whether any far-side bar is volume-NA, the sit's per-bar mean volume, and its kind: `gap` when a session's first bar is among the outside closes, else `normal`. The ref band becomes none.

**A LEAVE lives** while no close comes back inside the band left, no close crosses that band's mid, and fewer than `leave_ttl_bars` bars have passed since the visit ended (it reads on the leave bar and the next `leave_ttl_bars − 1` bars; the bar `leave_ttl_bars` after the leave bar ends it). A close back inside ends the LEAVE, sets the band's `leave_failed`, and hands the live visit back to that band as visit n+1 *if no other band holds the live visit* (the D01 tie-break; otherwise the neighbour keeps the visit and the bar is counted as `leave_return_no_visit`). A close across the mid or the ttl ends the LEAVE without a return. Every further far-side bar adds to the leave's far-side volume; a session's first bar turns the kind to `gap`.

**No live visit** (start of memory, after a leave into open ground, after a LEAVE ended): the band containing the close opens a visit on that bar (nearest mid among containing bands, ties to the older zone; a return into the band just left takes it back first). `entry_dir` of the visit is the direction of the close relative to the previous bar.

---

## 6. Edge events: HUNT and REJECT

Both are read on the ref band, only on a bar whose close is inside it (`out_run == 0`), and stored on the band as `hunt_at/dir` and `reject_at/dir`.

**HUNT** (`hunt_form = close`, 1 min): the previous bar was exactly one close outside this band and this close is back inside; the pierce side is the side of that outside close. (`hunt_form = wick`, 5 min): the previous close and this close are inside and the bar's wick reaches beyond an edge by at least `hunt_min_depth_atr × ATR14`; the pierce side is the deeper wick. In both forms the pierce must be within `hunt_max_bars` of the reclaim (always true under the seeded forms) and, when the sit's volume is live, the pierce bar's volume must be at least `hunt_burst` × the sit's per-bar mean (`hunt_no_burst` is counted when it fails; with NA volume the burst test is skipped).

**REJECT** (only when no HUNT on this bar): the previous close was inside, the bar's wick lies within ± `reject_tol` of an edge (not beyond it by more), and the close is nearer the mid than the open. The edge is the one the wick reaches further towards.

The card's `wick_depth` is the deepest wick beyond either edge of the ref band (0 when none) on every bar whose close is inside it, event or not; a wick beyond an edge by more than `reject_tol` that does not qualify as a HUNT shows there with no edge event (the documented "shallow pierce" class).

**One slot per event kind.** A band remembers only its latest HUNT (`hunt_at/dir`) and its latest REJECT (`reject_at/dir`); a later event of the same kind overwrites the earlier one, whatever its direction. The `hunt_fade` block and the defend branch (§8) read these slots, so an earlier HUNT or REJECT that a later one overwrote does not count (S44 in `docs/STRATEGY_ANALYSIS_TODO.md`).

---

## 7. The card

One row per bar, computed as of that bar and never rewritten. Fields: `zone_id` (the ref band), `visit_n`, `this_bars`, `this_vol`, `vol_na`, `first_bars`, `first_vol`, `first_vol_na`, `read`, `left_id` (the band whose LEAVE is live), `out_run`, `out_side`, `session_bar`, `gap_pts`, `wick_depth`, `last_hunt_at/dir`, `last_reject_at/dir`, `cluster_sit`, `prev_bars`, `prev_vol`, `last_leave_failed`, `in_id` (the band containing the close, nearest mid), `leave_side`, `leave_vol_ok`, `leave_kind`, `first_clock_lived`.

**Read precedence.** LEAVE (a LEAVE is live on `left_id`) → HUNT → REJECT → the inside read of the ref band's visit when the close is inside it → PENDING (the close is outside the ref band, visit still live) → NEW (no ref band).

**Inside reads.** Visit 1 reads FIRST_PRINT (`first_clock_lived` says whether it has lasted `accept_bars`). On a revisit, with B = the base visit (`volume_base`: the first visit, or the previous one): ACCEPTED when `this_bars ≥ accept_bars` and (volume is NA on either side, or `this_vol ≥ accept_vol_ratio × B.vol`); else THIN when volume is live and `this_vol < thin_ratio × B.vol`; else RECYCLE.

**Volume NA.** A bar is NA when its session is not the front month (`front_month == 0` in the 1-minute file) or its volume is 0. A visit is NA if any of its bars is; the first visit's NA flag never changes. NA makes ACCEPTED time-only, THIN unavailable, the HUNT burst skipped and R4 skipped. Because `fm_na` folds the front-month flag in, two visits with live volume are always in the same volume regime, so a cross-regime ratio cannot be computed by construction.

`leave_vol_ok` (the R4 of a LEAVE read): per-bar mean volume of the far-side closes since R1 ≥ the sit's per-bar mean; `null` when either side is NA; re-evaluated on every far-side bar.

---

## 8. The gate at a Foundation SETUP

Evaluated on the SETUP bar k with direction S, after the watch step of that bar. The ledger row is created first with the card's columns; on a LEAVE read it also records the entered band (`entered_zone_id`, `entered_visit_n`, `entered_read` = that band's read as if it were the ref band).

1. **A REENTER already decided on this bar** by the watch step (R5 satisfied on the SETUP bar itself) makes the row `REENTER` with branch `watch`.
2. **Hard BLOCK**, in this order, no watch opened and any existing watch untouched: `in_position` (an FZ position is open on this bar), `clock` (bar open time ≥ `no_entry_from`), `open_pierce` (within the session's first `open_bars` bars and before `open_window_until`, the bar's range crosses an edge of a band whose last visit ended in an earlier session and that has fewer than `open_sit_closes` closes inside today), `hunt_fade` (the latest HUNT of the ref band or of the band just left, or of any band under `fade_scope = any_band`, is in S's direction, completed within `fade_block_bars`, same session), `new` (the read is NEW).
3. **TAKE branches**, the first that holds:
   - **leave**: read LEAVE, S equals the leave side, `leave_vol_ok` is not False, not a gap LEAVE inside the first `open_quiet_bars` bars, and `leave_far_side`: `any` accepts; `block_list` refuses when the entered band reads RECYCLE, THIN, HUNT or REJECT (`block_reason = leave_into_recycle`); `no_band` refuses whenever a band contains the close (`leave_into_band`). A refusal records `take_why` and falls through to WATCH.
   - **first_print**: read FIRST_PRINT, the visit is at least `first_print_min_bars` old, S equals the visit's `entry_dir`.
   - **defend**: read ACCEPTED and the ref band's latest HUNT or latest REJECT (one slot each, §6) fell in this visit, within `defend_window_bars`, at the edge S points away from.
   - A **leave** TAKE of the band a watch waits on, in the watch's direction, is that watch's REENTER instead (branch `leave`, `reenter_reason = take_on_watch:leave`); a first_print or defend TAKE stays Foundation's own position and leaves the watch as it is.
   - A TAKE calls `open_position('TAKE')`; the engine may have skipped the SETUP for a wrong-side stop, in which case the row records `refused` and no position opens. An opposite-direction TAKE ends an open watch (`opposite_take`). A converted (branch-1) REENTER that the callback refuses keeps `gate = REENTER` with `refused` set and no position, and its `outcome_gate` is then REENTER too; this has not occurred on the tape (0 rows in all four strategies), and what it should become is open (S44 b).
4. **WATCH_EDGE**: `edge_watch = ref_band`, the read is PENDING, the previous close was inside the ref band and S is the side the close is on: a watch on the ref band that is already armed (this bar is R1).
5. **WATCH**: a band contains the close: a watch on that band with `dir = S`, not armed.
6. **BLOCK `new`** otherwise.

One watch at a time: a later SETUP that opens a watch replaces the current one (`outcome = replaced`); a BLOCKed SETUP leaves it untouched. `gate` on the row is the decision as of the SETUP bar (what the truncation test compares); `outcome_gate` is how the SETUP ended (REENTER when a later REENTER used this SETUP as its R5), and the tables and headline counts use `outcome_gate`.

---

## 9. The watch machine

A watch pins a snapshot of its band (edges, mid, the sit's per-bar mean volume) and runs once per bar before the gate, from the bar after it opened.

- **Cancels**, checked first: the first bar of a new session (`session_end`); `leave_closes` consecutive closes beyond the band on the side opposite to the watch direction (`opposite_leave`); from ARMED, `cancel_inside_bars` consecutive closes back inside (`back_inside`). An opposite TAKE cancels from the gate (`opposite_take`).
- **R1**: a close beyond the band on the watch's side arms the watch (`armed_at`; `first_armed_at` on the first arming). A close back inside breaks the far-side run; the next far-side close arms again (R1 again), so R3 (no close inside or across the mid since R1) holds by construction on the unbroken run. The ledger reports both `armed_bars` (from the first arming) and `rearmed_bars` (from the latest).
- **R2**: `leave_closes` consecutive far-side closes. **R4**: per-bar mean volume of the far-side run ≥ the pinned sit mean, skipped (None) when the run or the sit is volume-NA. `r4_bars_evaluated / fail / na` are counted per window.
- **R5**: a Foundation SETUP in the watch direction on this bar or on the previous bar of the same session.
- **REENTER** on the first bar j where R1–R5 hold, unless the bar's open time is at or past `no_entry_from` (`clock_1520` counted, watch stays armed) or a position is open (`reenter_in_position`). The callback prices nothing back; it may refuse (`wrong_side_stop`, `sl_dead_at_fill`), counted as `reenter_refused`, the watch continues. On success the row of the R5 SETUP gets `fill_bar`, `fill_used` (`setup_close` when j is the SETUP bar, else `reenter_close`), `fill_delay_bars`, `edge_dist_pts`, `armed_bars`, `rearmed_bars`, `reenter_reason` and `outcome_gate = REENTER`.
- **Outcomes** in the watch log: `reenter`, `replaced`, `cancelled:<reason>` (never armed) or `armed_expired:<reason>` (armed), `active` at the data end. `no_same_dir_setup` counts armed watches that expired with R1–R4 satisfied on their last bar.

Position lifetime is entry bar ≤ k < exit bar, so a SETUP on a position's exit bar may open a new one at that bar's close; `build_trades` asserts that no two FZ positions overlap under that convention.

---

## 10. Execution: `fz_exec.py`

- `view(r)`: the frozen view: swings as (kind, bar, price, conf), setups as (bar, dir, CHoCH bar), CHoCHs as (bar, dir, level), the protected level per bar. Nothing final-state.
- `stops(bars, swings, sl_rule)`: the Foundation stop rule at any bar: `prev_swing` = the latest confirmed swing low (long) or high (short) with conf ≤ bar; `choch_candle` = the CHoCH candle's low/high.
- `refusal(...)`: `wrong_side_stop` (the engine's own skip: the stop is not on the loss side of the entry close) and, for REENTER, `sl_dead_at_fill` (the entry candle already traded through the stop).
- `simulate(bars, entry, dir, sl, chi, touch, band, choch, dead)`: the engine's trade loop restated statement for statement: exit at the stop on any later candle (touch mode: the worse of the candle open and the stop; a session's first candle: its close; close mode: the close), else at the close of the first CHoCH after the entry, else open at the last candle. With a band (REENTER), a close on the band side of the band's mid (long: below it; short: above it) exits at that close with reason `band_reclaim`, checked after the stop and before the CHoCH exit on the same candle.
- `opener(...)`: the `open_position` callback. TAKE returns the engine trade's exit bar for that SETUP (or `wrong_side_stop` when the engine skipped it). REENTER evaluates the stop rule at the fill bar, refuses if needed, else runs `simulate()` and returns its exit bar.
- `build_trades(...)`: the FZ trade list in engine shape, sorted by entry. TAKE rows are the engine's trade dicts copied and annotated (`gate`, `zone_id`, `fill_used`, `reenter_reason`); REENTER rows come from `simulate()` at the fill bar with `setup_i`, `sl_bar` (`setup` when the stop at the fill bar equals the SETUP-bar stop, else `fill`) and `sl_in_band`. It asserts that `fz.run` and `simulate()` agree on every REENTER and that positions do not overlap.

`tests/test_fz_parity.py` runs `simulate()` on every Foundation SETUP with the engine's own stop and requires every Foundation trade back field for field (207 of 207 on 1 min, 73 of 73 on 5 min) before any REENTER row is trusted.

---

## 11. Lab integration: `lab.py`

- **Loading.** `entry_rule` must be `setup_v1`, `fz_v1` or `fz_v2` (§19; every `fz*` rule runs the same FZ path). An `fz*` file needs an `fz` block for its design timeframe, validated by `fz.thresholds()`; an `fz` block on a `setup_v1` file is refused. `type_rows()` copies the block verbatim into a new `strategy.fz_json` column (added by `migrate()`, together with `trade.gate / reenter_reason / zone_id / fill_used` and the `fz_setup` table).
- **Front month.** `fm_by_day()` reads `front_month` per session from the 1-minute futures file (cached like `sessions()`); `fm_na` per bar is `front_month == 0 or volume == 0`.
- **Memory starts at the file.** For FZ rows `main()` sets the engine warm-up to every session before the window, so the band memory begins at the data file's first session and the Design, Unseen and 1M windows are exact date slices of the All-data run (`info.memory_start`, `info.same_sample = file_start`; Foundation rows keep their own warm-up, `own_warmup`). `resolve_backtest` still refuses a window using the strategy's own `warmup_days`. A backtest on a timeframe with no `fz` block is refused with a reason; an FZ row of type Options (standalone) is refused with `FZ thresholds are futures points; no native-option unit rule in v1`.
- **`run_fz(st, fut, s0, r)`.** Builds `fm_na` and `atr14` (Wilder ATR on the futures bars, seeded like `atr_series`), the frozen view and the callback, runs `fz.run`, builds the FZ trades, exits with an error if the ledger has no WATCH or BLOCK and the trades equal Foundation's (an FZ row must never be Foundation reported under an FZ code), runs the gate a second time with volume NA on every bar (the all-NA comparator), and computes the window's cross-tabs.
- **`run_variant`.** For FZ rows the FZ trade list replaces `r["trades"]` before the pricing loop, so the futures book and the options-via-futures book are priced from FZ's positions by the existing code; the engine's own trades are priced too, tagged `RAW`, for the bridge. Trade records carry `gate`, `reenter_reason`, `zone_id`, `fill_used`, written at indices 25–28 of the stored trade arrays and into the `trade` table (non-FZ rows carry None there; indices 29–30 are `lots` and `tranche` from the position-lock work).
- **`fz_payload`.** Per priced choice, `summary.json['fz']` holds: `fz_hash`, `memory_start`, `window_start`, `same_sample`, the thresholds, the headline (SETUPs; TAKE / WATCH / BLOCK / REENTER by `outcome_gate` and `at_setup`; positions; priced positions; control percentile; permutation p; active sessions; sample flag), the cross-tabs, the raw counters, the bridge, the control, the permutation, both books, the sample flags, the all-NA comparator, the ledger (`{cols, rows}`, with the diagnostic join added here: `fnd_*` = the Foundation outcome of the SETUP, `fz_*` = the FZ position it opened), the watch log and a legend of every compact array.
- **Chart chunks.** `fz_chart()` adds to every futures session chunk `Z` (one row per bar: time, zone_id, visit_n, this_bars, this_vol, first_bars, first_vol, read code, left_id, out_run, vol_na, gap_pts, session_bar, wick_depth, in_id, first_vol_na, read from the as-of card, never from the final zone list) and `ZONES` (every band holding a close of the chunk, every band a Z row names, plus the three bands nearest the chunk's first close: id, kind, lo, hi, born time).
- **Persistence.** `save_run` writes one `fz_setup` row per ledger row and puts `fz_json`, `fz_hash` and the warm-up into `params_json`; `write_result` adds `fz` and `fz_hash` to `summary.json`. `results/summary.json` rows gain `fz_take`, `fz_watch`, `fz_block`, `fz_reenter` (by outcome), `fz_reenter_at_setup`, `fz_take_trades`, `fz_reenter_trades`, `fz_priced`, `control_pct`, `perm_p`, `active_sessions`, `fz_sessions`, `fz_hash`. `results/fz_setups.csv` (one row per ledger row) and `results/fz_ledger.csv` (every table flattened to table / row / col / value) are written for the futures rows and the default option choice, on full runs only.
- **Cache and identity.** `cache_key` hashes `fz.py`, `fz_exec.py`, `fz_report.py` and the 1-minute file for FZ rows only, so an FZ edit recomputes FZ rows and nothing else; `fz_hash` (sha1 of the three modules) is stored beside every result. `lab.py` itself is hashed minus the cache-exempt functions (`CACHE_EXEMPT`: `main`, `add_backtest`, `load_strategies`, `type_rows`, `sync`, `connect`, `migrate`, `save_run`, `cache_key`, `code_hash`, `record_history`, `def_view`, `flat`, `fz_flat`, `slug`), so an edit confined to those does not recompute stored rows; any other line of `lab.py`, even a blank one, does. The group-run key includes `entry_rule`.
- **Guards.** A filtered run (`python lab.py ST5 ST6`) computes but does not rewrite `dashboard.html` or `results/*` (it prints `partial run ... not rebuilt`); the `backtest` subcommand appends to the strategy file and then runs unfiltered with stored results reused.

---

## 12. Reporting: `fz_report.py`

Pure functions over the ledger, the watch log, the priced positions and the card of one window.

- `units(legs, lot, slippage)`: one record per position (legs summed): net, gross, charges, slippage paid, open flag, entry and exit day.
- `book(units, lot)`: n, net, mean, sd, wins, PF, per-trade t and **per-session t**, sessions and weeks, net with and without positions still open, and the t-based confidence half-width on expectancy in rupees and points (a stdlib Student-t quantile).
- `sample_flags(...)`: n < 10 → PF and t not reported; 10 ≤ n < 30 → indicative, printed with the CI; fewer than 4 weeks with a trade → week stats suppressed; fewer than 10 active sessions → Sharpe and Calmar suppressed.
- `bridge(raw, fz)`: Foundation net + avoided price move of the Foundation positions FZ did not hold + avoided charges and slippage of those + REENTER exit delta (a REENTER replacing Foundation's trade on the same SETUP) + REENTER new (a REENTER with no Foundation trade of its own) = FZ net, asserted to close. A TAKE is Foundation's own position and is not bridged. Cost savings are reported but never counted as edge.
- `random_control(raw, fz, draws, seed, tag)`: the session-matched random gate: every draw keeps, in each session, as many Foundation positions drawn without replacement as FZ held that session; returns the 5/50/95 percentiles, FZ's percentile among the draws and `p_beat`. Draw d is seeded `random.Random(f"{seed}|{tag}|{k}|{d}")`, so every number reproduces.
- `permutation_p(kept, refused, ...)`: kept = Foundation's trades on the SETUPs FZ held a position on (a TAKE, or a REENTER on that SETUP, on its own bar or later), refused = the rest; two-sided permutation p of the difference of means.
- `crosstabs(...)`: gate × read (BLOCK split by reason; WATCH rows that fell through a refused LEAVE by reason), gate by hour bin (edges from the clock keys), by visit_n, by direction, by zone kind, reads at SETUP, ACCEPTED on revisits, ACCEPTED time-only, volume-NA counts, R4 evaluated / failed / NA, the branch-1 split (far side in no band vs inside a band, with that band's visit_n and read) and the counts each `leave_far_side` option would admit, watch kinds and outcomes with `armed_expired` by reason and the median bars armed, REENTER exits and fills, active sessions and dormant stretches, and card statistics (share of bars inside a band, reads per bar, births and merges since memory start).

---

## 13. Dashboard: `dashboard.tpl`

- `merge()` concatenates `Z` and unions `ZONES` by id across chunks; option chunks have neither. A room id (v2) gets the end time of the last merged chunk that lists it, so a room retired in the window is not drawn on past it in a multi-session view (base ids keep none).
- `drawChart()`: a *Zones* layer (chip shown only when the chunk has zones): one baseline series per band from `max(born, first bar)` to the last bar (a room: to that end time), filled between lo and hi, off the autoscale; A bands in the chart purple, B bands in the chart blue, made translucent by a tint helper (no new colour literals). The crosshair line appends the card: `Z <kind><mm-dd hh:mm> lo–hi · visit n · this/first bars · vol ratio or NA · READ [from <left band>]`. Gate markers T / W / B / R at SETUP times (and an R at a later fill bar), toggled with the Trades chip.
- `band_reclaim` in the three exit-reason maps (trades table pill `Band`, breakdown `Band reclaim`, marker prefix `BAND`).
- The **Zone gate** tab (`renderFZ`): KPI tiles with the control percentile and permutation p beside net, gate × read, watches, positions, the three `leave_far_side` counts, volume NA and R4 with the all-NA comparator, the bridge, the random control and the permutation, both books with sample flags, active sessions and dormant stretches, gate by hour / visit / direction / zone kind, card statistics, and the ledger table with a gate filter; a row click opens that session's futures chart at the SETUP (`openAt`). For a non-FZ strategy the tab shows a hint. The KPI strip above the tabs also shows the control percentile and permutation p for FZ rows.
- Signals shows Read and Gate columns joined on the SETUP time; Config prints every `fz` key with value, source, statistic and note plus `fz_hash`, memory start and `same_sample`; Rules has a fifth static card, *Foundation-Zone (Strategies 5–8)*, bands and rooms. Profit-and-loss figures use the page's `.pos` / `.neg` classes, which follow the colour palette.

---

## 14. Tests

`tests/test_fz_parity.py` (about six seconds):
1. `simulate()` on every Foundation SETUP with the engine's own stop reproduces `engine.run()`'s trades field for field and refuses exactly the SETUPs the engine skipped, on both files over the lab's all-data windows.
2. `fz.py` never names a trade-outcome field, a swing's `broken` flag or the engine's `["end"]`, and imports neither `engine` nor `lab`.
3. `fz.run()` with a callback that refuses every position produces the same card as the real run; the ledger's card columns match and gates differ only on rows touched by `in_position` or a REENTER.
4. Every key of every strategy file's `fz` block has a value and a source, the blocks of one family share one key set, and `fz.thresholds()` refuses a missing key, an unknown key and an unsourced key.
5. No REENTER fills on a close inside its band, a TAKE becomes a REENTER only on branch 1, and every REENTER position's SETUP row ends with `outcome_gate = REENTER`.

`tests/test_truncation.py` (about four minutes) keeps the six engine cases and adds two FZ cases (ST5 on 1 min, ST6 on 5 min, touch mode, the lab's own warm-ups). `fz_decisions()` compares, before each cut, the card rows, the ledger rows (zone_id, read, gate, block_reason for SETUPs before the cut), the watch transitions and the closed FZ positions. Cuts are 12 uniform plus up to 24 targeted at one to five bars after a SETUP and inside WATCH / ARMED windows, because Foundation 1 min is dormant after 4 Sep and uniform cuts mostly land where nothing is live. A mutation check during the build (a non-causal ATR injected) failed 34 of 36 cuts, so the comparison does catch look-ahead.

---

## 15. Running it

```bash
cd research/strategy_lab && python tests/test_fz_parity.py
```

```bash
cd research/strategy_lab && python tests/test_truncation.py
```

```bash
cd research/strategy_lab && python lab.py ST5 ST6
```

```bash
cd research/strategy_lab && python lab.py
```

- A plain run reuses every stored result (about 20 seconds when nothing changed) and rebuilds `dashboard.html` and `results/`.
- Editing `fz.py`, `fz_exec.py` or `fz_report.py`, or a value in an `fz` block, recomputes only the FZ rows (about five minutes). Editing `lab.py` outside its cache-exempt functions invalidates every stored result; the full recompute of ST1 to ST6 with all option choices takes 45 minutes to 3 hours. `lab.py` holds `cache/lab.lock` while it runs, so two runs never overlap, and `serve.py` queues runs started from the dashboard. `results/history/<CODE>.json` keeps one headline version per change of a strategy's definition or result code, so a before-and-after comes for free.
- Never commit `results/` after a filtered run; the filtered run does not rebuild them, but the next plain run does.
- Serve the dashboard with `python -m http.server 8766` in `research/strategy_lab` and open `dashboard.html`.

---

## 16. First results (seeded rules)

| Window | ST5 positions (TAKE + REENTER) of SETUPs | ST5 net vs Foundation | ST5 control percentile · permutation p | ST6 positions | ST6 net vs Foundation | ST6 percentile · p |
|---|---|---|---|---|---|---|
| All data | 29 + 22 of 207 | −81,023 vs −216,468 | 6.2th · 0.44 | 14 + 12 of 73 | −52,261 vs −73,753 | 49.8th · 0.18 |
| Design period | 4 + 6 of 55 | −14,337 vs −16,985 | 37.0th · 0.62 | 1 + 5 of 26 | −4,368 vs −15,560 | 42.1th · 0.97 |
| Unseen test | 25 + 16 of 152 | −66,686 vs −197,287 | 6.5th · 0.54 | 13 + 7 of 47 | −47,893 vs −56,783 | 80.6th · 0.08 |

The 1-minute bridge on all data: Foundation −216,468; avoided price move of the 156 positions FZ did not hold −37,160; avoided charges and slippage of those +173,698; REENTER delta over 22 positions −1,091; FZ −81,023. The higher net is cost avoidance. Against a control that keeps the same number of Foundation trades per session at random, ST5 sits at the 6th percentile, so random selection did better; on 5 minutes the SETUPs FZ traded had worse Foundation outcomes than the ones it refused. Under the seeded `block_list` the 1-minute branch-1 TAKE count is 10; `any` would give 65 and `no_band` 4. The REENTER book is 22 on 1 minute with `edge_watch = ref_band` and would be about 4 with `containing_band`. These are the numbers filed as S39 in `docs/STRATEGY_ANALYSIS_TODO.md`.

Pre-registered expectations versus the first run: LEAVE is the most common read (44% of 1-minute bars, as expected); NEW is rare (0.4%); FIRST_PRINT at SETUP is 0 (as expected); visit_n at SETUP came out at a median of 19 against an expected ~30, because the evaluation's simulator ended a visit on the first close into a neighbouring band and the built rule does not.

---

## 17. What is still a user decision

Recorded in `docs/STRATEGY_ANALYSIS_TODO.md`; no seeded value changes without confirmation and a before-and-after rerun of the same windows.

- **S35 `leave_far_side`**: what a LEAVE may enter. `any` is a momentum entry into the next room, `block_list` (seeded) refuses recycles, `no_band` allows leaves into open ground only.
- **S36 Birth B** as a band source: under protected-level Birth A, cluster bands are 70–77% of SETUP zones; the alternative is `birth_b = flag`.
- **S40 a–d**: a gap LEAVE re-meeting R2 after the quiet bars; a strict R3 (no REENTER after any close back inside); the visit rule when price returns into a band just left while a neighbour holds the visit (D01, as built) versus reopening visit n+1 on the returned band; whether a same-direction FIRST_PRINT or defend TAKE should end a watch.
- **S44 a–b**: whether `hunt_fade` and the defend branch read only a band's latest HUNT / REJECT (as built) or any event in the window (ST5 1 SETUP, ST7 4 SETUPs differ); what a converted REENTER the callback refuses should become (latent, 0 rows).
- **Named variants, not v1**: `FZ1_v1_1` (fill on the R1–R4 bar without a Foundation SETUP), `edge_watch = containing_band`, `volume_base = previous`, `fade_scope = any_band`, `birth_a_source = every_swing`.
- **Out of sample**: the Unseen window was used for threshold selection, so the first genuine out-of-sample check is the sessions from 2026-09-28 on, run once with the frozen files and published whatever it shows.

---

## 18. Conventions and gotchas

- All durations are bars, counted across the overnight break; a visit inside at a session's last bar continues at the next session's first bar. Clock rules compare the bar's **open-time** label with `no_entry_from` and `open_window_until`.
- Band edges are inclusive with `EPS = 1e-6`; mids are rounded to four decimals at birth and never move.
- A zone's id is `A` + the swing's confirmation timestamp or `B` + the birth bar's timestamp, so ids are stable across runs and cuts.
- `gate` is as of the SETUP bar and is what the truncation test compares; `outcome_gate` is how the SETUP ended and is what the tables count. `fz_reenter` in `results/summary.json` counts SETUPs that ended as REENTER; `fz_reenter_at_setup` those gated REENTER on their own bar; `fz_reenter_trades` the positions.
- The options-via-futures rows of ST5 and ST6 price FZ's positions with the same strike and expiry rules as ST1 and ST2; the options-standalone rows are refused.
- The Foundation book FZ is compared with comes from the same file-start run, so ST5's Unseen Foundation comparator (152 trades) differs from ST1's own Unseen run (146 trades): the ST1 and ST2 cards are independent runs with their own warm-up, badged `own_warmup`.
- `hunt_max_bars` cannot bind under either seeded HUNT form; it is kept as the spec's number and documented as reserved.
- The pricing loop enforces one open position per option instrument (strike, expiry, right), processing exits before entries; a skipped leg goes to `skipped` with a `strike locked` reason and is never priced. FZ never holds two futures positions at once, so the lock can only touch an option leg entered on the exact bar another leg on the same strike exits.
- The 1M preset resolves to the same dates as the Design period on this tape; both rows are published with the same positions and net, and their control percentiles and permutation p differ only through the run label in the seeds.

---

## 19. v2: rooms (Strategies 7, 8)

**Why.** The user's verdict on the base (2026-09-27): the card named tiles, not rooms. Zones were born at every protected level and every cluster sit, absorbed into a permanent 20-point mesh and never retired, so on 3 Sep the card said `B07-23 14:52 visit 7` (and `B07-02 10:31 visit 51` elsewhere) where the user saw one afternoon box; every LEAVE was a step from tile A into tile B; the first clock was a July sit, so the volume ratio was NA on the only window with volume; REENTER fired on tile edges. Median visit_n at a 1m SETUP was 19, FIRST_PRINT at SETUP 0, and the gate sat at the 6th percentile of its random control (S39). v2 changes identity only: what a room is, when it is born, when it dies, what it is called. Reads, precedence, PENDING, LEAVE liveness, REJECT, the gate's order and branches, `leave_far_side`, the watch machine, `fz_exec` and `fz_report` are the same code. Recorded as S42 in `docs/STRATEGY_ANALYSIS_TODO.md`.

**Room model** (`room_model = "rooms"`, in `fz.py` next to the band model; `bands` is the base):

1. **Birth only from sits.** A room is born on the transition into a sit (the last `cluster_bars` closes of one session within `cluster_width`), centred on the sit's `(max + min) / 2`, ± `band_half_width`, origin = the sit's first bar; visit 1 is that sit, replayed over the window only. No drift births (`drift_birth = false`) and no swing births (`birth_a_source = "none"`; `protected_level` / `every_swing` still work in either model, as diagnostics).
2. **No mesh.** A sit overlapping a live room by at least `merge_overlap` of the width (with 0.5: its mid is inside the room) is a visit of that room, never a birth; it takes the live visit when its close is inside that room (below). Two live rooms never overlap (a shared edge is allowed). A sit that overlaps live rooms by less than `merge_overlap` is a new room, and `room_overlap` says how the overlap is removed: **`supersede`** (seeded): the new room keeps its full width and the rooms it overlaps are retired on its birth bar (`retired_by = superseded`); `clip`: the new room's edges stop at the neighbours' edges. Retired rooms absorb nothing and contain no price.
3. **Rooms retire.** On a session's first bar, a room with no inside close in the last `room_max_age_sessions` sessions (`session - last session with an inside close > room_max_age_sessions`) is retired (`retired_by = retired`), unless it holds the live visit. A new sit at a retired room's price is a new room with a new name and its own first clock. A LEAVE still live on a room that retires ends (`leave_end_retired`).
4. **Names.** `zone_id = "<letter> <mm-dd hh:mm>"`: the letter is the room's birth order within its birth session (A … Z, then AA, AB …), the time its birth bar. Rooms keep `kind = "B"` (sit-born; `A` only under a swing `birth_a_source`), so the Zone-gate tab's zone-kind table and the chart colours work unchanged.
5. **Visits and touches.** A stay with fewer than `visit_min_bars` inside closes that ends by the leave rule is a *touch*: it keeps its record (`touch: true`), does not advance `visit_n`, and is counted on the room and on the card (`touches`). Visit numbers are as-of: the current stay counts as a visit while it lasts. The first visit (`first_bars`, `first_vol`) and the previous visit (`volume_base = previous`, `prev_bars`) are the first / previous stay that is not a touch. With `visit_min_bars = 1` no stay can be a touch (a stay opens on an inside close), which is how the base stays unchanged.
6. **The live visit follows the sit.** When a room is born, or a sit is absorbed by a live room, while another room holds the live visit and the sit's close is inside the new (or absorbing) room, the old visit ends at the previous bar (`ended_by = sit_moved`, no LEAVE is recorded) and the room the market sits in takes the visit (the base instead cuts the newborn zone's replayed visit, `ref_live`). A room retired by supersession while it holds the visit with no room taking over ends its visit with `ended_by = superseded`.
7. **Leave and hunt.** `leave_closes` 1m 3, 5m 2 (so HUNT and LEAVE do not overlap on 1m). The close-form HUNT is `1 ≤ outside run ≤ hunt_max_bars` closes on one side, then a close back inside (the base only ever had a run of 1); the burst test takes the loudest of those outside bars and is skipped when any of them is volume-NA (identical to the base for a run of 1). The 5m wick form is unchanged.
8. **First clock and volume** come from visit 1 of this room, born in the memory horizon, so on the Design window they are live; NA handling is unchanged.

**Keys** (all four files carry all of them; the base values keep Strategies 5 and 6 unchanged, source `evaluation:v2 (base model, no behaviour change)`):

| key | ST5 / ST6 (base) | ST7 (1m) | ST8 (5m) | source |
|---|---|---|---|---|
| `room_model` | bands | rooms | rooms | evaluation:v2 (user brief) |
| `room_overlap` | supersede (not read) | supersede | supersede | evaluation:v2 (build: "two live rooms never overlap"); kept by user decision 2026-09-27 call 2; see below |
| `same_session_overlap` | keep_older (not read) | keep_older | keep_older | user decision 2026-09-27 call 2 |
| `session_visit_rule` | any_close (not read) | sit | sit | user decision 2026-09-28 |
| `adjacent_birth` | allow (not read) | block_half_width | block_half_width | user decision 2026-09-28 |
| `defend_half` | off | away_half | away_half | user decision 2026-09-28 |
| `room_edges` | half_width (not read) | sit_range | sit_range | user decision 2026-09-28b |
| `absorb_rule` | overlap (not read) | mid_inside | mid_inside | user decision 2026-09-28b |
| `defend_direction` | any | one_per_visit | one_per_visit | user decision 2026-09-28b |
| `same_day_replace` | off (not read) | replace_unaccepted | replace_unaccepted | user decision 2026-09-28c; value 2026-09-28d |
| `drift_birth` | true | false | false | evaluation:v2 |
| `room_max_age_sessions` | null | 2 | 3 | evaluation:v2 ("yesterday's shelf, not a two-month hash") |
| `visit_min_bars` | 1 | 2 | 1 | evaluation:v2 |
| `birth_a_source` | protected_level | none | none | evaluation:v2 |
| `leave_closes` | 2 | 3 | 2 | user brief |
| `hunt_max_bars` | 3 / 1 | 2 | 1 | user brief |
| `cluster_bars` | 10 / 6 | 10 | 4 (the 20-minute sit) | user brief |

`fz.check()` refuses a missing key, `room_model` / `room_overlap` outside their choices, a non-boolean `drift_birth`, a negative `room_max_age_sessions`, and `visit_min_bars` below 1. Every other key of Strategies 7 and 8 is copied from Strategies 5 and 6.

**`room_overlap` is a build choice, not in the plan.** The plan says both "a sit overlapping a live room by less than `merge_overlap` is a new room" and "two live rooms never overlap", which contradict each other for a partial overlap. The first build clipped (`clip`): on 1m it clipped 131 of 226 rooms and left slivers (on 2 Sep `D 09-02 12:45` was 0.65 points wide, `F 09-02 14:38` 10.25), and on 3 Sep the afternoon box was split between two 2 Sep fragments with a 13-visit neighbour: the 10-point stagger the verdict rejects. `supersede` keeps every room the width and mid of a real sit. The cost is memory: a room superseded by a partly overlapping sit is gone even if price later returns to it. Both options stay in code; `clip` is the named alternative and is never seeded.

**User decisions 2026-09-27 (after the first acceptance run).** (1) Room E (`E 09-03 12:20 · 24029.5–24049.5`) is the 3 Sep noon room; F must not exist; E is not widened toward 24000 (23985 is the poke under the room, not the room); existing rooms' edges are never touched. (2) `same_session_overlap` (`keep_older` | `supersede`, seeded `keep_older` in Strategies 7 and 8, inert under bands): a sit whose band overlaps, by any amount, a live room that already had an inside close this session (before the sit's bar) is not a birth; the older room keeps its edges and the sit is a visit of it (absorbed as `merge_overlap` absorbs, taking the live visit when the close is inside it). `room_overlap = supersede` still applies to overlaps with live rooms not visited this session. (3) The dashboard's `zn()` prints room ids whole (base ids `A/B<yyyy-mm-dd hh:mm:ss>` are still shortened), and `lab.fz_chart()` leaves a room retired at or before a chunk's first bar out of the ZONES fill unless a Z row of the chunk names it (under the call-2 seeds this drops 367 of 739 per-session ZONES entries on ST7 and 284 of 607 on ST8, over all sessions).

**Result of call 2 on the acceptance window: the test fails, and E is not born.** Price crossed the 2 Sep room `D 09-02 14:38 · 24028.4–24048.4` from 11:09 on 3 Sep (18 closes inside it before 12:20), so every 3 Sep sit around it (11:13, 11:17, 12:10, 12:20, 12:25, 12:34) overlaps a room visited this session and is kept by that older room: the 12:20 sit that was E is a visit of D 09-02. The 13:48 sit (mid 24018) that was F is kept by `B 09-02 10:30 · 23999.3–24019.3`, also crossed that session. The window then reads `D 09-02 14:38` visits 4–9 and `B 09-02 10:30` visits 13–14 (two-digit), no room born on 3 Sep after 09:48, and the 13:11 up / 13:23 down SETUPs still gate TAKE on branch defend (on D 09-02 visit 5). Note also that the 13:48 sit's band (24008–24028) does not overlap E's (24029.5–24049.5) at all, so call 2 alone could not have removed F even if E had been born. Card statistics under call 2 (ST7 / ST8, All data): 2.0 / 1.8 rooms born per session, 61.5% / 55.4% of bars inside a room, NEW 6.2% / 9.8%, LEAVE 42.4% / 32.8%, visit_n at SETUP median 9.5 (max 27) / 5 (max 17). The "First numbers" and first "Priced" tables below are from the build before call 2 (`same_session_overlap` absent, i.e. `supersede`). The lab *was* then run under the call-2 seeds: the stored ST7 / ST8 results (filtered run, 2026-09-27 19:57–20:00) and the published `results/summary.json` / `dashboard.html` (plain run, 21:01, committed in `8761709`) carry the call-2 numbers in the last table of this section; their cache keys match the files and code on disk.

**User decisions 2026-09-28 (the three identity questions).** (1) `session_visit_rule` (`any_close` | `sit`, seeded `sit`): "visited this session" for `keep_older` means a real sit today, a run of at least `cluster_bars` consecutive same-session closes inside the room (the sit that bore the room counts), not any close. (2) `adjacent_birth` (`allow` | `block_half_width`, seeded `block_half_width`): a sit whose band edge is within `band_half_width` of a live room sat in this session (overlapping or not, checked after `merge_overlap` and `keep_older`) is not a birth and not a visit; it is counted as `sits_near_room` and the card keeps reading the existing room. (3) `defend_half` (`off` | `away_half`, seeded `away_half`; it is gate code, so it acts in either model, base `off`): a defend TAKE also needs the SETUP close in the half of the room away from the defended edge (above the mid for a long, below it for a short), else the row falls through to WATCH with `take_why = defend_wrong_half`. Order in `room_fit`: `merge_overlap` absorption, then `keep_older`, then `adjacent_birth`, then `room_overlap`. Strategies 5 and 6 unchanged bit for bit (pre-v2 snapshot, all fields).

**Result of the 2026-09-28 rules on the acceptance window: the test fails again; E is not born.** Verified on the 3-month tape (the working-tree `config/data.json` now points at 5-year files; the checks pin the 2026-07-01..09-25 files). What each rule did on 3 Sep:
- Rule 1 worked as intended for yesterday's rooms: no 2 Sep room keeps a 3 Sep sit it was only crossed by. But the morning's own sits now make rooms that were sat today: the 10:59 sit sat in `A 09-01 14:16 · 24069–24089` (absorbed by `merge_overlap`, 18.7 points), so that room counts as sat today; the 11:13 sit (24046–24066) is then 3.05 points from it and is blocked by rule 2; the 11:17 sit is born as `B 09-03 11:17 · 24038.5–24058.5`.
- The 12:20 sit (24029.5–24049.5, the one that was E) overlaps `B 09-03 11:17` by 11.0 points, which is at least `merge_overlap` × width (10): it is absorbed by the base `merge_overlap` rule, before rules 1–2 are even read. The 12:25 and 12:34 sits (24020–24040, 24023.25–24043.25) overlap `B 09-03 11:17` by 1.5 and 4.75 points, a room sat today, so `keep_older` keeps them. No room is born for the afternoon box; its closes (mostly 24020–24038) are under B 09-03 11:17's low edge, so from 12:19 to 14:54 the card alternates between "no room" (LEAVE / NEW) and short THIN stays in `B 09-03 11:17` (visits 3–10), and `B 09-02 10:30` (visits 13–14, two-digit) takes the late afternoon.
- Rule 2: F is not born, but by the base `merge_overlap` rule: the 13:48 sit (24008–24028) overlaps `B 09-02 10:30 · 23999.35–24019.35` by 11.35 points.
- Rule 3 is inert on this tape: all 7 ST7 defend TAKEs over all data (and 0 on ST8) already close in the away half. Under the call-2 identity, 13:11 up closed at 24046.5 and 13:23 down at 24030.1 in `D 09-02 14:38` (mid 24038.4), each in the half away from its defended edge, so both still TAKE with `away_half`. On the new identity 13:11 reads REJECT (gated WATCH) and 13:23 reads LEAVE (TAKE, branch leave), so only one of them TAKEs, but not through rule 3.
Card statistics under the 2026-09-28 seeds (ST7 / ST8, All data; dry run, lab not run): 2.2 / 2.0 rooms per session, 49.7% / 48.6% of bars inside a room, NEW 12.3% / 15.4%, LEAVE 35.4% / 29.1%, visit_n at SETUP median 6 (max 26) / 4 (max 13); SETUPs by outcome TAKE / WATCH / BLOCK / REENTER 37 / 84 / 83 / 3 of 207 and 14 / 28 / 23 / 8 of 73 (call 2: 40 / 89 / 74 / 4 and 16 / 26 / 21 / 10).

**User decisions 2026-09-28b (second round).** (1) `room_edges` (`half_width` | `sit_range`, seeded `sit_range`): a room's lo / hi are the min / max close of the `cluster_bars` window that bore it, frozen at birth; mid = (lo + hi) / 2 (a swing-born room, diagnostic only, keeps mid ± `band_half_width`). (2) `absorb_rule` (`overlap` | `mid_inside`, seeded `mid_inside`): a sit is a visit of a live room only when its mid lies inside that room (nearest mid, then the older room); otherwise it is a birth candidate and passes through `same_session_overlap`, `adjacent_birth` and `room_overlap` as before. (3) `defend_direction` (`any` | `one_per_visit`, seeded `one_per_visit`): after a defend TAKE one way in a visit, a defend the other way in the same visit gates WATCH with `take_why = defend_opposite_in_visit`; the direction is recorded on the gate's TAKE decision, whether or not a position opens, so the card-without-positions check still holds. `defend_half` is kept.

Which distance each rule uses under `room_edges = sit_range`: the candidate's band is the sit's own close range. `absorb_rule = mid_inside` uses no distance (the candidate's mid against a room's edges). `absorb_rule = overlap` (not seeded) needs an overlap of `merge_overlap` × the candidate's own width. `same_session_overlap = keep_older` and `room_overlap` use any positive overlap of the two bands. `adjacent_birth` uses the sat room's own half-range, (hi − lo) / 2, as the distance from its edge to the candidate's band. Under `half_width` every distance is `band_half_width` as before. No rule needed a further change for variable-width rooms: `supersede` still removes every positive overlap, so live rooms never overlap (parity check 6 passes); a sit whose range is a single price makes a zero-width room, which is allowed.

**Result of the 2026-09-28b rules on the acceptance window: the test fails; no 3 Sep room covers the afternoon box.** The geometry that keeps the box from being one room is a same-day room directly above it. `C 09-03 11:17 · 24040–24057` is born from the 11:08–11:17 sit (it supersedes `C 09-02 14:38`, 24029–24047.8, which was not sat that day). The afternoon sits then fall just under it:
- 12:20 sit 24030–24049, mid 24039.5: 0.5 below C's low edge, so it is not absorbed by `mid_inside`. It overlaps C by 9.0 and C was sat today, so `keep_older` makes it a visit of C.
- 12:25 sit 24020–24040, mid 24030: it only touches C (overlap 0.0), so it is not kept. Its gap to C (0.0) is within C's half-range (8.5), so `adjacent_birth` blocks it.
- 12:34 sit 24025.1–24041.4: overlaps C by 1.4, kept by `keep_older`.
- 14:03 sit 24022–24041: overlaps C by 1.0, kept by `keep_older`.

C keeps its 24040–24057 edges, so the box's closes (24020–24040) are under its low edge. From 12:19 to 14:39 the card alternates between "no room" (LEAVE / NEW) and 1–4-bar THIN stays in C (visits 3–7, with touches). A second same-day room, `D 09-03 13:48 · 24012–24024` (the 13:39–13:48 sit, superseding `B 09-02 10:30`), takes the late afternoon (visits 1–5). Visits in the window stay under 10 apart from `B 09-02 10:30` at visit 11 (13:25–13:47), and the volume ratios are live.

Rule 3 does what it says but never binds on this tape: 8 defend TAKEs on ST7 with `any` and 8 with `one_per_visit`, 0 on ST8, and no two opposite defends ever share a visit. On the call-2 identity (`D 09-02 14:38`, visit 5) the unit check gives 13:11 up TAKE (defend) and 13:23 down WATCH `defend_opposite_in_visit`. On the new identity 13:11 reads REJECT (WATCH) and 13:23 reads LEAVE (BLOCK `hunt_fade`), so neither is a defend and neither TAKEs.

Card statistics under the 2026-09-28b seeds (ST7 / ST8, All data, dry run, lab not run): 2.6 / 2.6 rooms per session, 47.8% / 48.5% of bars inside a room, NEW 10.4% / 13.4%, LEAVE 41.1% / 33.7%, visit_n at SETUP median 6 (max 27) / 3.5 (max 14); SETUPs TAKE / WATCH / BLOCK / REENTER 42 / 80 / 80 / 5 of 207 and 16 / 23 / 26 / 8 of 73.

**User decision 2026-09-28c.** `same_day_replace` (`off` | `replace`, seeded `replace`) is checked in `room_fit` after the absorb rule and before `keep_older` / `adjacent_birth`. A sit whose mid is inside a live room is still a visit of that room, same-day or not. A sit that is not absorbed and whose own close range overlaps or touches (gap ≤ 0) a live room born earlier the same session is born, and that room is retired (`retired_by = same_day_replace`, stat `rooms_same_day_replace`). Those same-day rooms are skipped by `keep_older` and `adjacent_birth` for this sit; rooms born on earlier days keep both protections. A watch pinned on a replaced room ends with reason `room_replaced`. The existing `end_watch` convention names it `cancelled:room_replaced` when the watch never armed and `armed_expired:room_replaced` when it had armed. A replaced room's visit count does not carry over (accepted by the user).

**Result of 2026-09-28c on the acceptance window: the test fails.** The afternoon box gets a 3 Sep room, but not a single one through the afternoon:
- 12:20 sit 24030–24049 (mid 24039.5) is born as `G 09-03 12:20` and replaces the same-day `F 09-03 12:10`. G is the ref 12:20–13:56 at visits 1–5, with `first_bars` 11 and live ratios; the 12:25 and 12:34 sits are visits of G (mid inside).
- 13:48 sit 24012–24024 is blocked by `adjacent_birth` (gap 6.0 ≤ G's half-range 9.5).
- 13:57 sit 24016.6–24034 (mid 24025.3, under G's low edge 24030, overlapping G by 4.0) is not absorbed. It is born as `H 09-03 13:57` and replaces G. H is the ref 13:57–15:06 at visits 1–5; the 14:03 and 15:00 sits are visits of H.
- 15:18 sit 24010.1–24020 is born as `I 09-03 15:18` and replaces H.
- So `same_day_replace` itself splits the box. The sit that ends G is the 13:48–13:57 sit, whose range extends 13.4 points under G's low edge while overlapping it by 4.0.
- 13:11 up TAKEs (defend on G, visit 2); 13:23 down is WATCH `defend_opposite_in_visit`. Only one of the pair TAKEs.
- Visits stay single-digit throughout, and the volume ratios are live.

Card statistics under the 2026-09-28c seeds (ST7 / ST8, All data, dry run, lab not run): 5.6 / 3.8 rooms per session, 47.9% / 50.6% of bars inside a room, NEW 10.3% / 12.2%, LEAVE 36.9% / 31.6%, visit_n at SETUP median 3 (max 26) / 3 (max 11); SETUPs TAKE / WATCH / BLOCK / REENTER 42 / 79 / 81 / 5 of 207 and 11 / 24 / 26 / 12 of 73. Rooms replaced same-day: 192 (1m) / 77 (5m); watches ended `room_replaced`: 7 / 0.

**User decision 2026-09-28d.** `same_day_replace` gains a third value, `replace_unaccepted`, which is the seed for Strategies 7 and 8; there is no new key. A same-day room can be replaced only while it has not yet had an ACCEPTED stay. Each room carries `accepted_at`, the first close on which a stay of that room reads ACCEPTED. It is set as of that close, so a sit on a later bar sees it; nothing looks ahead. Once accepted, a later same-day sit that overlaps or touches the room with its mid outside it is treated like a sit next to an earlier-day room: a visit of it under `keep_older`, or blocked by `adjacent_birth`.
- **Reading chosen:** "accepted" is the ACCEPTED read, i.e. a revisit with `this_bars ≥ accept_bars` whose volume is not below `accept_vol_ratio` × the first visit's.
- **Why not the literal reading:** "a visit of at least `accept_bars` inside closes" would make every sit-born room accepted on its birth bar. `cluster_bars` = `accept_bars` = 10 on 1m, and on 5m `cluster_bars` 4 > `accept_bars` 2, so the rule would never replace anything.

**Result on the acceptance window.** The afternoon box is now one 3 Sep room:
- `G 09-03 12:20 · 24030–24049` is born at 12:20 (replacing the unaccepted `F 09-03 12:10`) and accepted at 12:38.
- G is the ref from 12:20 until price leaves the box downward at 14:56, visits 1–7, `first_bars` 11, live volume ratios.
- The 13:57 sit is kept by G (overlap 4.0, G sat today), and the 15:00 sit likewise (overlap 0.5). The 13:48 sit is blocked by `adjacent_birth`. `H 09-03 13:57` is not born.
- 13:11 up TAKEs (defend); 13:23 down is WATCH `defend_opposite_in_visit`.

Against the stated bar, two items still miss:
- G's visit count reaches 7 (visit 6 at 13:58, visit 7 at 14:45), more than one hand.
- After the box is left at 14:56, the card names the 2 Sep room `C 09-02 10:43 · 23991.8–24010` at visits 10–11 (15:05–15:10, 15:24–15:29), with `H 09-03 15:18 · 24010.1–24020` born in between.

Card statistics under the 2026-09-28d seeds (ST7 / ST8, All data, dry run, lab not run):

| | ST7 | ST8 |
|---|---|---|
| rooms per session | 4.8 | 3.4 |
| bars inside a room | 47.3% | 49.5% |
| NEW | 11.4% | 12.8% |
| LEAVE | 38.1% | 31.8% |
| visit_n at SETUP, median (max) | 4 (21) | 3 (11) |
| SETUPs TAKE / WATCH / BLOCK / REENTER | 37 / 75 / 91 / 4 of 207 | 12 / 23 / 28 / 10 of 73 |
| rooms replaced same-day | 144 | 49 |

**Acceptance 2026-09-28: passed by user decision with G reaching visit 7 and the post-leave 2 Sep room at visit 10-11 accepted as is; ST7/ST8 rules frozen.** The card on 3 Sep 12:00–15:30 shows one room, `G 09-03 12:20 · 24030–24049`, as the ref from 12:20 to 14:55 (visits 1–7), then `C 09-02 10:43` at visits 10–11 after the leave. Reading of "accepted" used by `same_day_replace = replace_unaccepted`: a room is accepted from the first close on which one of its stays reads ACCEPTED, i.e. a revisit with `this_bars ≥ accept_bars` and volume not below `accept_vol_ratio` × the first visit's (time only when volume is NA). It is recorded as `accepted_at` as of that close, so no look-ahead. The literal "a visit of at least `accept_bars` inside closes" was not used, because every sit-born room would be accepted on its birth bar.

**Outputs.** The card gains `touches` (None without a ref room); the zones output gains `touches`, `retired_bar` and `retired_by`; the visit records of a touch carry `touch: true`. Stats: `rooms_retired`, `rooms_superseded`, `rooms_clipped`, `sits_kept_by_older`, `touches`, `visit_ends_sit_moved`, `leave_end_retired`. `lab.py` changed in two places: `ENTRY_RULES` gains `fz_v2` (`fz_rule()` already matches any `fz*`), and `fz_chart()` leaves out rooms retired at or before the chunk's first bar (unless a Z row names them). `dashboard.tpl`'s two `zn()` shorteners shorten base ids only and print room ids whole (user decision 2026-09-27 call 3).

**Tests.** `tests/test_fz_parity.py` runs all four strategies (the engine parity, the token scan, the card-without-positions check, the REENTER rules) and adds check 6 for the room model: no two live rooms overlap at any bar, and no room is the ref band (`zone_id`) or the containing band (`in_id`) on or after its retirement. `tests/test_truncation.py` adds ST7 and ST8 to the FZ cases (12 uniform + targeted cuts each). Strategies 5 and 6 were checked against the stored `web/ST5|ST6/all-data_*/-/summary.json` ledgers (207 and 73 rows on every gate column fz.py writes) and trades (51 and 26): identical.

**Acceptance test (the picture the user agreed on).** On ST7, 3 Sep 2026 12:00–15:30 must show one room for the afternoon box around 24025–24045, born that day, with a visit count you can count on one hand, `first_bars` from that day's own sit, live volume ratios, the 13:02 CHoCH reading as inside the room (RECYCLE / ACCEPTED, gated WATCH, not REENTER), the 15:07 print reading HUNT or PENDING under the box (not LEAVE), and a LEAVE only when three closes have held outside. A July id or a two-digit visit count in that window fails the test. The script is `fz_v2_accept.py` (session scratchpad). Result of the seeded build:
- **Met:** the box is `E 09-03 12:20 · 24029.5–24049.5`, born that day from the 12:11–12:20 sit; its visits in the window run 1 to 6; `first_bars` 11 from that sit; the volume ratio is live on every row (0.03 to 3.52); no July id and no two-digit visit count appear (the ids in the window are `C 09-03 10:44`, `D 09-03 11:13`, `E 09-03 12:20`, `F 09-03 13:48`, `H 09-02 15:09`); every LEAVE follows three closes outside. The 13:02 SETUP is gated WATCH (WATCH_EDGE on E, armed, expired `back_inside`), not REENTER.
- **Not met:** (a) the 13:02 bar reads PENDING (its close is one close under E's low edge of 24029.5), not RECYCLE / ACCEPTED; (b) a second room `F 09-03 13:48 · 24008–24028` is born under E from the 13:39–13:48 sit, so from 14:41 the card steps between E and F (E visits 5–6, F visits 2–4); (c) the 15:07 SETUP reads LEAVE (E was left at 14:56 after three closes under it; the card's ref is F visit 3), gated BLOCK `hunt_fade`, not HUNT or PENDING. With the box's edges where the sit put them, every close from 14:54 to 15:07 was under E, so under the leave rule this is a leave; the user's "hunt under D" reading implies a lower edge nearer 24000 than the sit's 24029.5.
- ST5 on the same window, for contrast: ids `B2026-07-23 12:51`, `B2026-07-23 13:10`, `B2026-07-23 14:52`, `B2026-07-24 12:52` … with visits 6 to 17, volume NA on every row.

**First numbers, before call 2 (dry run, same inputs as the parity test; futures positions, before pricing).**

| | ST7 (1m) All · Design · Unseen | ST8 (5m) All · Design · Unseen | ST5 / ST6 base, All data |
|---|---|---|---|
| rooms born per session | 6.7 · 7.3 · 6.3 | 4.2 · 4.9 · 3.7 | 1.8 / 1.4 zones |
| bars inside a room | 61.6% · 62.5% · 61.2% | 56.1% · 56.7% · 55.7% | 94.7% / 83.5% |
| NEW share of bars | 4.5% · 2.1% · 6.0% | 8.7% · 6.2% · 10.2% | 0.4% / 5.7% |
| LEAVE share of bars | 35.7% · 36.4% · 35.8% | 29.6% · 31.5% · 28.4% | 43.7% / 38.4% |
| visit_n at SETUP, median (max) | 3 (16) · 3 (9) · 3 (16) | 3 (8) · 2 (6) · 3 (8) | 19 (68) / 7 (31) |
| FIRST_PRINT at SETUP | 10 · 1 · 9 | 6 · 1 · 5 | 0 / 0 |
| SETUPs TAKE / WATCH / BLOCK / REENTER (by outcome) | 43/84/79/1 of 207 · 11/26/18/0 of 55 · 32/58/61/1 of 152 | 21/23/23/6 of 73 · 4/10/8/4 of 26 · 17/13/15/2 of 47 | 29/114/42/22 · 14/32/15/12 |

**Priced, before call 2 (futures, filtered `python lab.py ST7 ST8`, 2026-09-27; superseded by the call-2 seeds, not published):**

| Window | ST7 positions (TAKE + REENTER) · net vs Foundation · control pct · perm p | ST8 positions · net vs Foundation · control pct · perm p |
|---|---|---|
| All data | 43 + 1 · −57,181 vs −216,468 · 29.1th · 0.77 | 21 + 6 · −19,444 vs −73,753 · 67.3th · 0.82 |
| Design period | 11 + 0 · −15,566 vs −16,985 · 22.9th · 0.58 | 4 + 4 · +7,937 vs −15,560 · 59.5th · 0.54 |
| Unseen test | 32 + 1 · −39,419 vs −197,287 · 46.5th · 0.86 | 17 + 2 · −25,971 vs −56,783 · 67.0th · 0.84 |

**Priced, call 2 (the published results: futures, `results/summary.json` of the 2026-09-27 21:01 plain run; SETUPs by outcome TAKE / WATCH / BLOCK / REENTER):**

| Window | ST7 positions (TAKE + REENTER) · net vs Foundation · control pct · perm p · outcomes | ST8 positions · net vs Foundation · control pct · perm p · outcomes |
|---|---|---|
| All data | 40 + 4 · −63,746 vs −216,468 · 39.6th · 0.61 · 40 / 89 / 74 / 4 of 207 | 16 + 10 · −30,170 vs −73,753 · 57.0th · 0.90 · 16 / 26 / 21 / 10 of 73 |
| Design period | 12 + 2 · −22,141 vs −16,985 · 23.5th · 0.52 · 12 / 26 / 15 / 2 of 55 | 4 + 4 · +13,394 vs −15,560 · 55.6th · 0.28 · 4 / 11 / 7 / 4 of 26 |
| Unseen test | 28 + 2 · −41,605 vs −197,287 · 61.0th · 0.87 · 28 / 63 / 59 / 2 of 152 | 12 + 6 · −43,564 vs −56,783 · 62.8th · 0.27 · 12 / 15 / 14 / 6 of 47 |

Options via futures, W-ATR2, All data: ST7 88 legs −14,985, 54.1th, p 0.96; ST8 52 legs −9,864, 75.7th, p 0.97. On 1m every TAKE is branch leave (27) or defend (13); FIRST_PRINT is 0 of the 207 SETUP reads (3.6% of bars); on 5m FIRST_PRINT is read at 2 SETUPs, both refused `first_print_against`.

The base on All data was 6.2th · 0.44 (ST5) and 49.8th · 0.18 (ST6). No v2 percentile or p is evidence of selection skill; the net gain over Foundation is still mostly cost avoidance. The room model's product is the card, which is what S42 asks the user to review. Nothing here is out of sample: the room rules were written against 3 Sep, and the Unseen window is still volume-blind.
