# Architecture

How the packages in `com.moneymaker.*` fit together. This is the "wiring diagram" companion to [`Readme.md`](../Readme.md). For deeper drills see [`LOGIN_FLOW.md`](LOGIN_FLOW.md), [`HEARTBEAT.md`](HEARTBEAT.md), [`BACKTESTING.md`](BACKTESTING.md).

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

