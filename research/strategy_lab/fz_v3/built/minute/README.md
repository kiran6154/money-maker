# FZ v3 data build, 1-minute (`fz_v3/minute/`)

Built 2026-09-29 for the study in `../../FZ_V3_STUDY_BRIEF.md`. Everything here is derived from one file,
`D:/nifty/niftyfut_nearmonth_minute_2021-10-01_to_2026-09-25.csv` (near-month NIFTY futures, 1-minute), read in full
through `engine.load` (warm-up 0; `lab.sessions()` is never used, so `config/data.json`'s `history_from` does not apply).
The build asserts the first bar is `2021-10-01 09:15:00` and the last `2026-09-25 15:29:00`.

Three scripts, run one after another as separate processes (each under 1 GB), read-only on the repository:

| script | what | outputs |
|---|---|---|
| `01_engine.py` | `engine.run` with Strategy 1 rules (`break_mode touch`, `choch_mode touch`, `avwap_weight volume`, `sl_rule prev_swing`), every Foundation trade priced | `bars.csv`, `sessions.csv`, `swings.csv`, `events.csv`, `setups.csv`, `trades.csv`, `skipped.csv`, `r_slim.pkl`, `timing_01.json` |
| `02_fz.py` | `fz.run` with the ST7 `fz.minute` block (`fz.thresholds(strategy_7.json['fz']['minute'])`), `fz_exec.view` / `opener` (prev_swing, touch), `s0 = 0` (memory from the first bar, ledger over every SETUP), `fz_exec.build_trades` | `card.csv`, `ledger.csv`, `zones.csv`, `visits.csv`, `watches.csv`, `decisions.csv`, `fz_trades.csv`, `fz_stats.json` |
| `03_features.py` | per-bar volume baselines, the per-SETUP feature table, parquet copies | `bars_volume.csv`, `setup_features.csv`, `*.parquet`, `timing_03.json` |

Every CSV has a parquet twin (pandas 2.3.3 / pyarrow 24). Floats in the stage-1 and stage-2 CSVs are written with
`repr` (exact round trip); booleans are 0/1; None is an empty cell.

**Protocol reminders.** IS = sessions `2021-10-01 .. 2025-12-31`, OOS = `2026-01-01 .. 2026-09-25` (column `split`).
Costs per Foundation trade: `lab.trade_charges(ZERODHA_NFO_FUT)` on the slipped prices + 5 pts slippage per side at
lot 65, i.e. `lab.price_trade`'s arithmetic restated (`fnd_net = (pts - 10) x 65 - charges`). Every feature at a SETUP
bar `k` uses bars `<= k` only; the label and `st7_*` post-SETUP columns are the only look-ahead columns and are marked
**LABEL** / **POST** below. `fz.py` is causal by construction (the lab's truncation test), so every card field is as of
its bar.

Counts and run times: see the "Numbers" section at the end (filled from `timing_01.json`, `fz_stats.json`,
`timing_03.json`).

---

## Per-bar tables

### `bars.csv` (one row per 1-minute bar, in file order)

| column | definition | look-ahead |
|---|---|---|
| `bar_i` | 0-based bar index; every other table's `entry` / `i` / `setup_i` / `bar` columns index into it | none |
| `datetime`, `date`, `tod` | bar open time `YYYY-MM-DD HH:MM:SS`, its date, its `HH:MM` | none |
| `session_i` | 0-based session (trading day) index | none |
| `session_bar` | 0-based bar within the session (09:15 = 0) | none |
| `open`, `high`, `low`, `close`, `volume` | the candle as `engine.load` reads it | none |
| `fm_na` | 1 when the bar's volume is not usable: the session's `front_month` flag is 0 (last row of the day, as `lab.fm_by_day`) or the bar's volume is 0; what `fz.run` reads as volume-NA | none |
| `atr14` | `lab.atr_series(…, 14)`: Wilder ATR over the futures bars, value includes the bar itself, simple mean for the first 14 bars | none |
| `prot` | the engine's protected level at that bar (`r["prot"][i]`, None when no trend / candidate yet) | none (as of the bar) |

### `bars_volume.csv` (same rows; the H3 baselines)

| column | definition | look-ahead |
|---|---|---|
| `vol_med20_prior`, `vol_med60_prior` | median volume of the previous 20 / 60 bars **of the same session, excluding the bar itself**; NaN until 5 prior same-session bars exist | none |
| `vol_ratio20`, `vol_ratio60` | `volume / vol_medN_prior`; NaN when the baseline is NaN or 0 or `fm_na` | none |
| `sess_cumvol` | cumulative volume of the session up to and including the bar | none |
| `sess_cumvol_ratio20s` | `sess_cumvol` / median of `sess_cumvol` at the same `session_bar` over the previous 20 sessions (at least 5); NaN when `fm_na` or fewer than 5 prior sessions | none (prior sessions only) |

`bars.parquet` carries both tables in one frame.

### `card.csv` (one row per bar: the ST7 room card as of that bar; `fz.run` never rewrites a row)

`bar_i`, `datetime`, then the 29 card fields exactly as `fz.py` writes them (`read` in `FIRST_PRINT ACCEPTED RECYCLE THIN
HUNT REJECT LEAVE PENDING NEW`):

| field | definition (FZ.md §7, §19) |
|---|---|
| `zone_id` | the ref room (the room holding the live visit), `'<letter> <mm-dd hh:mm>'`; empty when none |
| `visit_n`, `this_bars`, `this_vol`, `vol_na` | number of the live visit of the ref room and its inside closes / volume so far; `vol_na` = any bar of the visit is volume-NA (without a ref room: the bar's own `fm_na`) |
| `first_bars`, `first_vol`, `first_vol_na` | the ref room's first visit (its first stay that is not a touch), as of this bar |
| `read` | the card read, precedence LEAVE > HUNT > REJECT > inside read (FIRST_PRINT / ACCEPTED / THIN / RECYCLE) > PENDING > NEW |
| `left_id` | the room whose LEAVE is live |
| `out_run`, `out_side` | consecutive closes outside the ref room and their side (0 / empty when the close is inside) |
| `session_bar`, `gap_pts` | bar in session; today's open gap (first close minus the previous session's last close), constant over the session |
| `wick_depth` | deepest wick beyond either edge of the ref room on a bar whose close is inside it (0 when none); empty otherwise |
| `last_hunt_at`, `last_hunt_dir`, `last_reject_at`, `last_reject_dir` | the ref room's latest HUNT / REJECT (bar index and pierce side); one slot each, overwritten by a later event |
| `cluster_sit` | 1 when the last `cluster_bars` (10) closes are in one session within `cluster_width` (20) |
| `prev_bars`, `prev_vol` | the visit before the live one (number `visit_n - 1`, not a touch) |
| `last_leave_failed` | the ref room's last LEAVE ended with a close back inside |
| `in_id` | the room containing the close (the ref room when the close is inside it, else the nearest containing live room) |
| `leave_side`, `leave_vol_ok`, `leave_kind` | the live LEAVE's side, its R4 (far-side per-bar volume >= the sit's per-bar mean; empty when NA), `gap` / `normal` |
| `first_clock_lived` | on a FIRST_PRINT read: the visit has lasted `accept_bars` (10) |
| `touches` | touches counted on the ref room so far |

All of these are as of the bar (no look-ahead).

---

## Engine tables (`01_engine.py`)

### `sessions.csv`
`session_i`, `date`, `first_bar`, `last_bar`, `n_bars`, `front_month` (last row of the day, as `lab.fm_by_day`),
`contract`, `expiry`, `split` (IS / OOS), `front_month_mixed` (1 when the day's rows disagreed on `front_month`).

### `swings.csv`
`swing_i` (confirmation order), `kind` (H / L), `bar`, `bar_time`, `price`, `conf` (the bar that confirmed it), `conf_time`,
**`broken_final`** — the engine's end-of-run `broken` flag (whether the swing was ever traded through by the end of the
file): **final state, look-ahead, diagnostic only; never a feature**. A swing exists for a feature at bar `k` only when
`conf <= k`.

### `events.csv`
Engine order (within one bar a BOS is appended before a CHoCH). `event_i`, `i` (bar), `time`, `kind` (CHoCH / BOS), `dir`
(up / down), and for CHoCH: `flip` (trend flipped at this CHoCH), `lvl` (the protected level broken), `av` (AVWAP from the
anchor at that bar), `tr` (trend before the CHoCH, +1 / -1), `hi_bar`, `hi_p`, `lo_bar`, `lo_p` (the last confirmed swing
high / low at the CHoCH, the AVWAP pair anchors), `prot_swing_bar`, `prot_swing_kind` (the swing that was the protected
level), **`end`** = the next CHoCH's bar (the SETUP search window end): **look-ahead, diagnostic only**. An event is known
at bar `k` when `i <= k`.

### `setups.csv`
`setup_i` (the SETUP bar), `time`, `dir`, `ch` (its CHoCH bar), `ch_time`, `traded` (the engine opened a trade), `trade_i`,
`skipped_wrong_side_stop` (the engine skipped it: the prev_swing stop was not on the loss side of the entry close).

### `trades.csv` (every Foundation trade; entry at the SETUP close)
| column | definition |
|---|---|
| `trade_i`, `entry`, `entry_time`, `exit`, `exit_time`, `dir`, `choch`, `choch_time` | bars / times; `entry` = the SETUP bar |
| `sl` | the stop: the latest confirmed swing low (long) / high (short) with `conf <= entry` (`prev_swing`) |
| `sl_dist_pts` | `close[entry] - sl` (long) / `sl - close[entry]` (short); positive |
| `entry_px`, `exit_px` | `close[entry]`; the engine's exit price (stop: worse of the candle open and the stop; a session's first candle: its close; CHoCH exit: that bar's close; open: the last close) |
| `pts` | the engine's raw points, `dir_sign x (exit_px - entry_px)`, before slippage |
| `exit_reason` | `stop_loss` / `next_choch` / `open` (still open at the file end) |
| `open` | 1 when `exit_reason = open` |
| `bars_held` | `exit - entry` |
| `mfe`, `mae` | `lab.excursion` restated: over candles `entry+1 .. exit` inclusive, max favourable move (>= 0) and max adverse move (<= 0) from `entry_px`, in points before slippage; 0 / 0 when the trade has no candle after the entry |
| `mfe_bar`, `mae_bar` | bar offset from the entry at which they occur |
| `slip_pts` | `pts - 10` (5 pts each side) |
| `gross` | `slip_pts x 65` |
| `charges` | `lab.trade_charges(ZERODHA_NFO_FUT, buy, sell, 65)` on the slipped prices |
| `net` | `gross - charges` |
| `win` | `net > 0`; `win_pts` | `pts > 0` |

### `skipped.csv`
The SETUPs the engine skipped (`entry`, `time`, `dir`, `sl`).

### `r_slim.pkl`
The engine output fields `fz_exec.view` / `opener` / `build_trades` read (`sw`, `setups`, `chs` as `(i, dir, lvl)`, `prot`,
`trades`), for stage 2.

---

## FZ tables (`02_fz.py`, ST7 thresholds, room model)

### `ledger.csv` (one row per Foundation SETUP)
`fz.py`'s ledger row: `i` (SETUP bar), `time`, `dir`, `choch_i`, `choch_time`, the card columns it copies (`zone_id`,
`zone_kind`, `band_lo`, `band_hi` = the ref room's edges, `visit_n`, `this_bars`, `this_vol`, `first_bars`, `first_vol`,
`vol_na`, `first_vol_na`, `read`, `left_id`, `session_bar`, `in_id`, `level_in_band` = the CHoCH level lies inside the ref
room), the gate **as of the SETUP bar** (`gate` TAKE / WATCH / BLOCK / REENTER, `block_reason`, `branch`, `take_why`,
`refused`, `entered_zone_id`, `entered_visit_n`, `entered_read`, `leave_vol_ok`, `leave_kind`, `watch_kind`,
`watch_band_id`), and the **post-SETUP** columns (`outcome_gate` = how the SETUP ended, REENTER when a later REENTER used
it; `watch_outcome`; `reenter_reason`; `fill_used`; `fill_bar`; `fill_time`; `fill_delay_bars`; `edge_dist_pts`;
`armed_bars`; `rearmed_bars`; `sl_bar`): **look-ahead, diagnostic only**.

