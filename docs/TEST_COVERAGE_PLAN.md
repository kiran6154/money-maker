# Test coverage plan

> Companion to [`MILESTONE_DETAILS.md`](MILESTONE_DETAILS.md) and
> [`EXECUTION_PLAN.md`](EXECUTION_PLAN.md). Where those docs describe the
> *integration* harness (`BacktestParityTest`, M0–M2), this doc covers the
> *unit-test* coverage strategy for the existing codebase.
>
> **Goal.** Establish a regression net so any subsequent change can be
> validated by `mvn test`. The set of tests below is what we believe
> catches real bugs; tests for everything else are deliberately omitted.

---

## Pushback on "test every class"

122 Java files in `src/main/java/com/moneymaker/`. Writing a unit test for every one is the wrong default for three reasons:

1. **Lombok-generated and JPA-mapped classes have no behaviour to test.** Asserting that `tradeOrder.setProfit(...)` followed by `getProfit()` returns the same value tests `lombok.Data`, not the application.
2. **Spring Data repository interfaces have no implementation to test in isolation.** They're tested at the JPA-slice level (`@DataJpaTest`) only when the query carries complexity worth verifying.
3. **Configuration classes, enums, and exceptions** have no logic worth a test file.

The principle: **test behaviour, not declarations.** A test that doesn't fail when behaviour breaks is dead weight on every refactor.

---

## Tiered coverage

### Tier 1 — Business logic, full unit tests *(must)*

Pure-logic classes where bugs hide. These get dedicated test classes covering happy paths, edge cases, and known-bug scenarios. **No Spring context.**

| # | Class | Why it matters | Test file |
|---|---|---|---|
| 1 | `market.service.MarketHoursService` | New code from prior session; gates the live pipeline | `MarketHoursServiceTest` |
| 2 | `login.util.TotpGenerator` | RFC 6238 math; broker auth depends on it | `TotpGeneratorTest` |
| 3 | `util.ConverterUtility` | Used by every `Object[]`-row mapper | `ConverterUtilityTest` |
| 4 | `indicator.IndicatorConfig` | Validates period; small but used everywhere | `IndicatorConfigTest` |
| 5 | `indicator.IndicatorFactory` | Indicator dispatch | `IndicatorFactoryTest` |
| 6 | `indicator.SMAIndicatorImpl` | Real math via ta4j; computes per-period SMA | `SMAIndicatorImplTest` |
| 7 | `indicator.EMAIndicatorImpl` | **Currently a stub** (always returns 0.0); test pins the stub so a real impl shows up in CI as a failing test | `EMAIndicatorImplTest` |
| 8 | `indicator.RSIIndicatorImpl` | Same — currently a stub | `RSIIndicatorImplTest` |
| 9 | `backtesting.BacktestMarketDataCache` | Lifecycle (`beginDay`/`slice`/`endDay`) + active gating | `BacktestMarketDataCacheTest` |
| 10 | `state.DailyEventGuard` | Once-per-day gating (Telegram suppression) | `DailyEventGuardTest` |
| 11 | `state.AppState` | Session + heartbeat state machine | `AppStateTest` |
| 12 | `strategy.rules.SmaTrendCalculator` | Trend detection from candles | `SmaTrendCalculatorTest` |
| 13 | `strategy.rules.CommonRules` | Rule predicates | `CommonRulesTest` |
| 14 | `strategy.rules.TradeRules` | Rule predicates | `TradeRulesTest` |
| 15 | `strategy.rules.RuleEngine` | The buy/sell decision orchestrator | `RuleEngineTest` |
| 16 | `strategy.Strategy1` | The main strategy | `Strategy1Test` |
| 17 | `strategy.Strategy2` | The second strategy | `Strategy2Test` |
| 18 | `order.service.OrderService` | Dedupe, caps, lifecycle, force-close | `OrderServiceTest` |
| 19 | `position.service.PositionService` | Peak tracking, SL/target triggers | `PositionServiceTest` |
| 20 | `scheduler.DaySummaryScheduler` | End-of-day summary building + gate | `DaySummarySchedulerTest` |
| 21 | `scheduler.TradeConfigScheduler` | Date-keyed cache + reporting | `TradeConfigSchedulerTest` |
| 22 | `tradeconfig.service.TradeConfigAdminService` | CRUD + cache invalidation + live `SharedData` refresh | `TradeConfigAdminServiceTest` |
| 23 | `login.service.LoginOrchestrator` | Auth state machine; ensureLoggedIn idempotency | `LoginOrchestratorTest` |
| 24 | `backtesting.support.TradeOrderSnapshot` | **Already exists** | ✅ done |

### Tier 2 — Wiring + integration, slice tests *(should)*

Classes whose value is integration. Use Spring's slice annotations (`@WebMvcTest`, `@DataJpaTest`, `@SpringBootTest`).

