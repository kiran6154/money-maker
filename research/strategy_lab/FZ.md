# How the Foundation-Zone gate (Strategies 5 and 6) is built

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

`fz.thresholds()` reduces the block to `{key: value}` after checking that every key is an object with a `value` and a non-empty `source`; `fz.check()` then refuses a missing key, an unknown key, a wrong type or an out-of-range value. There are no defaults in code: 33 keys, all required in both files. `load_strategies()` also refuses an `fz` block on a `setup_v1` file (it would be stored and hashed but never applied) and an `fz_v1` file without a block for its design timeframe.

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

**A LEAVE lives** while no close comes back inside the band left, no close crosses that band's mid, and at most `leave_ttl_bars` bars have passed since the visit ended. A close back inside ends the LEAVE, sets the band's `leave_failed`, and hands the live visit back to that band as visit n+1 *if no other band holds the live visit* (the D01 tie-break; otherwise the neighbour keeps the visit and the bar is counted as `leave_return_no_visit`). A close across the mid or the ttl ends the LEAVE without a return. Every further far-side bar adds to the leave's far-side volume; a session's first bar turns the kind to `gap`.

**No live visit** (start of memory, after a leave into open ground, after a LEAVE ended): the band containing the close opens a visit on that bar (nearest mid among containing bands, ties to the older zone; a return into the band just left takes it back first). `entry_dir` of the visit is the direction of the close relative to the previous bar.

---

## 6. Edge events: HUNT and REJECT

Both are read on the ref band, only on a bar whose close is inside it (`out_run == 0`), and stored on the band as `hunt_at/dir` and `reject_at/dir`.

**HUNT** (`hunt_form = close`, 1 min): the previous bar was exactly one close outside this band and this close is back inside; the pierce side is the side of that outside close. (`hunt_form = wick`, 5 min): the previous close and this close are inside and the bar's wick reaches beyond an edge by at least `hunt_min_depth_atr × ATR14`; the pierce side is the deeper wick. In both forms the pierce must be within `hunt_max_bars` of the reclaim (always true under the seeded forms) and, when the sit's volume is live, the pierce bar's volume must be at least `hunt_burst` × the sit's per-bar mean (`hunt_no_burst` is counted when it fails; with NA volume the burst test is skipped).

**REJECT** (only when no HUNT on this bar): the previous close was inside, the bar's wick lies within ± `reject_tol` of an edge (not beyond it by more), and the close is nearer the mid than the open. The edge is the one the wick reaches further towards.

