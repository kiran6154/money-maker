# S8 + corrected-ladder measurement (the "s4b" pair)

**Date:** 2026-08-31 · **Window:** 2024-01-01 → 2024-01-31 · **Executor:** main session (Fable), directly.

## What changed since the last baseline

Baseline = the S5 Arm After ledger (21 trades, −127.40/share; pct bracket live,
ladder seeded, old close-tested exits). One build added, all signed off
2026-08-31: **S8** (stale strike keys skipped — tick-stamped cache),
**resting-order stop model** (floors = SL orders: breach on the bar's adverse
extreme, fill AT the floor, adverse-first within a bar, peaks from the
favorable extreme), **S9** (force-close sweep widened — inert on a replay),
**S11a** (09:16 cron gated — inert on these runs). DB wipes and the ladder
column toggle were executed by the user via `analysis/db-scripts/*.bat`
(the permission classifier blocks table writes for the agent).

## Results

| | Baseline (pre-fix) | Ladder ON (corrected) | Ladder OFF |
|---|---:|---:|---:|
| Trades | 21 | 19 | 15 |
| Total P&L (per share) | −127.40 | **+80.94** | **+85.29** |
| Mean P&L / trade | −6.07 | +4.26 | +5.69 |
| Winners / losers | 9 / 12 | 15 / 4 | 9 / 6 |
| TARGET | 7 | 7 (+218.95) | 7 (+253.95) |
| TRAIL_SL | 4 (red-heavy) | 6 (**+12.00 total, none red**) | — |
| STOP_LOSS | 5 | 3 (−118.76) | 3 (−118.76) |
| SIGNAL | 5 | 3 (−31.25) | 5 (−49.90) |

Per lot (×75): −9,555 → +6,070.50 (ON) / +6,396.75 (OFF). Charges not modelled.

## Reading

1. **S8 is the driver of the sign flip.** The app log recorded **8,296
   stale-strike-key skips** over the month — the frozen-series bug was not the
   single observed incident but a constant background contaminant of entries.
   With it gone, the same strategy, bracket and window flip from −127.40 to
   +85.29 (ladder-off).
2. **The corrected ladder is no longer harmful — it is a smoothing trade.**
   Under the old close-tested model it cost 258 points against no-ladder; under
   the resting-order model it costs **4.35** points of total P&L in exchange
   for a much steadier profile (15/4 vs 9/6 win/loss; every trailing exit
   green, floor fills exact). Keep/drop is now a risk-preference decision.
3. **Floor fills verified**: all 6 TRAIL_SL exits book small positives
   (+12.00 combined) — the red trailing exits the old model produced are gone
   by construction. STOP_LOSS exits are identical in both arms (−118.76),
   filling exactly at the stop.
4. **Attribution caveat**: the jump from baseline bundles S8 with the exit
   model (single build). Entry-set differences are S8's (only it changes which
   entries fire); exit-price differences on shared trades are the model's.
   S9/S11a are inert on a replay by construction.
5. **Parity caveat (S12)**: the backtest now assumes live rests SL orders at
   the broker. Live does not do that yet — do not run the ladder live until
   S12 lands.

## Files

- `run-ladder-on.tsv`, `run-ladder-off.tsv` — full ledger exports.
- `app.log` (ladder-ON run; contains the 8,296 skip lines), `app-off.log`.
- End state: user restores the ladder columns via
  `analysis/db-scripts/2-restore-ladder.bat`; ladder-OFF ledger left in
  `trade_order` until the next run.
