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

## EXP-005 — Phase 12, the baseline's own exits on real options (development data) (2026-09-30)

| | |
|---|---|
| Hypothesis | Held with its own position rules the frozen strategy makes money on real option prices. |
| Change | None: ITM1 of the nearest monthly ≥ 15 days, one position at a time, entry at the open of the option candle after the signal, `c2c.hold` — premium stop 5 %, 5-pt trail behind the peak premium, opposite flip exits, 15:15 ladder (profit > 40 %, loss > 2 %), positional. PCR rule off (no full-chain OI before 2026). Stops on the close and by touch. Books: bearish → PE (the baseline), bullish → CE (the mirror), R-A and R-B. |
| Data | Research-fetched expiries only (2021 complete, 2022 42 of 52; 2023 not yet fetched — 406–697 signals per book skipped as "no research data"). Index ≤ 2023-12-31. Script `studies/c2c/phase7_12.py`, output `phase7_12.json`. Rupees per 65-unit lot after today's charges and 0.5 pt slippage a side. |
| Result | Every one of the 8 books loses, in both years: R-A bearish (the baseline) close stops 377 trades, win 31.8 %, avg −212, median −343, net −80,001, PF 0.64, max DD −86,514, t −3.25, median hold 15 min; touch stops 414 trades, net −70,211, PF 0.53, t −4.44, median hold 5 min. R-B bearish −57,372 (PF 0.81, t −1.67) / −78,570 (PF 0.64, t −3.03). Bullish mirror −71,052 to −136,031 (PF 0.50–0.70, t −2.8 to −6.3). 2021 and 2022 both negative in every book. Exits: the 5-pt trail closes 74–89 % of trades — on a ≈ ₹330 premium it is ≈ 1.5 %, inside one 5-minute candle's noise — the 5 % stop 7–21 %, the bullish flip 2–12 %, the ladder ≤ 3 %. Average premium ≈ 320–345, DTE ≈ 28–30, max consecutive losses 11–18. |
| Conclusion | The exact baseline exits turn the signal into many small losing trades: the trail is tighter than the option's candle-to-candle noise, so most positions are stopped out within one or two candles and charges + slippage (≈ ₹130–150 a round trip) do the rest. |
| Status | Baseline (R-A bearish) and every variant: **NO EDGE** on development data; **DATA-LIMITED** for 2023. |

## EXP-006 — Phase 7, flat-market features, one at a time (signal-level, 2021–2023) (2026-09-30)

