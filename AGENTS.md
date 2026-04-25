# AGENTS.md

Operating instructions for any AI coding assistant working on this repository (Codex, Cursor, Continue, Aider, generic GPT-class agents…). The Claude-specific mirror is [`CLAUDE.md`](CLAUDE.md) — content is identical; only tone differs.

---

## TL;DR

This is a **Spring Boot 3 / Java 17** broker-automation app. Respect these invariants:

1. **One auth code path.** Every "make sure we're logged in" decision goes through `com.moneymaker.login.service.LoginOrchestrator`. Do not re-implement it in a scheduler, controller, or backtest step.
2. **One adapter per broker.** Implement `BrokerLoginService` in `com.moneymaker.broker.<name>`. Translate native responses into the standard `BrokerSession` DTO — do not leak broker-specific types into shared packages.
3. **Single global state holder.** Inject `com.moneymaker.state.AppState` rather than reaching into `BrokerSessionStore` or repositories from feature code.
4. **Notifications are transition-only.** `LoginScheduler` + `LoginOrchestrator` together guarantee one Telegram message per state change. Never put `notifier.alert*(...)` inside a loop or per-tick code path.
5. **Backtest preflight === live preflight.** The backtest pipeline (`com.moneymaker.backtesting`) reuses `LoginOrchestrator`. Do not introduce a separate "test login" flow.
6. **Liquibase only for schema.** Never edit a previously deployed changeset; always add a new `00X_*.xml` file under `src/main/resources/db/changelog/` and `<include>` it from the master.

---

## Repo layout

```
src/main/java/com/moneymaker/
├── broker/{angelone, groww, zerodha}     Per-broker adapters
├── controller/                           Thymeleaf + JSON controllers
├── backtesting/                          Pipeline runner + steps/
├── dto/                                  Cross-cutting view objects
├── entity/                               JPA entities
├── login/
│   ├── config/                           BrokerProperties, RestTemplate bean
│   ├── exception/                        BrokerLoginException
│   ├── model/                            Broker, BrokerSession, Heartbeat*
│   ├── service/                          BrokerLoginService, BrokerLoginManager,
│   │                                     BrokerSessionStore, LoginOrchestrator
│   └── util/TotpGenerator                RFC 6238
├── repository/                           Spring Data JPA
├── scheduler/                            LoginScheduler (08:00 cron + 1-min heartbeat)
├── state/AppState                        Global runtime facade
├── telegram/                             TelegramNotifier + NotificationService
└── util/

src/main/resources/
├── application.properties                broker.* and telegram.* keys
├── db/changelog/                         Liquibase changesets (00X_*.xml)
├── static/css/app.css                    Glassmorphism palette
└── templates/                            Thymeleaf views
```

For an end-user view see [`Readme.md`](Readme.md). For deeper dives see `docs/*.md`.

---

## Workflow

### Editing existing code
- **Read first.** Use file-read / search tools before editing — do not guess at structure.
- **Match style.** Lombok (`@Data`, `@RequiredArgsConstructor`, `@Slf4j`) is used heavily. Keep using it.
- **Keep packages tight.** New broker → `com.moneymaker.broker.<name>`. New backtest stage → `com.moneymaker.backtesting.steps`.
- **Compile after each meaningful edit:** `mvn -q -DskipTests compile`. IDE-only "never used" warnings on Spring beans are false positives — ignore them.

### Adding a broker
See [`Readme.md` → Adding a new broker](Readme.md#adding-a-new-broker). In short:
1. New package `com.moneymaker.broker.<name>` with `<Name>LoginService implements BrokerLoginService`.
2. Add a value to the `Broker` enum.
3. Add `broker.<name>.*` keys + nested config class in `BrokerProperties`.
4. If broker JSON is snake_case (Kite, Groww), annotate the response POJO with `@JsonNaming(SnakeCaseStrategy)` — otherwise tokens silently bind to null.
5. Override `fetchHeartbeatQuote()` with a real LTP probe so the heartbeat catches "token valid but data dead".

### Adding a backtest stage
See [`Readme.md` → Adding a new backtest stage](Readme.md#adding-a-new-backtest-stage). Pick `order() ≥ 100`; login is fixed at `0`. Failures short-circuit subsequent steps automatically.

### Adding a DB column / table
1. Create `src/main/resources/db/changelog/00N_<purpose>.xml`.
2. `<include>` it in `db.changelog-master.xml`.
3. Add / update the JPA entity with `@Column(name="…")`.
4. Update relevant repositories.
5. **Never** edit an existing committed changeset — Liquibase will refuse to start.

### Adding a Telegram alert type
Add a method to `NotificationService` (`alertSomething(...)`). Call it from the relevant state-transition site. Do **not** call `TelegramNotifier.send(...)` directly from outside `com.moneymaker.telegram`.

---

## What NOT to do

- ❌ Duplicate the auth flow. Always call `LoginOrchestrator.ensureLoggedIn()` (or `forceLogin()`).
- ❌ Store credentials, tokens, or chat-ids in source. Use `application.properties` (or `${ENV_VAR:default}` interpolation).
- ❌ Add `@Scheduled` methods that call `notifier.*` directly without a transition guard.
- ❌ Edit committed Liquibase changesets.
- ❌ Introduce broker-specific types (e.g. `ZerodhaTokenResponse`) into shared packages (`login.*`, `state.*`, `controller.*`). They belong inside `broker.<name>`.
- ❌ Reach into `BrokerSessionStore` from a feature package when `AppState` already exposes the data you need.

---

## Run / test commands (PowerShell)

```powershell
mvn -q -DskipTests compile              # compile only
mvn spring-boot:run                     # run on :8080 (requires MySQL)
mvn -DskipTests package                 # build fat jar
java -jar target/money-maker-1.0.0.jar
curl -X POST http://localhost:8080/api/backtest/run   # trigger backtest
curl http://localhost:8080/api/session                # inspect runtime state
```

---

## Glossary

| Term | Meaning |
|---|---|
| **Broker session** | Authenticated session with a broker. Persisted in `broker_session`, surfaced as `BrokerSession` DTO. |
| **Active broker** | The broker selected by `broker.active`. Only one is active at a time. |
| **Heartbeat** | The 1-min scheduler tick that runs an auth probe + a data probe and records `last_heartbeat_status` in `broker_session`. |
| **Transition** | A change in `HeartbeatStatus` (e.g. `OK → AUTH_FAIL`). Telegram alerts fire only on transitions. |
| **Backtest pipeline** | Ordered list of `BacktestStep` beans executed by `BacktestRunner`. Today: just `LoginStep` (order 0). |

---

## When in doubt

Re-read [`Readme.md`](Readme.md) and the relevant `docs/*.md` file. If a change spans more than three files, write a short plan first — maintainers prefer reviewing plans before refactors.

