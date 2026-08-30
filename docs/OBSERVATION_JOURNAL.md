# Observation journal

> **Status (2026-08-31): all five kinds wired.** `CANDIDATE`, `ENTRY` and `EXIT`
> are wired and verified writing (10,991 / 9 / 9 rows on a live run).
> `MONITOR` and `EVENT` — the during-position timeline — are wired into
> `PositionService` as of this change and are **written but not yet observed in a
> run**: no backtest has been executed against them, so there are no row counts
> below for them yet. See [The during-position
> timeline](#the-during-position-timeline) for the semantics and [What is not
> built](#what-is-not-built) for what remains.

Platform-level capture of what the pipeline saw and what it decided, so strategy
performance can be analysed after the fact.

---

## Why it is not per-trade metadata

The obvious design — a metadata blob hung off each `trade_order` — cannot answer
the question that motivates this: *what would have happened on the strikes we
passed over?* Counterfactuals need the **rejected candidates** recorded with the
same feature set as the taken ones.

So the unit of record is **one observed leg at one moment**, not one trade.
`CANDIDATE` rows carry a `selected` flag; the legs that were evaluated and not
traded are journalled identically to the leg that was. "How would the other
strikes have done" becomes a query rather than another backtest run.

## Why strategies never touch it

Capture happens at **platform chokepoints** every strategy already flows through:

| Chokepoint | Emits | Why it is universal |
|---|---|---|
| `AnalysisScheduler` | `CANDIDATE` per leg per tick | every strategy's legs are resolved here |
| `OrderService` | `ENTRY` / `EXIT` | CLAUDE.md invariant 7 — all order lifecycle goes through it |
| `PositionService` | `MONITOR` / `EVENT` | every open position, every tick |

All three are *services*, not schedulers — so a backtest replays the journal
exactly as live writes it (CLAUDE.md invariant 8). Nothing is journalled from
inside a `@Scheduled` body.

A new strategy is journalled without knowing the journal exists. There is
deliberately **nothing to add per strategy**.

## Why features are contributed, not hardcoded

`FeatureContributor` is an SPI; Spring injects every implementation as a
`List<FeatureContributor>` — the same auto-discovery `OrderPlacementFactory` and
`PositionMonitorFactory` use for broker adapters.

**Adding a recorded feature is a new bean and nothing else**: no call-site edit,
no strategy edit, no migration, because output lands in the `features` JSON
column. That constraint is the point — the codebase already shows what the
alternative costs, with the strike-key format parsed in four separate places.

Contract, enforced by convention and by the recorder:

- **Pure observation.** Must not mutate context, candles, or shared state. It runs
  on the trading hot path and must never be able to change a decision.
- **Never throws.** A missing feature is a gap in analysis; a thrown exception is
  a lost trade.
- **Only settled data.** Anything derived from an unclosed bar or an unconfirmed
  swing must be reported at the point it became knowable.
- **Stable key names.** Keys become column headers in analysis; renaming one
  orphans historical rows.

---

## CHoCH and BOS

`MarketStructureAnalyzer` (`com.moneymaker.structure`) detects fractal swings and
the two structure breaks.

A **swing high** at bar `i` is a high strictly greater than the highs of the
`fractalN` bars either side (default 2); a swing low is the mirror.

| Event | Condition | Meaning |
|---|---|---|
| **BOS** (Break of Structure) | close beyond the last swing **in the direction of** the prevailing structure | trend continues |
| **CHoCH** (Change of Character) | close beyond the last swing **against** the prevailing structure | first contrary break — possible reversal |

### `confirmableAt` is load-bearing

**A swing cannot be recognised when it prints.** Bar `i` is only known to be a
swing high once `fractalN` further bars have closed below it, so the earliest a
strategy could act on that level is bar `i + fractalN`.

Every `StructureEvent` therefore carries two timestamps:

- `occurredAt` — the bar whose close broke the level
- `confirmableAt` — the bar by which the broken swing had itself been confirmed

> **Analysis must filter on `confirmableAt`.** Reading these events at
> `occurredAt` credits the strategy with a level before the market finished
> drawing it — reintroducing exactly the look-ahead documented in
> [`BACKTEST_PERFORMANCE.md` → The settled-bar rule](BACKTEST_PERFORMANCE.md),
> which cost this codebase a 640-point swing in apparent edge.

The analyzer enforces this internally: a swing is promoted to "usable" only once
the loop reaches its confirmation bar, so a level can never be broken before it
existed.

### WITH / AGAINST, not bullish / bearish

`directionFor(...)` converts a raw break into its relationship to the position,
because a "bullish CHoCH" means opposite things to a short call and a short put:

| Series | Bullish break | Short CE | Short PE |
|---|---|---|---|
| Option premium | premium rising | **AGAINST** | **AGAINST** |
| Underlying | index rising | **AGAINST** | WITH |

That framing is what makes structure comparable across legs, and it is what makes
the motivating question testable: *did an AGAINST CHoCH precede the adverse move,
and with how many bars of warning?* Against a ledger where **all 21 stop-losses
overshot their stop** and 17 trades gave back an average of +13.81 before closing
at −77.19, that is a measurable alternative to a percentage stop rather than a
guess.

---

## The during-position timeline

`ENTRY` and `EXIT` record structure at the two ends of a trade and nothing in
between, so the ledger can say a trade gave back 90 points but not whether
anything warned first. [`PositionJournal`](../src/main/java/com/moneymaker/journal/PositionJournal.java),
called from
[`PositionService.handleOne`](../src/main/java/com/moneymaker/position/service/PositionService.java),
fills that gap with two kinds.

### `MONITOR` — one row per open trade per evaluated tick

No sampling, no "only when something changed" filter. Any such filter is a
behaviour parameter with no `TradeConfig` field behind it, and inventing one in
code is what CLAUDE.md invariant 9 forbids — so every evaluated tick is written
and the cadence question is left to whoever asks for a config field.

**Which ticks count.** Exactly the ticks the monitor evaluated. A tick it
skipped — no quote for the leg, or the [same-candle
guard](ORDERS_AND_POSITIONS.md#same-candle-guard) — writes nothing, and that
absence *is* the record that the monitor had nothing to act on.

**What a row carries.** The full contributor payload (structure state, SMA
state, premium context, volume / OI) plus the monitor's own state, which no
contributor can see because it is a decision rather than a market fact:

| Feature | Meaning |
|---|---|
| `monitor_decision` | `HOLD`, or the threshold this tick breached (`TARGET` / `TRAIL_SL` / `STOP_LOSS`) |
| `monitor_pnl`, `monitor_price` | unrealised per-share P&L and the quote it came from |
| `monitor_peak_profit`, `monitor_peak_loss` | the excursion so far |
| `monitor_target_at_entry`, `monitor_stop_loss_at_entry`, `monitor_trail_sl_at` | the bracket as it stood on this tick |
| `monitor_minutes_since_entry` | age of the trade |

Those arrive through `JournalRecorder.record(ctx, selected, extraFeatures)`,
which applies call-site features *after* the contributors. Keys are namespaced
`monitor_` so that ordering is a stated rule rather than an accident.

`selected` is `true` on a `MONITOR` row, the same sense `ENTRY` / `EXIT` use it
in: the row describes a leg that was actually traded. Only `CANDIDATE` rows
carry `false`.

**Which series describes the row.** `trade_order` carries no timeframe — the
signal's interval is known at entry and never persisted — so a monitor tick has
no config-supplied answer and must not invent one. `ObservationContextFactory`
resolves the leg's **finest cached series**, which is what the monitor priced the
tick off (`SharedData.latestCachedCandle` documents the same reasoning), and
stamps the resolved width on `interval_minutes` so a row says which timeframe it
describes. When a caller *does* know the timeframe — `ENTRY`, from the signal —
that series is used instead, so an `ENTRY` row describes what the strategy
actually read. Before this change the factory took the first option-token hit in
`ConcurrentHashMap` iteration order, so an `ENTRY` row could be described by a
15-minute series when the signal was 5-minute. Journal content only; no trading
path read it.

### `EVENT` — a structure break that landed while the trade was running

Emitted when `MarketStructureAnalyzer` reports a BOS or CHoCH — on the option's
own premium *and* on the underlying — subject to two gates:

1. **`confirmableAt <= observedAt`.** The confirming bar has settled, so the
   break was knowable at the tick that records it. Recording at `occurredAt`
   would re-introduce exactly the look-ahead described above.
2. **`confirmableAt >= entry_time`.** It became knowable *during* the position.
   A break confirmed before entry is already summarised in the `ENTRY` row's
   structure features; re-emitting it as a during-position warning would be a
   false one.

The second gate is on `confirmableAt`, not `occurredAt`, and deliberately: a bar
that broke a level shortly before entry but was confirmed after it is new
information arriving during the trade — which is the whole point.

A break is journalled **once per trade**, not once per tick, keyed on
series + type + `occurredAt` + level. That state is bounded by the open set:
`PositionService` hands `PositionJournal.retainOpen(...)` the ids it is about to
walk, so a closed trade's state is dropped on the next tick with no guessing.

`event_type` is `BOS` / `CHOCH`; `direction` is `WITH` / `AGAINST` from
`directionFor(...)`, so a CE and a PE trade are comparable. `confirmable_at` is
the column; the rest sits in features:

| Feature | Meaning |
|---|---|
| `break_series` | `OPTION` or `UNDERLYING` — **not** the `series` column, see below |
| `event_occurred_at` | the bar whose close broke the level |
| `event_confirm_lag_min` | how long the break waited to become actionable |
| `event_level`, `event_structure_before`, `event_structure_after` | the break itself |
| `monitor_minutes_since_entry`, `monitor_pnl`, `monitor_peak_profit` | how much warning it gave, and what the trade was worth when it arrived |

> **Known schema wrinkle.** The `series` column is *leg identity* — an `EVENT`
> detected on the index during an option trade is still a row about that option
> leg, so the column reads `OPTION` and the actual series of the break lands in
> `break_series` inside the JSON. Filtering "index breaks only" is therefore a
> JSON predicate rather than a typed column. Left as is rather than adding a
> changeset; recorded here so the next reader does not mistake the column for an
> answer to a question it is not answering.

An `EVENT` row runs no contributors — the `MONITOR` row written at the same tick
already carries the full payload, and they join on
`(run_id, observed_at, trade_order_id)`. Both read the same memoised structure
analysis (`StructureEventCache`), so an `EVENT` can never disagree with the
`MONITOR` row beside it.

### It cannot change an exit

`PositionService` calls the journal after `thresholdBreach` has already
answered, and passes that answer in as a recorded fact. The call is wrapped at
the call site *and* inside `PositionJournal`, and `JournalRecorder` swallows its
own write failures — three layers, because a journal that cannot write is a gap
in analysis while an exception escaping it is a missed stop-loss on a live
account. `PositionServiceJournalTest` pins that a throwing journal still closes
the trade at the same price, time and reason, and still saves the monitor
columns.

---

## Schema

One table, `journal_observation` (changeset `030_observation_journal.xml`).

Typed columns only where they get filtered or aggregated — `kind`, `event_type`,
`direction`, and the leg identity. Everything else is `features` JSON, so new
contributors need no migration.

| Column | Notes |
|---|---|
| `run_id` | groups one backtest run or live session |
| `observed_at` | the tick this row describes |
| `confirmable_at` | structure rows only — see above |
| `kind` | `CANDIDATE` / `ENTRY` / `MONITOR` / `EXIT` / `EVENT` |
| `event_type`, `direction` | `EVENT` rows: `BOS` / `CHOCH` / `SMA_FLIP` / …, and `WITH` / `AGAINST` / `NEUTRAL` |
| `strategy_id`, `trade_config_id`, `trade_order_id` | `trade_order_id` null for a candidate never traded |
| `series`, `instrument_name`, `option_token`, `option_type`, `strike`, `interval_minutes` | leg identity |
| `selected` | `CANDIDATE` rows: was this leg actually traded at this tick |
| `features` | JSON |

### Volume and open interest

`market_data` gained `volume` / `open_interest` in the same changeset, and
`HistoricalIciciMarketDataProvider` now carries both through. They were present in
`historical_option_candles` all along and silently dropped, because `MarketData`
had nowhere to put them — losing the strongest single input available to a
premium *seller*: rising OI against a rising premium is fresh buying into the
position, falling OI is unwinding.

In aggregation, **volume sums** across a bucket while **OI takes the bucket's last
value** — it is a level, not a flow.

---

## What is not built

| Built and writing | Missing |
|---|---|
| `journal_observation` table | **a run against `MONITOR` / `EVENT`** — the wiring is in and unit-tested, but no backtest has been executed since, so their row counts and cost are unmeasured |
| `JournalRecorder` (batched, `journal.enabled`) | post-hoc labels (would-it-have-hit-target, MFE/MAE timing) |
| `ObservationContextFactory` | anything *reading* the journal — no query layer, no analysis view, no report |
| `PriceContextContributor`, `SmaStateContributor`, `StructureContributor`, `VolumeOiContributor` | `SMA_FLIP` and other non-structure `EVENT` types — `event_type` is open, only `BOS` / `CHOCH` are emitted |
| `AnalysisScheduler` → `CANDIDATE` | a typed column for an `EVENT`'s series (see the wrinkle above) |
| `OrderService` → `ENTRY` / `EXIT` | a cadence / filter config field, if per-tick `MONITOR` volume ever proves too much |
| `PositionService` → `MONITOR` / `EVENT` | |
| `BacktestAnalysisService` → run id + flush | |

The gap that mattered — **the during-position timeline** — is closed as of
2026-08-31: an AGAINST CHoCH appearing while a trade is running is now an
`EVENT` row carrying how many minutes of warning it gave and what the trade was
worth at the time. What is *not* closed is the other half: nothing reads these
rows yet, and no strategy consumes them. Whether a structure-based exit beats
the fixed / trailing stop is now a query rather than a guess — and it is an
open one, filed as
[`STRATEGY_ANALYSIS_TODO.md` S10](STRATEGY_ANALYSIS_TODO.md).

### First run

Against a 2025-01 backtest: **10,991 `CANDIDATE`, 9 `ENTRY`, 9 `EXIT`** across 6
runs. Structure features present on 9,809 of 11,009 rows, OI on 10,945. A row
that is missing structure is a series too short to have a confirmed swing yet —
a real absence, not a failure.

That run predates the `MONITOR` / `EVENT` wiring, so it contains none of either.

### Sizing

Journalling every candidate is roughly **24 legs × 73 ticks × 79 days ≈ 138k rows
per run**, each with a JSON blob. Fine for MySQL, but these are per-tick writes on
the hot loop — where DB round-trips have already been measured as dominant (see
Phase 6a). The writer must batch rather than insert per observation, and the whole
journal must sit behind a property so a run can turn it off.

**`MONITOR` adds little on top of that.** Its volume is bounded by *open trades*,
not by legs: with `no_of_parrellel_trades = 1` it is at most one row per tick
against the ~24 `CANDIDATE` rows the same tick already writes — a few percent,
into the same batch. `EVENT` is rarer still, at most one row per confirmed break
per trade. If the per-tick cadence ever does prove too much, the fix is a
`TradeConfig` field, not a constant in the journal — see the note on cadence
above.