### `zones.csv` (every room ever born)
`zone_id`, `kind` (B = sit-born), `lo`, `hi`, `mid` (frozen at birth: the sit's close range), `origin_bar` (the sit's first
bar), `birth_bar`, `born_ts`, `merges`, `n_stays`, `n_visits` (stays that are not touches), `touches`, `retired_bar`,
`retired_by` (`retired` / `superseded` / `same_day_replace`), `retired_time`. A room is **alive at bar `k`** when
`birth_bar <= k` and (`retired_bar` empty or `retired_bar > k`); using it that way is causal.

### `visits.csv` (every stay of every room)
`zone_id`, `visit_n`, `start`, `start_time`, `end`, `end_time`, `ended_by` (`left` / `sit_moved` / `superseded` / `ref_live`),
`bars`, `vol`, `vol_na`, `entry_dir`, `touch`, `defend_dir`. `end` / `ended_by` are known only at the end bar.

### `watches.csv`, `decisions.csv`
The watch log (`opened_at`, `band_id`, `dir`, `kind`, `opened_by_read`, `setup_i`, `outcome`, `outcome_bar`, `armed_at`,
`last_armed_at`) and every position `fz.run` opened (`kind` TAKE / REENTER, `entry`, `dir`, `setup_i`, the pinned band
snapshot). Outcomes are final state.

