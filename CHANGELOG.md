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

### Added — M5 Operational hardening (2026-05-28)

The P1 ops batch — closes GAPS #3, #5, #6 and SEQ §5 #6. **243 tests cumulative, all green.**

**M5.1 — Two-key DailyEventGuard for day-summary (closes GAPS #5)**
- Replaced single `day-summary` guard key with two: `day-summary-forceclose` (marked only after force-close succeeds) and `day-summary-telegram` (marked only after telegram send succeeds).
- Transient Telegram failure no longer loses the digest forever — next cron tick re-attempts only the unmarked half.
- `DaySummaryScheduler.runEndOfDay` refactored into `runForDate(date, force)` so the manual endpoint can target a date and bypass guards.

**M5.2 — Manual day-summary re-trigger (closes GAPS #6)**
- New [`AdminController`](src/main/java/com/moneymaker/scheduler/AdminController.java) — `POST /api/admin/day-summary?date=&force=true`. Default `date=today`, `force=false`. Validates `date ≤ today`.
- Returns a `RunSummary` record documenting which halves ran this invocation.
- **Known limitation:** no auth on the endpoint. Filed for future hardening.

**M5.3 — Heartbeat windowing (closes GAPS #3)**
- `MarketHoursService.isWithinHeartbeatWindow()` — `[app.market.heartbeat-window-start, end]`, default `07:50–15:40` IST.
- `LoginScheduler.heartbeat` early-returns outside the window. No more AUTH_FAIL Telegram at 22:00 Friday for a token death that doesn't matter until Monday.

**M5.5 — `LiveCacheJanitor` (SEQ §5 #6)**
- New [`LiveCacheJanitor`](src/main/java/com/moneymaker/scheduler/LiveCacheJanitor.java) clears `SharedData.optionTokenMap`, `strikesByInstrumentAndInterval`, and `NotificationService.clearAllDedupeState()`.
- Fires daily at 08:00 IST Mon–Fri AND on `ApplicationReadyEvent` (architect's pushback — JVM restart after 08:00 must still get a fresh cache before the first analysis tick).
- Live-only via `app.mode` check.

**Tests added (+9):** 4 in `DaySummarySchedulerTest` (two-key guard scenarios), 4 in new `LiveCacheJanitorTest`, 2 in `MarketHoursServiceTest` (heartbeat window).

**Remaining open gaps after M5:** #10 (M4.5 rename — 3-calendar-day hold deferred), #12 (M12 options-data — deferred to demand).

### Added — B3 service tests + M3 force-close + M4 live polish (2026-05-28)

This wave: **B3 service test coverage**, **M3 (force-close real broker exit, closes GAPS #1)**, and **M4.1 / M4.2 / M4.3 / M4.4** of the live-polish batch. M4.5 (stratergyId rename) deferred — the architect-mandated 3-step migration needs a 3-calendar-day deploy hold and can't ship in a single session.

**B3 service tests (+54 tests)** — see commits c4f9eea (B3a) and 03386da (B3b). OrderService, PositionService, LoginOrchestrator, TradeConfigAdminService, DaySummaryScheduler, TradeConfigScheduler. Surfaced one real bug: `TradeConfigAdminService.list` was calling `.sort()` on the repo result, which fails on immutable Spring Data results; fixed with defensive copy.

**M3 — force-close real broker exit** — commit d7f7127. `OrderService.forceCloseOpenPositions` now calls `placement.place(order)` after the local-state update. Three outcome branches: live success persists broker order id with `fill_status=PENDING`; backtest no-op stays `BACKTEST`; live null/throw reverts row to `OPEN` with `fill_status=EXIT_FAILED` and fires `[CRITICAL]` `alertOrderExitFailed`. New `app.market.force-close-time=15:25` property + `MarketHoursService.forceCloseToday()`; `DaySummaryScheduler` anchors at the new method. **Closes GAPS #1.**

**M4.1 — rupee P&L on day-summary (GAPS #2)**
- Liquibase `018_add_lot_quantity_at_entry.xml` — adds the column with backfill from `trade_config.lot_quantity` for historical rows.
- `OrderService.openOrder` snapshots `tradeConfig.lotQuantity` onto the order. Per architect: null lotQuantity → 0 (not silent fallback to 1) + WARN log.
- `DaySummaryScheduler.buildSummary` adds `P/L (rupees): N` line = sum of (per-share profit × lot_quantity_at_entry).

**M4.3 — soft-delete via `is_active` (GAPS #7)**
- Liquibase `019_add_is_active_to_trade_config.xml` — `BOOLEAN NOT NULL DEFAULT TRUE`.
- `TradeConfigRepository`: new `findByTradingDateAndIsActiveTrue`; `fetchCombinedByTradingDate` native query gains `AND is_active = TRUE` filter so the pipeline only runs active configs.
- `TradeConfigAdminService.applyForm` writes `isActive` from the form (defensive default true).
- `TradeConfigScheduler.mapToTradeConfig` reads the new column; downstream offsets shifted by +1 (instrument now starts at row index 17, instrument_details at 22). Test fixture updated to match.

**M4.2 — clone yesterday's configs (GAPS #9)**
- `TradeConfigAdminService.cloneFromDate(from, to)` copies all <b>active</b> source configs (inactive ones skipped) including SMA timeframes. Dedupe key: `(instrumentId, strategyId, tradingSide, transactionType)`. Same-date call rejected.
- `POST /api/trade-configs/clone?fromDate=&toDate=` endpoint returns `CloneSummary{cloned, skipped, ...}`.

**M4.4 — open-trade warning banner (GAPS #8)**
- `TradeOrderRepository.countByTradeConfigIdAndStatus` (new derived query).
- `TradeConfigViewDTO` gains `active`, `openTradeCount`, and computed `hasOpenTrades` — populated by `toView()`. UI Thymeleaf banner deferred (DTO change is the API contract).

**Tests added** (cumulative 234 after wave, up from 183 at start of session):
- `OrderServiceTest.ForceCloseOpenPositions`: 3 new tests for live success / live failure / live throw.
- `MarketHoursServiceTest`: 2 new tests for `forceCloseToday` default + boundary rejection.
- `TradeConfigAdminServiceTest`: 4 new tests for clone happy-path / clone dedupe-skip / clone arg rejection / view openTradeCount populated.

**Deferred from M4** — M4.5 `stratergyId` → `strategyId` rename. Per architect's M4.5 review, must run as a 3-step deploy (add new column → dual-write + backfill → drop old column) with ≥1 calendar day soak between steps. Not appropriate for a single-session commit.

### Removed — M1.5 GAP #15 resolution: dead EMA/RSI stubs (2026-05-28)

- Deleted `EMAIndicatorImpl.java` and `RSIIndicatorImpl.java` — both were stubs returning `0.0` regardless of input. Grep confirmed zero production callers asked for `"EMA"` or `"RSI"`: `AnalysisScheduler.java:457` is the only `IndicatorService.calculate` caller and it hardcodes `"SMA"`.
- Removed the corresponding `IndicatorFactory.registry.put(...)` lines. `IndicatorFactory.create("EMA")` now throws `IllegalArgumentException("Unknown indicator: EMA")`.
- Deleted `EMAIndicatorImplTest.java` and `RSIIndicatorImplTest.java` (the stub-pinning tests).
- Updated `IndicatorFactoryTest` with `EMA_and_RSI_no_longer_registered_after_gap_15_resolution` so a future re-registration without intent will fail this test loudly.
- Factory class-comment block documents the contract for re-adding: implement real calculation (not a stub), register, write real tests.

**Closes GAP #15.** When EMA / RSI are needed for a real strategy, the implementation work is M-level (write real ta4j-based calculation) but the architectural plumbing is unchanged.

### Added — M1 Reproducibility fix (2026-05-28)

The substantive reproducibility milestone: identical inputs now produce identical `trade_order` rows across runs. 184 tests cumulative; all green.

**M1.1 — Deterministic iteration**
- [`OrderService.lastPriceFor`](src/main/java/com/moneymaker/order/service/OrderService.java) iterates the strike-cache to find a matching `optionToken` for force-close pricing. Multiple cache keys can share an `optionToken` (different `itm/otm` depth suffixes); without sorting, HashMap order determined which cached candle's close was returned. Now sorts keys naturally first → deterministic exit price across runs.
- [`BacktestingPositionMonitorService.currentQuote`](src/main/java/com/moneymaker/backtesting/BacktestingPositionMonitorService.java) — same fix, same reason. Without it, peak-P&L tracking drifted subtly across reruns.

**M1.2 — `TradingPipelineScheduler` with `tryLock` guard**
- New [`TradingPipelineScheduler`](src/main/java/com/moneymaker/scheduler/TradingPipelineScheduler.java) — single `@Scheduled(cron = "0 0/5 9-15 …")`, calls `analysis → orders → positions` in strict order. `ReentrantLock.tryLock()` skips re-entrant ticks (when a slow broker fetch overruns the 5-min window); cumulative skip counter logged every 10 events.
- Removed `@Scheduled` from `AnalysisScheduler.analyzeMarketData`, `OrderScheduler.processOrders`, `PositionScheduler.processPositions`. Methods stay public — backtest still calls them directly; live now goes through the new coordinator. Fixes the "correct by alphabetical accident" failure mode that GAPS #4 / SEQUENCING_AND_CACHE §1 called out.
- 5 new tests in [`TradingPipelineSchedulerTest`](src/test/java/com/moneymaker/scheduler/TradingPipelineSchedulerTest.java) — strict ordering via `InOrder`, backtest-mode no-op, market-hours gate, concurrent re-entrant skip with `CountDownLatch`, exception-tolerance.

**M1.3 — `BacktestResetService` + `POST /api/backtest/reset` + auto-reset**
- New [`BacktestResetService`](src/main/java/com/moneymaker/backtesting/BacktestResetService.java) — purges `trade_order` rows + `alert_state` rows in `[fromDate, toDate]` and invalidates `TradeConfigScheduler` date-cache (C9) + `NotificationService` dedupe (C11/C12).
- New `POST /api/backtest/reset?fromDate=&toDate=` endpoint on `BacktestController`. Validates `toDate ≤ today` (returns 400 with body if violated — operator-typo guard).
- Auto-reset wired into `POST /api/backtest/analysis` when `backtest.auto-reset=true`. Default `false` in `application.properties` (operator-safety); `true` in `application-test.properties` so the parity-test harness always starts clean.
- New `NotificationService.clearAllDedupeState()` for the reset path. Documented as not-for-live-use.
- 6 new tests in [`BacktestResetServiceTest`](src/test/java/com/moneymaker/backtesting/BacktestResetServiceTest.java) — SQL + arg verification per delete, cache invalidations, null / reversed-range rejection.

**Closes** GAPS #4 (pipeline crons firing in backtest mode bodies); resolves the architect's #1 reproducibility prescription from SEQUENCING_AND_CACHE.

### Added — M0.1.7 B2 strategy + rule-engine tests (2026-05-28)

6 new test classes, **64 new tests** (109 → 173 cumulative). All green; full suite `mvn test` completes in ~35s.

- [`TradeRulesTest`](src/test/java/com/moneymaker/strategy/rules/TradeRulesTest.java) — value-class invariants + immutability of `empty()`.
- [`CommonRulesTest`](src/test/java/com/moneymaker/strategy/rules/CommonRulesTest.java) — 22 tests across 6 `@Nested` groups: `isMarketCloseTime`, `isDistanceToNextHigherSmaAboveTarget`, `nextHigherSmaPeriod`, `profitTarget`, `smaValue`, price helpers. Every rule predicate and every SMA-period mapping pinned.
- [`SmaTrendCalculatorTest`](src/test/java/com/moneymaker/strategy/rules/SmaTrendCalculatorTest.java) — first-candle-of-day trending, strictly-monotonic SMA series, `maxDeviations` tolerance, day-boundary reset, zero-SMA / null-SMA edge cases.
- [`RuleEngineTest`](src/test/java/com/moneymaker/strategy/rules/RuleEngineTest.java) — 17 tests covering `resolvePrimarySmaPeriod`, the SMA-cross gate decision matrix (SELL/BUY/NONE for every combination of gate × rule outcome), and the required-AND / anyOf-OR evaluator.
- [`Strategy1Test`](src/test/java/com/moneymaker/strategy/Strategy1Test.java) — `SharedData`-aware integration unit test: wipes static state before/after each case, verifies SELL signal end-to-end, instrument-token + interval filtering, **CE = ascending strike order / PE = descending strike order** (pins the determinism fix that prevents "different strike each run").
- [`Strategy2Test`](src/test/java/com/moneymaker/strategy/Strategy2Test.java) — pins stub contract; will fail loudly when real logic lands.

### Fixed — M0.1.6 Gap cleanup (2026-05-28)
- **GAP #11** — Deleted `TradeConfigScheduler.dailyTaskAt912AM` no-op stub. The method only logged a line and added cron metadata for no real work.
- **GAP #13** — Wired orphan `016_add_interval_expiry_to_market_data.xml` and `017_add_underlying_name_to_market_data.xml` into `db.changelog-master.xml`. Both already carried `columnExists` preconditions with `onFail=MARK_RAN`, so production picks up no-op if the columns were created out-of-band; fresh installs get them via Liquibase. Closes the orphan-changeset class of bug for these two files.

### Added — M0.1.6 (2026-05-28)
- **GAP #14** — [`LiquibaseMasterInclusionTest`](src/test/java/com/moneymaker/architecture/LiquibaseMasterInclusionTest.java): build-time guard that scans every `*.xml` under `db/changelog/` and asserts each is referenced by `<include file="…"/>` in the master, plus the reverse (no dangling includes). A new orphan changeset now fails the build at test time instead of failing silently on production / failing loudly on H2 weeks later. Two tests; pure file I/O, no Spring context.

### Added — M0.1.5 Tier-1 unit test coverage (2026-05-28)

10 new test classes, **107 tests, all green** (`mvn test` passes cleanly). Covers the pure-logic Tier-1 classes per [TEST_COVERAGE_PLAN.md](docs/TEST_COVERAGE_PLAN.md). Pure-logic tests run in <5s total; the single Spring Boot test (`BacktestParityTest`) adds ~25s. The canary test from M0.1 was removed — the new ~100-test suite gives sufficient proof the harness can detect failures.

- [`MarketHoursServiceTest`](src/test/java/com/moneymaker/market/service/MarketHoursServiceTest.java) — init parsing, validation, window helpers, alternative-market support.
- [`TotpGeneratorTest`](src/test/java/com/moneymaker/login/util/TotpGeneratorTest.java) — RFC 6238 reference vectors at three published timestamps; 30s step boundary; secret-format tolerance.
- [`ConverterUtilityTest`](src/test/java/com/moneymaker/util/ConverterUtilityTest.java) — every `Object[]`-row mapper depends on these three methods.
- [`IndicatorConfigTest`](src/test/java/com/moneymaker/indicator/IndicatorConfigTest.java) — period validation.
- [`IndicatorFactoryTest`](src/test/java/com/moneymaker/indicator/IndicatorFactoryTest.java) — dispatch, case-insensitivity, registration.
- [`SMAIndicatorImplTest`](src/test/java/com/moneymaker/indicator/SMAIndicatorImplTest.java) — math correctness, side-effect on `MarketData.smaValueN`, edge cases (period > size, empty, null).
- [`EMAIndicatorImplTest`](src/test/java/com/moneymaker/indicator/EMAIndicatorImplTest.java), [`RSIIndicatorImplTest`](src/test/java/com/moneymaker/indicator/RSIIndicatorImplTest.java) — pin the **stub** contract so future real implementations fail these tests in CI, forcing real coverage in the same commit.
- [`BacktestMarketDataCacheTest`](src/test/java/com/moneymaker/backtesting/BacktestMarketDataCacheTest.java) — active gating, slice semantics, null-tolerance, immutability of cached series.
- [`AppStateTest`](src/test/java/com/moneymaker/state/AppStateTest.java) — heartbeat state machine, "transient probe failure preserves session" contract, defensive list copying.
- [`DailyEventGuardTest`](src/test/java/com/moneymaker/state/DailyEventGuardTest.java) — once-per-day semantics, race-loser handling via `DataIntegrityViolationException`.

### Changed — M0.1.5 (2026-05-28)
- [`BacktestParityTest`](src/test/java/com/moneymaker/backtesting/BacktestParityTest.java) — removed `canary_must_fail` (purpose served by the 107-test green suite). `spring_context_boots_against_h2` retained as Spring-context-startup smoke.

### Fixed — M0.1.5 (2026-05-28)
- [`TotpGeneratorTest.invalid_base32_character_is_rejected`](src/test/java/com/moneymaker/login/util/TotpGeneratorTest.java) — initial assertion looked for the wrong message. `TotpGenerator` wraps the inner `BrokerLoginException("Invalid Base32 character: …")` in an outer `BrokerLoginException("Failed to generate TOTP", "TOTP_ERROR", e)`. Test now asserts both the outer message and the root-cause message — pins the wrapping contract.

### Added — M0.1.5 docs (2026-05-28)
- [`docs/TEST_COVERAGE_PLAN.md`](docs/TEST_COVERAGE_PLAN.md) — tiered approach (Tier 0 skipped with rationale, Tier 1 must-have, Tier 2 should-have, Tier 3 on-demand), inventory of 24 Tier-1 classes, ship-incrementally batch plan (B1 done; B2 strategy/rule tests next).
- [`docs/GAPS.md`](docs/GAPS.md) — new gap #15: EMA and RSI implementations are stubs returning 0.0.

### Added — M0.1 test harness scaffold (2026-05-27)
- [`src/test/resources/application-test.properties`](src/test/resources/application-test.properties) — H2 in MySQL-compatibility mode for the test profile. **Decision:** H2 over Testcontainers because the dev environment has no Docker; trade-off accepted is periodic manual re-verification against real MySQL.
- [`BacktestParityTest`](src/test/java/com/moneymaker/backtesting/BacktestParityTest.java) with two tests: a `canary_must_fail` (proves the harness can detect failures; removed in M2) and `spring_context_boots_against_h2` (proves Liquibase migrations are portable).
- [`TradeOrderSnapshot`](src/test/java/com/moneymaker/backtesting/support/TradeOrderSnapshot.java) — deterministic JSON-ish serialiser. Rows sorted by business keys, never by DB-assigned id. `BigDecimal` via `toPlainString()` so scale survives round-trip.
- [`FixtureLoader`](src/test/java/com/moneymaker/backtesting/support/FixtureLoader.java) — skeleton for loading `.sql` fixture files (used by M0.2/M0.3).
- [`TradeOrderSnapshotTest`](src/test/java/com/moneymaker/backtesting/support/TradeOrderSnapshotTest.java) — 5 unit tests asserting determinism + scale preservation + id exclusion.

### Fixed — M0.1 surfaced two pre-existing schema bugs (2026-05-27)
- [`db/changelog/005_create_market_data_table.xml`](src/main/resources/db/changelog/005_create_market_data_table.xml) was orphaned — present on disk, not wired into the master changelog. Production worked only because Hibernate `ddl-auto=update` created the table from the JPA entity; Liquibase never ran the changeset. Wired into master with a `tableExists` precondition (`onFail=MARK_RAN`) so production picks up no-op and H2/fresh installs run the CREATE. Same file referenced `dbchangelog-4.23.0.xsd` (unbundled, requires network); aligned to `dbchangelog-3.8.xsd` matching the rest of the changesets.

### Added prior to M0.1 (uncommitted across earlier sessions, now committed)
- Trade-config admin UI at `/trade-configs` with inline form + paginated report. New endpoints under `/api/trade-configs/*`. New package `com.moneymaker.tradeconfig.*` (controller + service + DTOs). Backed by [`TradeConfigAdminService`](src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java) which invalidates the date-cache and refreshes `SharedData.combinedDto` on writes to today's configs.
- [`MarketHoursService`](src/main/java/com/moneymaker/market/service/MarketHoursService.java) as the single source of truth for the trading window (default 09:15–15:30 Asia/Kolkata, configurable via `app.market.*`).
- [`DaySummaryScheduler`](src/main/java/com/moneymaker/scheduler/DaySummaryScheduler.java) fires once at 15:31 IST Mon–Fri: force-closes any leftover OPEN trades, builds a Telegram summary, gates with `DailyEventGuard`.
- `NotificationService.alertDaySummary(String)` — thin pass-through; caller owns dedupe.
- `TradeOrderRepository.findByEntryTimeBetween(...)` and `existsByTradeConfigId(...)`.
- `InstrumentRepository` (was missing; now needed by the trade-config admin dropdown).
- `SmaTimeframeRepository.deleteByTradeConfigId(...)` for replace-on-update of SMA rows.
- `StrategyFactory.availableStrategyIds()` so the strategy dropdown is auto-discovered.

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
- Added [`docs/MILESTONE_DETAILS.md`](docs/MILESTONE_DETAILS.md) and [`docs/EXECUTION_PLAN.md`](docs/EXECUTION_PLAN.md).
- Added this `CHANGELOG.md`.

---

<!-- Released entries go below this line, newest first. -->
