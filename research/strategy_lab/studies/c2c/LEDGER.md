# C2C research ledger (CHoCH-to-option-buying programme)

Permanent experiment ledger for the research programme the user set on 2026-09-29 (NIFTY CHoCH retest → long option).
Rules: entries are appended, never overwritten; every experiment gets one status from ROBUST / PROMISING BUT NEEDS MORE
TESTING / NO EDGE / OVERFIT / EXECUTION-SENSITIVE / DATA-LIMITED / INCONCLUSIVE; no ranking, no "best strategy".
Chronological split (pre-registered): development 2021–2023, validation 2024, blind 2025–2026. No parameter is fitted on
2025–2026. Open strategy questions go to `docs/STRATEGY_ANALYSIS_TODO.md` S52 (Rule 0).

Contamination note: Strategy 25–28 option results for 2026-06-23 → 09-14 were seen on 2026-09-29 before this programme
started (no parameter was chosen from them; they sit inside the blind period).

---

## EXP-001 — Phase 1 execution and data audit (2026-09-29)

| | |
|---|---|
| Hypothesis | The frozen baseline (Strategy 25, `c2c.py`) can be measured 2021–2026 without execution or data defects. |
| Data | NIFTY 5-minute index: long file `nifty50_5minute_2019-01-01_to_2026-09-26.csv`, Breeze file `nifty50_breeze_5minute_2021-10-01_to_2026-09-25.csv`, Kite file 2026-07 → 09; option folders under `D:/nifty/data`. |
| Result | **Blocking defects found — the baseline cannot yet be measured as specified.** |
| Status | **DATA-LIMITED** (and the regime definition is EXECUTION-SENSITIVE, see A3) |

Findings (each separately):

- **A1 Data — Breeze index candles are corrupt at times.** 111 bars with a 5-minute range above 150 pts (46 in 2024, 43 in
  2026; mostly 09:15 and 15:20). In 2026, 33 of 162 15:20 candles have a range above 60 pts, 0 in the long file and in
  Kite, which agree bar for bar (e.g. 2026-09-10 15:20: Breeze H 23,781.95 vs Kite / long flat at 23,389.25). The lab's
  index signals (`config/data.json` spot files, `underlying: INDEX`) read this file, so every INDEX backtest in the lab —
  including Strategy 25–28's reported index numbers — is affected. Not fixed here (shared data; the user's call).
- **A2 Data — the two index sources differ in candle convention.** Where both exist, 2,655 closes differ by more than 1 pt,
  mostly Oct 2021 – Jun 2022; Breeze's close matches the long file's next open (464 of 473 checked). Breeze lacks whole
  sessions (2022-03-29 → 03-31, 05-31, 06-14 …) and has a special Saturday session (2024-03-02) the long file lacks. This
  study uses the long file.
- **A3 Engine — the regime is path-dependent and can freeze.** The trend flips only on a close through the protected level
  AND the AVWAP anchored at the trend's start. After a long trend that anchor is far away, so no flip happens: run
  continuously from 2020-10, the regime stayed bullish for 330 sessions (2020-11-02 →) and 300 sessions (2023-11-02 → 2025-02),
  with 0 flips in 2021 and 2024. The lab re-warms each backtest from 5 sessions before its start: 2024-H2 run that way has
  90 flips, run continuously 0. Signals therefore depend on the start date of the run; a live deployment running
  continuously would have gone silent for a year. **The regime definition must be settled before any baseline number is
  meaningful** (user decision, S52).
- **A4 Execution — opening-print entries.** "Next candle open" enters on the 09:15 opening print when the signal is the
  session's last candle (14 of 1,384 index signals 2021–2026); the lab's fill rules forbid a fill on the opening print.
- **A5 Data — option prices.** Full-chain option data (strikes chosen from spot at decision time) exists only for the
  Jul-28, Aug-25 (Breeze) and Sep-29 (Kite) 2026 monthlies: priceable sessions 2026-06-23 → 07-13 and 07-22 → 09-14.
  2021–2025 option folders hold five strikes around settlement (hindsight-selected): usable for prices of the strikes they
  contain, never for choosing strikes. Option-side phases (baseline P&L, 4–9, 13, 17–18) are DATA-LIMITED until the
  Breeze fetch runs.
- **A6 Data — PCR.** No option OI before the 2026 full-chain window; the PCR rule cannot be applied 2021–2025. In 2026 the
  lab uses a ±300-pt window PCR, not the exchange PCR (S52).
- **A7 Execution — spreads.** No bid/ask history; the lab charges 0.5 pt per side as slippage. Spread sensitivity must be a
  scenario, not a measurement.
- **A8 Rules — unbuilt guard rails.** Delta ≤ 0.3, gamma, vega, 2 % max-loss cap, 10 % bid-ask tolerance are not
  implemented; delta ≤ 0.3 contradicts the ITM1 strike rule.
- **A9 Construction — anchored "VWAP" on the index is a TWAP** (no index volume). The futures-volume version is the lab's
  futures-signal backtest.