### `fz_trades.csv`
`fz_exec.build_trades`: the ST7 positions in engine shape (TAKE = Foundation's own trade copied; REENTER = `simulate()` from
the fill bar with the `band_reclaim` exit), with `gate`, `setup_i`, `zone_id`, `fill_used`, `reenter_reason`, `sl_bar`,
`sl_in_band`, priced exactly as `trades.csv` (`slip_pts`, `gross`, `charges`, `net`, `win`).

### `fz_stats.json`
`fz.run`'s counters (`counters`), the thresholds used, gate counts by outcome and as of the SETUP bar, reads per bar, run
times and peak RSS.

---

## `setup_features.csv` / `.parquet` (one row per Foundation SETUP; the H5 table)

Prefixes: `reg_` regime (H2), `vol_` volume (H3), `lvl_` levels (H4), `card_` the ST7 card at the SETUP bar, `st7_` the ST7
gate (as of) and outcome (POST), `fnd_` / `win` / `fwd_` labels (LABEL). `dir_sign` = +1 for `up`, -1 for `down`; "dir"
distances are multiplied by it, so a positive `_dir_atr` distance is "ahead in the trade direction" for levels named
"ahead" and "behind the entry" for the protected / CHoCH levels (see each row). `a` = `atr14` at the SETUP bar.

