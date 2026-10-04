# Wave-lifecycle study — ledger

Append-only. What was decided, when, and on which data. The design is [`PREREG.md`](PREREG.md); every result file
carries its SHA-256. Rule 0 entry: `docs/STRATEGY_ANALYSIS_TODO.md` S54.

## 2026-09-30 — before any outcome

- `PREREG.md` written and hashed before any option outcome was computed. No screenshot was supplied to the study.
- Data audit (prices only, no outcomes):
  - 2024: native 5-minute, every 50-pt strike within ±3 % of the Monday 09:20 ATM of each expiry week, 51 weeks.
  - 2025–26: 1-minute, 5 strikes on the 100-pt grid around the Monday 09:20 ATM, 45 + 38 weeks. Sessions more than a
    week from expiry are thin (≈ 40–60 % filler minutes).
  - 1-minute bars resampled to 5 minutes vs the native 5-minute files (20 weeks of 2025 where both exist, 122,234 CE
    bars): close identical in 100 %, open / high / low in 99.3 / 99.7 / 99.7 %, volume ratio median 1.00. 2024 native
    5-minute and 2025–26 resampled 5-minute are therefore comparable.

## Development phase (2024 only)

- **DEV-1 (bug fix, detector).** Inspecting a 2024 event (2024-02-21, PE 22200, DTE 1) showed a single wide bar
  confirming its own high as a peak through its own low. OHLC does not say whether that low came before or after the
  high, so the peak was a hindsight swing point. Fixed in every zig-zag (`detect.py`): a bar that makes a new extreme
  cannot confirm the reversal in the same bar. The truncation test and the user-example test still pass. Effect on
  development: wave-2 (I) events, ATM front, clean sessions 40 → 26.
- **DEV-2 (memory, no definitional intent).** The machine is shared (7.9 GB, other sessions' jobs running). The bar
  panel keeps each contract's chosen sessions plus the two sessions before each (ATR warm-up); the raw loader keeps
  only 100-pt strikes (the study never uses others). ATR could differ from the untrimmed panel only where the two
  previous sessions hold < 10 traded bars.

### Implementation choices the pre-registration left open

- Expansion amplitude E_1 is measured from the Base 0 **low** (E_n = ln(P_n / B_{n−1}), B_0 = box low).
- Decomposition (§11) uses closes of the leg's start bar (Base low bar) and end bar (peak bar). IV is implied from the
  same closes, so the residual is identically zero and the "vega" share also absorbs smile / model error.
- The permutation test draws matched pool bars with replacement within each matched cell.
- Control E (higher low) uses the same k as the lifecycle zig-zag.
- Base 0 stays armed for L bars even if price closes below the box (as written in PREREG §3). Open question, not
  changed: a downside break arguably ends the compression.
- 10- and 15-minute bars reuse the bar-count parameters; with L = 12 a wave-2 event needs most of a session, so few
  occur. That is a property of the pre-registered bar-count scaling, reported as such, not re-tuned.

### Power warning, before validation

Development gave 26 wave-2 (I) events on the primary contracts (ATM, front weekly, clean sessions). The pre-registered
rule treats < 100 I events in a period as inconclusive for H1; validation and blind are likely to be similar in size.
The pooled-contract rows (all four moneyness, front weekly) are the larger secondary sample.

### Development readings recorded before validation was opened (2024, in-sample)

- I (wave 2 accepted), front weekly, all four strikes, clean sessions: 30-minute excess over the J-matched pool
  **+10.7 %** (week-clustered 95 % CI +3.3 to +19.3, n = 105, 33 weeks); primary ATM only +9.4 % (+0.5 to +19.3, n = 26,
  permutation p = 0.095). G (wave 1) and the single-component controls B–F: about 0.
- Grid (360 cells): I front excess positive in 359 of 359 cells with >= 10 events (median +5.7 %).
- Null (20 bar-shuffles per contract-session): lifecycle counts equal to the real ones (wave 1: 1,032 vs 1,007; wave 2:
  117 vs 113), P(wave 3 | wave 2) real 6 % vs null 10 %; **the null I events also show a positive matched excess (+2.3 %
  front, +3.8 % ATM)**, so the matched baseline is biased upward for this conditioning and the real effect must be read
  against the null, not against zero.
- Decomposition: delta 85 %, convexity 15 %, theta −3.5 %, IV +3 % of the expansion gain; NIFTY moved with the wave in
  99.8 % of legs. Volume spikes on the breakout bar, not before it.

## CODE FREEZE — 2026-09-30, before any 2025 / 2026 outcome

`results/FREEZE.sha256` holds the SHA-256 of `PREREG.md`, `data.py`, `detect.py`, `pipeline.py`, `study.py`, `stages.py`,
`test_detect.py`. Validation (2025) and blind (2026) are run once with these files. Any later change is logged below
with the reason, and the frozen-code numbers stay the reported ones.

### POST-FREEZE-1 (memory only, results unchanged)

`pipeline.build_bars` now builds one expiry at a time; the whole-year version could not allocate the 2025 1-minute panel
on the shared machine. Checked: the 2024 5-minute panel rebuilt this way is identical to the frozen one
(`assert_frame_equal`, 487,833 × 29). New `pipeline.py` hash recorded in `results/FREEZE.sha256` as `POST-FREEZE-1`.

### POST-FREEZE-2 (memory only, results unchanged)

The shared machine dropped below 1 GB free commit (another session's `lab.py` at 2.3 GB, mysqld 2.9 GB). `build_bars`
now reads the raw cache one expiry at a time through a parquet filter instead of loading the year. Checked again: the
2024 5-minute panel is identical to the frozen one. Hash appended to `results/FREEZE.sha256`.

## 2026-09-30 — validation and blind, run once on frozen code

Result summary in `REPORT.md`; conclusion **4 (inconclusive)** by the pre-registered rule: H1 not confirmed in 2025
(+2.4 %, CI across 0) or 2026 (−10.5 %), H2 not separable from the shuffled null in either year, 2025–26 intervals
wider than the round-trip cost. Nothing was re-tuned. The first launch of the 2025–26 run died with the session after
2025 5-minute; the remaining stages were re-run with the same frozen files (`run_oos2.ps1`), not re-executing what
had finished. Post-hoc observations (wave-3 on 1-minute, CE > PE) are recorded as leads in S54, not as findings.
