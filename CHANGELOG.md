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
