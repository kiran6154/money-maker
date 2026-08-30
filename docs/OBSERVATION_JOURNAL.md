# Observation journal

> **Status (2026-08-30): live and capturing.** `CANDIDATE`, `ENTRY` and `EXIT`
> are wired and writing. `MONITOR` / `EVENT` (during-position deviation) are
> **not** — see [What is not built](#what-is-not-built).

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
| `journal_observation` table | `MONITOR` rows — samples while a position is open |
| `JournalRecorder` (batched, `journal.enabled`) | `EVENT` rows — BOS/CHoCH observed *during* a position |
| `ObservationContextFactory` | `PositionService` wiring |
| `PriceContextContributor`, `SmaStateContributor`, `StructureContributor`, `VolumeOiContributor` | post-hoc labels (would-it-have-hit-target, MFE/MAE timing) |
| `AnalysisScheduler` → `CANDIDATE` | |
| `OrderService` → `ENTRY` / `EXIT` | |
| `BacktestAnalysisService` → run id + flush | |

The gap that matters: **the during-position timeline.** Structure state is
captured at entry and exit, but not the moment an AGAINST CHoCH appeared while
the trade was running — which is exactly the "did we get a warning before the
adverse move" question. Either `PositionService` wiring or the post-hoc deriver
still has to be built for that.

### First run

Against a 2025-01 backtest: **10,991 `CANDIDATE`, 9 `ENTRY`, 9 `EXIT`** across 6
runs. Structure features present on 9,809 of 11,009 rows, OI on 10,945. A row
that is missing structure is a series too short to have a confirmed swing yet —
a real absence, not a failure.

### Sizing

Journalling every candidate is roughly **24 legs × 73 ticks × 79 days ≈ 138k rows
per run**, each with a JSON blob. Fine for MySQL, but these are per-tick writes on
the hot loop — where DB round-trips have already been measured as dominant (see
Phase 6a). The writer must batch rather than insert per observation, and the whole
journal must sit behind a property so a run can turn it off.