| # | Target | Slice | Test file |
|---|---|---|---|
| 25 | Controllers — `LoginController`, `OrderController`, `TradeConfigAdminController`, `BacktestController` | `@WebMvcTest` | one per controller, with mocked services |
| 26 | Critical repositories with custom queries — `TradeConfigRepository.fetchCombinedByTradingDate`, `TradeOrderRepository.sumRealisedProfitForDay` | `@DataJpaTest` | one per repository |
| 27 | `BacktestParityTest` — full pipeline | `@SpringBootTest` | **Already exists** (M0.1) |
| 28 | `TradingPipelineScheduler` — pipeline ordering | `@SpringBootTest` slice | lands with M1 |

### Tier 3 — Broker adapters, mocked HTTP *(when changed)*

| # | Target | Approach |
|---|---|---|
| 29 | Per-broker `LoginService`, `OrderPlacementService`, `PositionMonitorService` | Each broker's adapter gets a test with mocked broker SDK / RestTemplate. Tests cover: happy-path response → standard DTO, failure → typed exception, malformed JSON → handled. Lands when we touch a broker (not pre-emptive). |

### Tier 0 — Skipped, with rationale *(intentional)*

| Pattern | Files | Why skipped |
|---|---|---|
| Lombok-`@Data` DTOs | `dto/*`, `tradeconfig/dto/*`, `login/model/{BrokerLoginRequest,BrokerLoginResponse}` | No behaviour. If a Lombok bug ships, our parity test fails. |
| JPA entities | `entity/*`, `broker/*/{...TokenResponse}`, `data/download/OptionsDataEntity` | Field mappings only. Verified by the parity test executing real queries. |
| Spring Data repository interfaces (no custom query) | most `repository/*` | Spring Data is library code; we test our overrides only. |
| `@ConfigurationProperties` binders | `BrokerProperties`, `TelegramProperties`, `AppModeProperties` | Spring Boot tests bind these; pure data classes. |
| Enums | `Broker`, `HeartbeatStatus`, `AppMode`, `TradeAction` | Constants. |
| Exceptions | `BrokerLoginException`, `KiteRateLimitException` | Trivial. |
| `MoneyMakerApplication` | the main | Just a `@SpringBootApplication` with `main`. |

---

## Test naming & layout

- Test class = `<ClassName>Test`, sibling package under `src/test/java/`.
- Methods: `verb_noun_when_condition` (e.g. `returns_null_when_value_is_null`).
- One `@Nested` block per behavioural surface when a class has >5 tests.
- AssertJ `assertThat`; never JUnit 4 `assertEquals` (less helpful diff messages).
- Mockito for collaborators in Tier 1 service tests; **no `@MockBean` outside Spring tests** (it's slow).

---

## Execution model

```
mvn test          → all unit tests (Tier 1) + slice tests (Tier 2 minus full Spring boot)
mvn verify        → adds @SpringBootTest classes (BacktestParityTest + similar)
```

Tier 1 tests run in **<5 seconds total**. Tier 2 adds ~30s. Tier 3 (`BacktestParityTest`) adds ~30s. Total target: **<2 minutes for full `mvn verify`** so the parity contract stays cheap to enforce per PR.

---

## How to ship coverage incrementally

This is a multi-PR effort. Suggested batching:

| Batch | What | Effort | Status |
|---|---|---|---|
| **B1** | TEST_COVERAGE_PLAN.md + Tier 1 pure-logic tests (#1–#11) | 1 day | 🔧 this batch |
| **B2** | Tier 1 strategy + rule tests (#12–#17) | 1 day | not started |
| **B3** | Tier 1 service tests (#18–#23) | 1.5 days | not started |
| **B4** | Tier 2 slice tests (#25–#26) | 1 day | not started |
| **B5** | Broker adapters (#29) on-demand | 0.5 day each | not started |

Total time-to-coverage: **~5-6 days of focused work**. Worth doing because every milestone past M0 relies on this safety net.

Each batch lands as its own commit/PR. CHANGELOG updates per batch.

---

## What tests do NOT cover (and why)

- **Manual sandbox testing for broker-side behaviour** — broker SDK responses can't be perfectly mocked; manual paper-trading verification stays in place (already part of M3's done-definition).
- **Performance benchmarks** — handled separately by M9's regression check.
- **UI** — Thymeleaf templates rendered server-side; covered by manual smoke for now. Selenium / Playwright tests deferred until the UI grows beyond the current 4 pages.

---

## Open questions

1. **Should we add ArchUnit tests now?** They'd catch the orphan-changeset bug class (GAPS #14) at build time and prevent SharedData regressions (M7.1 plan). Recommend: **yes, in B4**.
2. **Mutation testing?** Pitest gives a quality signal on the unit tests themselves. Recommend: defer until B3 is done; pitest on Tier 1 only.
3. **Code coverage target?** Aim for ≥80% line coverage on Tier 1; don't measure coverage on Tier 0 (would distort the number).