- Checked and found consistent: signal on the closed candle i, entry at candle i+1; swing confirmation at its `conf` bar;
  CHoCH / flip at the close of its bar; strike from the index close at i; expiry = nearest monthly ≥ 15 calendar days
  (last Thursday to Aug 2025, last Tuesday from Sep 2025, holiday-adjusted); `tests/test_c2c.py` truncation test passes.

## EXP-002 — Phase 3, signal edge on NIFTY, frozen rules, M1 (no filter) (2026-09-29)

| | |
|---|---|
| Hypothesis | After a bearish (bullish) CHoCH retest signal NIFTY moves down (up) more than a random entry at the same time of day. |
| Change | None to the rules; PCR rule left out (A6); bullish side = exact mirror (swing low, trough-anchored AVWAP, ±50, day not up 0.6 %). |
| Data | Long index file, engine run continuously from 2020-10-01; signals 2021-01-01 → 2026-09-25. Script `studies/c2c/phase1_3.py`, output `phase1_3.json`, `signals.csv`. |
| Periods | reported separately: dev 2021–2023, validation 2024, blind 2025–2026; nothing fitted. |
| Trades | 1,384 signals (643 bearish, 741 bullish) — but 2021 and 2024 have 0 bearish and 1 bullish each (A3). |
| Result | Bearish, all years: mean directional move +1.5 pts at 60 min, −2.6 pts to the close; excess over the matched control +1.1 pts at 60 min (t 0.62, randomisation p 0.28), −3.7 pts to the close (t −1.09). Bullish: −2.0 pts at 60 min (t −1.29), −5.2 to the close (t −1.58). Blind 2025–2026: bearish +1.2 at 60 min (t 0.51), bullish −2.7 (t −1.30). By month regime the bullish side is positive in bullish months and negative in bearish / flat months (e.g. to the close +23.5 excess, t 3.6, in bullish months) — that is the month's own drift measured after the fact, not a signal property, and must not be read as an edge. |
| Conclusion | No measurable directional edge in this run. **Not a verdict:** the run is conditioned on the frozen-regime artefact (A3), which removed two whole years and changes which signals exist in the others. |
| Status | **INCONCLUSIVE** (re-run after the regime definition is settled) |

## EXP-003 — Phase 3 on development years, two regime definitions (2026-09-29)

| | |
|---|---|
| Hypothesis | With a regime that does not freeze, the CHoCH retest signal predicts the NIFTY move (Question A). |
| Change | The regime only (user, 2026-09-29: "test both, freeze none yet", research on the long index file only). R-A = rolling memory: each session's structure rebuilt from the previous 5 sessions + that session (engine unchanged). R-B = no AVWAP in the regime: every opposite swing is a protected-level candidate and its close-break flips (study-local engine copy; engine.py untouched). Retest band, day filter, entry, measurement = EXP-002. |
| Data | Long index file, **2020-10-01 → 2023-12-31 loaded, nothing later** (2024 validation and 2025–2026 blind sealed). Script `studies/c2c/phase3_dev.py`, output `phase3_dev.json`. |
| Periods | development 2021–2023 only. |
| Regime health (read first) | R-A: 229 / 199 / 181 flips a year, longest regime 21 days. R-B: 674 / 704 / 605 flips a year (2–3 a session), longest 5 days. Neither freezes. |
| Trades | R-A 856 bearish + 1,207 bullish; R-B 1,296 bearish + 1,497 bullish. |
| Result — bearish | Nothing at 15–60 min (excess over the same-year same-time control −0.6 to +0.6 pts). A small late drift: 240 min excess +5.3 pts (R-A, t 1.93, randomisation p 0.026) / +2.5 (R-B, t 1.26, p 0.11); to the close +4.0 (t 1.33) / +2.5 (t 1.15). Hit rates 48–52 %. By year the sign is not stable at 15–60 min. |
| Result — bullish mirror | No edge: 2021–2023 excess −0.9 (R-A) / −0.3 (R-B) at 60 min, −2.7 / −2.0 to the close; negative in 2021, a +24 % year, under both. One positive cell (R-B 2023, 15 min +1.6, t 2.31) among 32 tested. |
| Multiple testing | 2 definitions × 2 sides × 8 horizons = 32 cells; the best p (0.021, 0.026) are what 32 draws under no effect would give. |
| Conclusion | On development data the signal shows no reliable short-horizon directional information; the bearish side has a small, statistically weak drift over hours (a few NIFTY points on average). The regime definition changes the signal count, not the picture. |
| Status | R-A: **NO EDGE** (short horizon) / **INCONCLUSIVE** (240 min – close, bearish). R-B: **NO EDGE**. Bullish mirror (both): **NO EDGE**. |

