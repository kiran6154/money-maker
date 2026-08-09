# Architecture

How the packages in `com.moneymaker.*` fit together. This is the "wiring diagram" companion to [`Readme.md`](../Readme.md). For deeper drills see [`LOGIN_FLOW.md`](LOGIN_FLOW.md), [`HEARTBEAT.md`](HEARTBEAT.md), [`BACKTESTING.md`](BACKTESTING.md), and [`CHART_DASHBOARD.md`](CHART_DASHBOARD.md).

---

## High-level diagram

```
                       ┌──────────────────────┐
                       │ application.properties│
                       │  broker.active=…      │
                       │  telegram.*           │
                       └──────────┬───────────┘
                                  │ binds
                                  ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │  Spring context                                                  │
   │                                                                  │
   │   ┌──────────────┐    ┌──────────────────┐    ┌──────────────┐   │
   │   │ Thymeleaf UI │ ─► │ LoginController  │ ─► │ LoginOrches- │   │
   │   │ /, /login,   │    │ /api/session     │    │ trator       │   │
   │   │ /backtest    │    └──────┬───────────┘    └──────┬───────┘   │
   │   └──────────────┘           │                       │           │
   │                              │ resolves              │ delegates │
   │                              ▼                       ▼           │
   │                     ┌────────────────┐    ┌──────────────────┐   │
   │                     │ BrokerLogin-   │ ─► │ BrokerLoginSvc   │   │
   │                     │ Manager        │    │  · Zerodha       │   │
   │                     └────────────────┘    │  · Groww         │   │
   │                                            │  · AngelOne      │   │
   │                                            └──────┬───────────┘   │
   │                                                   │ saves         │
   │                                                   ▼               │
   │                                         ┌────────────────────┐    │
   │                                         │ BrokerSessionStore │    │
   │                                         │  → broker_session  │    │
   │                                         └────────┬───────────┘    │
   │                                                  │                │
   │                                                  ▼                │
   │                                      ┌────────────────────┐       │
   │   ┌──────────────────┐  reads/writes │ AppState           │       │
   │   │ LoginScheduler   │ ◄────────────►│ (single facade)    │       │
   │   │ 08:00 cron + 1m  │               └──────┬─────────────┘       │
   │   │ heartbeat        │                      │                     │
   │   └────┬─────────────┘                      │                     │
   │        │ on transition                      │                     │
   │        ▼                                    ▼                     │
   │   ┌────────────────────┐         ┌────────────────────┐           │
   │   │ NotificationService│ ──────► │ TelegramNotifier   │           │
   │   └────────────────────┘         └────────────────────┘           │
   │                                                                  │
   │   ┌──────────────────┐  uses                                     │
   │   │ BacktestRunner   │ ─────────────► LoginOrchestrator           │
   │   │  · LoginStep (0) │ (same auth code path as live)              │
   │   └──────────────────┘                                            │
   └──────────────────────────────────────────────────────────────────┘
```

---

## Layers

| Layer | Packages | Role |
|---|---|---|
| **Web / UI** | `controller`, `backtesting.*Controller`, `templates/`, `static/` | Thymeleaf pages + JSON endpoints. No business logic — every action delegates. |
| **Orchestration** | `login.service.LoginOrchestrator`, `backtesting.BacktestRunner`, `scheduler.LoginScheduler` | Deciders: when to log in, when to probe, when to alert. The only places that own a workflow. |
| **Adapters** | `broker.zerodha`, `broker.groww`, `broker.angelone` | Translate broker-native HTTP/JSON ↔ standard `BrokerSession`. Anything broker-specific is locked inside its own package. |
| **Domain models** | `login.model`, `entity`, `dto` | Plain Java records / DTOs / JPA entities. No Spring or HTTP types here. |
| **State / persistence** | `state.AppState`, `login.service.BrokerSessionStore`, `repository.*` | Single global runtime facade backed by JPA. Feature code injects `AppState`, never reaches into the repo directly. |
| **Notifications** | `telegram.*` | Outbound Telegram via `NotificationService` facade. `TelegramNotifier` is the only class that knows the API URL. |
| **Infrastructure** | `login.config`, `MoneyMakerApplication` | `RestTemplate` bean, `@ConfigurationProperties` binders, `@EnableScheduling`. |

---

## Cardinal data flow

### Login (live or backtest)
1. Caller invokes `LoginOrchestrator.ensureLoggedIn()`.
2. Orchestrator asks `BrokerLoginManager` for the active `BrokerLoginService`.
3. If `AppState.currentSession()` exists and `validateSession()` passes → `ALREADY_VALID`, exit.
4. Otherwise the adapter runs the broker-specific login (`completeLogin()`).
5. On success: orchestrator calls `appState.onLoginSuccess(session)` → `BrokerSessionStore.save()` writes `broker_session` (UNIQUE on `broker`, `logged_in=true`) and updates the in-memory facade.
6. Orchestrator emits **one** Telegram alert (success or failure) via `NotificationService`.

