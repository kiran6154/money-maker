# Wave-lifecycle study — final report (2026-09-30)

Design: [`PREREG.md`](PREREG.md) (hashed before any outcome). Log of every decision: [`LEDGER.md`](LEDGER.md).
Interactive version with every event drawn: `report.html` (built by `build_page.py`).
All numbers: 5-minute bars, front weekly, strike-set-clean sessions, unless stated. Development 2024 is in-sample;
validation 2025 and blind 2026 were run once on frozen code.

## J. Conclusion: **4 — Inconclusive** (the pre-registered rule), with every precise measurement pointing to no structure

- **H1 (predictive) fails out of sample.** Wave-2 signal, 30-minute excess over matched bars:
  2024 +10.7 % [+3.3, +19.3] n 105 → 2025 +2.4 % [−5.1, +8.7] n 47 → 2026 −10.5 % [−35.6, +18.3] n 27.
  ATM only (the pre-registered sample): +9.4 / +3.2 / −8.5 %, n 26 / 8 / 9.
- **H2 (structure) fails.** Bars shuffled within each session produce the same number of lifecycles
  (wave 1: 1,007 vs 1,032; 673 vs 663; 342 vs 320) and the same or higher continuation to wave 3
  (6 vs 10 %, 2 vs 10 %, 8 vs 8 %).
- Rule 3 ("no structure") would need 2025–26 intervals narrower than the round-trip cost; they are wider
  (few events), so the pre-registered label is 4. No trading edge was found.

## A. Definition
Compression = range of the last 12 bars ÷ (prior ATR·√12) ≤ 0.75 (random walk ≈ 1; measured median 0.91) → breakout close
above the box → 2 accepted closes → zig-zag peak (2 ATR reversal, confirmed only by a later bar) → higher base (every close
above the broken level) → breakout above the peak → … Signal I = the accepted second expansion. 360-cell neighbourhood
reported in full. Full table in `PREREG.md` §3.

## B. Mathematics
Next-peak forecast at the wave-2 signal, mean |log error| (2024 / 2025 / 2026): linear 0.180 / 0.192 / 0.238, log
0.178 / 0.200 / 0.186, power 0.173 / 0.195 / 0.356, **geometric / exponential 0.250 / 0.223 / 0.580 (worst every period,
overshoots)**, "2024 median step" 0.192 / 0.143. Too few lifecycles reach 4 levels for in-sample curve fits (2 / 1 / 0).
**Answer: none; a constant step does as well as any law; exponential is rejected.**

## C. Waves
Expansion 2 / expansion 1 ≈ 0.86–0.95, retracement ≈ 0.46–0.51 of the expansion, percentage steps shrink (g2/g1 0.51–0.85).
The shuffled null gives the same numbers (0.80–0.85, 0.46, 0.58–0.66). No amplitude relationship beyond what the
detector's selection creates.

## D. Prediction
Controls B–H (compression, volume spike, breakout, higher low and their combinations) are ≈ 0 or negative every year.
The wave-2 edge exists only in 2024. Shuffled-bar wave-2 signals show +0 to +2.5 % "excess" (baseline bias). Other
timeframes disagree in sign (1-min −1.4 / +5.8 %, 3-min +3.0 / +11.9 %). P(another expansion | wave 2) 4 / 0 / 11 %.

## E. CE vs PE / strikes
CE +7.7 / +17.9 %, PE −5.6 / −27.2 % out of sample (wide intervals, not pre-registered). Option waves are NIFTY moves:
delta 84–86 %, convexity 13–18 %, theta −3 to −5 %, IV +3–4 % of the gain; NIFTY moved with the wave in ≥ 99.8 % of legs
(**Part 8 answer: B**). Opposite leg at a CE signal: −33 / −6 / −13 %.

## F. DTE
ATM elasticity ≈ 60–80 at DTE 2–4, 100–140 at DTE 1, 185–240 on expiry day; on expiry day a −0.25 % NIFTY move costs
52–70 % of premium vs +40–60 % for +0.25 %, drift −5 to −9 % per 15 minutes. The pattern's edge does not grow near expiry.
DTE 5+ not measurable without hindsight-selected strike lists.

## G. Regimes
Out-of-sample cells hold 4–21 events; the pattern did better on days already moving its way (up-so-far +7.7 / +16.8 %,
down-so-far −2.2 / −27.3 %), descriptive only.

## H. Out of sample
See D and J; costs: ATM, 30-minute exit, 0.5 % slippage: +₹118 / −₹83 / −₹1,145 per lot.

## I. Falsification
Shuffled bars reproduce frequency, continuation and ratios; permutation p 0.095 / 0.26 / 0.78; the L-neighbourhood
flips from +7…+11 % (2024) to −6…−19 % (2026); timeframes disagree; mirror pattern ≈ 0; truncation test passes.

## Volume (Part 7)
Volume ratio 0.9–1.1 before the breakout, 1.5–2.0 on and after it: coincident, not leading. Volume-spike signals had
negative excess every year, and real spikes did worse than shuffled volume.

## Event dataset (Part 19)
`events_tf5_2024.csv`, `events_tf5_2025.csv`, `events_tf5_2026.csv`: one row per G / I / I3 signal on front contracts with the
requested columns; columns known only after the signal are prefixed `OUTCOME_`.
