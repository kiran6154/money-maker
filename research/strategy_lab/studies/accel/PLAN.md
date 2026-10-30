# S55 — NIFTY acceleration → option expansion: study plan (DRAFT, for review; nothing has run)

Follow-up to the wave study (S54, `studies/waves/`), which found the option "staircase" is NIFTY × delta (≈ 85 %)
+ gamma, reproduced by shuffled bars, and not predictive. The question moves to the cause:

> When NIFTY starts a directional acceleration, can it be detected early enough, from past bars only, that the
> continuation beats the option's own hurdle (theta plus the expiry-day asymmetry) for the DTE of the day?

Research only; no strategy bean, no `TradeConfig`, no orders. Rule 0 entry: `docs/STRATEGY_ANALYSIS_TODO.md` S55.

## 1. Data

| Source | Use |
|---|---|
| `D:/nifty/niftyfut_nearmonth_{minute,5minute}_2021-10-01_to_2026-09-25.csv` (O/H/L/C, volume, OI, contract, front_month) | the signal and the NIFTY outcome. Futures, not the index: the index has no volume and the Breeze index file is corrupt at 09:15 / 15:20 (c2c A1) |
| Option folders used by S54 (2024 5-min chain, 2025–26 1-min 5 strikes) | step 2 only: the real option outcome, strike from the futures price at the signal on the 100-pt grid, strike-list hindsight flag as in S54 |
| S54 DTE response table (`waves/results/dte_*.json`) | step 1 translation of a NIFTY move into an option move by DTE |

Audit first, before any outcome: bar ranges, 09:15 and 15:20 anomalies, roll days (front_month switch), missing
sessions, cross-check of 5-minute bars against resampled 1-minute bars.

## 2. Periods (proposed)

**User decision 2026-09-30:** development 2024, validation 2025, blind 2026-01 → 2026-09 (the S54 split, directly
comparable). 2021-10 → 2023-12 futures data is left untouched by this study (a reserve for a later confirmation).
Scope: NIFTY test + real options (2024–26). Go-ahead given.

## 3. Signals (all causal; parameters with a pre-registered neighbourhood, nothing chosen by result)

Units: ATR = mean log true range of the previous 20 bars; volume ratio VR_tod = volume / median volume of the same
bar-of-day over the previous 10 sessions (the 09:15 volume spike is normalized away).

| Code | Signal |
|---|---|
| A | every eligible bar (base rate) |
| M | momentum-matched control: bars with the same trailing L-bar return decile, hour, weekday-to-expiry |
| P | price acceleration: L-bar log return > a · ATR · √L, and the second half of the window moved more than the first |
| V | volume only: VR_tod ≥ v |
| PV | P and V on the same bar (the "volume-backed acceleration" hypothesis) |
| C | compression → expansion on NIFTY itself (the S54 detector, run on futures) |
| O | opening-range break (first 15 min) as a common-practice benchmark |

Primary cell on 5-minute: L = 6 (30 min), a = 1.5, v = 1.5. Grid: L 4 / 6 / 8, a 1.0 / 1.5 / 2.0, v 1.25 / 1.5 / 2.0.
Also 1-minute with the same bar counts (not re-tuned). Signals 09:20 → 15:00.

## 4. Outcomes

- NIFTY: forward log return at 5, 15, 30, 60 min and to close, signed in the signal's direction; hit rate for
  ±0.10 / 0.25 / 0.50 %; P(+x before −x); MFE / MAE.
- Option (translation): each event's forward NIFTY move run through the measured ATM response of its DTE bucket
  (includes drift and asymmetry), giving the required vs achieved hit rate per DTE bucket. S54 measured: ≈ 50 % needed at
  DTE 3–4, ≈ 59 % on expiry day (±0.25 %, before costs).
- Option (real, 2024–26 only): ATM at the signal, entry at the signal close, exit at 30 min and at close, full costs as S54.

## 5. Hypotheses and decision rule (fixed before validation opens)

- H1: PV's 30-minute directional excess over M > 0, week-clustered bootstrap CI, in validation and blind.
- H2: PV beats P (volume adds information) — the volume-profile question.
- H3: the achieved hit rate clears the DTE hurdle in at least one DTE bucket, in both periods, after costs.
- Nulls: bars shuffled within session (as S54); volume shuffled within session; label permutation within matched cells.
- Verdict classes as S54 (1 strong / 2 structure, not tradable / 3 no structure / 4 inconclusive), with a power check
  on development before validation opens.

## 6. Process

1. Data audit → ledger. 2. Code + tests (truncation / no-look-ahead) on development only. 3. Freeze by SHA-256.
4. Validation and blind once. 5. Report + event CSV + page, same format as S54. Heavy steps run one at a time
(shared machine, 7.9 GB).

Estimated files: `studies/accel/{PREREG,LEDGER,REPORT}.md`, `data.py`, `detect.py`, `study.py`, `test_*.py`, results/.
