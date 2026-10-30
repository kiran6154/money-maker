# S55 confirmation on the reserve — pre-registration (written 2026-10-02, before any 2021–2023 bar is read)

User go-ahead 2026-10-02 ("Continue" after the offer to run the reserve check with CE / PE as separate hypotheses).
Purpose: an independent test of the one S55 result (acceleration continued in 2026, not in 2025), and of the user's
question whether the up (CE) and down (PE) sides differ.

## Data
NIFTY near-month futures, `D:/nifty/niftyfut_nearmonth_minute_2021-10-01_to_2026-09-25.csv`, sessions
**2021-10-01 → 2023-12-31** only (never read by S54 or S55). Same session rules as S55 PREREG §1 (sessions with < 90 %
of the bars excluded). 5-minute bars. Frozen `accel.py` functions (`features`, `eligible`, `signals`, `outcomes`, `pool`,
`events`, `cboot`, `cboot_diff`, `perm`) unchanged; `confirm.py` only loads the reserve dates the same way `fut_bars` does.
Matched pool and deciles are built per calendar year, as in S55.

## Tests (primary cell L 6, a 1.5, v 1.5; 30-minute momentum-matched excess, week-clustered bootstrap)
- **C1 (the confirmatory test):** PV excess > 0, 95 % CI.
- **C2:** P (price only) excess > 0, 95 % CI.
- **C3 / C4:** PV up signals (CE side) > 0; PV down signals (PE side) > 0.
- **C5:** up minus down ≠ 0 (the asymmetry question).
  C3–C5 use Bonferroni 98.33 % intervals (3 tests).

## Decision
- C1 lower bound > 0 → the 2026 effect **replicates**; S55 stays "structure, not tradable" (two out-of-sample periods
  out of three positive), and the next step would be a paper-forward test, not a strategy.
- C1 upper bound < +3 bp → the effect is **not a stable property of NIFTY**; S55 is closed as no edge.
- Otherwise → inconclusive.
- C5 interval excluding 0 → a CE / PE asymmetry exists on NIFTY and gets its own pre-registered follow-up; otherwise the
  user's question is answered "no measurable difference".
Reported beside them, descriptive only: each calendar year separately, the 27-cell grid, V / C / O controls, and the
option translation through the S54 2024 (development) ATM table. No real-option test: the 2021–23 option folders'
strike lists have no recorded selection moment, so they cannot be used without hindsight risk.