| | |
|---|---|
| Hypothesis | Some objective feature, known before entry, marks signals whose NIFTY move to the close is too small to pay for an option (≈ 12 pts, from EXP-004). |
| Features | 20-session return, ATR, realised vol, daily ADX(14), 20-session slope / ATR, distance from the 20-session mean / ATR, distance from the anchored VWAP / 5-min ATR, 5- / 20-session range (compression), previous-session range, today's range so far, today's return / ATR. Quintiles from the development signals (descriptive, in-sample). |
| Result | No feature separates the signals: the share whose move to the close reached 12 pts lies between 29 % and 60 % in 220 cells (11 features × 5 quintiles × 2 sides × 2 definitions), with no monotonic pattern and none repeated across R-A and R-B (e.g. R-A bearish today's-range middle quintile 60 %, R-B the same quintile 43 %; R-A bullish top compression quintile 29 %, R-B 42 %). The mean favourable excursion to the close is 33–89 pts in every cell — several times the ≈ 12 pts an option needs — while the mean directional move to the close stays around zero. |
| Conclusion | Movement is not what is missing: NIFTY moves far enough after almost every signal, in both directions. What is missing is direction — the signal does not tell which way. A flat-market (no-trade) filter on these features addresses the wrong problem. |
| Status | Every feature: **NO EDGE** (no objective condition of insufficient movement found). |

## EXP-007 … EXP-017 — the remaining phases on development data (2026-09-30)

User, 2026-09-30: "run all remaining phases". One script, `studies/c2c/run_rest.py` (shared machinery `c2clib.py`), output
`run_rest.json`. Data as EXP-004/005: index 2021–2023, options from research-fetched expiries only (2021, 42 of 52 of 2022;
2023 not yet fetched), nothing after 2023-12-31 loaded. Outcome measures: **sig** = directional NIFTY move to the close minus
the same-year same-time control (Question A); **eod** = each signal's own ITM1 monthly option, next open → session close, net ₹
per 65-lot, no lock (Question B); **book** = the baseline position rules, one position at a time. All in-sample on 2021–2023
except EXP-017. With ~1,000 cells tested across these experiments, |t| ≈ 3 appears by chance several times; a finding counts
only if it is monotone, repeats under R-A and R-B, and survives EXP-017.

| ID | Phase | Hypothesis / change | Result (development) | Status |
|---|---|---|---|---|
| EXP-007 | 5 + 9 | Expected move (mean move to the close of EARLIER signals, same definition / side / entry hour) filters M2–M5, and decay-aware E2–E6 (expected move ≥ the ≈ 9 pts carry + costs) | Expected move is positive for bearish (R-A +7.6, R-B +3.8) and negative for bullish history, so bullish filters take almost nothing. Bearish filtered subsets: sig +0.2 to +7.2 (t ≤ 1.6), eod −20 to −442 ₹ (t −0.06 to −2.4) — no subset positive after costs | **NO EDGE** |
| EXP-008 | 8 + 9 (13) | Strike ATM / ITM1–2 / OTM1–2 × expiry W0 / W1 / M15 | **All 60 baseline books lose** (−39,476 to −144,965; PF 0.50–0.88). Per-signal eod: best cells R-A bearish W0 ITM2 +117 (t 0.50), ITM1 +86 (t 0.41); 0 of 60 with t > 1 | **NO EDGE** (every strike and DTE) |
| EXP-009 | 10 | CHoCH quality, 12 features one at a time, quintiles (480 cells) | Several \|t\| 3–4.7 cells, none monotone, none repeated across definitions (e.g. break size: R-A bearish best in its 3rd quintile 6–11 pts, R-B bearish in its 2nd 1.8–4 pts). One pattern repeats in 3 of 4 books: the **largest break-size quintile loses most as an option** (eod −1,105 / −1,182 ₹, t −4.8 / −5.1 under R-B; R-A bearish −240, t −0.65) | **NO EDGE**; largest-break exclusion **INCONCLUSIVE** |
| EXP-010 | 11 + 27 | Entry band ±20 … ±100 pts and 0.25–1.0 × 20-session ATR | **Bearish sig excess rises monotonically as the band narrows** under both definitions: R-B +7.1 (t 3.07) at ±20 → +2.5 at ±50 → +1.7 at ±100, at 60 min +3.0 (t 2.24) → +0.6; R-A +5.9 (t 1.65) at ±20 → +4.0 at ±50. ±40–60 around 50 behaves like 50 (no knife-edge). Options still lose at every band: R-B bearish ±20 eod −157 (t −1.26), book −18,176 (t −0.59) — the best book of the programme, still negative. Bullish: negative at every band | Bearish narrow band, signal level: **PROMISING BUT NEEDS MORE TESTING** (see EXP-017). As an option trade: **NO EDGE**. ATR bands: **NO EDGE** |
| EXP-011 | 12 + 16 | Exits with the entry frozen: X1 current, X2 option target 10/20/40 pts, X3 10/20/40 %, X4 NIFTY target 25/50/100, X5 flip only, X6 trail 10/20/40, X7 time 15 min … next close, X9 exhaustion (NIFTY +40). X8 decay-aware = X7 30 min here (the expected remaining move is ≤ 0 at every hour), not run separately | Tight exits lose most (X7 15–30 min t −3.5 to −7.2; X1 current −57k to −136k). **Wider exits lose less in all four books** — trail 40, target 40 %, flip only: R-A bullish trail 40 +79,386 (t 1.22), target 40 % +60,550 (t 0.89), flip only +56,303 (t 0.58); R-B bullish target 40 % +29,178 (t 0.50); R-B bearish target 40 % +6,457 (t 0.11). 2021 negative, 2022 positive in almost every wide-exit cell (a year effect). Holding period: no horizon from 15 min to next close is positive in the bearish books | The 5-pt trail is **an identified defect of the baseline** (exits inside one candle's noise). Wide exits: **INCONCLUSIVE** (sign flips by year, t ≤ 1.2; EXP-017 fails to carry them forward) |
| EXP-012 | 13 + 17 + 18 | IV at entry and its percentile over the previous 60 sessions (ATM monthly IV at 10:15, 413 days) | Quintiles of ~86 signals; single-quintile spikes (R-A bearish IV 17.5–19.1 %: sig +57, t 4.4) with neighbours negative — not monotone, not repeated in R-B. The greek split (EXP-004): profit comes from the NIFTY move and is eaten by an intraday **IV decline on puts (≈ −5 to −7 pts to the close)**; IV expansion after a CHoCH was not observed on average | **NO EDGE**; IV effect on puts **measured (a cost, not a source)** |
| EXP-013 | 14 + 20 | Higher timeframe (15 / 30 / 60 min / daily; last completed candle vs EMA20): B = same direction only | Inconsistent: R-A bearish same-direction helps a little (daily sig +8.6, t 1.59; eod −25) while R-B bearish same-direction is worse than against (eod −564 vs −111). No book positive. Note: "close above EMA and EMA rising" is always true together (the EMA moves toward the close), so the label is effectively close vs EMA — no neutral class. C (counter-trend with a larger expected move) and D (HTF for strike choice) not run: no expected-move signal to scale (EXP-007), no strike with an edge (EXP-008) | **NO EDGE** |
| EXP-014 | 21 | Realised vol of the previous 20 sessions, quintiles | Non-monotone and inconsistent across definitions (R-A bearish best in the 4th quintile, R-B bearish in the 1st); highest-vol quintile negative in all four books (eod t −1.8 to −3.3) — expensive options, not more movement | **NO EDGE** |
| EXP-015 | 22 | Gap / previous-day trend / previous range (quintiles), weekly-expiry day, expiry week, monthly-expiry week. No event calendar in the data | Bearish on the weekly-expiry day: sig +12.2 (t 1.75, R-A) / +8.9 (t 2.0, R-B), eod +416 (t 1.04) / −54 (t −0.21); other days eod −337 / −442. Monthly-expiry week bearish: R-B sig +9.7 (t 2.1), eod −43. Bullish in expiry weeks: worse (R-B eod −538, t −3.6). Gap / previous-day quintiles: non-monotone. Scheduled events: not analysed (no calendar) | Expiry-day bearish: **INCONCLUSIVE** (both definitions positive at signal level, options ≈ flat); rest **NO EDGE**; events **DATA-LIMITED** |
| EXP-016 | 16 / 23 / 24 / 27 | Execution and parameters of the baseline book (bearish): entry at next close, +1 / +2 candle delay, slippage 1 / 2 pts, stops by touch, stop 4–6 %, trail 4–6 pts | Slippage is decisive: −80k at 0.5 pt → −104k at 1 → −153k at 2 (R-A). **Delaying entry one candle loses less** (R-A −80k → −25k; R-B −57k → −21k; entry at the next close −40k / −32k): the entry candle itself moves against the trade on average. Stop 4–6 % changes little; a wider trail monotonically loses less (4 → 6 pts: −87k → −69k) — consistent with EXP-011. No variant positive | **EXECUTION-SENSITIVE** and **NO EDGE**; the one-candle-delay effect is **INCONCLUSIVE** (both definitions, but +2 candles under R-B is worse again) |
| EXP-017 | 15 + 29 | Walk-forward (the only selecting step): band chosen on the earlier year(s) by sig excess, applied unchanged to the next; exit variant chosen on 2021 book net, applied to 2022 | **Band, R-B bearish: ±20 chosen in both folds; test 2022 +6.8 pts (t 1.52), test 2023 +6.2 pts (t 1.76)** — the same sign as training, twice; R-A bearish: ±35 → 2022 +2.7 (t 0.34), ±20 → 2023 +5.6 (t 1.52); bullish: signs flip. **Exits:** the 2021 choice carried to 2022 is ≤ 0 in three of four books (R-B bullish: next-close chosen at +47,656, tested −82,166); R-A bullish flip-only +41,420 (t 0.58, 49 trades) | Bearish narrow-band **signal**: **PROMISING BUT NEEDS MORE TESTING** (two out-of-year folds with the same sign, neither significant alone; not yet an option edge). Exit selection: **OVERFIT** (does not carry forward) |

Not run: phase 25 (sizing — "do not use sizing to rescue a weak strategy"); phase 28 permutation tests on the candidates above
(deferred to the validation step — permuting in-sample cells chosen from ~1,000 would only confirm the multiple-testing count);
ML (phase 33: no stable edge to model).

## EXP-018 — the user's failure conditions: yesterday's range, previous day, open, gap (2026-09-30)

| | |
|---|---|
| Question (user) | Does the signal fail when it is inside yesterday's high–low, after a bearish previous day, on a flat open, or on a gap up / gap down? |
| Method | `studies/c2c/patterns.py`, output `patterns.json` / `patterns.txt`. Development data as EXP-007…017; splits fixed before reading (gap thresholds 0.25 % and 0.5 %, round numbers). Measures: NIFTY excess to the close vs the same-time control, the per-signal ITM1 monthly option to the close, the baseline book. 80 cells (6 splits × 2–6 groups × 2 sides × 2 definitions), chosen after the development results were seen: hypotheses for 2024, not findings. |
| Result 1 — inside yesterday's range | The option trade loses most when the signal is inside yesterday's range, in all four books: −363 (t −1.6), −507 (t −3.3) for puts; −397 (t −2.8), −477 (t −2.8) for calls, with NIFTY excess ≈ 0. The same holds for the open: bearish signals on a day that opened inside yesterday's range −610 (t −3.1) / −667 (t −4.3). |
| Result 2 — previous day | Signals in the **same direction as the previous day's candle** fail; signals against it do better. Puts after a bearish day: NIFTY +2.0 / −2.4, option −297 / −576 (t −3.5), book −60,781 / −51,301; after a bullish day: NIFTY +8.8 / +7.2 (R-B t 2.54, positive in 2021, 2022 and 2023), option +45 / −186, book −21,170 / −7,599. Calls mirror it: after a bullish day NIFTY −5.3 / −5.6 (t −2.0), option −365 / −597; after a bearish day +0.1 / +1.8. |
| Result 3 — gap / open | Signals **with the opening gap** fail; signals **against it** do better. Puts on gap-down days (0.25 %): NIFTY −1.5 / −9.4; on gap-up days +3.9 / +6.0. Calls on gap-up days: −4.1 / −9.0 (t −2.6), option −284 / −747 (t −4.4); on gap-down days +8.7 / +8.6, option −157 / +289. By the open's location: puts when the day opened above yesterday's high NIFTY +28.7 (t 2.3) / +10.9 (t 3.0, positive in all three years); calls when it opened above yesterday's high −3.0 / −8.7 (t −2.5). Combined: puts after a bullish day + gap up NIFTY +45.3 (t 2.5, n 57) / +11.0 (t 2.5, n 265); calls after a bearish day + gap down +12.9 / +17.0 (t 2.6), option −428 / +799 (t 2.7). A flat open is in between. |
| Pattern | One consistent shape across both sides and both regime definitions: **the CHoCH retest works, at the NIFTY level, as a fade of the previous day / the opening gap, and fails as a continuation of them**; and it fails as an option trade when price is inside yesterday's range (no directional release). Year consistency is partial: several cells are driven by one year (2022). |
| Not solved | As option books even the favourable groups stay negative under the baseline exits (best: R-B puts after a bullish day + gap up −778, PF 0.99) — the 5-pt trail (EXP-011) still dominates. |
| Status | "Fade the previous day / gap" and "skip inside yesterday's range": **PROMISING BUT NEEDS MORE TESTING** — pre-register as fixed rules and test once on 2024 (validation) with wider exits; not to be tuned further on 2021–2023. |