### Identity, clock, price context (no look-ahead)
| column | definition |
|---|---|
| `setup_i`, `time`, `date`, `session_i`, `session_bar`, `tod`, `minute_of_day` | the SETUP bar and its clock |
| `hour_bin` | `fz_report.crosstabs`'s bins with the ST7 clock keys: `<09:25`, `09` … `15`, `>=15:20` (bar open time) |
| `split` | `IS` (session <= 2025-12-31) / `OOS` |
| `dir`, `dir_sign` | SETUP direction |
| `ch`, `ch_time`, `choch_flip`, `choch_lvl` | the SETUP's own CHoCH: bar, time, whether it flipped the trend, the level it broke |
| `close`, `atr14`, `atr_bps` | the SETUP close, ATR14 at the bar, `1e4 x atr14 / close` |
| `traded`, `skipped_wrong_side_stop` | the engine took / skipped the SETUP (known at the SETUP close: the stop rule is evaluated there) |
| `sl`, `sl_dist_pts`, `sl_dist_atr` | the prev_swing stop, its distance from the entry close (negative for a skipped SETUP), in ATR |

### `reg_*` regime from engine events with `i <= k` (H2; no look-ahead)
| column | definition |
|---|---|
| `reg_n_choch_since_bos` | CHoCH events after the last BOS (all CHoCHs when no BOS yet) |
| `reg_n_flip_since_bos` | of those, the ones that flipped the trend |
| `reg_n_bos_since_choch` | BOS events after the last CHoCH |
| `reg_bars_since_choch` | `k -` bar of the last CHoCH with `i <= k` (equals `reg_bars_since_own_choch` unless a later CHoCH landed on `k` itself) |
| `reg_bars_since_own_choch` | `k - ch` |
| `reg_bars_since_bos`, `reg_last_bos_dir`, `reg_last_bos_agree` | the last BOS: bars ago, its direction, 1 when it equals the SETUP direction (NaN / `none` when no BOS yet) |
| `reg_alt6` | direction changes between consecutive events among the last 6 events (0..5) |
| `reg_last6` | the last 6 events as `Cu Cd Bu …` (C = CHoCH, B = BOS, u / d), oldest first |
| `reg_n_choch_60`, `reg_n_bos_60`, `reg_n_choch_120`, `reg_n_bos_120` | events with `k - N < i <= k` |
| `reg_range20_atr`, `reg_range60_atr` | `(max high - min low)` over bars `k-N+1 .. k` (may cross the overnight), over `a` |
| `reg_session_range_atr`, `reg_pos_in_session_range` | the session's range up to `k` over `a`; where the close sits in it (0 = at the low) |
| `reg_range_since_choch_atr` | range over bars `ch .. k`, over `a` |
| `reg_prior_setups_today` | SETUPs earlier in the session |
| `reg_prior_closed_pts_today` | sum of `pts` of the session's Foundation trades that had **exited by `k`** (`exit <= k`); uses past outcomes only, causal |

