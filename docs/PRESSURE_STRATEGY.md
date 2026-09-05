# Pressure (Strategy 5) — NIFTY intraday continuation

A one-position-at-a-time continuation engine on **NIFTY 5-minute spot**, trading
weekly options. Registered as `stratergy_id = 5`
([`Strategy5`](../src/main/java/com/moneymaker/strategy/Strategy5.java)).

> **This is not an SMA strategy and it is not a fade.** It shares no rules with
> Strategy 1/2/3/4 and must not be mixed with them. Where they compute an SMA on
> the *option premium* and sell a cross, this scores the *underlying* on five
> indicators and trades the continuation.

---

## Contents

- [What it trades](#what-it-trades)
- [The pressure score](#the-pressure-score)
- [The clock](#the-clock)
- [Exits](#exits)
- [The seven books](#the-seven-books)
- [Strike selection](#strike-selection)
- [Charges — two columns](#charges--two-columns)
- [How to run it](#how-to-run-it)
- [Deviations from the written spec](#deviations-from-the-written-spec)
- [How it fits the framework](#how-it-fits-the-framework)
- [Why strategies 1–4 are unaffected](#why-strategies-14-are-unaffected)
- [Debugging checklist](#debugging-checklist)

---

## What it trades

Each 5-minute tick, the strategy scores the latest **settled spot bar** on two
integer pressure scores. When one side reaches 3, it opens a single position on
the leg its config trades:

| Signal | Sell book | Buy book | Spot book |
|---|---|---|---|
| `P_down >= 3` | SELL CE | BUY PE | SHORT spot |
| `P_up >= 3` | SELL PE | BUY CE | LONG spot |

One position at a time, across the whole book. When it exits, the next bar may
take a new signal — **re-arm immediately**. There is deliberately no forced
dead window after an exit.

---

## The pressure score

All five indicators are computed on **spot 5-minute**, with no lookahead.
Implementations live in
[`indicator/series/`](../src/main/java/com/moneymaker/indicator/series/) and the
scoring in
[`PressureScore`](../src/main/java/com/moneymaker/strategy/pressure/PressureScore.java).

```
P_down = (RSI < 40) + (close < ANCHOR) + (ST_dir == -1) + (close < OR_low)
         - 1  if  (ADX > 40  AND  -DI now < -DI 3 bars ago)

P_up   = (RSI > 60) + (close > ANCHOR) + (ST_dir == +1) + (close > OR_high)
         - 1  if  (ADX > 40  AND  +DI now < +DI 3 bars ago)

signal if P_down >= 3 or P_up >= 3.  If BOTH, skip.
```

> ### The third term is NOT a VWAP
>
> The written spec calls it "Session VWAP". It is not one, and the reference
> implementation that produced the 1,560-ticket 2024 book **used no volume at
> all** — confirmed by the strategy's author, 2026-09-05: *"I should have called
> it session typical-price mean."*
>
> ```
> typical   = (high + low + close) / 3
> ANCHOR[i] = mean( typical[0..i] )        # expanding, reset each session
> ```
>
> Reading the word literally already cost one invalid full-year run: NIFTY spot
> has no volume column worth the name, so an earlier build **invented** a
> front-weekly option-volume weight to satisfy it. That is a different
> indicator, it changes which bars score the term, and nothing in the output
> looks wrong when it happens. `TYPICAL_MEAN` is the default and is what
> reproduces the reference.

| Term | Indicator | File |
|---|---|---|
| RSI | RSI(14), **Wilder** smoothing | [`WilderRsi`](../src/main/java/com/moneymaker/indicator/series/WilderRsi.java) |
| Anchor | Session **typical-price mean** from 09:15, `(H+L+C)/3`, expanding, **unweighted** | [`SessionAnchoredPrice`](../src/main/java/com/moneymaker/indicator/series/SessionAnchoredPrice.java) |
| ST_dir | Supertrend(ATR 10, multiplier 3), `+1` / `-1` | [`Supertrend`](../src/main/java/com/moneymaker/indicator/series/Supertrend.java) |
| OR | High/low of bars in `[09:15, 09:30]`, **both inclusive** | [`OpeningRange`](../src/main/java/com/moneymaker/indicator/series/OpeningRange.java) |
| ADX, ±DI | ADX(14) Wilder | [`DirectionalIndex`](../src/main/java/com/moneymaker/indicator/series/DirectionalIndex.java) |

### Three scoring rules that are easy to get wrong

**1. A missing confirming input scores nothing.** With a threshold of 3 out of 4,
counting one unknown as satisfied silently turns the rule into 2-of-3. So an
un-computable RSI, anchor or Supertrend contributes zero, and an **incomplete
opening range** contributes zero — a range built from a partial window is
guaranteed too narrow, which would hand every early bar a free breakout point.

**2. A missing penalty input applies no penalty.** The opposite reading, on
purpose. A penalty is a reason *not* to trade; inventing one from missing data
would suppress valid entries. The asymmetry is deliberate and tested.

**3. Both sides firing is skipped, not tie-broken.** A bar that is simultaneously
3 points down-pressured and 3 points up-pressured is a bar the model does not
understand; picking the larger score would manufacture a decision out of
self-contradiction. It is logged at INFO so a rising count is visible.

### Why a separate indicator package

The existing `Indicator` SPI is `List<MarketData> -> Double` — one scalar for the
whole series. That is fine for an SMA and wrong for three of these five:

- **Supertrend is path-dependent.** Its direction at bar *i* depends on the
  direction at bar *i−1*, and its bands ratchet. There is no way to answer "what
  is the direction now" without walking the chain from the start, so a scalar SPI
  called per bar is both O(n²) and *wrong* — it returns a different answer
  depending on how much history the caller passed.
- **ADX / ±DI** are the same recurrence one level down.
- **The session anchor** is anchored and expanding, i.e. defined per bar.

So `indicator/series/` computes `double[]` aligned index-for-index with the
input, once per tick, and callers index into it.

> `RSIIndicatorImpl` in the old package is a **stub that returns `0.0`**. It is
> deliberately left alone — it is registered in `IndicatorFactory` and changing
> it would be a behaviour change for anything resolving "RSI" through the
> factory. `WilderRsi` is a new, separate implementation, pinned against
> Wilder's own published worked example in
> [`WilderRsiTest`](../src/test/java/com/moneymaker/indicator/series/WilderRsiTest.java).

### Warmup vs session windows

[`SpotFeatures`](../src/main/java/com/moneymaker/indicator/series/SpotFeatures.java)
computes over **two different windows**, and the split matters:

- **RSI, Supertrend, ADX** use the *warmup* series — the day plus several prior
  sessions. All three are Wilder recurrences with unbounded memory, so restarting
  them at 09:15 would give the first hour of every session a value that is still
  converging, making morning scores systematically different from afternoon ones.
- **The anchor and the opening range** use *today only*, because both are
  anchored to today's open by definition.

Both windows are **session-filtered**. `historical_spot_candles` carries
out-of-session rows — 09:05, 09:10 and 15:35 on most days, 762 of them across
2024 — and anchoring the mean or the opening range to 09:05 instead of 09:15
would shift both on nearly every day in the set.

---

## The clock

Every boundary is a `trade_config` column (changeset 042), not a constant —
CLAUDE.md invariant 9.

| Rule | Column | Value |
|---|---|---|
| First new entry, inclusive | `entry_from` | 09:25 |
| Last new entry, inclusive | `entry_to` | 14:15 |
| Max hold | `max_hold_minutes` | 90 (18 bars) |
| Hard flatten | `flatten_at` | 15:15 |

The entry window is enforced in `OrderService` and applies to **entries only** —
never to exits. A window that could strand an open position past its own
stop-loss would be a risk control that creates risk.

> **This is the FULL CLOCK.** When a trade exits, the next bar may take a new
> signal. There is no forced 90-minute dead window after an exit. That other
> clock produces a different, smaller book and is not this spec.

---

## Exits

All four are position-level rules applied by `PositionService` from the bracket
snapshotted on the order at entry. **The strategy emits no exit signal at all.**

| Exit | `exit_reason` | Rule |
|---|---|---|
| Target | `TARGET` | +50 premium points, tested on bar close |
| Stop | `STOP_LOSS` | −50 premium points, tested on the bar's **adverse extreme**, fills at the floor |
| Trail | `TRAIL_SL` | arm at +25 favorable excursion, exit on a fall back to +25 |
| Time | `TIME_STOP` | 90 minutes from `entry_time` |
| Flatten | `FLATTEN` | 15:15, regardless of P&L |

`TIME_STOP` and `FLATTEN` are new in changeset 043 and are distinct from
`FORCE_CLOSE`, which is the replay's own 15:20 end-of-day sweep and means "the
run ended with this still open". Collapsing them would make it impossible to tell
a strategy that exits on its own clock from one that had to be cleaned up after.

### Ordering within a bar

`target` → `time exits` → `floors`. A bar can satisfy several at once, and this
ordering is the conservative reading:

- **Target first**, unchanged from before, so a bar that reached the target books
  it rather than being downgraded to a coincident time stop.
- **Time exits before the floors**, because a stop-loss on the flatten bar is not
  a stop the strategy would have taken — the position was already due to close at
  that moment regardless of price, and labelling it `STOP_LOSS` would overstate
  how often the stop is hit.

### The `25:25` trail

The trail is expressed as a `trail_ladder` of `"25:25"` — a rung locking at
exactly its own trigger. `TrailLadder.parse` **used to reject this**, on the
grounds that "the trade would exit the moment the rung arms". That objection is
wrong about this codebase: `PositionService.handleOne` arms rungs *after* its
breach check, so the bar whose excursion earns a rung cannot also exit on it, and
the earliest such a floor can fire is the next bar.

It is genuinely different from a `+25` target: a target books +25 on the way
**up**; this books +25 only on the way back **down** from a higher peak. A trade
that runs to +60 and retraces exits here at +25 having reached +60; on a target
it would have exited at +25 without ever seeing it.

Only `lock > trigger` is now refused — that floor would sit above the peak that
armed it.

---

## The seven books

Defined as data in
[`PressureBook`](../src/main/java/com/moneymaker/tradeconfig/generation/PressureBook.java).
All seven see **identical entry decisions** and differ only in what instrument
the trade is put on.

| Book | Legs | `strike_offset_points` |
|---|---|---|
| `SPOT` | SHORT / LONG on the synthetic underlying | — (`underlying_leg = true`) |
| `SELL_ITM300` | SELL CE + SELL PE | 300 |
| `SELL_ITM200` | SELL CE + SELL PE | 200 |
| `SELL_ATM` | SELL CE + SELL PE | 0 |
| `BUY_ITM300` | BUY CE + BUY PE | 300 |
| `BUY_ITM200` | BUY CE + BUY PE | 200 |
| `BUY_ATM` | BUY CE + BUY PE | 0 |

### Why each book is two configs

`trade_config.trading_side` is single-valued, so a book acting on both
down-pressure and up-pressure needs one config per leg. They share a `book_id`.

**This is what `book_id` exists for.** Every other cap in `OrderService` keys on
`(trade_config_id, strategy_id)`, so the two legs would hold two *independent*
budgets and could run a CE short and a PE short concurrently — not one position,
and double the intended risk. `TradeOrderRepository.countOpenInBook` counts OPEN
rows across every config in the book.

### The SPOT baseline book

Same signals, same clock, same brackets, but priced in **index points** off
`historical_spot_candles`. It is the row that separates *how good the signal is*
from *how good the chosen option expression is*.

It runs through the ledger as a pseudo-contract —
[`SyntheticUnderlyingContract`](../src/main/java/com/moneymaker/market/instrument/SyntheticUnderlyingContract.java):

```
option_token = NIFTY-SPOT      option_type = SPOT      option_strike = 0
```

`AnalysisScheduler` publishes the spot series into the strike cache under that
key, so `SharedData.latestCachedCandle` — and therefore
`BacktestingPositionMonitorService` and the force-close sweep — quote it with **no
knowledge of spot at all**. Nothing in the position or order layer was modified
for it.

The alternative was a separate in-memory walker, which would have meant a second
copy of the target / stop / trail / time-stop / flatten logic that has to stay in
step with `PositionService` forever — exactly the duplication invariant 8 exists
to prevent — and would have put the baseline in a different table from the six
books it exists to be compared against.

Its charges are **zero**: there is no contract note for a hypothetical index
trade.

---

## Strike selection

```
ATM        = round(spot_close / 50) * 50
CE strike  = ATM - offset          (offset > 0 is ITM for a call)
PE strike  = ATM + offset
fallback   = exact, then ±50, then ±100
```

Implemented in
[`OffsetStrikeSelector`](../src/main/java/com/moneymaker/market/instrument/OffsetStrikeSelector.java),
used by `AnalysisScheduler` only when `strike_offset_points` is set.

### Three things this does differently from the depth-count path

1. **One exact strike, not a set.** `itm_depth` / `otm_depth` are *counts of
   strike steps* that expand into a set the SMA strategies then rank by premium.
   Pressure wants one contract, so the offset is in **points**.
2. **Rounds, not floors.** The shared path uses `floor(close/step)*step`. On a
   50-point grid that biases the chosen strike down by an average of 25 points on
   every trade — systematically less ITM on a CE, more on a PE.
3. **Its own strike step.** `instrument.strike_points` is **100** for NIFTY while
   the imported chain is on a **50-point grid** (20250, 20300, 20350 …). Both are
   right for their own consumer, so the config carries
   `strike_step_points = 50` and the shared instrument row is left untouched —
   editing it would move every strike strategies 1–4 pick on historical replay.

> **Resolution is per-config, by exact strike.** Every Pressure config writes into
> the one shared strike cache and they all leave the depth columns null, so their
> keys differ only in strike and contract. `Strategy5` therefore recomputes its
> own strike from the same spot close and looks that up, rather than taking the
> first key with a matching side. An earlier version did the latter and
> `SELL_ITM300`, `SELL_ITM200` and `SELL_ATM` all silently traded the *same* leg,
> non-deterministically — three books that are the whole comparison collapsing
> into one.

---

## Charges — two columns

Every trade is costed **twice** and both are reported:

| Column | Source | Brokerage | Exchange txn (pre-Oct 2024) |
|---|---|---|---|
| `net_broker` | `TradeChargeService` + seeded `charge_rate` rows | ₹20/leg **or 0.03% of turnover, whichever lower** → ~₹16 round trip at ITM300 | 0.053% |
| `net_spec` | [`PressureSpecCharges`](../src/main/java/com/moneymaker/backtesting/PressureSpecCharges.java) | ₹40 round trip, flat | 0.0495% |

STT (both eras), SEBI, stamp duty and GST agree exactly between the two.

The gap is **~₹25–30 a trade**, dominated by brokerage — about **₹44,000 over
1,560 trades**, roughly 30% of the spec's implied charge total. Too large to
average away.

**Why the rate table was not simply corrected:** `charge_rate` is global and
date-effective, so editing those rows silently restates the net P&L of every
trade strategies 1–4 have ever produced. Reporting both leaves the existing
ledger untouched. Neither column is "the" answer — the spec column reconciles
against the reference run, the broker column is what this desk would actually
have paid.

---

## How to run it

All endpoints are gated to `app.mode=backtest`.

```powershell
# 1. Generate configs (idempotent; re-running creates nothing)
curl -X POST "http://localhost:8080/api/pressure/configs/generate?fromDate=2024-01-01&toDate=2024-12-31"

#    ...or scope to specific books
curl -X POST "http://localhost:8080/api/pressure/configs/generate?fromDate=2024-01-01&toDate=2024-12-31&books=SELL_ITM300,SPOT"

#    list the book ids
curl "http://localhost:8080/api/pressure/configs/books"

# 2. Replay
curl -X POST "http://localhost:8080/api/backtest/analysis?fromDate=2024-01-01&toDate=2024-12-31&strategyIds=5"

# 3. Report
curl "http://localhost:8080/api/pressure/report/summary?fromDate=2024-01-01&toDate=2024-12-31"
curl "http://localhost:8080/api/pressure/report/csv?fromDate=2024-01-01&toDate=2024-12-31" -o pressure-trades.csv
```

A full-year run is **7 books × 2 legs × 249 trading days = 3,486 configs**.

> **Wipe `trade_order` rows for strategy 5 between comparison runs.** The replay
> has an exact-duplicate guard on `(config, strategy, contract, direction,
> entry_time)`, so an identical re-run will not duplicate — but any change that
> moves a strike or a timestamp will leave the old rows alongside the new ones
> and every aggregate will be wrong.

### Config values the generator writes

| Field | Value | Why |
|---|---|---|
| `target` / `stop_loss` | 50 / 50 | absolute points; `strategy_defaults.target_mode = POINTS` |
| `trail_ladder` | `25:25` | the give-back trail |
| `min_option_price` | 8 | the spec's "skip if premium < 8"; null on the SPOT book |
| `no_of_trades` | **null** | no daily cap — re-arm on exit. "No cap" *is* the configured value |
| `max_loss` | **null** | the spec names no daily loss cap, and adding one would be an extra filter |
| `no_of_parrellel_trades` | 1 | |
| `max_parallel_per_side` | 1 | |
| `lot_quantity` | 75 | |
| `source` | `PRESSURE` | scopes a re-run or a cleanup |

---

## Deviations from the written spec

Three, all forced or measured, all recorded in
[`STRATEGY_ANALYSIS_TODO.md`](STRATEGY_ANALYSIS_TODO.md) as S22–S24.

### 1. The "VWAP" term — resolved, was a naming problem not a data problem

**No longer a deviation.** The spec's wording said VWAP; the reference used an
unweighted session typical-price mean, and that is now what this implements. See
the callout above.

The history is worth keeping because the failure mode is instructive. NIFTY is an
index and has no traded volume — 19,572 of the 19,602 `historical_spot_candles`
rows for 2024 carry `volume = 0`. Faced with a spec term that could not be
computed, the first build **invented a substitute** (front-weekly option-chain
volume as a weight) rather than asking. It ran, it logged plausible numbers, and
it was silently a different strategy. The lesson is the one Rule 0(b) already
states: an unmeasurable input is a question, not a modelling opportunity.

The volume path survives as opt-in — `app.pressure.anchor-mode=OPTION_TAPE_VWAP`
— for a genuinely different experiment the author proposed: a real
volume-weighted price off the **option tape** (ATM ±2 strikes, both rights).
That is not a refinement of the reference; it changes what trades get taken, so
the 1,560-ticket book would have to be re-marked before its figures could be
compared against it. Tracked as S22.

### 2. The trail tests the wick, not the close

The spec says test the trail on close. `PositionService` tests floors on the bar's
**adverse extreme** and fills at the floor — the resting-order model (S4). Kept
deliberately (user decision 2026-09-04): it is consistent with every other
strategy here and needs no change to shared exit code. It is the more
conservative of the two and will exit earlier on some trades.

### 3. Entry fill is the signal candle's close

The spec says "last option close at or before the signal timestamp". The framework
convention is the signal candle's own close, carried on `TradeSignal.price`.

---

## How it fits the framework

| Invariant | How this honours it |
|---|---|
| 3 — single state holder | reads `SharedData` caches; no direct repository reads for runtime state |
| 5 — backtest == live preflight | no separate test path; the replay drives the same three schedulers |
| 6 — Liquibase only | changesets 042, 043, 044; nothing committed was edited |
| 7 — `trade_order` is the ledger | every entry and exit persists; the SPOT book included |
| 8 — schedulers replayable | all work is in services; nothing added to a `@Scheduled` body |
| 9 — no hardcoded trading rules | every clock, bracket and strike number is a `trade_config` column |
| 10 — trade-config writes | the generator follows `EodDowntrendDetectionService`'s precedent for the `tradeconfig.generation` package, and explicitly invalidates the date-keyed config cache |

Signals still go `Strategy5` → `SharedData.tradeSignals` → `OrderService`. The
strategy never calls `OrderPlacementService`.

---

## Why strategies 1–4 are unaffected

This is the load-bearing claim of the whole change. Every mechanism is
**opt-in via a nullable column**, and null means "the rule that applied before":

| Change | Inert for 1–4 because |
|---|---|
| 8 new `trade_config` columns | all nullable (or default FALSE); every consumer reads null as pre-042 behaviour. Pinned by `TradeConfigCombinedQueryContractTest.pressureColumnsAreOptional` |
| 2 new `trade_order` columns | nullable; `PositionService` reads null as "this exit does not apply" |
| `AnalysisScheduler` offset branch | guarded on `strike_offset_points != null` |
| `AnalysisScheduler` spot-publish branch | guarded on `underlying_leg` |
| `OrderService` entry window | guarded on `entry_from` / `entry_to` being set |
| `OrderService` book cap | guarded on `book_id` being set |
| `PositionService` time exits | guarded on the snapshotted columns being set |
| `TrailLadder` relaxation | a **widening** of validation — no existing ladder becomes invalid |
| `resolveOptionType` visibility | private → protected; body unchanged |
| `strategy_defaults` row for 5 | `auto_config_enabled = FALSE`, so the EOD detector never generates Pressure configs |
| `charge_rate` | **not touched** — that is why there are two charge columns |
| `instrument.strike_points` | **not touched** — that is why `strike_step_points` exists |

The full suite (338 tests) passes, including the two contract tests that exist
specifically to catch a column added to the query but not the mapper.

---

## Debugging checklist

Enable `logging.level.com.moneymaker.strategy=DEBUG` for the `[pressure]` lines.

| Symptom | Look at |
|---|---|
| No signals at all | `[pressure]` line present? If absent, the spot series is not cached — check the `underlying\|interval` key |
| Same bar scored every tick | `SpotFeatureCache` key must include the newest bar timestamp. A `session bars=1` trace line is the tell |
| All books trading the same strike | `Strategy5.resolveTradableKey` must match the config's own strike, not the first key with a matching side |
| Bracket is a percentage, not 50 points | `strategy_defaults` row for strategy 5 missing → `BracketMode.parse(null)` defaults to `PERCENT` |
| Anchor term looks wrong | it is an UNWEIGHTED typical-price mean by design; `app.pressure.anchor-mode` must read `TYPICAL_MEAN` to match the reference |
| Opening range never completes | out-of-session bars, or `app.pressure.opening-range-end` set past the data |
| Two positions open in one book | `book_id` not set on both legs |
| Entries outside 09:25–14:15 | `entry_from` / `entry_to` null on the config — check the mapper, not the DB |

### Related docs

- [`STRATEGIES.md`](STRATEGIES.md) — what each `stratergy_id` runs
- [`ORDERS_AND_POSITIONS.md`](ORDERS_AND_POSITIONS.md) — exit reasons, `trade_order` columns
- [`STRATEGY_ANALYSIS_TODO.md`](STRATEGY_ANALYSIS_TODO.md) — S22–S24, the open questions on this strategy
- [`BACKTESTING.md`](BACKTESTING.md) — the replay pipeline this runs inside