### Heartbeat (every 60 s)
1. `LoginScheduler.heartbeat()` reads the active session from `AppState`.
2. **Auth probe** → `BrokerLoginService.validateSession()`. Failure → `AUTH_FAIL`.
3. **Data probe** → `BrokerLoginService.fetchHeartbeatQuote()` (NIFTY 50 LTP). Failure → `NO_DATA`.
4. `transitionAndNotify(newStatus)` writes the status + last-tick timestamp to `AppState` and `broker_session`.
5. Telegram fires **only** on a state change (`prev != newStatus`).

### Backtest
1. UI/REST hits `BacktestRunner.run()`.
2. Runner sorts all `BacktestStep` beans by `order()` and executes sequentially.
3. `LoginStep` (order 0) calls `LoginOrchestrator.ensureLoggedIn()` — exactly what live does.
4. First failure → remaining steps marked `SKIPPED`; report returned to caller.

---

## Chart Dashboard

For the full request/response flow, repository usage, ATM logic, expiry rules,
frontend rendering behavior, and debugging checklist, see
[`CHART_DASHBOARD.md`](CHART_DASHBOARD.md).

### Routes

- Page route: `GET /charts/dashboard`
- Data API: `GET /api/charts/market-data`

### Request parameters

- `date`
- `dataSource`
- `indexSymbol`
- `chartType`
- `timeframe`
- `smaPeriods`

### Supported values

- `indexSymbol`: `NIFTY`, `BANKNIFTY`
- `dataSource`: `HISTORICAL_ICICI`, `TOKEN_BASED`
- `chartType`: `UNDERLYING`, `CE`, `PE`
- `timeframe`: `5m`, `10m`, `15m`
- `smaPeriods`: `20`, `50`, `100`, `200`, `500`

### Data source

- `TOKEN_BASED` uses the existing `market_data` and token metadata path.
- `HISTORICAL_ICICI` uses `historical_spot_candles` and `historical_option_candles`.
- `5m` uses raw 5-minute candles directly.
- `10m` and `15m` are aggregated from the 5-minute candles.
- SMA overlays are computed at runtime from 5-minute candle closes with
  prior-day lookback, then projected onto aggregated charts.

### Expiry and ATM rules

- `TOKEN_BASED` uses `expiry_dates` for expiry lookup.
- `HISTORICAL_ICICI` derives available expiries from `historical_option_candles`.
- The nearest expiry date greater than or equal to the selected date is chosen.
- Token-based NIFTY weekly expiry is Tuesday.
- Token-based BANKNIFTY weekly expiry is Wednesday.
- ATM rounding:
  - `NIFTY` -> nearest `50`
  - `BANKNIFTY` -> nearest `100`
- Token-based CE/PE resolution uses `instrument_details` metadata.
- Historical CE/PE resolution uses `stock_code`, `expiry_date`, `strike_price`, and `right`.

### No-data behavior

- Empty data is returned safely from the API when candles, expiry, or option metadata cannot be resolved.
- The UI shows a no-data message instead of failing.

### Example API requests

- `GET /api/charts/market-data?date=2024-06-06&dataSource=HISTORICAL_ICICI&indexSymbol=NIFTY&chartType=UNDERLYING&timeframe=5m&smaPeriods=20,50,100,200,500`
- `GET /api/charts/market-data?date=2024-06-06&dataSource=TOKEN_BASED&indexSymbol=NIFTY&chartType=CE&timeframe=10m&smaPeriods=20,50`
- `GET /api/charts/market-data?date=2024-06-06&dataSource=HISTORICAL_ICICI&indexSymbol=BANKNIFTY&chartType=PE&timeframe=15m&smaPeriods=20,50,100`

### Current limitations

- Token-based CE/PE results depend on correct `instrument_details` metadata.
- Token-based expiry lookup depends on populated `expiry_dates`.
- Historical results depend on imported ICICI spot and option CSV data.

---

## Invariants enforced by code

- **Single active broker.** UNIQUE constraint on `broker_session.broker` + `BrokerSessionStore.save()` clears `logged_in` on every other row.
- **Single auth path.** `LoginOrchestrator` is the only class that calls `BrokerLoginService.completeLogin()`.
- **Notifications are transition-only.** `LoginScheduler.transitionAndNotify` short-circuits when `prev == newStatus`. Auto-recovery is attempted exactly once per `AUTH_FAIL` entry.
- **Adapters never leak broker types.** `BrokerSession` is the only DTO crossing the package boundary. Broker-specific token POJOs (e.g. `ZerodhaTokenResponse`) live inside the broker package.

---

## Where to add new code

| Adding… | Goes in | Notes |
|---|---|---|
| New broker | `broker.<name>` | Implement `BrokerLoginService`. Add value to `Broker` enum + nested config in `BrokerProperties`. |
| New backtest stage | `backtesting.steps` | Implement `BacktestStep` with `order() ≥ 100`. Auto-discovered. |
| New alert type | `telegram.NotificationService` | Add a method; call it from a transition site. Never call `TelegramNotifier` directly from outside the package. |
| New persisted column | `db/changelog/00N_*.xml` + entity update | Never edit a committed changeset. |
| New runtime flag | `state.AppState` | Don't sprinkle flags across services. Centralise here so the UI / API has one source of truth. |

