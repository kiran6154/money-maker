# Money Maker

A Spring Boot 3 / Java 17 broker-automation backend that authenticates with Indian retail brokers (Zerodha Kite Connect, Groww, Angel One SmartAPI), keeps the session alive via a two-tier heartbeat, exposes a glassmorphism UI, and runs a sequenced backtest pipeline whose preflight is byte-for-byte identical to live trading.

> **Status:** active development. Login + heartbeat + Telegram alerting + a single-step backtest pipeline are implemented. Strategy / order placement / P&L stages are intentionally not wired yet.

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
| Backtest pipeline (login-only today; runner discovers more steps automatically) | `com.moneymaker.backtesting` |
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
│   ├── angelone                    Angel One SmartAPI adapter (TOTP login)
│   ├── groww                       Groww adapter (TOTP login)
│   └── zerodha                     Zerodha Kite Connect adapter (OAuth)
│
├── controller
│   └── LoginController             /, /login, /login/start, /login/callback,
│                                   /login/manual, /logout, /api/session
│
├── backtesting
│   ├── BacktestStep (interface)    Pipeline stage contract
│   ├── BacktestRunner              Auto-discovers steps, sorts by order(), runs in sequence
│   ├── BacktestContext             Shared mutable bag passed between steps
│   ├── BacktestReport / StepResult JSON-friendly outcomes
│   ├── BacktestController          POST /api/backtest/run
│   ├── BacktestViewController      GET /backtest (Thymeleaf)
│   └── steps
│       └── LoginStep               order=0; the only step today
│
├── dto
│   └── TradeConfigCombinedDTO      Aggregated trade-config view
│
├── entity
│   ├── BrokerSessionEntity         broker_session table
│   ├── Instrument / InstrumentDetails / TradeConfig / SmaTimeframe
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
├── repository
│   ├── BrokerSessionRepository
│   └── TradeConfigRepository
│
├── scheduler
│   ├── LoginScheduler              08:00 cron + 1-min heartbeat
│   ├── IndicatorScheduler          (placeholder — strategy work)
│   ├── PositionScheduler           (placeholder)
│   └── TradeConfigScheduler        (placeholder)
│
├── state
│   └── AppState                    Global runtime facade (loggedIn flag, heartbeat,
│                                   trade-config cache, orders cache)
│
├── telegram
│   ├── TelegramProperties          telegram.* binder
│   ├── TelegramNotifier            Low-level /sendMessage client
│   └── NotificationService         alertLoginSuccess/Failed/SessionLost/NoData/Recovered
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

### JSON
| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/session`       | `{ activeBroker, loggedIn, dataHealthy, lastHeartbeatStatus, lastHeartbeatAt, lastDataAt, session: {...} }` |
| POST | `/api/backtest/run`  | Run the backtest pipeline; returns `BacktestReport` |

---

## Schedules

| Cron / fixed-delay | What it does | Defined in |
|---|---|---|
| `0 0 8 * * MON-FRI` (08:00 IST) | First-of-day login: `LoginOrchestrator.ensureLoggedIn()`. Silent if already valid. | `LoginScheduler.ensureSessionAtMarketOpen` |
| `fixedDelay = 60_000ms` | Heartbeat: auth probe + data probe; updates `broker_session`, drives Telegram on state transitions. | `LoginScheduler.heartbeat` |

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
| `trade_config`       | User-defined trade rules |
| `sma_timeframe`      | SMA settings per trade config |
| `broker_session`     | Persisted broker session + heartbeat (UNIQUE on `broker`) |

To add a table, drop a new `00X_create_*.xml` file in the `db/changelog` folder and `<include>` it from `db.changelog-master.xml`.

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

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) – package interactions, data flow.
- [`docs/LOGIN_FLOW.md`](docs/LOGIN_FLOW.md) – broker-by-broker auth sequences.
- [`docs/HEARTBEAT.md`](docs/HEARTBEAT.md) – two-tier probe + alert state machine.
- [`docs/BACKTESTING.md`](docs/BACKTESTING.md) – pipeline contract & extension recipe.
- [`CLAUDE.md`](CLAUDE.md) / [`AGENTS.md`](AGENTS.md) – instructions for AI coding agents working on this repo.