Correction to EXP-001 A3 (mechanism, found in this experiment): the freeze does not come from the flip condition — with
close breaks every CHoCH already flips (a first R-B that changed only the flip line was identical to the engine). It comes
from the protected-level candidate rule: in an uptrend only swing lows below the AVWAP anchored at the trend's start qualify,
so once price has run far from that anchor no swing qualifies, there is no protected level, and no CHoCH can occur. The
finding (path dependence, year-long freezes) stands.

Note: R-A windows end at each session's close, so a swing confirming on a session's last candle (entry on the next 09:15
print) is not taken — consistent with the no-opening-print fill rule (EXP-001 A4); R-B keeps them (12 + 13 such signals).

## EXP-004 — Phases 4–9, option economics on development data, both regime definitions (2026-09-30)

| | |
|---|---|
| Hypothesis | The NIFTY move after a signal is large enough to pay for the option: time decay, IV change, costs (Question B). |
| Change | None to the signals (EXP-003's R-A and R-B, bearish → long PE, bullish → long CE). Option grid: ATM / ITM1–2 / OTM1–2 from the index close at the signal, expiry W0 (nearest weekly) / W1 (next weekly) / M15 (nearest monthly ≥ 15 days). Entry at the open of the option's exact-time candle after the signal (no 09:15 print), valued at 15–240 min and the session close. |
| Data | Options: only expiries fetched by `tools/breeze_options.py --research` to completion (strikes from decision-time spot) — after the first fetch day that is **2021 (52 expiries) and most of 2022 (42 of 52); 2023 not yet fetched** (the five-strikes-around-settlement files are never used: a first run that used them was discarded as hindsight-priced). Index: long file ≤ 2023-12-31. Script `studies/c2c/phase4_9.py`, output `phase4_9.json`, `option_trades.csv` (the per-trade option economics table: premium, intrinsic, extrinsic, DTE, IV, Greeks, move, time / spot / vol split, costs, expected carry, required move, net). |
| Method | Price change split exactly with Black-Scholes (r 6.5 %, calendar time): time (spot, IV held) / spot (IV held) / vol (IV change). Costs = today's Zerodha option charges per unit of a 65-lot + 0.5 pt slippage a side (≈ 1.9–2.3 pts round trip). D6 empirical carry = time + vol of a no-signal control (ATM CE and PE bought at every :15 / :45, same expiries) per DTE bucket × entry hour × horizon; required NIFTY move x solves |Δ|x + Γx²/2 = −carry + costs. In-sample on development data. |
| Withdrawn | A first decay measure (change of extrinsic value against spot intrinsic) mixed in the moneyness change — an ATM option's extrinsic falls ≈ |move|/2 whichever way NIFTY moves — and showed "−12 pts an hour at every DTE". Replaced by the exact split above. |
| Result — the market (control, no signal) | Buying an ATM option at a random time and holding to the close lost money at every DTE for both rights (net −1 to −9 pts, t −1 to −7). **Puts lose 5–7 pts to the close through falling implied vol at every DTE** (vol component −5.3 to −7.2 for 1–30 DTE); calls lose 0–2 through vol. Calendar time costs 0.5–1.5 pts a day beyond 5 DTE, 3–4 at 1–3 DTE, ~26 on the last day. The carry is front-loaded in the session: an entry in the 09:xx hour carries −5.7 (time) −5.0 (vol) to the close, a 14:xx entry −1.4 / −2.0. |
| Result — required vs realised move | To the close the trade needs NIFTY to move ~9–15 pts its way (monthly / next weekly) or ~20–25 pts (current weekly); to 60 min ~6–7 pts. After R-A bearish signals NIFTY moved +10 pts on average to the close (median ~5); after bullish −6 (median ~0). The required move was reached in 40–47 % of trades in every cell — a coin-flip's share. |
| Result — net per unit (to the close) | R-A bearish: W0 ITM1 +1.3 (t 0.41), W1 ITM1 −1.1 (t −0.39), M15 ITM1 −2.8 (t −1.03). R-B bearish: −4.8 to −5.6 (t −2.3 to −3.1). Bullish (both definitions): −3.0 to −6.7 (t −2.0 to −4.2). The time / spot / vol split of bearish R-A W1 ITM1: time −1.2, spot +9.4, vol −7.2 — the NIFTY move is eaten by the put IV decline, not by theta. |
| Result — DTE (ITM1) | No DTE bucket is positive under both definitions; the one large cell (R-A bearish 0–1 DTE, +17.5, t 2.03, n 92) is +4.1 (t 0.78) under R-B and negative for the bullish side — noise under ~60 cells tested. |
| Conclusion | On 2021–2022 the signal's move does not pay for the option: puts in particular pay a structural intraday IV decline of ~6 pts, and the move needed to cover carry + costs is reached in fewer than half the trades. Question B: no option edge measured. Preliminary: 2023 is missing (fetch in progress), and exits here are fixed horizons, not the baseline's stop / trail / 15:15 ladder. |
| Status | Both definitions, both sides: **NO EDGE** (development data, fixed horizons); **DATA-LIMITED** for 2023 — re-run when the fetch completes. |
