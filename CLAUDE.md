# CLAUDE.md

Operating instructions for **Claude Code** (and any other Claude-family agent) working on this repository.
> If you are a different AI assistant, also read [`AGENTS.md`](AGENTS.md) — it carries the same content with tool-agnostic phrasing.

---

## TL;DR

This is a **Spring Boot 3 / Java 17** broker-automation app. The architecture is opinionated — please respect these invariants:

1. **One auth code path.** All broker login decisions go through `com.moneymaker.login.service.LoginOrchestrator`. Never re-implement the "ensure we're logged in" logic in a scheduler, controller, or backtest step. Call the orchestrator instead.
2. **One adapter per broker.** Implement `BrokerLoginService`, `OrderPlacementService`, and `PositionMonitorService` in `com.moneymaker.broker.<name>`. Translate native responses into the standard DTOs (`BrokerSession`, `FillSnapshot`); don't leak broker-specific types upward.
3. **Single global state holder.** Inject `com.moneymaker.state.AppState` rather than touching `BrokerSessionStore` or DB repositories directly when reading runtime status (logged-in flag, heartbeat, cached configs).
4. **Notifications go through the facade.** Always call `NotificationService.alert*(...)` — never `TelegramNotifier.send(...)` directly. The notifier handles dedupe, throttling, and backtest-mode suppression for you.
5. **Backtest preflight === live preflight.** The backtest pipeline (`com.moneymaker.backtesting`) reuses `LoginOrchestrator` and the same scheduler entry points the cron uses. Do not add a separate "test" path.
6. **Liquibase only for schema.** Never edit a previously deployed changeset; always add a new `00X_*.xml` file under `src/main/resources/db/changelog/` and include it from the master.
7. **`trade_order` is the order ledger.** Every entry / exit / force-close persists a row before any broker call. `OrderService` is the single owner of order lifecycle — feature code calls it, not the placement service directly.
8. **Schedulers run identically in live and backtest.** `BacktestAnalysisService` calls the same `analysisScheduler.runStrategies()` / `orderScheduler.processOrders()` / `positionScheduler.processPositions()` methods the cron does. Do not put work inside the `@Scheduled` method that backtest can't replay.
9. **No hardcoded trading-behaviour rules.** Caps, thresholds, lifecycle rules, and any number/boolean that controls *when to enter, when to exit, how many trades* must come from `TradeConfig` (or equivalent config). Idempotency guards and correctness invariants (e.g. "don't insert the same row twice", "don't monitor the candle that opened the trade") are technical and may stay in code. If a needed parameter has no `TradeConfig` field, **ask the user** before hardcoding — don't guess at a default. See ["Hardcoded vs config-driven" in ORDERS_AND_POSITIONS.md](docs/ORDERS_AND_POSITIONS.md#hardcoded-vs-config-driven).

---

## Repo layout (high level)

```
src/main/java/com/moneymaker/
├── broker/{angelone, groww, zerodha}     Per-broker adapters: login, order placement, position monitor
├── controller/                            Thymeleaf + JSON controllers
├── backtesting/                           BacktestAnalysisService + Backtesting{OrderPlacement,PositionMonitor} impls
├── dto/                                   TradeAction, TradeSignal, FillSnapshot, TradeConfigCombinedDTO …
├── entity/                                JPA entities (broker_session, trade_config, trade_order, market_data, …)
├── indicator/                             SMA implementation
├── login/
│   ├── config/                            BrokerProperties, RestTemplate bean
│   ├── exception/                         BrokerLoginException
│   ├── model/                             Broker, BrokerSession, Heartbeat*
│   ├── service/                           BrokerLoginService, BrokerLoginManager,
│   │                                      BrokerSessionStore, LoginOrchestrator
│   └── util/TotpGenerator                 RFC 6238
├── market/
│   ├── exception/KiteRateLimitException   precise retry trigger for the broker rate-limit case
│   ├── provider/                          MarketDataProvider abstraction
│   └── service/MarketDataService          Resilience4j-wrapped historical fetch
├── order/
│   ├── controller/OrderController         GET /api/orders, POST /api/orders/{id}/sync
│   └── service/                           OrderService, OrderPlacementService + OrderPlacementFactory
├── position/
│   └── service/                           PositionService, PositionMonitorService + PositionMonitorFactory
├── repository/                            Spring Data JPA
├── scheduler/                             LoginScheduler, AnalysisScheduler, TradeConfigScheduler,
│                                          OrderScheduler, PositionScheduler
├── shared/data/SharedData                 Static caches (combinedDto, strikeMarketData…, tradeSignals)
├── state/AppState                         Global runtime facade
├── strategy/                              Strategy interface + Strategy1 + rules/{RuleEngine, CommonRules, …}
├── telegram/                              TelegramNotifier + NotificationService
└── util/

src/main/resources/
├── application.properties                 broker.* / telegram.* / app.mode / resilience4j.* keys
├── db/changelog/                          Liquibase changesets (numbered NNN_*.xml, currently up to 023)
├── static/css/app.css                     Glassmorphism palette
└── templates/                              Thymeleaf views (index, login, manual-login, backtest)
```

