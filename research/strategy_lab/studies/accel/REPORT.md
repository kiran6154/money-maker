# S55 — NIFTY acceleration → option expansion: report (2026-09-30)

Design [`PREREG.md`](PREREG.md) (hashed before any forward outcome), decisions [`LEDGER.md`](LEDGER.md), plan [`PLAN.md`](PLAN.md).
Futures = NIFTY near-month; 2024 development (in-sample), 2025 validation, 2026-01 → 09-25 blind, run once on frozen code.
Excess = signed 30-minute futures move minus momentum-matched bars (same hour, DTE bucket, trailing-z decile), basis
points, week-clustered 95 % intervals.

## Verdict: **2 — structure, not tradable** (pre-registered rule: H1 passes in one period only)

| 5-minute, 30-min excess (bp) | 2024 dev | 2025 validation | 2026 blind |
|---|---|---|---|
| **PV** volume-backed acceleration (H1) | +1.3 [−2.9, +5.4] n 135 | −0.2 [−4.0, +3.8] n 108 | **+5.0 [+0.6, +10.0] n 67**, perm p 0.033 |
| P price acceleration | +1.6 [−1.8, +5.0] n 168 | +0.7 [−2.7, +4.0] n 135 | **+4.9 [+1.2, +9.1] n 79**, perm p 0.016 |
| V volume spike | −0.2 | −0.4 | −0.6 |
| C compression → expansion (S54 detector on futures) | +1.4 [+0.1, +2.8] | −0.8 | +0.2 |
| O opening-range break | −0.4 | −0.5 | +1.2 |
| PV on shuffled bars (20×) | +0.8 | +0.8 | +0.6 |
| Grid, PV cells > 0 (27) | 56 % | 44 % | **100 %** |

- **The effect exists in 2026 only.** 2025 is flat in every cell (grid median −0.1 bp) and 2024 is small and in-sample.
  One out-of-sample period out of two is exactly what the rule calls "structure, not tradable".
- **Volume adds nothing (H2 fails every year):** PV minus price-only-without-volume −1.5 / −4.2 / +0.8 bp, all
  intervals across zero. With volume shuffled within the session, 2026 PV scores higher (+7.1 bp) than with real volume.
  Whatever continues in 2026 is the price acceleration itself.
- **No general momentum:** the signed 30-minute move by trailing-return decile is flat (within ±0.8 bp) every year; the
  acceleration shape, not trend-following in general, is what showed up in 2026.
- **1-minute:** nothing in any year (PV +0.2 / −0.3 / +0.7 bp).

## Options (H3)

| ATM weekly on PV, 30-min exit, 0.5 % slippage + charges | 2024 | 2025 | 2026 |
|---|---|---|---|
| Net per trade | −3.5 % [−11.9, +5.5] | +2.3 % [−11.8, +18.4] | +18.4 % [+1.2, +40.0] |
| ₹ per lot · win rate · positive weeks | −195 · 37 % · 15/46 | −427 · 35 % · 11/27 | +447 · 56 % · 8/14 |
| Trades (clean / signals) | 105 / 135 | 52 / 108 | 25 / 67 |

Missing strikes (the 2025–26 files hold 5 strikes around the Monday ATM) and strike-list-hindsight sessions remove most
2025–26 signals, so the option samples are small. Entering at the next bar's open changes little (≤ 0.4 pt).
Translated through the S54 response table, the 2026 hit rate (56 % on expiry day, 55 % at DTE 1) sits at or just under
the break-even rate (60 %, 53 %), and 2025 falls below it in every bucket.

## What this means for the original question

The S54 reframing holds: the option "staircase" is NIFTY moving. The only NIFTY signal that showed any follow-through
is plain price acceleration (a 30-minute move ≥ 1.5 ATR-units with the second half stronger), and only in 2026.
2025 says it is not a stable property of NIFTY. Volume, compression and opening-range breaks add nothing.

## What would settle it

The 2021-10 → 2023-12 futures were reserved and never read by this study. Running the frozen code once on them (H1 on
P and PV, same rule) is an independent confirmation of the NIFTY half at no cost to the design; 2021 also has 5-minute
option chains. A paper-forward test from 2026-10 is the other clean check. Neither was run; both need the user.

Files: `results/primary_tf{5,1}_{year}.json`, `options_tf5_{year}.json`, `null_tf5_{year}.json`, `grid_tf5_{year}.json`,
`events_tf{5,1}_{year}.parquet`.

## Reserve confirmation, 2021-10 → 2023-12 (2026-10-02; design `CONFIRM.md`, hashed before the data was read)

| 30-min excess (bp), 5-minute | 2021-Q4 | 2022 | 2023 | pooled reserve |
|---|---|---|---|---|
| PV (C1, confirmatory) | −2.0 (n 21) | +4.2 [−0.7, +9.6] | −0.1 [−3.1, +2.9] | **+1.4 [−1.3, +4.1] n 249** |
| P price only (C2) | +3.1 (n 29) | +4.6 [+0.2, +9.2] | +0.3 [−2.3, +3.0] | +2.2 [−0.1, +4.6] n 305 |
| PV up (CE side) / down (PE side) | | | | +1.9 / +1.1; difference +0.9 [−5.8, +7.1] |

- **C1: inconclusive** by the rule fixed beforehand — not confirmed, not ruled out.
- **CE vs PE (the user's question): no measurable difference** on NIFTY; up and down continue alike.
- Across all six periods the price-acceleration excess is positive every time (2021-Q4 +3.1, 2022 +4.6, 2023 +0.3,
  2024 +1.6, 2025 +0.7, 2026 +4.9 bp), but significant only in 2022 and 2026. Read together: a small continuation of
  about +2 bp per 30 minutes may exist, strong in some years and absent in others — well below what an ATM weekly needs
  on expiry day (≈ +4.5 bp per 15 minutes) and not reliable year to year. (This pooled reading is post hoc.)
- Volume once more adds nothing; price acceleration without the volume condition did better.

**Bottom line for S54 → S55:** the option staircase is NIFTY moving; NIFTY's own acceleration continues only weakly and
unevenly; neither side (CE / PE) is better; no option-buying rule follows. The remaining clean check is paper-forward.