### `vol_*` volume (H3; no look-ahead)
| column | definition |
|---|---|
| `vol_bar`, `vol_fm_na` | the SETUP bar's volume; 1 when unusable |
| `vol_ratio20`, `vol_ratio60`, `vol_med20_prior` | `bars_volume.csv` at `k` |
| `vol_sess_cumvol_ratio20s` | `bars_volume.csv` at `k` |
| `vol_max_ratio20_5`, `vol_max_ratio20_15` | max `vol_ratio20` over the last 5 / 15 bars ending at `k`, same session only |
| `vol_hv{2,3}_bars_ago` | `k - j` for the latest bar `j <= k` **in the same session** with `vol_ratio20 >= 2` / `>= 3`; NaN when none |
| `vol_hv{2,3}_dir` | that bar's direction (`up` close > open, `down`, `flat`, `none`) |
| `vol_hv{2,3}_agree` | 1 when that direction equals the SETUP direction |
| `vol_hv{2,3}_low_held`, `_high_held` | over bars `j+1 .. k`: no low below that bar's low / no high above its high (NaN when `j = k`) |
| `vol_hv{2,3}_ratio` | that bar's `vol_ratio20` |
| `vol_ratio20_at_choch`, `vol_max_ratio20_choch_to_k` | `vol_ratio20` at the CHoCH bar; its max over `ch .. k` |

