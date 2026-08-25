# Money Maker

A Spring Boot 3 / Java 17 broker-automation backend that authenticates with Indian retail brokers (Zerodha Kite Connect, Groww, Angel One SmartAPI), keeps the session alive via a two-tier heartbeat, exposes a glassmorphism UI, and runs a sequenced backtest pipeline whose preflight is byte-for-byte identical to live trading.

> **Status:** active development. Login + heartbeat + Telegram alerting, the full analysis → order → position trading pipeline, a multi-day backtest runner (with EOD downtrend auto-config generation), a trade-config admin UI, an end-of-day summary, and a chart dashboard (live token-based + imported historical ICICI data) are all implemented and wired identically in live and backtest. Zerodha is the most complete broker adapter; Groww and Angel One order placement / position monitoring are still skeletons — see [`docs/ORDERS_AND_POSITIONS.md`](docs/ORDERS_AND_POSITIONS.md#things-that-are-still-pending) for the exact remaining gaps.

---

## Table of contents
1. [Quick start](#quick-start)
2. [Feature highlights](#feature-highlights)
3. [Architecture at a glance](#architecture-at-a-glance)
4. [Package map](#package-map)
5. [Configuration reference](#configuration-reference)
6. [HTTP endpoints](#http-endpoints)
7. [Schedules](#schedules)
8. [Database](#database)
9. [Adding a new broker](#adding-a-new-broker)
10. [Adding a new backtest stage](#adding-a-new-backtest-stage)
11. [Telegram setup](#telegram-setup)
12. [Troubleshooting](#troubleshooting)
13. [Further reading](#further-reading)

---

## Quick start

### Prerequisites
- JDK 17+
- Maven 3.9+
- MySQL 8 running on `localhost:3306` with `root / root` (or override the datasource properties)
- *(optional)* A Telegram bot token + chat id

### Run
```powershell
git clone <this-repo> money-maker
cd money-maker
mvn spring-boot:run
```
The app comes up on **http://localhost:8080**. The MySQL schema `moneymath` is created automatically (Liquibase). Open the dashboard, click **🔑 Broker Login**, follow the broker-specific flow.

### Build a fat jar
```powershell
mvn -DskipTests package
java -jar target/money-maker-1.0.0.jar
```

---

## Feature highlights

| Capability | Where it lives |
|---|---|
| Pluggable broker adapters (Zerodha / Groww / Angel One) | `com.moneymaker.broker.<broker>` |
| Standard session DTO + JPA-persisted store | `login.model.BrokerSession`, `entity.BrokerSessionEntity`, `login.service.BrokerSessionStore` |
| Single source of truth for the auth flow | `login.service.LoginOrchestrator` |
| Two-tier heartbeat (auth + market-data probe) | `scheduler.LoginScheduler` + `BrokerLoginService.fetchHeartbeatQuote` |
| Telegram alerting on state transitions | `com.moneymaker.telegram` (`TelegramNotifier`, `NotificationService`) |
| Global runtime state (logged-in flag, heartbeat, cached configs) | `com.moneymaker.state.AppState` |
| Multi-day backtest runner — replays the same scheduler services the live cron uses, tick by tick | `com.moneymaker.backtesting.BacktestAnalysisService` |
| End-of-day auto-generation of next-day `trade_config` rows from a sustained SMA downtrend | `com.moneymaker.backtesting.EodDowntrendDetectionService` — see [`docs/EOD_DOWNTREND.md`](docs/EOD_DOWNTREND.md) |
| 5-min analysis → order → position pipeline, market-hours gated | `com.moneymaker.scheduler.{AnalysisScheduler,OrderScheduler,PositionScheduler}` — see [`docs/SCHEDULERS.md`](docs/SCHEDULERS.md) |
| Trade-config admin UI (CRUD + bulk delete for auto-generated configs) | `com.moneymaker.tradeconfig.*`, page at `/trade-configs` — see [`docs/ORDERS_AND_POSITIONS.md`](docs/ORDERS_AND_POSITIONS.md#trade-config-admin) |
| End-of-day force-close + Telegram digest | `com.moneymaker.scheduler.DaySummaryScheduler` |
| Chart dashboard — live token-based candles or imported historical ICICI CSV data | `com.moneymaker.chart.*`, page at `/charts/dashboard` — see [`docs/CHART_DASHBOARD.md`](docs/CHART_DASHBOARD.md) |
| Glassmorphism UI (Thymeleaf + plain CSS/JS) | `src/main/resources/templates/*` and `static/css/app.css` |

---

## Architecture at a glance

```
                                                ┌────────────────────────┐
                                                │  application.properties │
                                                │  broker.active=zerodha  │
                                                └───────────┬────────────┘
                                                            │
       ┌──────────────────┐                       ┌─────────▼────────────┐
       │ Thymeleaf UI     │  HTTP                 │ LoginController      │
       │ /  /login        │ ───────────────────► │ /api/session         │
       │ /backtest        │                       │ /login/* /logout     │
       └─────────┬────────┘                       └─────────┬────────────┘
                 │                                          │
                 │                                          ▼
                 │                            ┌──────────────────────────┐
                 │                            │ LoginOrchestrator        │
                 │                            │  (single auth code path) │
                 │                            └─────────┬────────────────┘
                 │                                      │
        ┌────────┴────────┐                             ▼
        │ BacktestRunner  │            ┌─────────────────────────────────┐
        │  · LoginStep    │ ─────────► │ BrokerLoginService (interface)  │
        │   (order 0)     │            │  · ZerodhaLoginService          │
        └─────────────────┘            │  · GrowwLoginService            │
                 ▲                     │  · AngelOneLoginService         │
                 │                     └────────────┬────────────────────┘
                 │                                  │ saves
                 │                                  ▼
        ┌────────┴────────┐            ┌──────────────────────────┐
        │ LoginScheduler  │ ─────────► │ AppState  (global state) │
        │ 08:00 cron +    │            └────────────┬─────────────┘
        │ heartbeat 1 min │                         │
        └────────┬────────┘                         ▼
                 │                       ┌─────────────────────────┐
                 │ on transition         │ BrokerSessionStore →    │
                 └─────────────────────► │ broker_session (MySQL)  │
                                         └─────────────────────────┘
                 │ on transition
                 ▼
        ┌────────────────┐                ┌────────────────────────┐
        │ Notification   │ ─────────────► │ TelegramNotifier       │
        │ Service        │                │ /sendMessage           │
        └────────────────┘                └────────────────────────┘
```

Key invariants:
- **One adapter per broker.** Driven by a single shared interface (`BrokerLoginService`).
- **Single active broker.** `broker.active` selects it; the `broker_session` table has a UNIQUE constraint on `broker` and at most one row may have `logged_in = true`.
- **One auth code path.** Both the live scheduler and the backtest runner call `LoginOrchestrator.ensureLoggedIn()` — there is no parallel "test login" implementation.
- **Notifications fire on transitions only.** `LoginScheduler.transitionAndNotify` and `LoginOrchestrator` together guarantee one Telegram per state change, never per tick.

---

## Package map

```
com.moneymaker
├── MoneyMakerApplication           Spring Boot entry point (@EnableScheduling)
│
├── broker
│   ├── angelone                    Angel One SmartAPI adapter (TOTP login; order/position monitor still skeletons)
│   ├── groww                       Groww adapter (TOTP login; order/position monitor still skeletons)
│   └── zerodha                     Zerodha Kite Connect adapter (OAuth) — most complete: login + order placement + position monitor
│
├── controller
│   └── LoginController             /, /login, /login/start, /login/callback,
│                                   /login/manual, /logout, /api/session
│
├── tradeconfig
│   ├── controller/TradeConfigAdminController   /trade-configs UI + /api/trade-configs CRUD + bulk-delete/calendar/runs
│   ├── service/TradeConfigAdminService         Single owner of trade-config writes — see CLAUDE.md invariant #10
│   └── dto                                     Form/View DTOs, AutoConfigCalendarDTO, AutoDelete{Request,Result}DTO
│
├── chart
│   ├── controller   ChartDashboardViewController (/charts/dashboard), ChartDashboardApiController
│   │                (/api/charts/market-data), HistoricalChartImportController (CSV import)
│   ├── service      ChartDashboardService, HistoricalIciciChartDashboardService, ChartExpiryResolver,
│   │                ChartTimeframeAggregator, HistoricalChartCsvImportService
│   └── dto          MarketChartRequest/Response, ChartCandleResponse, ChartType/IndexSymbol/ChartTimeframe/ChartDataSource
│
├── backtesting
│   ├── BacktestController          POST /api/backtest/login, /api/backtest/analysis
│   ├── BacktestViewController      GET /backtest (Thymeleaf)
│   ├── BacktestAnalysisService     Drives Analysis→Order→Position per simulated day/tick; force-closes EOD
│   ├── EodDowntrendDetectionService  Auto-generates next-day trade_config rows from a sustained SMA downtrend
│   ├── BacktestMarketDataCache     Per-day in-memory candle cache
│   └── Backtesting{OrderPlacement,PositionMonitor}Service   No-op broker adapters used for replay
│
├── data/download
│   ├── OptionsDataController / OptionsBulkDownloadService / ZerodhaMarketDataService   Bulk options_data / market_data ingestion (Zerodha-only)
│   └── IndexDataController / IndexDataDownloadService / IndexDataPersistService        Index candle ingestion
│
├── dto
│   └── TradeConfigCombinedDTO, TradeAction, TradeSignal, FillSnapshot, AllTimeFramedto, …
│
├── entity
│   ├── BrokerSessionEntity         broker_session table
│   ├── Instrument / InstrumentDetails / TradeConfig / SmaTimeframe / SmaDowntrendRule
│   ├── TradeOrder                  trade_order — the order ledger
│   ├── MarketData / HistoricalSpotCandle / HistoricalOptionCandle
│   └── AlertState                  alert_state — once-per-day Telegram gating
│
├── indicator
│   └── SMAIndicatorImpl (ta4j, SMA computed on candle lows), IndicatorFactory / IndicatorService
│
├── login
│   ├── config
│   │   ├── BrokerProperties        broker.* binder
│   │   └── HttpClientConfig        brokerRestTemplate bean
│   ├── exception
│   │   └── BrokerLoginException
│   ├── model
│   │   ├── Broker                  enum {ZERODHA, GROWW, ANGEL_ONE}
│   │   ├── BrokerLoginRequest / BrokerLoginResponse
│   │   ├── BrokerSession           Standard session DTO (broker-agnostic)
│   │   ├── HeartbeatStatus         {OK, AUTH_FAIL, NO_DATA, HTTP_ERROR, NO_SESSION}
│   │   └── HeartbeatResult
│   ├── service
│   │   ├── BrokerLoginService      Interface every broker adapter implements
│   │   ├── BrokerLoginManager      Resolves active adapter via broker.active
│   │   ├── BrokerSessionStore      JPA-backed persistence + heartbeat updates
│   │   └── LoginOrchestrator       Single auth code path (live + backtest)
│   └── util
│       └── TotpGenerator           RFC 6238 TOTP from Base32 secret
│
├── market
│   ├── provider     MarketDataProvider abstraction + per-broker implementations
│   └── service      MarketDataService (Resilience4j-wrapped fetch), MarketHoursService (trading-window gate)
│
├── order
│   ├── controller/OrderController  GET /api/orders, POST /api/orders/{id}/sync, POST /api/orders/purge
│   └── service      OrderService (single owner of order lifecycle), OrderPlacementService + OrderPlacementFactory
│
├── position
│   └── service      PositionService, PositionMonitorService + PositionMonitorFactory
│
├── repository
│   └── BrokerSessionRepository, TradeConfigRepository, TradeOrderRepository, SmaTimeframeRepository, …
│
├── scheduler
│   ├── LoginScheduler              08:00 cron + 1-min heartbeat
│   ├── TradeConfigScheduler        09:16 cron + ApplicationReadyEvent — loads SharedData.combinedDto
│   ├── AnalysisScheduler           5-min cron — OHLC fetch, SMA compute, strategy run (market-hours gated)
│   ├── OrderScheduler              5-min cron — drains trade signals into trade_order (market-hours gated)
│   ├── PositionScheduler           5-min cron — monitors OPEN trade_order rows, SL/target close (market-hours gated)
│   └── DaySummaryScheduler         15:31 cron — EOD force-close + Telegram digest (live only)
│
├── shared/data/SharedData          Static caches: combinedDto, strikeMarketData…, tradeSignals
│
├── state
│   ├── AppState                    Global runtime facade (loggedIn flag, heartbeat, cached configs)
│   └── DailyEventGuard             Once-per-day gating backed by alert_state
│
├── strategy
│   ├── Strategy1 (active) / Strategy2, StrategyFactory
│   └── rules/{RuleEngine, CommonRules, SmaTrendCalculator, TradeRule, TradeRules, RuleContext}
│
├── telegram
│   ├── TelegramProperties          telegram.* binder
│   ├── TelegramNotifier            Low-level /sendMessage client (throttled)
│   └── NotificationService         alertLoginSuccess/Failed/SessionLost/NoData/Recovered/Order*/DaySummary/…
│
└── util
    └── ConverterUtility
```

---

## Configuration reference

All values live in [`src/main/resources/application.properties`](src/main/resources/application.properties).

### Broker
```ini
broker.active=zerodha          # zerodha | groww | angel-one

broker.zerodha.enabled=true
broker.zerodha.api-key=${KITE_API_KEY:...}
broker.zerodha.api-secret=${KITE_API_SECRET:...}
broker.zerodha.user-id=GP3319
broker.zerodha.redirect-url=http://localhost:8080/login/callback

broker.groww.enabled=false
broker.groww.api-key=
broker.groww.totp-secret=

broker.angel-one.enabled=false
broker.angel-one.api-key=
broker.angel-one.client-code=
broker.angel-one.password=
broker.angel-one.totp-secret=
```

### Telegram
```ini
telegram.enabled=true
telegram.bot-token=123456:ABC-DEF...
telegram.chat-id=-100123456
```
When `enabled=false` (or token / chat id blank) `TelegramNotifier` is a no-op — it logs at DEBUG and never makes a HTTP call.

### Database
```ini
spring.datasource.url=jdbc:mysql://localhost:3306/moneymath?...&createDatabaseIfNotExist=true
spring.datasource.username=root
spring.datasource.password=root
spring.liquibase.enabled=true
spring.liquibase.change-log=classpath:db/changelog/db.changelog-master.xml
```

---

## HTTP endpoints

### UI (HTML)
| Method | Path | Purpose |
|---|---|---|
| GET  | `/`                | Dashboard – session + heartbeat status |
| GET  | `/login`           | Broker selector |
| GET  | `/login/start`     | Redirect to active broker's hosted login |
| GET  | `/login/callback`  | Zerodha OAuth callback (`?request_token=…`) |
| GET  | `/login/manual`    | TOTP form (Groww / Angel One) |
| POST | `/login/manual`    | Submit TOTP form |
| POST | `/logout`          | Clear session + invalidate broker-side |
| GET  | `/backtest`        | Backtest console |
| GET  | `/trade-configs`   | Trade-config admin (CRUD + bulk delete for `AUTO_DOWNTREND` rows) |
| GET  | `/charts/dashboard`| Zerodha Kite-style chart dashboard |

### JSON
| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/session`       | `{ activeBroker, loggedIn, dataHealthy, lastHeartbeatStatus, lastHeartbeatAt, lastDataAt, session: {...} }` |
| POST | `/api/backtest/login`  | Backtest-mode login preflight (same `LoginOrchestrator` as live) |
| POST | `/api/backtest/analysis?fromDate=&toDate=` | Run the multi-day analysis→order→position replay; returns per-day summary |
| GET/POST/PUT/DELETE | `/api/trade-configs[...]` | Trade-config CRUD — see [`docs/ORDERS_AND_POSITIONS.md`](docs/ORDERS_AND_POSITIONS.md#trade-config-admin) |
| GET/POST | `/api/trade-configs/auto/{calendar,runs,delete}` | Bulk config delete — `AUTO_DOWNTREND` by default, `MANUAL` on opt-in; see [`docs/EOD_DOWNTREND.md`](docs/EOD_DOWNTREND.md#deleting-generated-configs) |
| GET  | `/api/orders`        | Persisted `trade_order` rows |
| POST | `/api/orders/{id}/sync` | Re-fetch broker fill status for one order |
| POST | `/api/orders/purge`  | Clear ledger rows by entry-date (`dryRun` defaults to true) — see [`docs/ORDERS_AND_POSITIONS.md`](docs/ORDERS_AND_POSITIONS.md#purging-the-ledger) |
| GET  | `/api/charts/market-data` | Chart candle data (token-based or historical ICICI) — see [`docs/CHART_DASHBOARD.md`](docs/CHART_DASHBOARD.md) |
| POST | `/api/charts/historical/import/{spot,options}` | Import ICICI-style historical CSV — see [`docs/HISTORICAL_CHART_DATA_PLAN.md`](docs/HISTORICAL_CHART_DATA_PLAN.md) |

---

## Schedules

| Cron / fixed-delay | What it does | Defined in |
|---|---|---|
| `0 0 8 * * MON-FRI` (08:00 IST) | First-of-day login: `LoginOrchestrator.ensureLoggedIn()`. Silent if already valid. | `LoginScheduler.ensureSessionAtMarketOpen` |
| `fixedDelay = 60_000ms` | Heartbeat: auth probe + data probe; updates `broker_session`, drives Telegram on state transitions. | `LoginScheduler.heartbeat` |
| `0 16 9 * * MON-FRI` (09:16 IST) + `ApplicationReadyEvent` | Loads `trade_config` (+ instrument + `sma_timeframe`) for today into `SharedData.combinedDto`. | `TradeConfigScheduler` |
| `0 0/5 9-16 * * MON-FRI` (every 5 min, market-hours gated) | Fetch OHLC, compute SMAs, run strategies → trade signals. | `AnalysisScheduler` |
| `0 0/5 9-16 * * MON-FRI` (same tick, after Analysis) | Drain trade signals into `trade_order` rows + broker order calls. | `OrderScheduler` |
| `0 0/5 9-16 * * MON-FRI` (same tick, after Order) | Monitor OPEN `trade_order` rows; SL/target close. | `PositionScheduler` |
| `0 31 15 * * MON-FRI` (15:31 IST, live only) | Force-close leftover OPEN trades + Telegram end-of-day digest. | `DaySummaryScheduler` |

Full detail — including the market-hours gate that all three 5-min schedulers share, and how the backtest runner replays the exact same service methods — lives in [`docs/SCHEDULERS.md`](docs/SCHEDULERS.md).

### Heartbeat state machine
```
                ┌────────────┐
                │ NO_SESSION │
                └─────┬──────┘
                      │ login
                      ▼
       ┌──────────► OK ◄───────────┐
       │            │               │
recovery       data probe          recovery
       │       fails │               │
       │            ▼               │
       │        NO_DATA             │
       │            │               │
       │       data healthy         │
       │            │               │
       └────────────┘               │
                                    │
       AUTH_FAIL ◄─── auth probe fails (single auto-relogin attempt)
            │                       │
            └───── token healed ────┘
```

Telegram alerts:
- **Once** per transition into `AUTH_FAIL` / `HTTP_ERROR` (`alertSessionLost`)
- **Once** per transition into `NO_DATA` (`alertNoData`)
- **Once** per recovery to `OK` from a failure state (`alertRecovered`)
- **Zero** while a state persists (`OK→OK`, `AUTH_FAIL→AUTH_FAIL`, …)

---

## Database

Schema is managed by Liquibase; changesets in [`src/main/resources/db/changelog`](src/main/resources/db/changelog).

| Table | Purpose |
|---|---|
| `instrument`         | Tradable instruments / symbols |
| `instrument_details` | Per-instrument metadata |
| `trade_config`       | User-defined (or auto-generated, `source='AUTO_DOWNTREND'`) trade rules |
| `sma_timeframe`      | SMA settings per trade config |
| `sma_downtrend_rule` | Detection thresholds for the EOD downtrend auto-config generator |
| `trade_order`        | The order ledger — one row per open-and-close trade lifecycle |
| `broker_session`     | Persisted broker session + heartbeat (UNIQUE on `broker`) |
| `alert_state`        | Once-per-day Telegram gating (`DailyEventGuard`) |
| `market_data`        | Token-based candle store — written by the bulk options download, read by the chart dashboard's `TOKEN_BASED` source |
| `historical_spot_candles` / `historical_option_candles` | Natural-key candle store for imported ICICI CSV data, read by the chart dashboard's `HISTORICAL_ICICI` source |
| `options_data`       | Raw bulk-downloaded options metadata (Zerodha-only ingestion) |

To add a table, drop a new `00X_create_*.xml` file in the `db/changelog` folder and `<include>` it from `db.changelog-master.xml`. Current head is `023`; check the directory before picking the next number — `018` is already used twice.

---

## Adding a new broker

1. Create a package `com.moneymaker.broker.<name>`.
2. Add `<Name>LoginService implements BrokerLoginService`. Implement:
   - `getBroker()` / `getLoginUrl()` / `completeLogin()` / `validateSession()` / `logout()`
   - *(optional but recommended)* `fetchHeartbeatQuote()` returning a `HeartbeatResult` after pulling a known LTP.
3. Add a token-response POJO (use `@JsonNaming(SnakeCaseStrategy)` if the broker JSON is snake_case — see `ZerodhaTokenResponse`).
4. Add the broker to the `Broker` enum.
5. Append broker config keys + a `broker.<name>.enabled` flag in `application.properties`.
6. Spring auto-discovers the new adapter and `BrokerLoginManager` registers it on startup.

That's it — controllers, scheduler, and backtest pick the new adapter up automatically.

---

## Adding a new backtest stage

The pipeline today contains exactly one step: `LoginStep` (order 0). To add the next stage:

```java
@Component
@RequiredArgsConstructor
class DataDownloadStep implements BacktestStep {
    public String name() { return "data-download"; }
    public int order() { return 100; }   // 100, 200, 300… leaves room to splice
    public StepResult execute(BacktestContext ctx) {
        Instant start = Instant.now();
        // … do work, store in ctx.put(...)
        return StepResult.success(name(), "downloaded N bars", start);
    }
}
```

`BacktestRunner` discovers it via component scan, sorts by `order()`, and the backtest UI at `/backtest` renders the new row automatically. A failed step short-circuits the pipeline — subsequent steps are reported as `SKIPPED`.

---

## Telegram setup

1. Talk to **@BotFather**, create a bot, copy the token.
2. Add the bot to a chat (channel / group / DM). Use **@RawDataBot** or `getUpdates` to find the chat id (channels start with `-100`).
3. Set in `application.properties`:
   ```ini
   telegram.enabled=true
   telegram.bot-token=123456:ABC...
   telegram.chat-id=-100...
   ```
4. Restart. Trigger a login — you should see a `[OK] *ZERODHA* login successful` message.

If nothing arrives:
- Check the logs for `[Telegram] sendMessage failed` lines.
- Make sure the bot has permission to post in the target chat.
- The notifier is a no-op when the token / chat id is blank.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Login failed: null` after Zerodha redirect | Snake-case JSON not bound. Already fixed via `@JsonNaming(SnakeCaseStrategy)` on `ZerodhaTokenResponse`. |
| `Missing or empty field api_key` | `broker.zerodha.api-key` blank in `application.properties`. |
| `No login adapter registered for broker: GROWW` | `broker.groww.enabled=false`. Set it to `true` and provide credentials. |
| `loggedIn=true` but no market data on dashboard | Heartbeat status will flip to `NO_DATA`; check broker quota / market hours. |
| Telegram message every minute on a broken session | Should not happen (transition guard + single auto-relogin). If it does, check logs for `AUTH_FAIL transition for ...` vs `AUTH_FAIL persists for ...` lines. |
| `Liquibase: changeset already executed` after schema change | Add a *new* changeset file; never edit a previously deployed changeset. |

---

## Further reading

- [`docs/WORKFLOWS.md`](docs/WORKFLOWS.md) – every workflow end-to-end and which ones feed each other's data — start here for the system-level view.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) – package interactions, data flow.
- [`docs/LOGIN_FLOW.md`](docs/LOGIN_FLOW.md) – broker-by-broker auth sequences.
- [`docs/HEARTBEAT.md`](docs/HEARTBEAT.md) – two-tier probe + alert state machine.
- [`docs/BACKTESTING.md`](docs/BACKTESTING.md) – pipeline contract & extension recipe.
- [`docs/BACKTEST_PERFORMANCE.md`](docs/BACKTEST_PERFORMANCE.md) – speed-up phases & live-parity checklist.
- [`docs/SCHEDULERS.md`](docs/SCHEDULERS.md) – every `@Scheduled` bean, cadence, and mode-gating.
- [`docs/ORDERS_AND_POSITIONS.md`](docs/ORDERS_AND_POSITIONS.md) – order lifecycle, dedupe rules, trade-config admin.
- [`docs/NOTIFICATIONS.md`](docs/NOTIFICATIONS.md) – Telegram alert facade, dedupe strategies, backtest gate.
- [`docs/RATE_LIMITING.md`](docs/RATE_LIMITING.md) – Resilience4j wiring for broker calls.
- [`docs/EOD_DOWNTREND.md`](docs/EOD_DOWNTREND.md) – end-of-day SMA-downtrend auto-config generator.
- [`docs/CHART_DASHBOARD.md`](docs/CHART_DASHBOARD.md) – chart dashboard flow (both data sources).
- [`docs/HISTORICAL_CHART_DATA_PLAN.md`](docs/HISTORICAL_CHART_DATA_PLAN.md) – historical ICICI CSV import format & tables.
- [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) – instructions for AI coding agents working on this repo (also lists the proposed-but-not-started architecture roadmap docs).

