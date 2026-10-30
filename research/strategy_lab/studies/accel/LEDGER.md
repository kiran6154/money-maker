# S55 NIFTY acceleration study — ledger

Append-only. Design: [`PREREG.md`](PREREG.md) (hashed before any forward outcome). Plan and user decisions: [`PLAN.md`](PLAN.md).
Rule 0 entry: `docs/STRATEGY_ANALYSIS_TODO.md` S55.

## 2026-09-30 — user decisions
Periods 2024 dev / 2025 validation / 2026 blind (the S54 split); scope NIFTY test + real options; go-ahead given.

## 2026-09-30 — data audit (prices / volume only, `audit.py`, `results/audit.json`)
- Near-month futures 2024-01 → 2026-09-25: 639 sessions; 5-minute file identical to resampled 1-minute (100 %).
- Contract rolls only at session boundaries (30 roll days), never intraday.
- Short special sessions 2024-03-02, 2024-05-18, 2025-10-21 → excluded. Largest bars are real (2024-06-04 election
  result, 2025-05-12 gap, 2026-02-03), kept.
- Volume U-shape: 5-minute median 290k at 09:15, 40k at noon, 164k at 15:25 → time-of-day normalization.

## Development (2024 only)
- Truncation test (`test_accel.py`): 12 random cuts, every signal before each cut unchanged — passes.
- Readings (in-sample, recorded before validation opened): 5-minute PV 30-min M-excess +1.3 bp [−2.9, +5.4] n 135
  (permutation p 0.26); P +1.6 bp; PV minus P-without-volume −1.5 bp [−10.2, +7.5]; V −0.2; C +1.4 [+0.1, +2.8];
  O −0.4. 1-minute PV +0.2 bp. Momentum decile curve flat (−0.7 … +0.7 bp). Translation through the S54 ATM table:
  negative in every DTE bucket. Real ATM options on PV, 30-min, 0.5 % slip: −3.5 % [−11.9, +5.5] per trade, −₹195 / lot,
  37 % winners. Null: shuffled bars PV +0.8 bp; shuffled volume PV +4.2 bp. Grid: 56 % of 27 cells positive.
- No code change was needed after the development run.

## CODE FREEZE — 2026-09-30, before any 2025 / 2026 outcome
`results/FREEZE.sha256`: PREREG.md, accel.py, test_accel.py, audit.py. Validation and blind run once.

## 2026-09-30 — validation and blind, run once on frozen code (hashes verified after the run)
Verdict **2 — structure, not tradable**: H1 (PV 30-min excess) fails in 2025 (−0.2 bp [−4.0, +3.8]) and passes in 2026
(+5.0 bp [+0.6, +10.0], perm p 0.033); grid 44 % / 100 % positive; H2 (volume adds) fails every year; real options
+2.3 % (2025, n 52) and +18.4 % [+1.2, +40.0] (2026, n 25). Details in `REPORT.md`. Nothing re-tuned. The 2021–23
reserve was not read.

## 2026-09-30 — post-hoc CE / PE split (user question; not pre-registered; `side_split.py`, `results/side_split_tf5.json`)
NIFTY 30-min excess by direction (PV, 5-min): up +0.6 / +0.3 / +3.6 bp, down +1.9 / −0.5 / +7.0 bp (2024 / 25 / 26), all
intervals across zero; the stronger side flips between years; 1-minute the same. Real ATM options on PV, 30 min, net:
CE −3.0 / +6.7 / +19.1 %, PE −3.8 / −0.7 / +17.2 % (n 46/21/15 and 59/31/10), every interval across zero. CE looks
slightly better in 2025–26 on per-trade %, but 2025 CE loses in ₹ per lot (−570: a few large-premium losers). Not a
finding; a separate CE / PE hypothesis belongs in the pre-registration of the reserve confirmation run.

## 2026-10-02 — reserve confirmation (CONFIRM.md hashed before the reserve was read; `confirm.py`)
2021-10 → 2023-12, frozen functions. **C1 PV +1.4 bp [−1.3, +4.1] n 249 → inconclusive** (neither > 0 nor below +3 bp).
C2 P +2.2 bp [−0.1, +4.6] n 305. **C5 up − down +0.9 bp [−5.8, +7.1] (98.3 %) → no CE / PE asymmetry.** Up PV +1.9,
down PV +1.1. Volume again adds nothing (P-without-volume +5.8 > PV). Per year PV / P: 2021-Q4 −2.0 / +3.1,
2022 +4.2 / +4.6 [+0.2, +9.2], 2023 −0.1 / +0.3. Grid 81 % PV cells positive (median +0.8 bp). Translation through the
2024 ATM table: positive in 2022 (DTE 1–2), negative on expiry day in 2023. No real-option test (strike lists of
unknown selection moment).