A wick beyond an edge by more than `reject_tol` that does not qualify as a HUNT is recorded as `wick_depth` on the card with no edge event (the documented "shallow pierce" class).

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
2. **Hard BLOCK**, in this order, no watch opened and any existing watch untouched: `in_position` (an FZ position is open on this bar), `clock` (bar open time ≥ `no_entry_from`), `open_pierce` (within the session's first `open_bars` bars and before `open_window_until`, the bar's range crosses an edge of a band whose last visit ended in an earlier session and that has fewer than `open_sit_closes` closes inside today), `hunt_fade` (a HUNT in S's direction completed within `fade_block_bars`, same session, on the ref band or the band just left, or on any band under `fade_scope = any_band`), `new` (the read is NEW).
3. **TAKE branches**, the first that holds:
   - **leave**: read LEAVE, S equals the leave side, `leave_vol_ok` is not False, not a gap LEAVE inside the first `open_quiet_bars` bars, and `leave_far_side`: `any` accepts; `block_list` refuses when the entered band reads RECYCLE, THIN, HUNT or REJECT (`block_reason = leave_into_recycle`); `no_band` refuses whenever a band contains the close (`leave_into_band`). A refusal records `take_why` and falls through to WATCH.
   - **first_print**: read FIRST_PRINT, the visit is at least `first_print_min_bars` old, S equals the visit's `entry_dir`.
   - **defend**: read ACCEPTED and the ref band had a HUNT or REJECT in this visit within `defend_window_bars` at the edge S points away from.
   - A **leave** TAKE of the band a watch waits on, in the watch's direction, is that watch's REENTER instead (branch `leave`, `reenter_reason = take_on_watch:leave`); a first_print or defend TAKE stays Foundation's own position and leaves the watch as it is.
   - A TAKE calls `open_position('TAKE')`; the engine may have skipped the SETUP for a wrong-side stop, in which case the row records `refused` and no position opens. An opposite-direction TAKE ends an open watch (`opposite_take`).
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

- **Loading.** `entry_rule` must be `setup_v1` or `fz_v1`. An `fz_v1` file needs an `fz` block for its design timeframe, validated by `fz.thresholds()`; an `fz` block on a `setup_v1` file is refused. `type_rows()` copies the block verbatim into a new `strategy.fz_json` column (added by `migrate()`, together with `trade.gate / reenter_reason / zone_id / fill_used` and the `fz_setup` table).
- **Front month.** `fm_by_day()` reads `front_month` per session from the 1-minute futures file (cached like `sessions()`); `fm_na` per bar is `front_month == 0 or volume == 0`.
- **Memory starts at the file.** For FZ rows `main()` sets the engine warm-up to every session before the window, so the band memory begins at the data file's first session and the Design, Unseen and 1M windows are exact date slices of the All-data run (`info.memory_start`, `info.same_sample = file_start`; Foundation rows keep their own warm-up, `own_warmup`). `resolve_backtest` still refuses a window using the strategy's own `warmup_days`. A backtest on a timeframe with no `fz` block is refused with a reason; an FZ row of type Options (standalone) is refused with `FZ thresholds are futures points; no native-option unit rule in v1`.
- **`run_fz(st, fut, s0, r)`.** Builds `fm_na` and `atr14` (Wilder ATR on the futures bars, seeded like `atr_series`), the frozen view and the callback, runs `fz.run`, builds the FZ trades, exits with an error if the ledger has no WATCH or BLOCK and the trades equal Foundation's (an FZ row must never be Foundation reported under an FZ code), runs the gate a second time with volume NA on every bar (the all-NA comparator), and computes the window's cross-tabs.
- **`run_variant`.** For FZ rows the FZ trade list replaces `r["trades"]` before the pricing loop, so the futures book and the options-via-futures book are priced from FZ's positions by the existing code; the engine's own trades are priced too, tagged `RAW`, for the bridge. Trade records carry `gate`, `reenter_reason`, `zone_id`, `fill_used`, written at indices 25–28 of the stored trade arrays and into the `trade` table (non-FZ rows carry None there; indices 29–30 are `lots` and `tranche` from the position-lock work).
- **`fz_payload`.** Per priced choice, `summary.json['fz']` holds: `fz_hash`, `memory_start`, `window_start`, `same_sample`, the thresholds, the headline (SETUPs; TAKE / WATCH / BLOCK / REENTER by `outcome_gate` and `at_setup`; positions; priced positions; control percentile; permutation p; active sessions; sample flag), the cross-tabs, the raw counters, the bridge, the control, the permutation, both books, the sample flags, the all-NA comparator, the ledger (`{cols, rows}`, with the diagnostic join added here: `fnd_*` = the Foundation outcome of the SETUP, `fz_*` = the FZ position it opened), the watch log and a legend of every compact array.
- **Chart chunks.** `fz_chart()` adds to every futures session chunk `Z` (one row per bar: time, zone_id, visit_n, this_bars, this_vol, first_bars, first_vol, read code, left_id, out_run, vol_na, gap_pts, session_bar, wick_depth, in_id, first_vol_na, read from the as-of card, never from the final zone list) and `ZONES` (every band holding a close of the chunk, every band a Z row names, plus the three bands nearest the chunk's first close: id, kind, lo, hi, born time).
- **Persistence.** `save_run` writes one `fz_setup` row per ledger row and puts `fz_json`, `fz_hash` and the warm-up into `params_json`; `write_result` adds `fz` and `fz_hash` to `summary.json`. `results/summary.json` rows gain `fz_take`, `fz_watch`, `fz_block`, `fz_reenter` (by outcome), `fz_reenter_at_setup`, `fz_take_trades`, `fz_reenter_trades`, `fz_priced`, `control_pct`, `perm_p`, `active_sessions`, `fz_sessions`, `fz_hash`. `results/fz_setups.csv` (one row per ledger row) and `results/fz_ledger.csv` (every table flattened to table / row / col / value) are written for the futures rows and the default option choice, on full runs only.
- **Cache and identity.** `cache_key` hashes `fz.py`, `fz_exec.py`, `fz_report.py` and the 1-minute file for FZ rows only, so an FZ edit recomputes FZ rows and nothing else; `fz_hash` (sha1 of the three modules) is stored beside every result. `lab.py` itself is hashed minus a set of cache-exempt functions (`main`, `add_backtest`, `sync`, `history`, ...), so an edit confined to those does not recompute stored rows; any other line of `lab.py`, even a blank one, does. The group-run key includes `entry_rule`.
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

- `merge()` concatenates `Z` and unions `ZONES` by id across chunks; option chunks have neither.
- `drawChart()`: a *Zones* layer (chip shown only when the chunk has zones): one baseline series per band from `max(born, first bar)` to the last bar, filled between lo and hi, off the autoscale; A bands in the chart purple, B bands in the chart blue, made translucent by a tint helper (no new colour literals). The crosshair line appends the card: `Z <kind><mm-dd hh:mm> lo–hi · visit n · this/first bars · vol ratio or NA · READ [from <left band>]`. Gate markers T / W / B / R at SETUP times (and an R at a later fill bar), toggled with the Trades chip.
- `band_reclaim` in the three exit-reason maps (trades table pill `Band`, breakdown `Band reclaim`, marker prefix `BAND`).
- The **Zone gate** tab (`renderFZ`): KPI tiles with the control percentile and permutation p beside net, gate × read, watches, positions, the three `leave_far_side` counts, volume NA and R4 with the all-NA comparator, the bridge, the random control and the permutation, both books with sample flags, active sessions and dormant stretches, gate by hour / visit / direction / zone kind, card statistics, and the ledger table with a gate filter; a row click opens that session's futures chart at the SETUP (`openAt`). For a non-FZ strategy the tab shows a hint. The KPI strip above the tabs also shows the control percentile and permutation p for FZ rows.
- Signals shows Read and Gate columns joined on the SETUP time; Config prints every `fz` key with value, source, statistic and note plus `fz_hash`, memory start and `same_sample`; Rules has a fifth static card, *Foundation-Zone (Strategy 5, 6)*. Profit-and-loss figures use the page's `.pos` / `.neg` classes, which follow the colour palette.

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
- The 1M preset resolves to the same dates as the Design period on this tape; both rows are published and their control percentiles differ only through the run label in the seed.
