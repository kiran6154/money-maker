# Plan: Persist Login + Heartbeat + Telegram Alerts (v2)

Persist broker logins to MySQL, expose a single global app-state holder (session + trade configs + orders + flags) accessible across the project, run a two-tier heartbeat (auth-validity + data-flow probe), and push Telegram alerts on any failure.

## Steps

### 1. Liquibase: persist sessions
Add `005_create_broker_session_table.xml` with columns `id`, `broker` (UNIQUE — only one broker active at a time), `user_id`, `access_token`, `refresh_token`, `public_token`, `login_at`, `expires_at`, `last_heartbeat_at`, `last_heartbeat_status` (`OK | AUTH_FAIL | NO_DATA | HTTP_ERROR`), `last_data_at`, `logged_in` (BOOLEAN), `raw_json` (TEXT). Register it in [db.changelog-master.xml](src/main/resources/db/changelog/db.changelog-master.xml).

### 2. Entity + repository
- `entity/BrokerSessionEntity.java` mirroring the table.
- `repository/BrokerSessionRepository.java`: `findByBroker(Broker)`, `findFirstByLoggedInTrue()`.

### 3. JPA-backed BrokerSessionStore
Refactor [`BrokerSessionStore`](src/main/java/com/moneymaker/login/service/BrokerSessionStore.java) to upsert by broker (single-row-per-broker, single-active-row overall): `save()` sets `loggedIn=true` and clears the flag on any other rows; `current()` returns the lone `loggedIn=true` row; `clear()` flips it. Convert to/from existing [`BrokerSession`](src/main/java/com/moneymaker/login/model/BrokerSession.java) DTO so adapters/controller stay unchanged.

### 4. Global AppState holder (replaces "just use BrokerSessionStore")
New `state/AppState.java` Spring bean acting as the single in-memory facade for runtime data: current `BrokerSession`, `loggedIn`, `lastHeartbeatAt`, `lastHeartbeatStatus`, cached active `List<TradeConfigCombinedDTO>`, recent `List<Order>` (placeholder until orders entity exists), `Broker activeBroker`. Backed by the JPA store + repositories; rebuilt on startup via `@PostConstruct`. Inject `AppState` anywhere instead of touching multiple stores. Exposes `isLoggedIn()`, `currentSession()`, `tradeConfigs()`, `orders()`, `markSessionInvalid(reason)`.

### 5. Telegram package
New `com.moneymaker.telegram`:
- `TelegramProperties` bound to `telegram.*` from [application.properties](src/main/resources/application.properties) (`telegram.enabled`, `telegram.bot-token`, `telegram.chat-id`) — values read straight from the property file per request.
- `TelegramNotifier` posts to `https://api.telegram.org/bot<token>/sendMessage` via `brokerRestTemplate`; no-op when `enabled=false` or token blank.
- `NotificationService` facade (`alertSessionLost`, `alertNoData`, `alertLoginFailed`, `alertLoginSuccess`) so other packages depend on the abstract notifier, not Telegram directly.

### 6. Two-tier heartbeat in `LoginScheduler`
Answering the concern: `validateSession()` only proves the auth token is accepted — it does **not** prove market data is flowing. So heartbeat runs **two probes** every ~2 min:

1. **Auth probe** — existing `validateSession()` (profile endpoint).
2. **Data probe** — fetch a known LTP/quote (e.g. NIFTY 50) via the broker's market-data endpoint; success requires HTTP 200 **and** a non-stale timestamp (within last N minutes during market hours). Add a `fetchHeartbeatQuote()` method to `BrokerLoginService` (default impl returns `OK` so non-trading brokers don't break) and implement it per broker (Zerodha `/quote/ltp`, Groww `/v1/live-data/ltp`, Angel One `/rest/secure/angelbroking/order/v1/getLtpData`).

Status mapping written to DB + `AppState`:
- auth fail → `AUTH_FAIL`, `loggedIn=false`, alert + auto-relogin (TOTP brokers).
- auth ok, data fail/stale → `NO_DATA`, `loggedIn=true` but `dataHealthy=false`, alert.
- both ok → `OK`, update `lastDataAt`.

Only alert on **state transitions** (don't spam Telegram every 2 min).

### 7. Wire-up & UI
- Add `telegram.*` keys to [application.properties](src/main/resources/application.properties).
- Update [`LoginController.sessionJson()`](src/main/java/com/moneymaker/controller/LoginController.java) and dashboard model to read from `AppState` and include `loggedIn`, `lastHeartbeatAt`, `lastHeartbeatStatus`, `dataHealthy`.
- Replace existing direct `BrokerSessionStore` reads in schedulers/controllers with `AppState` where it makes the call simpler.

## Decisions locked in
1. **Single broker at a time** → UNIQUE constraint on `broker_session.broker`, single `loggedIn=true` row enforced in `BrokerSessionStore.save()`. Switching brokers means flipping `broker.active` and re-logging in; no concurrent multi-broker flow.
2. **Global state holder** → `AppState` Spring bean (not a static class) holding session + trade configs + orders + flags; everything queries it.
3. **Telegram credentials** → read from `application.properties` (`telegram.bot-token`, `telegram.chat-id`, `telegram.enabled`).
4. **Heartbeat reliability** → `validateSession()` alone is insufficient (token can be valid while market data stalls); combined with a data-fetch probe and stale-timestamp check, with separate `AUTH_FAIL` vs `NO_DATA` statuses driving distinct Telegram alerts.

## Open items to confirm before coding
1. Heartbeat cadence: default **120 s** during 09:00–15:30 IST, **600 s** off-hours — OK?
2. Data-probe instrument: hard-code NIFTY 50 LTP, or pick the first active `TradeConfig` symbol? Recommend NIFTY (always tradable).
3. Stale-data threshold: 2 min during market hours. OK?
4. Should `clear()` (manual logout) also send a Telegram "logged out" message, or stay silent?