For an end-user view of the same map see [`Readme.md`](Readme.md). For deeper dives see the docs index below.

---

## Documentation index

When changing anything in these areas, **read the relevant doc first**:

| Area | Doc | What it covers |
|---|---|---|
| Login flow + broker adapters | [`docs/LOGIN_FLOW.md`](docs/LOGIN_FLOW.md) | OAuth vs TOTP, controller endpoints, callback handling |
| Heartbeat probes + state machine | [`docs/HEARTBEAT.md`](docs/HEARTBEAT.md) | Auth + data probes, transition-only alerting, state diagram |
| Backtesting | [`docs/BACKTESTING.md`](docs/BACKTESTING.md) | Run modes, pipeline, controller endpoints |
| Backtest performance + live parity | [`docs/BACKTEST_PERFORMANCE.md`](docs/BACKTEST_PERFORMANCE.md) | Speed-up phases, per-phase live-mode impact, parity verification checklist |
| Architecture overview | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | High-level layering and conventions |
| Schedulers (all 5) | [`docs/SCHEDULERS.md`](docs/SCHEDULERS.md) | LoginScheduler, AnalysisScheduler, TradeConfigScheduler, OrderScheduler, PositionScheduler — cadence, pipeline, mode-gating |
| Orders + position monitoring | [`docs/ORDERS_AND_POSITIONS.md`](docs/ORDERS_AND_POSITIONS.md) | Order lifecycle, dedupe rules, broker factories, peak / SL / target tracking, `trade_order` columns |
| Broker rate limiting + retry | [`docs/RATE_LIMITING.md`](docs/RATE_LIMITING.md) | Resilience4j wiring, the cache / reshape PR roadmap |
| Telegram alerts + dedupe | [`docs/NOTIFICATIONS.md`](docs/NOTIFICATIONS.md) | `NotificationService` facade, `sendIfChanged` / `sendThrottled`, backtest gate |
| EOD downtrend auto-config | [`docs/EOD_DOWNTREND.md`](docs/EOD_DOWNTREND.md) | `sma_downtrend_rule` table, end-of-day detector, `trade_config.source` marker, extension hooks |

If you add a doc, link it here. If you change behaviour described in a doc, update the doc in the same PR — see the next section.

---

## Documentation hygiene

Docs in this repo are first-class. They are how the next contributor (human or AI) understands intent and constraints quickly.

**Update the relevant `docs/*.md` in the same change** when you:

- Add a new scheduler, alert type, exit reason, or `trade_order` column → update [`SCHEDULERS.md`](docs/SCHEDULERS.md), [`NOTIFICATIONS.md`](docs/NOTIFICATIONS.md), and [`ORDERS_AND_POSITIONS.md`](docs/ORDERS_AND_POSITIONS.md) as applicable.
- Add a new broker → update the broker tables in [`ORDERS_AND_POSITIONS.md`](docs/ORDERS_AND_POSITIONS.md) and the recipe in [`Readme.md`](Readme.md).
- Add a new Liquibase changeset → reference it in the relevant doc's "columns" or "schema" section.
- Add a new `application.properties` key → mention it in the doc that describes the feature it gates.
- Land one of the pending PRs listed in a doc → strike it through or remove the bullet.

**Do not** create speculative docs. Add a page only when something exists in code that needs explaining beyond what the code itself shows.

If a change spans more than three files, write a short plan first; the user prefers reviewing plans before refactors.

---

## How to make changes

### Editing existing code
- **Read first.** Use the file-read / search tools before editing. Don't guess at structure.
- **Match style.** Lombok (`@Data`, `@RequiredArgsConstructor`, `@Slf4j`) is in heavy use — keep using it.
- **Keep packages tight.** New broker adapter → `com.moneymaker.broker.<name>`. New backtest stage → `com.moneymaker.backtesting`. New scheduler → `com.moneymaker.scheduler`.
- **Compile after each meaningful edit.** Run:
  ```powershell
  mvn -q -DskipTests compile
  ```
  IDE-only "never used" warnings on Spring beans are false positives — ignore them.

