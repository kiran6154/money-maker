# Changelog

All notable changes to this project are recorded here, in reverse chronological order. Update this file in the **same commit** that makes the change — it's the audit trail that ties intent (the milestones in [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) and the operational items in [`docs/GAPS.md`](docs/GAPS.md)) to the code that landed.

Format inspired by [keep-a-changelog](https://keepachangelog.com/). Dates are `YYYY-MM-DD` IST. We do **not** follow semver — this is an internal trading tool with no consumers — but we do tag a release name per iteration so a future reader can quickly find "what was in the M0 batch".

---

## How to update this file

Every change that touches behaviour, schema, config, or public API gets one line under `[Unreleased]`. When a milestone lands (or any meaningful slice of work):

1. **Promote `[Unreleased]` entries** to a new dated section above it.
2. **Tag it** with the milestone identifier and a short release name, e.g. `## [M0 — Backtest reproducibility] — 2026-06-03`.
3. **Reset `[Unreleased]`** to the empty stub at the top.
4. **Flip the matching row** in [`IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)'s status table.
5. **Cross-reference** any GAPS / ARCH / SEQ doc items that this batch closes — so the next reader can trace the change back to the design.

### Entry categories

Use these headings in each release block. Omit empty ones.

- **Added** — new feature, endpoint, scheduler, table.
- **Changed** — behaviour of existing functionality is different.
- **Fixed** — bug fix; reference the symptom and root cause.
- **Removed** — feature / column / file deleted.
- **Deprecated** — still works, planned for removal; name the replacement.
- **Security / Ops** — credential rotation, on-call procedure, alerting.
- **Schema** — list every Liquibase changeset added (`018_*.xml`, …) and what it does.
- **Docs** — meaningful doc additions; trivial typo fixes can be omitted.

### Style rules

- One line per change, past tense (`Added`, `Fixed`, not `Adds`, `Fix`).
- Link to the file or symbol using markdown link syntax, e.g. `[TradingPipelineScheduler.java](src/main/java/com/moneymaker/scheduler/TradingPipelineScheduler.java)`.
- Reference the milestone / gap, e.g. *(closes GAPS #4)*, *(M2.3)*.
- If a change has a non-obvious **migration step** (operator must run X, restart Y), put it in **bold** so it's not missed.

### Template for a new release block

```markdown
## [M0 — Backtest reproducibility] — 2026-06-03

### Added
- …

### Changed
- …

### Fixed
- …

### Schema
- …

### Docs
- …
```

---

## [Unreleased]

### Added
- [`Strategy8`](src/main/java/com/moneymaker/strategy/Strategy8.java) (`stratergy_id = 8`): the "20SMA 15min candle" rule — on the leg's 15-minute candles, SMA-20 of closes sloping down and close below the previous close → SELL, no cross gate (`AbstractSmaCrossStrategy.decide` hook + `RuleEngine.decideWithoutCrossGate`), 14:45 cut-off, no target, chandelier exit. Intraday form; carry-to-expiry is S29. Pinned by `Strategy8RulesTest`.
- Chandelier trailing stop (changeset 048): `strategy_defaults.trail_atr_multiple`, `trade_order.trail_atr_distance_at_entry`, `TradeSignal.atr`, `AbstractSmaCrossStrategy.signalAtr`; `PositionService.applyTrail` floors the stop at `peak_profit − distance` (never ratchets on the exit tick). `BracketMode.NONE` for a side with no bracket. Seeds strategy 8's `strategy_defaults` from strategy 1's block with `target_mode = NONE`, `trail_atr_multiple = 2.00`; no rule tag. Pinned by `PositionServiceAtrTrailTest`.
- [`Strategy7`](src/main/java/com/moneymaker/strategy/Strategy7.java) (`stratergy_id = 7`): Strategy 6 plus the first-hour regime gate — after 10:15, no entry on a leg whose side the underlying's first hour moved against by more than 0.2 × ATR-14 (`CommonRules.firstHourMoveInFavourAtr`, `sessionAtr`; unknown allows). Numbers and the regime signals that did *not* transfer in [S22](docs/STRATEGY_ANALYSIS_TODO.md). `Strategy7RulesTest`.
- [`Strategy6`](src/main/java/com/moneymaker/strategy/Strategy6.java) (`stratergy_id = 6`): Strategy 2 plus three replay-selected entry gates — the leg's 15-minute SMA-50 whole-day down-trend (unknown allows), no entry bar after `closeSignalTime − 30 min` (14:45), and a `STOP_LOSS` exit that locks the `(config, strategy)` book for the day. Rationale, numbers and caveats in [`STRATEGY_ANALYSIS_TODO.md` S21](docs/STRATEGY_ANALYSIS_TODO.md). **To auto-generate configs for it, insert its `strategy_defaults` row and `sma_downtrend_rule_strategy` tag** (SQL in [`STRATEGIES.md`](docs/STRATEGIES.md)).
- `Strategy.confirmationTimeframes()` / `Strategy.stopLossLocksBookForDay()` default methods; [`AnalysisScheduler.confirmationTimeframesByConfig`](src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java) unions declared confirmation intervals into each config's fetch set across every tag; `RuleContext.strikeKey` lets a rule find the same leg on another interval; [`CommonRules.higherTimeframeSmaDownTrending`](src/main/java/com/moneymaker/strategy/rules/CommonRules.java) / `isAtOrBeforeEntryCutoff` / `isSmaDownTrending`.
- [`OrderService`](src/main/java/com/moneymaker/order/service/OrderService.java) gate 6, the stop-loss lock, driven by an optional `StrategyFactory` (`required = false`, so hand-built services keep the old behaviour); `TradeOrderRepository.existsByTradeConfigIdAndStrategyIdAndExitReasonAndEntryTimeBetween`.
- Tests: `Strategy6RulesTest`, `OrderServiceStopLossLockTest`, `AnalysisSchedulerConfirmationTimeframesTest`.
- Trade-config admin UI at `/trade-configs` with inline form + paginated report. New endpoints under `/api/trade-configs/*`. New package `com.moneymaker.tradeconfig.*` (controller + service + DTOs). Backed by [`TradeConfigAdminService`](src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java) which invalidates the date-cache and refreshes `SharedData.combinedDto` on writes to today's configs.
- [`MarketHoursService`](src/main/java/com/moneymaker/market/service/MarketHoursService.java) as the single source of truth for the trading window (default 09:15–15:30 Asia/Kolkata, configurable via `app.market.*`).
- [`DaySummaryScheduler`](src/main/java/com/moneymaker/scheduler/DaySummaryScheduler.java) fires once at 15:31 IST Mon–Fri: force-closes any leftover OPEN trades, builds a Telegram summary, gates with `DailyEventGuard`.
- `NotificationService.alertDaySummary(String)` — thin pass-through; caller owns dedupe.
- `TradeOrderRepository.findByEntryTimeBetween(...)` and `existsByTradeConfigId(...)`.
- `InstrumentRepository` (was missing; now needed by the trade-config admin dropdown).
- `SmaTimeframeRepository.deleteByTradeConfigId(...)` for replace-on-update of SMA rows.
- `StrategyFactory.availableStrategyIds()` so the strategy dropdown is auto-discovered.

### Schema
- [`047_seed_strategy7_defaults.xml`](src/main/resources/db/changelog/047_seed_strategy7_defaults.xml) — same shape as 046 for strategy 7: seeds `strategy_defaults` as a copy of strategy 1's block, tags no rule.
- [`046_seed_strategy6_defaults.xml`](src/main/resources/db/changelog/046_seed_strategy6_defaults.xml) — seeds `strategy_defaults` for strategy 6 as a copy of strategy 1's block (idempotent, `opposite_side = FALSE`); tags no rule. **To switch strategy 6 on, insert its `sma_downtrend_rule_strategy` rows** (SQL in the changeset).

### Changed
- `AnalysisScheduler`, `OrderScheduler`, `PositionScheduler` now early-return outside market hours (`MarketHoursService.isOpenNow()`) in live mode. Backtest path unaffected.
- New `app.market.{open,close,timezone,summary-cron}` properties added to [`application.properties`](src/main/resources/application.properties).

### Fixed
- [`SmaTimeframe.id`](src/main/java/com/moneymaker/entity/SmaTimeframe.java) was missing `@GeneratedValue(IDENTITY)`; UI inserts now succeed without manual ID assignment.

### Docs
- Added [`docs/ARCHITECTURE_REVIEW.md`](docs/ARCHITECTURE_REVIEW.md) — forward-looking design review (live/backtest seams, data persistence, indicator model).
- Added [`docs/SEQUENCING_AND_CACHE.md`](docs/SEQUENCING_AND_CACHE.md) — scheduler ordering, concurrency, cache inventory, backtest reproducibility prescription.
- Added [`docs/GAPS.md`](docs/GAPS.md) — operational follow-ups (13 entries).
- Added [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) — milestone plan M0–M7 with status table.
- Added this `CHANGELOG.md`.

---

<!-- Released entries go below this line, newest first. -->
