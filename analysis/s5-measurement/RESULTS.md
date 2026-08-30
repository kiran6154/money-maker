# S5 measurement — session-window unification, paired ledger diff

**Date:** 2026-08-31 · **Window:** 2024-01-01 → 2024-01-31 · **Executor:** main session (Fable), directly.

## Question

Does deriving the session times from `MarketHoursService` + `app.market.*` (with
offset defaults chosen to reproduce the legacy constants — close signal 15:15,
replay bounds 09:20–15:20) change the ledger? The sign-off condition was an
**empty** per-order diff: unification, not retuning.

## Setup

- Identical config state both arms: 18 window configs, pct bracket live
  (`target_pct=0.20` / `sl_pct=0.30`), ladder seeded (`60` /
  `25:2,50:25,75:50,100:75`). Verified by SELECT before each arm.
- `trade_order` and `journal_observation` wiped between arms (run by the user —
  the permission classifier blocks table clears for the agent).
- One variable: the S5 code change. Arm Before = HEAD `3b456f6` unchanged
  (jar 01:19); Arm After = same tree + the S5 change (jar 01:35).
- Both arms ran with journal MONITOR/EVENT capture active (first build to
  include it), 1047/1047 ticks OK, ~36 s per arm on the cached pipeline.
- Backtest login preflight reported `INTERACTIVE_REQUIRED` (dead Zerodha
  session at 01:30); the replay reads the local historical tables and ran
  regardless.

## Result

| | Arm Before (constants) | Arm After (derived) |
|---|---:|---:|
| Trades | 21 | 21 |
| Total P&L (per share) | −127.40 | −127.40 |
| SIGNAL / TARGET / STOP_LOSS / TRAIL_SL | 5 / 7 / 5 / 4 | 5 / 7 / 5 / 4 |
| Per-order diff (all columns except autoincrement id) | — | **EMPTY** |

**S5 resolved: the unification is not a behaviour change.**

## Side verdicts

1. **S11 part (b) — cron-interference audit.** Arm Before, on the post-GAPS #4
   build, reproduced the recorded S6 Arm B ledger **byte-identically modulo
   id**. The S4 / S6 / S7 / S8 numbers recorded for this window are confirmed
   uncontaminated by the pre-fix wall-clock crons.
2. **Journal is inert w.r.t. trades**, now shown on a full replay, not just unit
   tests: S6 Arm B ran *without* MONITOR/EVENT capture, these arms ran *with*
   it, and the ledgers are identical.
3. **First journal volume data** (per month of replay): 9,289 CANDIDATE /
   21 ENTRY / 261 MONITOR / 77 EVENT / 21 EXIT.

## Files

- `run-before-ledger.tsv`, `run-after-ledger.tsv` — full exports, both arms.
- `trade_order-preexisting-s6-armB.csv` — the 145 rows exported before the
  first wipe (S6 Arm B + a foreign Jan–Jun replay from a peer session).
- `app-armA.log`, `app-armB.log` — app logs; armB's startup line shows
  `close-signal=15:15, replay=09:20-15:20` derived from config.

## End state

- The S5 change is **kept** (committed with this file).
- `trade_order` holds Arm After's 21 rows; DB config state unchanged.
- App left running on :8080 on the Arm After build.