### Adding a broker
Follow the recipe in [`Readme.md` → Adding a new broker](Readme.md#adding-a-new-broker) and the "Adding a new broker" section of [`docs/ORDERS_AND_POSITIONS.md`](docs/ORDERS_AND_POSITIONS.md). In short:
1. New package `com.moneymaker.broker.<name>` with `<Name>LoginService implements BrokerLoginService`.
2. Add `<Name>OrderPlacementService implements OrderPlacementService` and `<Name>PositionMonitorService implements PositionMonitorService` in the same package. Both factories auto-discover via Spring `List` injection.
3. Add a value to the `Broker` enum.
4. Add `broker.<name>.*` keys + nested config class in `BrokerProperties`.
5. If the broker JSON is snake_case (Kite, Groww), annotate the response POJO with `@JsonNaming(SnakeCaseStrategy)` — otherwise tokens silently bind to null.
6. Override `fetchHeartbeatQuote()` with a real LTP probe so the heartbeat catches "token valid but data dead".

### Adding a scheduler
See [`docs/SCHEDULERS.md` → Adding a new scheduler](docs/SCHEDULERS.md#adding-a-new-scheduler). Put the work in a service so backtest can replay it.

### Adding a DB column / table
1. Create `src/main/resources/db/changelog/NNN_<purpose>.xml`. Numbering is sequential — current head is 023. Check the directory before picking a number: `018` is already used twice (`018_create_sma_downtrend_rule_table.xml` and `018_create_historical_chart_tables.xml`), so confirm your number is actually free.
2. Include it in `db.changelog-master.xml`.
3. Add / update the JPA entity with `@Column(name="…")`.
4. Update relevant repositories.
5. **Never** edit an existing committed changeset — Liquibase will refuse to start.
6. Update the relevant `docs/*.md` columns table.

### Adding a Telegram alert type
See [`docs/NOTIFICATIONS.md` → How to add a new alert](docs/NOTIFICATIONS.md#how-to-add-a-new-alert). Add a method to `NotificationService` (`alertSomething(...)`); pick the right dedupe shape (`sendIfChanged` / `sendThrottled` / no dedupe). Do **not** call `TelegramNotifier.send(...)` directly from outside `com.moneymaker.telegram`.

---

## What NOT to do

- ❌ Do not duplicate the auth flow. Always call `LoginOrchestrator.ensureLoggedIn()` (or `forceLogin()`).
- ❌ Do not store credentials, tokens, or chat-ids in source. Use `application.properties` (or `${ENV_VAR:default}` interpolation).
- ❌ Do not add `@Scheduled` methods that call `notifier.*` directly without using `sendIfChanged` / `sendThrottled` or a transition guard.
- ❌ Do not edit committed Liquibase changesets.
- ❌ Do not introduce broker-specific types (e.g. `ZerodhaTokenResponse`) into shared packages (`login.*`, `order.*`, `position.*`, `state.*`, `controller.*`). They belong inside `broker.<name>`.
- ❌ Do not reach into `BrokerSessionStore` from a feature package when `AppState` already exposes the data you need.
- ❌ Do not call `OrderPlacementService.place(...)` from feature code — go through `OrderService` so the DB ledger and dedupe rules stay authoritative.
- ❌ Do not put work inside an `@Scheduled` method body that the backtest can't replay. Put it on the underlying service.
- ❌ Do not hardcode trading-behaviour rules — caps, thresholds, lifecycle counts. They belong in `TradeConfig`. Ask before adding a constant that affects entry/exit decisions.

---

## Run / test commands

```powershell
# compile only
mvn -q -DskipTests compile

# run app on :8080 (requires MySQL)
mvn spring-boot:run

# build fat jar
mvn -DskipTests package
java -jar target/money-maker-1.0.0.jar

# trigger backtest end-to-end (login only today)
curl -X POST http://localhost:8080/api/backtest/login

# trigger an analysis run
curl -X POST "http://localhost:8080/api/backtest/analysis?fromDate=2026-05-08&toDate=2026-05-08"

# inspect runtime state
curl http://localhost:8080/api/session

# fetch persisted orders
curl http://localhost:8080/api/orders
```

---

## Glossary

| Term | Meaning |
|---|---|
| **Broker session** | An authenticated session with a broker. Persisted in `broker_session`, surfaced as `BrokerSession` DTO. |
| **Active broker** | The broker selected by `broker.active`. Only one is active at a time. |
| **Heartbeat** | The 1-min scheduler tick that runs an auth probe + a data probe and records `last_heartbeat_status` in `broker_session`. |
| **Transition** | A change in `HeartbeatStatus` (e.g. `OK → AUTH_FAIL`). Telegram alerts only fire on transitions. |
| **Trade signal** | Strategy-emitted `BUY` / `SELL` intent on a specific option leg. Pushed onto `SharedData.tradeSignals`, drained by `OrderService`. |
| **Trade order** | A persisted row in `trade_order` representing one open-and-close trade lifecycle. |
| **Fill status** | Broker-side state of the most recent leg: `PENDING` / `COMPLETE` / `REJECTED` / `CANCELLED` / `BACKTEST`. |
| **Exit reason** | Why a trade closed: `SIGNAL` / `TARGET` / `STOP_LOSS` / `FORCE_CLOSE`. |
| **Position monitor** | The `PositionScheduler` tick that walks OPEN trades, updates peak / last-monitored fields, and triggers SL / target closes. |

---

## When in doubt

Re-read [`Readme.md`](Readme.md) and the relevant `docs/*.md` (the index above is the map). If a change spans more than three files, write a short plan first.
