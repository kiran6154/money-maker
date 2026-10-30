# Wave-lifecycle study — pre-registration (frozen 2026-09-30, before any outcome was computed)

Hypothesis under test (user, 2026-09-30): NIFTY option premiums sometimes move
COMPRESSION → EXPANSION 1 → HIGHER BASE → EXPANSION 2 → HIGHER BASE → EXPANSION 3,
and the geometry of those waves (and the pattern itself) is measurable and predictive.
The job is to try to break it. No screenshot was supplied to this study and no option
outcome had been looked at when this file was written. Research only — nothing here trades.

The SHA-256 of this file is written into every result file; a result whose hash does not match was run under a
different design.

## 1. Data (what exists, what it can and cannot support)

| Period | Role | Source | Strikes present |
|---|---|---|---|
| 2024-01 → 2024-12 | **development** | `D:/nifty/data/nifty_options/2024/*` native 5-minute | every 50-pt strike within ±3 % of the Monday 09:20 ATM of the expiry week |
| 2025-01 → 2025-12 | **validation** (untouched until the code is frozen on development) | `D:/nifty/data/nifty_options_1minute/2025/*` 1-minute | 5 strikes, 100-pt grid, ±200 around the Monday 09:20 ATM of the expiry week |
| 2026-01 → 2026-09 | **blind** | `nifty_options_1minute/2026/*` | same as 2025 |

- **Primary timeframe = 5 minutes** — the only one that exists in all three periods. 2025–26 5-minute bars are built from
  the 1-minute files (checked against the native 5-minute files where both exist). 1 / 3-minute exist only in 2025–26;
  10 / 15-minute are built in every period. Non-primary timeframes are **run with the frozen parameters, never re-tuned**.
- Session reference spot = the close of the 09:15 5-minute bar of the long index file
  `D:/nifty/nifty50_5minute_2019-01-01_to_2026-09-26.csv` (the c2c ledger A1 found the Breeze index file corrupt at 09:15 / 15:20).
- Underlying for Greeks / decomposition = the put-call-parity forward from the option pairs themselves
  (`F = K + (C − P)·e^{rT}`, median over strikes where both legs traded in the bar), index close as fallback.
- **Strike choice (no hindsight):** at each session the scanned contracts are fixed from the 09:20 reference spot on the
  100-pt grid: ATM, OTM1 (±100), OTM2 (±200), ITM1 (∓100), CE and PE. 100-pt grid in every year so 2024 is comparable with
  the 2025–26 files. A contract missing from the files is skipped and counted.
- **Hindsight flag:** the files' strike lists were chosen at the Monday 09:20 of the expiry week. Sessions **before** that
  moment belong to a strike list chosen from the future → `strike_set_hindsight = true`. Primary results use only
  sessions at or after the reference moment; everything is also reported with the flagged sessions added.
- **Expiries:** front weekly (nearest expiry ≥ session date) is primary. The next weekly is scanned only for the DTE study.
- DTE = calendar days from session date to expiry date. Buckets 0 (expiry day), 1, 2, 3–4, 5+.
- No bid / ask, no IV in the data. IV and Greeks = Black-76 on the forward, r = 6.5 %, T = calendar time to expiry 15:30.
  Spread is **assumed** (see §8) and labelled as such.

## 2. Bars and liquidity

- Session 09:15–15:30. A 1-minute row with volume 0 and O=H=L=C = previous close is a **filler** (no trade). A resampled bar
  is filler when all its minutes are.
- A bar is **eligible** as a signal bar when: it is not the session's first bar; its time ≤ 15:00 (so a 30-minute horizon
  fits); among it and the preceding L bars at most 10 % are filler; close ≥ ₹5.
- All structure (bases, waves) is **intraday**: state resets at each session open. Only the ATR may use previous-session bars
  (overnight gap excluded from the true range).

## 3. Mechanical definitions (upward lifecycle on log premium; all causal)

