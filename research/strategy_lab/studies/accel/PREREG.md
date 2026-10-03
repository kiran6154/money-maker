# S55 — NIFTY acceleration study: pre-registration (frozen 2026-09-30, before any forward outcome was computed)

Question: when NIFTY starts a directional acceleration, detectable from past bars only, does it continue enough to beat
the option's own hurdle (theta plus the expiry-day asymmetry measured in S54)? Research only; nothing trades.
Plan and user decisions: [`PLAN.md`](PLAN.md). Rule 0 entry: `docs/STRATEGY_ANALYSIS_TODO.md` S55.
The SHA-256 of this file is written into every result file.

## 1. Data and periods

- Signal and NIFTY outcome: near-month futures `D:/nifty/niftyfut_nearmonth_minute_2021-10-01_to_2026-09-25.csv`
  (1-minute; 5-minute = resampled, identical to the 5-minute file per the audit). Only sessions from 2024-01-01 are read.
- Periods (user decision): **development 2024, validation 2025, blind 2026-01-01 → 2026-09-25**.
- Excluded sessions: fewer than 90 % of the normal bar count (2024-03-02, 2024-05-18, 2025-10-21 per the audit).
- Rolls happen only at session boundaries; all signals and outcomes are intraday, so no roll adjustment is needed.
  The ATR may use the previous session's bars; the overnight gap is excluded from the true range.
- Spot for the option strike at a signal: the last completed 5-minute bar of the long index file
  `D:/nifty/nifty50_5minute_2019-01-01_to_2026-09-26.csv` (not the futures, which carry a basis of up to ~150 pts).
- DTE: calendar days to the front **weekly** option expiry (the S54 expiry calendar). Buckets 0, 1, 2, 3–4, 5+.

## 2. Timeframes and eligibility

Primary 5-minute; secondary 1-minute with the same bar-count parameters (not re-tuned). A bar is eligible as a signal
bar when its session is not excluded, it is not the first bar, the L-bar window lies inside today's session, and the bar
closes at or before 15:00. Entry reference = the signal bar's close.

## 3. Definitions (all causal)

- `ATR_pre`: mean log true range of the 20 bars ending at bar t−L (before the window).
- `R_L = ln(C_t / C_{t−L})`; `z = R_L / (ATR_pre·√L)` (a random walk gives |z| of order 1). Direction d = sign(R_L).
- Halves: `R_1 = ln(C_{t−L/2} / C_{t−L})`, `R_2 = ln(C_t / C_{t−L/2})`.
- `VR_tod(t)`: volume of bar t ÷ median volume of the same bar-of-day over the previous 10 eligible sessions (≥ 5 needed).
  `VRw`: summed volume of the window's second half ÷ summed same-time medians.

| Code | Signal (fires only at onset: condition true at t and false at t−1; then no same-direction signal for L bars) |
|---|---|
| A | every eligible bar, both directions (base rate) |
| P | price acceleration: \|z\| ≥ a **and** d·R_2 > d·R_1 > 0 (both halves in the direction, the second larger) |
| V | volume only: VR_tod ≥ v; d = sign(close − open) of bar t |
| PV | P **and** VRw ≥ v — the volume-backed acceleration (the hypothesis' signal) |
| C | compression → expansion on NIFTY futures: the S54 detector's accepted wave 1 (G) on log futures, up; its mirror on −log price, down (S54 primary cell L 12, c 0.75, k 2, m 2, strict) |
| O | opening-range break: first close after 09:30 beyond the 09:15–09:30 high / low; once per direction per day |

Primary cell: **L = 6, a = 1.5, v = 1.5**. Neighbourhood (all 27 cells reported, none chosen by result):
L 4 / 6 / 8, a 1.0 / 1.5 / 2.0, v 1.25 / 1.5 / 2.0.

## 4. Outcomes

Signed forward log return `y_h = d·ln(C_{t+h} / C_t)` at h = 5, 15, 30, 60 minutes and to the session close (a horizon is
used only if it ends inside the session); MFE / MAE in the direction; hit rates P(y ≥ +10 / +25 / +50 bp);
P(+25 bp before −25 bp). Basis points throughout.

- **Matched baseline M (momentum-matched):** pool = every eligible bar taken in both directions, with signed trailing
  z' = d·z. Expected y_h = mean over pool bars in the same (hour, DTE bucket, decile of z'). Excess = y_h − expected.
- **A-baseline:** the same without the z' decile.

## 5. Option translation and real options (H3)

- Translation (all periods): the S54 15-minute ATM response table of the same period and DTE bucket
  (`waves/results/dte_*.json`, CE for d = +1, PE for d = −1) applied to each event's 15-minute futures move:
  option ≈ intercept + b1·x + b2·x². Reported with the break-even hit rate per bucket.
- Real options (2024–26): ATM weekly (front expiry) at the signal, strike = spot rounded to 100; CE for d = +1, PE for
  d = −1; entry at the option's close of the same bar, exit at the close 30 minutes later and at the session close;
  costs exactly as S54 (Zerodha schedule, 0.25 / 0.5 / 1 % slippage per side, lot 25/75/65 by era; next-open entry
  variant). Missing strike = counted and skipped. Sessions before the files' Monday-09:20 strike list are flagged
  (strike-list hindsight) and excluded from the primary figure, as in S54.

## 6. Hypotheses and decision rule

- **H1** (the confirmatory test): PV, 5-minute, 30-minute M-excess > 0 — week-clustered bootstrap (5,000) 95 % CI, in
  validation and blind separately.
- **H2**: PV beats P-without-V (P events where VRw < v): difference of 30-minute M-excess, CI > 0.
- **H3**: real ATM option trades on PV, 30-minute exit, 0.5 % slippage: mean net > 0 with CI > 0.
- Nulls: bars shuffled within each session (20 replicas) through the identical code; volume shuffled within session
  (for V, PV); label permutation within matched cells.

Verdict:
1 **Strong** — H1 and H3 CI > 0 in validation and blind, ≥ 70 % of grid cells with positive PV excess in both, nulls do
  not reproduce it.
2 **Structure, not tradable** — H1 CI > 0 in both periods but H3 fails, or H1 passes in one period only.
3 **No predictive structure** — in both periods the H1 CI upper bound is below **+3 bp** (the NIFTY edge an ATM option
  needs on expiry day: 59 % hit at ±25 bp ≈ +4.5 bp per 15 min, taken conservatively).
4 **Inconclusive** — anything else.

Multiple testing: controls × horizons × timeframes × DTE / regime splits get Benjamini–Hochberg q-values; only H1 is
confirmatory.

## 7. Not done

No parameter fitted on 2025 or 2026; 2021-10 → 2023 futures are not read. No strategy, no orders.
