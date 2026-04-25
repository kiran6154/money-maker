# CLAUDE.md

Operating instructions for **Claude Code** (and any other Claude-family agent) working on this repository.
> If you are a different AI assistant, also read [`AGENTS.md`](AGENTS.md) — it carries the same content with tool-agnostic phrasing.

---

## TL;DR

This is a **Spring Boot 3 / Java 17** broker-automation app. The architecture is opinionated — please respect these invariants:

1. **One auth code path.** All broker login decisions go through `com.moneymaker.login.service.LoginOrchestrator`. Never re-implement the "ensure we're logged in" logic in a scheduler, controller, or backtest step. Call the orchestrator instead.
2. **One adapter per broker.** Implement `BrokerLoginService` in `com.moneymaker.broker.<name>`. Translate native responses into the standard `BrokerSession` DTO; don't leak broker-specific types upward.
3. **Single global state holder.** Inject `com.moneymaker.state.AppState` rather than touching `BrokerSessionStore` or DB repositories directly when reading runtime status (logged-in flag, heartbeat, cached configs).
4. **Notifications are transition-only.** `LoginScheduler` and `LoginOrchestrator` together guarantee one Telegram message per state change. Don't add `notifier.alert*(...)` calls inside loops or per-tick code paths.
5. **Backtest preflight === live preflight.** The backtest pipeline (`com.moneymaker.backtesting`) reuses `LoginOrchestrator`. Do not add a separate "test login" path.
6. **Liquibase only for schema.** Never edit a previously deployed changeset; always add a new `00X_*.xml` file under `src/main/resources/db/changelog/` and include it from the master.

---

## Repo layout (high level)

```
src/main/java/com/moneymaker/
├── broker/{angelone, groww, zerodha}     Per-broker adapters (BrokerLoginService impls)
├── controller/                            Thymeleaf + JSON controllers
├── backtesting/                           Pipeline runner + steps/
├── dto/                                   Cross-cutting view objects
├── entity/                                JPA entities (broker_session, trade_config, …)
├── login/
│   ├── config/                            BrokerProperties, RestTemplate bean
│   ├── exception/                         BrokerLoginException
│   ├── model/                             Broker, BrokerSession, Heartbeat*
│   ├── service/                           BrokerLoginService, BrokerLoginManager,
│   │                                      BrokerSessionStore, LoginOrchestrator
│   └── util/TotpGenerator                 RFC 6238
├── repository/                            Spring Data JPA
├── scheduler/                             LoginScheduler (08:00 cron + 1-min heartbeat)
├── state/AppState                         Global runtime facade
├── telegram/                              TelegramNotifier + NotificationService facade
└── util/

src/main/resources/
├── application.properties                 broker.* and telegram.* keys live here
├── db/changelog/                          Liquibase changesets (numbered 00X_*.xml)
├── static/css/app.css                     Glassmorphism palette
└── templates/                              Thymeleaf views (index, login, manual-login, backtest)
```

For an end-user view of the same map see [`Readme.md`](Readme.md). For deeper dives see `docs/*.md`.

---

## How to make changes

### Editing existing code
- **Read first.** Use the file-read / search tools before editing. Don't guess at structure.
- **Match style.** Lombok (`@Data`, `@RequiredArgsConstructor`, `@Slf4j`) is in heavy use — keep using it.
- **Keep packages tight.** New broker → `com.moneymaker.broker.<name>`. New backtest stage → `com.moneymaker.backtesting.steps`.
- **Compile after each meaningful edit.** Run:
  ```powershell
  mvn -q -DskipTests compile
  ```
  IDE-only "never used" warnings on Spring beans are false positives — ignore them.

### Adding a broker
Follow the recipe in [`Readme.md` → Adding a new broker](Readme.md#adding-a-new-broker). In short:
1. New package `com.moneymaker.broker.<name>` with `<Name>LoginService implements BrokerLoginService`.
2. Add a value to the `Broker` enum.
3. Add `broker.<name>.*` keys + nested config class in `BrokerProperties`.
4. If the broker JSON is snake_case (Kite, Groww), annotate the response POJO with `@JsonNaming(SnakeCaseStrategy)` — otherwise tokens silently bind to null.
5. Override `fetchHeartbeatQuote()` with a real LTP probe so the heartbeat catches "token valid but data dead".

### Adding a backtest stage
Follow [`Readme.md` → Adding a new backtest stage](Readme.md#adding-a-new-backtest-stage). Pick an `order()` value `≥ 100`; login is fixed at `0`. Failures short-circuit subsequent steps automatically.

### Adding a DB column / table
1. Create `src/main/resources/db/changelog/00N_<purpose>.xml`.
2. Include it in `db.changelog-master.xml`.
3. Add / update the JPA entity with `@Column(name="…")`.
4. Update relevant repositories.
5. **Never** edit an existing committed changeset — Liquibase will refuse to start.

### Adding a Telegram alert type
Add a method to `NotificationService` (`alertSomething(...)`). Call it from the relevant state-transition site. Do **not** call `TelegramNotifier.send(...)` directly from outside `com.moneymaker.telegram` — that bypasses the abstraction.

---

## What NOT to do

- ❌ Do not duplicate the auth flow. Always call `LoginOrchestrator.ensureLoggedIn()` (or `forceLogin()`).
- ❌ Do not store credentials, tokens, or chat-ids in source. Use `application.properties` (or `${ENV_VAR:default}` interpolation).
- ❌ Do not add `@Scheduled` methods that call `notifier.*` directly without a transition guard.
- ❌ Do not edit committed Liquibase changesets.
- ❌ Do not introduce broker-specific types (e.g. `ZerodhaTokenResponse`) into shared packages (`login.*`, `state.*`, `controller.*`). They belong inside `broker.<name>`.
- ❌ Do not reach into `BrokerSessionStore` from a feature package when `AppState` already exposes the data you need.

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
curl -X POST http://localhost:8080/api/backtest/run

# inspect runtime state
curl http://localhost:8080/api/session
```

---

## Glossary

| Term | Meaning |
|---|---|
| **Broker session** | An authenticated session with a broker. Persisted in `broker_session`, surfaced as `BrokerSession` DTO. |
| **Active broker** | The broker selected by `broker.active`. Only one is active at a time. |
| **Heartbeat** | The 1-min scheduler tick that runs an auth probe + a data probe and records `last_heartbeat_status` in `broker_session`. |
| **Transition** | A change in `HeartbeatStatus` (e.g. `OK → AUTH_FAIL`). Telegram alerts only fire on transitions. |
| **Backtest pipeline** | The ordered list of `BacktestStep` beans executed by `BacktestRunner`. Today: just `LoginStep` (order 0). |

---

## When in doubt

Re-read [`Readme.md`](Readme.md) and the relevant `docs/*.md` file. If a change spans more than three files, write a short plan first (the user prefers reviewing plans before refactors).