Units: `ATR` = mean over the previous N_v = 20 bars of the log true range (bar t's own ATR is known at its close).

| # | Term | Programmable definition |
|---|---|---|
| 1 | Compression | at bar t, the box of the last L bars (all in today's session): `W = ln(maxH / minL)`. `CR = W / (ATR_pre · √L)`, ATR_pre = ATR at the bar before the box started. Under a random walk CR ≈ 1. **Compressed if CR ≤ c.** |
| 2 | Base 0 | the latest compressed box: `base_high`, `base_low`. Stays armed for L bars after the last compressed bar. |
| 3 | Initial expansion (E1 breakout) | first close > `base_high` while Base 0 is armed. Breakout level = `base_high`. |
| 7 | Acceptance | the breakout bar and the next m−1 bars all close above the breakout level. A close at or below it inside that span = **failed expansion** (level stays; another breakout may follow). Signal time = the m-th close. |
| 3 | Resistance R_n | the peak of expansion n: a zig-zag on highs / lows with reversal k·ATR. The running max after acceptance is confirmed as R_n when a low ≤ max − k·ATR (confirmation time = that bar). |
| 5 | Higher low | a zig-zag swing low (confirmed when a high ≥ low + k·ATR) that is above the previous swing low. |
| 8 | Higher base n | the pullback after R_n: every **close** stays above the support level S_n. Strict (primary): S_n = R_{n−1} (S_1 = base_high: the old resistance becomes support). Loose (grid): S_n = the previous swing low (S_1 = base_low). A close ≤ S_n ends the lifecycle (**failed base**). |
| 4 | Resistance retest | during base n, a bar with high ≥ R_n − 0.5·ATR and close ≤ R_n. Counted (feature, not required). |
| 6 | Breakout n+1 | a close > R_n during base n. |
| 9–10 | Second / third expansion | the breakout above R_1 / R_2, accepted (definition 7). `wave_number` = count of accepted expansions. |
| 11 | Failed expansion | a breakout not accepted (7), or a lifecycle that ends by a failed base (8) or stalls: no new breakout within 2L bars of R_n's confirmation. |
| 12 | Complete lifecycle | wave_number reaches 3 inside the session. |

Mirror (downward) lifecycle = the same rules on −ln premium; used only as a falsification control (§10).

## 4. Parameters — primary cell and the pre-registered neighbourhood

| Parameter | Primary | Grid (all cells reported, none chosen by result) |
|---|---|---|
| L compression window (bars) | 12 | 8, 10, 12, 14, 16 |
| c compression ratio | 0.75 | 0.6, 0.75, 0.9 |
| k zig-zag reversal (ATR) | 2.0 | 1.5, 2.0, 2.5, 3.0 |
| m acceptance closes | 2 | 1, 2, 3 |
| support rule | strict | strict, loose |
| v volume spike (× median) | 3 | 2, 3, 5 |

Full grid = 5·3·4·3·2 = 360 cells on the primary timeframe; controls use their own parameter where they have one.
A finding that holds in the primary cell only, or flips sign between neighbouring values, is reported as fragile.

## 5. Signals and controls (Part 13)

All on the same eligible bars. Entry reference = the signal bar's close.

| Code | Signal |
|---|---|
| A | random / unconditional: every eligible bar (base rate) |
| B | compression only: bar where CR first drops ≤ c |
| C | volume spike only: `VR = vol / median(vol of previous 20 non-filler bars) ≥ v` |
| D | breakout only: close > max high of previous L bars |
| E | higher-low only: zig-zag confirms a swing low above the previous swing low |
| F | breakout + volume: D with VR ≥ v |
| G | compression + breakout: accepted E1 (wave 1) |
| H | compression + higher low + breakout: E1 → pullback with swing low > base_low → close > R_1 (no acceptance, loose support) |
| I | complete lifecycle so far: accepted E2 (wave 2) — **the hypothesis' signal**. I3 = accepted E3 (another expansion after a complete lifecycle?) |
| J | momentum-matched control (added): for each I event, eligible bars of the same period, option type, DTE bucket, hour of day and trailing-L-bar return decile |

## 6. Outcomes (Part 14)

Forward log return and MFE / MAE (highs / lows after the signal bar) at 5, 10, 15, 30, 60 minutes and to the session close;
P(MFE ≥ +5 / 10 / 20 / 30 / 50 %) to the session close; P(another accepted expansion), time to it; P(failure).
A horizon is used only for events whose horizon ends by 15:30. Points and percent both kept.

## 7. Pre-registered hypotheses and decision rule

- **H1 (predictive, the trading question).** Primary cell, 5-minute, front-weekly ATM CE and PE pooled, strike-set-clean
  sessions: mean 30-minute forward log return of I minus its J-matched expectation > 0. Inference: week-clustered bootstrap
  (5,000) 95 % CI. Evaluated separately on validation (2025) and blind (2026). Development only debugs.
- **H2 (structure).** P(accepted E3 | accepted E2) is higher than in the null (§10, shuffled bars through the same detector),
  CI of the difference excluding 0, in validation and blind.
- **H3 (geometry).** Which of the §9 models predicts the next peak best out of sample, and whether the increment ratios
  differ from the null distribution.

Conclusion (Part 20 J), fixed now:
1 **Strong evidence** — H1 CI > 0 in validation AND blind, the excess exceeds the round-trip cost of §8, ≥ 70 % of grid
  cells have a positive excess in both, and the falsification tests of §10 do not reproduce it.
2 **Structure, insufficient for trading** — H2 or H3 differs from the null in both periods, or H1 passes before costs /
  in one period / in the primary cell only.
3 **No meaningful predictive structure** — H1 and H2 not separable from the null / matched controls in validation and blind,
  with CIs narrow enough (half-width < round-trip cost) to rule out a tradable effect.
4 **Inconclusive** — anything else (e.g. < 100 I events in a period, or CIs wider than the round-trip cost).

Multiple testing: secondary families (controls × horizons × subgroups × timeframes) get Benjamini–Hochberg q-values;
only the single H1 test is confirmatory.

## 8. Costs (Part 15, applied only after §7)

Zerodha NFO options schedule from `config/charges.json` (₹20 / order, STT 0.1 % sell, NSE 0.03503 %, SEBI, stamp 0.003 % buy,
GST 18 %). Lot size 25 (2024 contracts to Nov), 75 (Dec 2024 – Dec 2025), 65 (2026) — assumptions. Spread + slippage per
side assumed at 0.25 %, 0.5 %, 1 % of premium (no bid/ask data). Timing variants: entry at the signal close (reference)
and at the next bar's open (realistic).

## 9. Wave geometry (Parts 3–6)

Levels of a lifecycle: P_0 = base_high, P_n = R_n (peaks), B_n = pullback lows.
Models on P(n): A linear, B a + b·ln(n+1), C a·e^{bn}, D a·(n+1)^b, E P_0·r^n (1 parameter), F wave: expansion
E_n = ln(P_n / B_{n−1}) and retracement D_n = ln(P_n / B_n) with D_n = ρ·E_n and E_{n+1} = γ·E_n.
In-sample: R², RMSE, MAE, AICc per lifecycle with ≥ 4 levels (reported, not used to choose). **Out of sample:** at the
accepted-E3 signal the models are fitted to P_0..P_2 and predict P_3 (if it forms); at the accepted-E2 signal the
1-parameter forms (geometric r = P_1/P_0; linear Δ = P_1 − P_0) predict P_2. Benchmarks: "no further gain" (P_n = current)
and the development-period median increment. Increment ratios Δ_{n+1}/Δ_n and log-increment ratios g_{n+1}/g_n are compared
with the null (§10) and split by DTE, underlying move, IV.

## 10. Falsification (Part 17)

- **Null paths:** each contract-session's bars shuffled in time (bar = its open-relative H / L / C offsets and volume,
  first bar kept), 20 replicas, run through the identical detector → pattern frequency, continuation rates, ratios, model
  preferences under "no serial structure".
- Matched-random entry times; permutation of the I label among J-matched bars (2,000); week block bootstrap CIs;
  volume shuffled within session for the volume-using signals; every grid cell; other strikes / next expiry;
  CE/PE reversal (does a CE I-event forecast the same-strike PE falling as it should, and does the mirror downward pattern
  behave like its reflection).

## 11. Decomposition (Part 8) and DTE (Part 9)

Each expansion leg, Black-76 revaluation: delta-linear (Δ_0·ΔF), convexity / moneyness (rest of the fixed-IV move in F),
theta (time at fixed F, IV), vega (IV change at the end state), residual. "Genuinely in the option" = the IV component's
share; "reflection of NIFTY" = delta + convexity share. DTE: over every eligible 15-minute window, option log return on
forward log return with a quadratic term, by DTE bucket and moneyness — measured, not assumed.

## 12. What this study does not do

No parameter is fitted on 2025 or 2026. No strategy bean, no `TradeConfig`, no order. Regime splits that use the full
day's information (bull / bear / flat by the session's open→close) are labelled ex-post and are descriptive only; the causal
versions (open→signal return, previous-session range) are reported beside them.