### `lvl_*` levels (H4; no look-ahead)
| column | definition |
|---|---|
| `lvl_prot`, `lvl_prot_dist_atr`, `lvl_prot_dist_dir_atr` | the protected level at `k`; `(close - prot) / a`; `dir_sign x` that (positive = the level is behind the entry) |
| `lvl_choch_dist_dir_atr` | `dir_sign x (close - choch_lvl) / a`: how far beyond the broken level the SETUP closes |
| `lvl_n_rooms_alive` | ST7 rooms alive at `k` (`birth_bar <= k < retired_bar`) |
| `lvl_room_edge`, `lvl_room_edge_id`, `lvl_room_edge_kind` | the nearest edge (lo or hi) of any alive room |
| `lvl_room_edge_dist_atr`, `lvl_room_edge_dist_dir_atr` | `(edge - close) / a` (positive = edge above); `dir_sign x` that (positive = edge ahead) |
| `lvl_room_ahead_dist_atr`, `lvl_room_behind_dist_atr` | nearest alive-room edge strictly ahead / strictly behind in the trade direction, in ATR (NaN when none) |
| `lvl_last_sh`, `lvl_last_sh_dist_atr`, `lvl_last_sh_age` | the latest confirmed swing high (`conf <= k`): price, `(price - close) / a`, `k - swing bar` |
| `lvl_last_sl`, `lvl_last_sl_dist_atr`, `lvl_last_sl_age` | the latest confirmed swing low: price, `(close - price) / a`, age |
| `lvl_swing_near_kind`, `lvl_swing_near_dist_atr`, `lvl_swing_near_dist_dir_atr` | the nearer of those two |
| `lvl_swing_ahead_dist_atr` | the last swing high for a long / swing low for a short, in ATR ahead (can be negative when already beyond it) |
| `lvl_touch_{prot,room,swing}_n60` | touch episodes (runs of consecutive bars with `low <= L <= high`) of that level in bars `k-60 .. k-1` |
| `lvl_touch_{…}_last` | verdict of the last episode: `broke` = within 15 bars after it (never past `k`) a close beyond `L` on the far side by more than 0.5 x atr14 (at the episode's last bar); `held` = no such close and the 15-bar window closed by `k`; `pending` = window still open at `k`; `none` = no touch; `na` = no level / approach side undecidable. The approach side is the close before the episode (else its first open) |
| `lvl_touch_{…}_bars_ago` | `k -` the episode's last bar |

### `card_*` the ST7 card at the SETUP bar (no look-ahead)
The 29 card fields with prefix `card_` (see `card.csv`), plus:
`card_vol_ratio` (`this_vol / first_vol` when both live, else NaN), `card_bars_since_hunt`, `card_bars_since_reject`,
`card_hunt_dir_agree` (the ref room's latest HUNT pierce side equals the SETUP direction), `card_in_room` (`in_id` set),
`card_ref_room_live` (`zone_id` set), `card_room_lo` / `hi` / `mid` (the ref room's edges from the ledger),
`card_room_width_atr`, `card_room_pos` (`(close - lo) / (hi - lo)` when the close is inside the ref room, else NaN),
`card_room_pos_dir` (the same seen in the trade direction: 1 = at the edge ahead).

### `st7_*` the ST7 gate
As of the SETUP bar (no look-ahead): `st7_zone_kind`, `st7_band_lo`, `st7_band_hi`, `st7_level_in_band`, `st7_gate`,
`st7_block_reason`, `st7_branch`, `st7_take_why`, `st7_refused`, `st7_entered_zone_id`, `st7_entered_visit_n`,
`st7_entered_read`, `st7_leave_vol_ok`, `st7_leave_kind`, `st7_watch_kind`, `st7_watch_band_id`.
**POST (look-ahead, diagnostic only)**: `st7_outcome_gate`, `st7_watch_outcome`, `st7_reenter_reason`, `st7_fill_used`,
`st7_fill_bar`, `st7_fill_delay_bars`, `st7_edge_dist_pts`, `st7_armed_bars`, `st7_rearmed_bars`, `st7_sl_bar`, and
`st7_traded` (ST7 held a position on this SETUP: a TAKE, or a REENTER whose R5 was this SETUP, possibly filled later —
the kept / refused split `fz_report.permutation_p` uses).

### Labels (**LABEL**, never features)
`fnd_pts`, `fnd_slip_pts`, `fnd_gross`, `fnd_charges`, `fnd_net`, `win` (`fnd_net > 0`), `win_pts` (`fnd_pts > 0`),
`fnd_exit_reason`, `fnd_bars_held`, `fnd_mfe`, `fnd_mae`, `fnd_mfe_bar`, `fnd_mae_bar`, `fnd_exit_time`, `fnd_open` — from
`trades.csv`; NaN / empty for a skipped SETUP (`traded = 0`). `fwd_ret5`, `fwd_ret15`, `fwd_ret30` = `dir_sign x (close[k+N]
- close[k])` (clipped at the file end, may cross the overnight); `fwd_mfe30`, `fwd_mae30` = best / worst excursion in
the trade direction over bars `k+1 .. k+30`.

---

## Numbers (this build, 2026-09-29)

**Data.** 443,826 bars, 1,188 sessions (every one 375 bars, every one `front_month = 1`, no mixed days), 4 zero-volume
bars (`fm_na`). IS 1,026 sessions, OOS 162 sessions. First bar `2021-10-01 09:15:00`, last `2026-09-25 15:29:00`
(asserted in every stage).

**Engine (ST1 rules, whole file).** 130,843 swings, 39,608 events (8,054 CHoCH, 31,554 BOS), 5,326 SETUPs, 5,326 trades,
0 skipped (no wrong-side stop on this tape). Exit reasons: `next_choch` 3,614, `stop_loss` 1,711, `open` 1.

| Foundation book (lot 65, 5 pts slippage per side, ZERODHA_NFO_FUT) | IS | OOS |
|---|---|---|
| trades (= SETUPs) | 4,502 | 824 |
| sessions with a SETUP | 579 | 106 |
| sum of raw `pts` | +8,719.05 | +2,740.30 |
| `fnd_net` sum, INR | −4,150,085.95 | −741,841.63 |
| mean `fnd_net` | −921.83 | −900.29 |
| win rate (`fnd_net > 0`) | 15.19% | 15.53% |
| mean cost (charges + 650 slippage), INR | 1,047.72 | 1,116.46 |
| exits stop / choch / open | 1,421 / 3,081 / 0 | 290 / 533 / 1 |

**ST7 (rooms, frozen thresholds, `s0 = 0`).** 6,802 rooms, 2,644 watches, 875 positions (711 TAKE + 164 REENTER).
SETUPs by outcome gate TAKE / WATCH / BLOCK / REENTER = 711 / 2,644 / 1,807 / 164 (as of the SETUP bar: 711 / 2,644 /
1,821 / 150). TAKE branches: leave 573, defend 85, first_print 62 (+ 141 REENTER via `watch`). Block reasons: new 1,344,
leave_into_recycle 297, hunt_fade 291, clock 121, open_pierce 65. Card reads at SETUPs: LEAVE 2,074, PENDING 1,644, THIN
619, NEW 371, REJECT 192, ACCEPTED 166, FIRST_PRINT 147, RECYCLE 110, HUNT 3. Reads per bar over the file: LEAVE 190,693,
PENDING 61,016, THIN 52,054, NEW 48,306, FIRST_PRINT 34,717, REJECT 26,273, ACCEPTED 13,899, RECYCLE 13,160, HUNT 3,708.

| kept vs refused (Foundation outcome of the SETUPs ST7 held / did not hold, `st7_traded`) | IS | OOS |
|---|---|---|
| kept n / `fnd_net` sum | 745 / −767,263.78 | 130 / −35,660.99 |
| refused n / `fnd_net` sum | 3,757 / −3,382,822.17 | 694 / −706,180.64 |
| ST7's own positions n / net (`fz_trades.csv`, REENTER exits differ from Foundation's) | 745 / −768,595.80 | 130 / −34,763.95 |

No control percentile or permutation p is computed in this build (that is H1's job, with `fz_report.random_control` /
`permutation_p` on these files).

**Feature table.** 5,326 rows × 185 columns. Null shares worth knowing: `card_zone_id` (no ref room at the SETUP) 26.9%,
`card_room_pos` 64.0% (close not inside the ref room), `vol_ratio20` / `vol_ratio60` 3.1% (fewer than 5 prior bars in the
session), `vol_hv3_bars_ago` 15.4% and `vol_hv2_bars_ago` 9.0% (no such bar yet in the session), `lvl_prot` 3.0%,
`lvl_room_ahead_dist_atr` 8.5%, everything else under 1%; labels 0%. `reg_bars_since_choch == reg_bars_since_own_choch`
on 99.6% of rows (the rest: a later CHoCH landed on the SETUP bar). `reg_n_choch_since_bos` distribution: 0: 1,411, 1:
2,086, 2: 973, 3: 449, 4: 212, 5: 94, 6: 58, 7: 21, more: 22. Touch verdicts: protected level pending 4,937 / held 196 /
na 162 / broke 27 / none 4 (the protected level at a SETUP is a swing confirmed within the last bars, so its 15-bar window
is rarely closed: weak as built); room edge broke 2,237 / pending 1,261 / held 954 / none 872 / na 2; swing broke 3,202 /
pending 2,118 / held 6 (the nearest swing at a SETUP is usually the one the CHoCH just broke: definitional, not a
finding). Visibly-high-volume bars over the file: 30,956 bars with `vol_ratio20 >= 3` (7.0%). `hour_bin`: `<09:25` 229,
09 448, 10 708, 11 796, 12 862, 13 911, 14 946, 15 305, `>=15:20` 121.

**Run times / memory (4-core PC shared with another session).** Stage 1: `engine.load` 17 s (peak working set 571 MB,
the transient row dicts), `engine.run` 958 s (the per-bar loop over never-broken swings across five years), writes ~40 s;
its in-script summary crashed after all files were written (string cells summed), so `timing_01.json` was produced by
`01b_summary.py` from the files with the run times copied from the console log. Stage 2, run 1 with `engine.load`:
`fz.run` 53 s, card write 32 s, peak 1,021 MB (`fz_stats_run1_engineload.json`, `log_02_run1_engineload.txt`); run 2
with the lean `bars.csv` loader (the published files): `fz.run` 22 s, peak 892 MB, all seven outputs md5-identical to
run 1 (`md5_run1.txt`, `md5_run2_lean.txt`, `md5_diff.txt`). Stage 3: 41 s, peak 623 MB. One python process at a time
throughout; the repository was not written to.

**Provenance.** `strategies/strategy_7.json` `fz.minute` block (46 keys) as on disk 2026-09-29; `fz.py`, `fz_exec.py`,
`engine.py`, `lab.py` as on disk (uncommitted working tree of branch `research/strategy-lab`, HEAD 49cb666).
