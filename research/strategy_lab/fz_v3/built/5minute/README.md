# FZ v3 study, 5-minute data build (built 2026-09-29, script `build_5m.py`)

Foundation (ST2 rules) + FZ v2 rooms (ST8 `fz.5minute` block) over the whole 5-minute near-month file, every table written
here as CSV and parquet. Nothing under the repository was written (bytecode off; `lab` imported only for `trade_charges`
and `atr_series`). `lab.sessions()` was not used: the file was loaded in full with `engine.load(path, "2021-10-01",
"2026-09-25", warmup_days=0)` and the build asserts the first bar is `2021-10-01 09:15:00` and the last `2026-09-25 15:25:00`.

## Definitions (fixed before any number was read)

| item | value |
|---|---|
| data file | `D:/nifty/niftyfut_nearmonth_5minute_2021-10-01_to_2026-09-25.csv`, sha1[:16] in `meta.json`; 88,771 bars, 1,188 sessions; `front_month` = 1 on every row; 2 zero-volume bars (`fm_na`) |
| engine rules | ST2 (`strategies/strategy_2.json`): `break_mode touch`, `choch_mode touch`, `avwap_weight volume`, `sl_rule choch_candle`; `engine.run` on all 88,771 bars, `s0 = 0` |
| FZ | ST8 (`strategies/strategy_8.json` `fz.5minute`, thresholds via `fz.thresholds`, copied into `meta.json`); memory from bar 0 (as `lab.py` does for FZ rows); `fm_na = front_month == 0 or volume == 0`; `atr14 = lab.atr_series` (Wilder 14, seeded with a simple mean); `fz_exec.opener` / `build_trades` with `choch_candle`, touch |
| unit of analysis | one Foundation SETUP (`engine.run` `setups`) with its own engine trade (`trades`): entry at the SETUP bar close, exit at the stop (touch: worse of the candle open and the stop; a session's first candle: its close) or at the close of the next CHoCH bar, else `open` at the data end. **No 15:25 square-off, no contract-expiry cap, no strike lock** (these are lab pricing rules, not engine rules): 358 of 1,012 trades are held past the entry session and 35 cross a contract roll (the file's price jump is inside `pts`) |
| costs | `lab.price_trade` mirrored: slippage 5 pts per side (`types.FUT.slippage_pts`), lot 65, charges `lab.trade_charges(ZERODHA_NFO_FUT, buy, sell, 65)` on the slipped prices. `net_inr = gross_inr - charges_inr = pts x 65 - cost_inr`, `cost_inr = charges_inr + 650`. Median cost 1,075 INR (962 .. 1,147; charges 312 .. 497 + 650 slippage); on OOS price levels 1,112 INR, the same order as the 1,114 INR the brief quotes for 1m |
| IS / OOS | by the SETUP (or trade entry) date: IS = 2021-10-01 .. 2025-12-31 (1,026 sessions, 832 SETUPs), OOS = 2026-01-01 .. 2026-09-25 (162 sessions, 180 SETUPs). Column `split` on every row |
| warm-up | `in_warmup = session_idx < 5` (ST2 / ST8 `warmup_days`), flagged, not dropped (9 SETUPs) |
| win | `net_inr > 0` |

## Counts (from `meta.json`)

| | IS | OOS | ALL |
|---|---|---|---|
| sessions / bars | 1,026 / 76,621 | 162 / 12,150 | 1,188 / 88,771 |
| SETUPs = Foundation trades (engine-skipped 0) | 832 | 180 | 1,012 |
| Foundation net INR (wins / n) | -230,262 (184 / 832), mean -277 | -190,753 (37 / 180), mean -1,060 | -421,015 (221 / 1,012), mean -416 |
| Foundation exits next_choch / stop_loss / open | 403 / 429 / 0 | 87 / 92 / 1 | 490 / 521 / 1 |
| ST8 gate at the SETUP bar TAKE / WATCH / BLOCK / REENTER | 228 / 384 / 219 / 1 | 41 / 92 / 47 / 0 | 269 / 476 / 266 / 1 |
| ST8 outcome_gate TAKE / WATCH / BLOCK / REENTER | 228 / 288 / 219 / 97 | 41 / 65 / 47 / 27 | 269 / 353 / 266 / 124 |
| ST8 positions TAKE + REENTER, net INR | 228 + 97 = 325, -140,291 | 41 + 27 = 68, -105,764 | 269 + 124 = 393, -246,055 |
| BLOCK reasons new / open_pierce / clock / hunt_fade | 159 / 31 / 11 / 18 | 39 / 3 / 4 / 1 | 198 / 34 / 15 / 19 |
| reads at SETUP (ALL) | LEAVE 568, PENDING 247, NEW 96, THIN 58, RECYCLE 15, FIRST_PRINT 10, REJECT 8, ACCEPTED 5, HUNT 5 | | |

