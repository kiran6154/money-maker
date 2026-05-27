# Implementation plan

> Cross-references [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md),
> [SEQUENCING_AND_CACHE.md](SEQUENCING_AND_CACHE.md), and the operational
> [GAPS.md](GAPS.md). This document is the **single execution order** drawn
> from all three. Update the status column as milestones land.
>
> Milestones are designed so each ends with a working, shippable state — a
> partially-completed milestone never leaves the codebase in a broken
> position. Skipping a milestone breaks the dependency chain (see §"Risk
> and dependency map" at the bottom).

---

## Status

| Milestone | Status | Notes |
|---|---|---|
| M0 — Stop the bleeding | ☐ not started | |
| M1 — Operational hardening | ☐ not started | |
| M2 — Data persistence migration | ☐ not started | |
| M3 — Indicator architecture | ☐ not started | |
| M4 — Backtest perf phases | ☐ not started | |
| M5 — Live trading polish | ☐ not started | |
| M6 — `RunSession` refactor | ☐ not started | |
| M7 — New capabilities | ☐ not started | |

---

## M0 — Stop the bleeding *(≈ 1 day)*

Three changes; ship together. After this, **backtest results are reproducible** and the scheduler ordering is no longer correct-by-luck.

| # | Source | Change | Files |
|---|---|---|---|
| 0.1 | SEQ §3.1 | Sort keys at every `SharedData` map iteration site (~5 sites — `AnalysisScheduler`, `Strategy1`, `Strategy2`, `OrderService`, `PositionService`) | ~5 files, ~15 lines |
| 0.2 | SEQ #4 | `POST /api/backtest/reset?fromDate=&toDate=` + `backtest.auto-reset=true`. Purges `trade_order` + `alert_state` rows + in-memory caches (C9 / C11 / C12) | 1 new controller + service, 1 property |
| 0.3 | SEQ #1, GAPS #4 | Collapse `Analysis/Order/Position` `@Scheduled` triggers into `TradingPipelineScheduler` with `ReentrantLock.tryLock()` for tick-overrun protection | 1 new + edits to 3 existing |

**Exit criteria.** Run a 5-day backtest twice in the same JVM; `diff` of `mysqldump trade_order` must be empty.

---

## M1 — Operational hardening *(≈ 1 day)*

Small follow-ups surfaced by the architecture review but not requiring an architectural change. Can run in parallel with M2 by a different engineer.

| # | Source | Change |
|---|---|---|
| 1.1 | GAPS #5 | Two-key `DailyEventGuard` for day-summary (don't mark sent on Telegram failure) |
| 1.2 | GAPS #6 | `POST /api/admin/day-summary?date=&force=true` to re-run end-of-day work |
| 1.3 | SEQ #6 | Daily 08:00 hook to clear unbounded live caches (C4, C7, C11, C12) |
| 1.4 | GAPS #3 | Gate `LoginScheduler.heartbeat` to `07:50–15:40` window |
| 1.5 | GAPS #11 | Delete `TradeConfigScheduler.dailyTaskAt912AM` (no-op stub) |

---

## M2 — Data persistence migration *(≈ 1 week)*

The first **architectural** change. After this, broker is no longer the cold-path dependency for backtest.

| # | Source | Change |
|---|---|---|
| 2.1 | ARCH §4 | Liquibase 018 — add `interval` column + UNIQUE on `market_data(instrumenttoken, timestamp, interval)` |
| 2.2 | ARCH §4 | `AnalysisScheduler` writes candles via `@Async MarketDataPersistenceService` (fire-and-forget; failures alert but don't break analysis) |
| 2.3 | ARCH §4 | New `MarketDataLocalProvider`; registered only when `app.mode=backtest`. Reads from `market_data`, falls through to `KiteHistoricalFetcher` on miss with a loud log |
| 2.4 | ARCH §4 | Nightly 16:00 gap-detection job; triggers targeted backfill via existing `OptionsBulkDownloadService` |
| 2.5 | GAPS #12 | While we're here: move `LoginScheduler.fetchOptionsData` behind `MarketDataProvider` so non-Zerodha brokers can override |

**Exit criteria.** Disable broker credentials, run a backtest for last week → success. Run twice → same result.

---

## M3 — Indicator architecture *(≈ 1 week)*

Removes the schema lock-in per new indicator. Done in two PRs for reversibility.

| # | Source | Change |
|---|---|---|
| 3.1 | ARCH §5 | `IndicatorComputeService` with registry. Rolling-sum SMA (also satisfies BACKTEST_PERFORMANCE Phase 3). All strategy reads route through it |
| 3.2 | ARCH §5 | Liquibase 019 — drop `sma_value20`–`sma_value500` columns + the transient trend booleans from `MarketData`. Move trend logic to a value object computed from candle list |
| 3.3 | ARCH §6 | Liquibase 020 — replace `sma_timeframe` with `indicator_binding(tc_id, indicator_name, params_json)`. Migrate existing rows. Update trade-config UI to attach arbitrary indicators |
| 3.4 | GAPS #13 (partial) | Doc updates for the new indicator contract |

**Exit criteria.** Add EMA to a config from the UI; trade-config writes succeed; strategy uses it on next analysis tick. **Zero schema migration was required.**

---

## M4 — Backtest perf phases *(≈ 2-3 days)*

Drop-in wins now that indicators are clean.

| # | Source | Change |
|---|---|---|
| 4.1 | BACKTEST_PERFORMANCE §2 | Phase 2 — skip redundant strategy runs per timeframe |
| 4.2 | ARCH §3.3 | Pre-resolve strike sets per day |
| 4.3 | GAPS #1 | Live force-close places a real broker exit order (no longer DB-only) |

---

## M5 — Live trading polish *(≈ 2-3 days)*

The operational gaps that have been waiting.

| # | Source | Change |
|---|---|---|
| 5.1 | GAPS #2 | Snapshot `lot_quantity_at_entry` on `trade_order`; day-summary reports rupee-P&L |
| 5.2 | GAPS #7 | `is_active` flag on `trade_config` for soft-delete / pause |
| 5.3 | GAPS #8 | Yellow-banner warning when editing configs with OPEN trades |
| 5.4 | GAPS #9 | Clone-yesterday button in trade-config UI |
| 5.5 | GAPS #10 | Rename `stratergy_id` → `strategy_id` (cross-cutting but mechanical) |

---

## M6 — `RunSession` refactor *(≈ 1-2 weeks)*

The big architectural cleanup. Only justified after prior milestones land — risk is high, mechanical change is large.

| # | Source | Change |
|---|---|---|
| 6.1 | SEQ §7, ARCH §3.2 | Define `RunSession` carrying every field currently on `SharedData` |
| 6.2 | SEQ §7 | Inject everywhere `SharedData.X` is read (~20-30 files) |
| 6.3 | SEQ #5 | `CacheRegistry` + `ClearableCache` SPI; new caches must declare a scope or fail the build |
| 6.4 | SEQ §7 | Delete `SharedData` |

**Exit criteria.** All existing tests pass; backtest parity preserved (same `diff trade_order` check as M0).

---

## M7 — New capabilities *(open-ended)*

Only worth doing once M6 is stable.

| # | Source | Change |
|---|---|---|
| 7.1 | ARCH §3.2 | Day-parallel backtest execution |
| 7.2 | ARCH §3.1 | Vectorise the inner loop |

---

## Risk and dependency map

```
M0 ──┬──> M1 (independent — can run in parallel)
     │
     └──> M2 ──> M3 ──> M4 ──> M5
                    │
                    └──> M6 ──> M7
```

- **M0 is non-negotiable and unblocks everything.** Without it, parity verification of any later milestone is fiction — you can't tell if your change broke something when re-runs already produce different results.
- **M1 is purely operational.** Independent of M2-M7; deploy as bandwidth allows.
- **M2 must precede M3.** Once indicators are compute-at-read-time, every backtest needs a fast local data source or pays broker latency on every tick.
- **M3 must precede M4.** Phase 2/3 wins assume a single compute service.
- **M6 is a giant batch.** Defer until M0-M5 have settled and a real day-parallel use case appears.

---

## Open decisions

Three calls to make before M0 starts:

| Question | Default if not answered | Reversible? |
|---|---|---|
| Ship M0 as one PR or three? | One PR — small, cohesive, easier to revert if needed | Yes |
| M2.1: are we OK adding an `interval` column to `market_data` for the UNIQUE constraint? | Yes — `interval` is currently implicit in the symbol; explicit is better | Yes (new column, defaultable) |
| M3.2: drop SMA columns in same migration as `sma_timeframe`, or split? | **Split** — two reversible Liquibase changesets is safer | Yes either way |

---

## Updating this plan

When a milestone (or any meaningful slice of work) lands:

1. **Update [`CHANGELOG.md`](../CHANGELOG.md) in the same commit.** Promote the entries from `[Unreleased]` into a dated, milestone-tagged release block. The changelog is the source of truth for *what shipped, when*; this plan is the source of truth for *what's next*.
2. **Flip the status row** in the table at the top of this doc to ☑.
3. **Add a one-line note** in the milestone's row pointing at the changelog release tag (e.g. *"shipped 2026-06-03 — see CHANGELOG `[M0 — Backtest reproducibility]`"*).
4. **If any sub-item was deferred, dropped, or replaced**, note it inline below the milestone table — don't silently delete it.
5. **Don't delete completed milestones.** The audit trail of which change closed which GAP / ARCH / SEQ item is the value of this doc.

The two files have different jobs: the changelog tells you "what's in the code now"; this plan tells you "what we still owe". They drift apart silently unless you update them together — make it one commit.