Engine: 26,578 swings, 7,950 events (1,532 CHoCH, 6,418 BOS). FZ: 4,673 rooms, 14,177 visits, 476 watches.

## Run times (`run_times.json`, one python process, well under 1 GB)

load 5.8 s, `engine.run` 50.9 s, trade pricing 0.1 s, `fz.run` 11.3 s, `build_trades` 0.1 s, features 20.5 s, write 35.4 s; total 124.4 s.
The truncated causality run (67,192 bars) took 66 s.

## Causality check (done, `build_5m.py --truncate "2025-06-30 12:00:00"`, folder `trunc_20250630_120000/`)

The same build on the bars up to 2025-06-30 12:00 (bar 67,191, mid-session) was diffed against the full build: for the 718
SETUPs at or before the cut all 143 as-of feature columns are identical, and so are `bars` (atr14, prot, session index),
`fz_card`, the as-of columns of `fz_ledger`, `events` (except the final-state `window_end`), `swings` (except
`broken_final`), the 717 Foundation trades and the 284 FZ positions that had exited by the cut. Only the one trade still
open at the cut differs, in its `fnd_*` label columns. So nothing in the as-of columns depends on bars after the SETUP bar.

## Look-ahead vocabulary used below

- **as-of**: computed from bars `<= setup_i` (and engine / FZ state as of that bar's close). Usable as a feature.
- **label**: uses bars after the SETUP bar. Never a feature.
- **post-SETUP**: an FZ ledger field written after the SETUP bar (what the gate / watch did later). Never a feature.
- **final-state**: a value that keeps changing until the data end (a swing's `broken` flag, a room's retirement). Use only through a bar-indexed condition (`birth_bar <= k`, `retired_bar is None or > k`).

## `features.csv` / `.parquet` (1,012 rows, one per Foundation SETUP, 186 columns)

`sg` = +1 for `dir = up`, -1 for `dir = down`; `k` = `setup_i`; prices in futures points; `NaN` = not defined (structural).

### identity (as-of)
| column | definition |
|---|---|
| `setup_i` | bar index of the SETUP (0-based over the file) |
| `time`, `date` | the bar's open-time label / its date |
| `session_idx` | 0-based session number over the 1,188 sessions |
| `session_bar` | 0-based bar number within the session (bar 0 opens 09:15) |
| `hhmm`, `hour` | the bar's open-time label `HH:MM` and its hour |
| `minute_of_session` | `session_bar x 5` |
| `dow` | weekday, 0 = Monday |
| `dir` | SETUP direction `up` / `down` (long / short futures) |
| `choch_i`, `choch_time` | the CHoCH bar the SETUP belongs to (engine `setups[].ch`) |
| `bars_since_choch` | `setup_i - choch_i` |
| `choch_flip` | that CHoCH flipped the engine trend (engine event `flip`) |
| `choch_trend_before` | engine trend before that CHoCH: 1 up, -1 down |
| `choch_same_session` | the CHoCH bar is in the SETUP's session |
| `open`, `high`, `low`, `close` | the SETUP bar's OHLC (the entry is at `close`) |
| `contract` | futures contract of the bar (from the file) |
| `days_to_expiry` | calendar days from `date` to the file's `expiry` of that bar |
| `split` | `IS` (date <= 2025-12-31) / `OOS` |
| `in_warmup` | `session_idx < 5` |

### Foundation stop (as-of)
| column | definition |
|---|---|
| `sl` | `choch_candle` stop: the CHoCH candle's low (up) / high (down) |
| `sl_dist_pts` | `sg x (close - sl)`; positive = the stop is on the loss side (always, on 5m) |
| `sl_dist_atr` | `sl_dist_pts / atr14` |
| `engine_skipped` | the engine skipped the SETUP for a wrong-side stop (0 rows on 5m: by construction the SETUP close is beyond the CHoCH candle) |

### price window (as-of)
| column | definition |
|---|---|
| `atr14` | Wilder ATR(14) on the futures bars including the SETUP bar (`lab.atr_series`) |
| `range12_pts`, `range36_pts` | max high - min low over the last 12 / 36 bars including the SETUP bar (1 h / 3 h, counted across the session break) |
| `range12_atr`, `range36_atr` | the above / `atr14` |
| `bar_range_pts`, `bar_body_pts`, `bar_range_atr` | `high - low`, `close - open`, `(high - low) / atr14` of the SETUP bar |
| `close_pos_in_bar` | `(close - low) / (high - low)`; NaN when `high == low` |
| `sess_open` | the session's first bar open |
| `close_vs_sess_open_pts` | `close - sess_open` |
| `sess_range_sofar_pts`, `sess_range_sofar_atr` | session high - low over bars up to `k`; / `atr14` |
| `close_pos_in_sess_range` | `(close - session low so far) / (session range so far)` |
| `gap_pts`, `prev_close` | `sess_open - previous session's last close`; that close (NaN in the first session) |
| `ret_6_pts`, `ret_12_pts`, `ret_36_pts` | `close - close 6 / 12 / 36 bars earlier` (across sessions) |

### regime from engine events (as-of; events with bar `<= k`, the SETUP's own CHoCH included; a CHoCH on the SETUP bar itself is included)
| column | definition |
|---|---|
| `n_events_asof` | events (BOS + CHoCH) up to `k` |
| `n_choch_since_bos` | CHoCH events after the last BOS (all CHoCHs when there is no BOS yet); `>= 2` = "CHoCH, CHoCH, no BOS" |
| `n_bos_since_choch` | BOS events after the last CHoCH |
| `n_flip_choch_since_bos` | those CHoCHs that flipped the trend |
| `bars_since_bos` | `k -` bar of the last BOS (NaN before the first BOS) |
| `last_bos_dir` | direction of the last BOS |
| `last_bos_same_session` | the last BOS is in the SETUP's session |
| `bars_since_prev_choch` | `k -` bar of the CHoCH before the latest one (NaN with fewer than 2 CHoCHs) |
| `last_choch_dir` | direction of the latest CHoCH (the SETUP's own, unless one sits on bar `k`) |
| `alternations_last6` | kind changes (BOS<->CHoCH) among the last 6 events |
| `last6_kinds` | the last 6 events as a string of `C` / `B`, oldest first |
| `choch_run` | consecutive CHoCH events at the end of the event list |
| `n_events_last_36`, `n_choch_last_36` | events / CHoCHs in the last 36 bars |
| `n_events_today`, `n_choch_today`, `n_bos_today` | events / CHoCHs / BOS in the SETUP's session up to `k` |

### volume (as-of)
| column | definition |
|---|---|
| `vol` | the SETUP bar's volume |
| `vol_med20`, `vol_med60` | median volume of the previous 20 / 60 bars (excluding the SETUP bar, across the session break) |
| `vol_ratio20`, `vol_ratio60` | `vol / vol_med20`, `vol / vol_med60` |
| `vol_na` | `front_month == 0 or volume == 0` on the SETUP bar |
| `hv3_bars_since` | `k - j` where `j` is the latest bar in the same session, `j <= k`, with `volume >= 3 x median(volume of its previous 20 bars)` (at least 5 previous bars, `j` not vol-NA); NaN when there is none this session (140 SETUPs) |
| `hv3_dir` | that bar's close vs open: `up` / `down` / `flat` |
| `hv3_dir_agree` | `hv3_dir == dir` |
| `hv3_ratio` | that bar's volume / its 20-bar median |
| `hv3_high_held` | no bar in `j+1 .. k` has a high above that bar's high |
| `hv3_low_held` | no bar in `j+1 .. k` has a low below that bar's low |
| `sess_vol_vs_prev_sess` | session volume up to `k` / the previous session's volume over the same number of bars (NaN in the first session) |

### levels (as-of)
| column | definition |
|---|---|
| `prot_lvl` | engine protected level as of bar `k` (NaN for 17 SETUPs) |
| `dist_prot_pts`, `dist_prot_atr` | `sg x (close - prot_lvl)`; / `atr14` |
| `last_sh_px`, `last_sl_px` | the latest swing high / low confirmed at or before `k` (engine `sw`, by `conf`) |
| `dist_sh_pts` | `last_sh_px - close` (positive: the swing high is above) |
| `dist_sl_pts` | `close - last_sl_px` (positive: the swing low is below) |
| `last_sh_bars_ago`, `last_sl_bars_ago` | `k -` the swing's own bar (not its confirmation bar) |
| `choch_lvl` | the protected level the SETUP's CHoCH broke |
| `dist_choch_lvl_pts`, `dist_choch_lvl_atr` | `sg x (close - choch_lvl)`; / `atr14` |
| `n_swings_last_36` | swings confirmed in the last 36 bars |
| `choch_bar_range`, `choch_bar_range_atr` | the CHoCH candle's high - low; / `atr14` at `k` |
| `move_since_choch_pts` | `sg x (close - close of the CHoCH bar)` |

### session ledger as of the bar (as-of; only trades that have exited by `k` count)
| column | definition |
|---|---|
| `today_n_closed_asof` | Foundation trades of this session with `entry < k` and `exit <= k` |
| `today_net_asof` | their `net_inr` sum |
| `today_n_stops_asof` | how many of them exited on the stop |
| `today_n_setups_before` | SETUPs earlier in this session |
| `last_closed_net_asof`, `last_closed_reason_asof` | the latest such trade's net / exit reason (NaN when none) |

### FZ card at the SETUP bar (`card_*`, as-of; see FZ.md section 7)
`card_out_run`, `card_out_side` (closes outside the ref band and their side), `card_wick_depth`, `card_cluster_sit` (the last
4 closes sit within 20 pts), `card_prev_bars`, `card_prev_vol` (the previous visit), `card_last_leave_failed`, `card_touches`,
`card_last_hunt_at`, `card_last_hunt_dir`, `card_last_reject_at`, `card_last_reject_dir` (the ref band's latest HUNT / REJECT,
bar index and side), `card_leave_side`, `card_first_clock_lived`. NaN when there is no ref band (398 SETUPs).

### FZ ledger as of the SETUP bar (`fz_*`, as-of; see FZ.md section 8)
| column | definition |
|---|---|
| `fz_zone_id`, `fz_zone_kind`, `fz_band_lo`, `fz_band_hi` | the ref room (the one holding the live visit) and its edges; NaN when none |
| `fz_visit_n`, `fz_this_bars`, `fz_this_vol`, `fz_first_bars`, `fz_first_vol`, `fz_vol_na`, `fz_first_vol_na` | the live visit's number, inside closes and volume; the room's first visit; NA flags |
| `fz_read` | LEAVE / HUNT / REJECT / FIRST_PRINT / ACCEPTED / THIN / RECYCLE / PENDING / NEW |
| `fz_left_id` | the room whose LEAVE is live |
| `fz_in_id` | the room containing the close (NaN in open ground) |
| `fz_level_in_band` | the CHoCH level lies inside the ref room |
| `fz_gate` | the gate decision **as of the SETUP bar**: TAKE / WATCH / BLOCK / REENTER (REENTER only when the watch step re-entered on this very bar: 1 row) |
| `fz_block_reason` | in_position / clock / open_pierce / hunt_fade / new (BLOCK rows; also `leave_into_recycle` on a refused branch-1 LEAVE) |
| `fz_branch`, `fz_take_why` | the TAKE branch (leave / first_print / defend / watch) or why a branch was refused |
| `fz_entered_zone_id`, `fz_entered_visit_n`, `fz_entered_read` | on a LEAVE read: the room the close entered and its read |
| `fz_leave_vol_ok`, `fz_leave_kind` | the LEAVE's R4 volume check (None when NA) and kind (normal / gap) |
| `fz_watch_kind`, `fz_watch_band_id` | the watch this SETUP opened (WATCH / WATCH_EDGE) and its room |
| `fz_band_width` | `band_hi - band_lo` |
| `fz_pos_in_band` | `(close - band_lo) / (band_hi - band_lo)` |
| `fz_dist_band_edge_ahead` | `band_hi - close` (up) / `close - band_lo` (down): room left in the trade direction |
| `fz_dist_band_edge_behind` | `close - band_lo` (up) / `band_hi - close` (down) |

### FZ ledger written after the SETUP bar (`fzpost_*`, **post-SETUP, never a feature**)
`fzpost_outcome_gate` (how the SETUP ended: a WATCH that a later REENTER used reads REENTER), `fzpost_refused` (0 rows on 5m),
`fzpost_watch_outcome`, `fzpost_reenter_reason`, `fzpost_fill_used`, `fzpost_fill_bar`, `fzpost_fill_delay_bars`,
`fzpost_edge_dist_pts`, `fzpost_armed_bars`, `fzpost_rearmed_bars`, `fzpost_sl_bar`.

### labels (**forward-looking, never a feature**)
| column | definition |
|---|---|
| `fwd_ret_5_pts`, `fwd_ret_15_pts`, `fwd_ret_30_pts` | `close[k + N] - close[k]` (across the session break; NaN past the data end) |
| `fwd_ret_N_dir_pts` | `sg x` the above (positive = in the SETUP's favour) |
| `fnd_traded` | the engine took the SETUP (always true on 5m) |
| `fnd_exit_i`, `fnd_exit_time`, `fnd_exit_px`, `fnd_exit_reason` (`next_choch` / `stop_loss` / `open`), `fnd_open` | the Foundation trade's exit |
| `fnd_pts` | engine points before slippage: `sg x (exit_px - close)` |
| `fnd_gross_inr` | after slippage: `(sell - buy) x 65` |
| `fnd_charges_inr`, `fnd_slip_inr` (= 650), `fnd_cost_inr` (= charges + slip) | costs |
| `fnd_net_inr` | `fnd_gross_inr - fnd_charges_inr = fnd_pts x 65 - fnd_cost_inr` |
| `fnd_win` | `fnd_net_inr > 0` |
| `fnd_bars_held`, `fnd_sessions_held`, `fnd_crosses_roll` | exit - entry in bars / sessions; contract at exit differs from entry |
| `fnd_mfe_pts`, `fnd_mae_pts` | best / worst excursion on wicks over bars `entry+1 .. exit`, in the trade direction, before slippage |
| `fzpos_kind`, `fzpos_entry_i`, `fzpos_entry_time`, `fzpos_exit_i`, `fzpos_exit_time`, `fzpos_exit_reason`, `fzpos_pts`, `fzpos_net_inr` | the ST8 position opened on this SETUP (TAKE on the SETUP bar, or the REENTER that used it as R5, possibly filled later); NaN when none |

## Other tables

| file | rows | columns and look-ahead status |
|---|---|---|
| `bars` | 88,771 | `i, datetime, date, session_idx, session_bar, open, high, low, close, volume, oi, contract, expiry, front_month, fm_na, atr14, prot, split, in_warmup`. All as-of (`prot` = engine protected level as of the bar) |
| `sessions` | 1,188 | `session_idx, date, split, in_warmup, n_bars, front_month, contract` |
| `swings` | 26,578 | `seq, kind (H/L), bar, time, price, conf_bar, conf_time` as-of from `conf_bar`; `broken_final` is **final-state** |
| `events` | 7,950 | `seq, i, time, kind (BOS/CHoCH), dir, flip, lvl, av, trend_before, sh_bar, sh_px, sl_bar, sl_px` as-of at bar `i` (CHoCH-only fields NaN on BOS rows); `window_end` (the next CHoCH's bar) is **final-state** |
| `setups` | 1,012 | `setup_i, time, dir, choch_i, choch_time, engine_skipped` |
| `skipped` | 0 | engine wrong-side-stop skips (none on 5m) |
| `trades` | 1,012 | Foundation trades priced: `entry_i, entry_time, date, session_idx, dir, choch_i, choch_time, entry_px, sl, exit_i, exit_time, exit_px, exit_reason, open, pts, pts_x_lot, gross_inr, charges_inr, slip_inr, cost_inr, net_inr, win, bars_held, sessions_held, crosses_roll, contract, mfe_pts, mae_pts, split, in_warmup`. Outcome columns are labels |
| `fz_trades` | 393 | ST8 positions (`fz_exec.build_trades`) priced the same way, plus `gate (TAKE/REENTER), setup_i, zone_id, fill_used, reenter_reason, sl_bar, sl_in_band` |
| `fz_card` | 88,771 | `i, time` + the fz.run card per bar (`zone_id, visit_n, this_bars, this_vol, vol_na, first_bars, first_vol, first_vol_na, read, left_id, out_run, out_side, session_bar, gap_pts, wick_depth, last_hunt_at, last_hunt_dir, last_reject_at, last_reject_dir, cluster_sit, prev_bars, prev_vol, last_leave_failed, in_id, leave_side, leave_vol_ok, leave_kind, first_clock_lived, touches`). All as-of, never rewritten |
| `fz_ledger` | 1,012 | fz.run's SETUP rows verbatim (`i, time, dir, choch_i, ... sl_bar`); as-of up to `watch_band_id`, post-SETUP: `outcome_gate, refused, watch_outcome, reenter_reason, fill_used, fill_bar, fill_delay_bars, edge_dist_pts, armed_bars, rearmed_bars, sl_bar` |
| `fz_zones` | 4,673 | rooms: `id, kind, lo, hi, mid, origin_bar, birth_bar, born_ts` (as-of from `birth_bar`); `merges, n_visits, touches, retired_bar, retired_by, retired_ts` are **final-state** (alive at `k` = `birth_bar <= k` and (`retired_bar` NaN or `> k`)) |
| `fz_visits` | 14,177 | `zone_id, visit_n, start, start_time` as-of from `start`; `end, end_time, ended_by, bars, vol, vol_na, entry_dir, touch, defend_dir` are **final-state** for that visit |
| `fz_watches` | 476 | `opened_at, opened_time, band_id, dir, kind, opened_by_read, setup_i` as-of at `opened_at`; `outcome, outcome_bar, outcome_time, armed_at, last_armed_at` post-open |
| `fz_stats.json` | | fz.run counters over the whole file (`s0 = 0`) |
| `meta.json` | | provenance: data sha, code sha1[:16] of `engine.py / fz.py / fz_exec.py / fz_report.py / lab.py`, script sha, the fz thresholds, charges, the counts above, run times |
| `run_times.json` | | the laps |
| `build_5m.log`, `build_5m_trunc.log` | | console output of the full and the truncated build |
| `trunc_20250630_120000/` | | the truncated build used for the causality check (same files) |

## Caveats

- The Foundation trade here is the engine's trade, not the lab's priced FUT book: no 15:25 square-off (ST2's lab book has one; ST8's does not), no cap at the contract's last candle, no strike lock. A study that wants intraday-only outcomes must cut at 15:25 itself (bars and times are all here).
- `fz_gate` REENTER at the SETUP bar occurs once (a watch re-entered on the SETUP bar itself); the 123 other REENTERs sit on WATCH rows and show only in `fzpost_outcome_gate` / `fzpos_*`.
- The all-NA comparator (`lab.run_fz`'s second gate run with volume NA on every bar) was not built.
- `hv3_*` uses one fixed definition (3 x median of the previous 20 bars, same session); the H3 grid (v in 2, 3, 4; N in 20, 60) must be computed from `bars` directly.
- The 5-minute file ends each session at 15:25; the bar label is the open time.
- `engine.run` on the full 5m file takes ~51 s; `fz.run` ~11 s; the whole build ~2 min. The process stays far below 1 GB.
