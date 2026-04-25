# Login Flow

How each broker is authenticated, and what `LoginOrchestrator` does on top.

> **Rule of thumb:** never call `BrokerLoginService.completeLogin()` directly from feature code. Go through `LoginOrchestrator.ensureLoggedIn()` (or `forceLogin()` for an explicit re-auth). Both the live scheduler and the backtest pipeline rely on this.

---

## Common contract

All broker adapters implement `com.moneymaker.login.service.BrokerLoginService`:

```java
Broker getBroker();
String getLoginUrl();                         // hosted URL or our /login/manual page
BrokerLoginResponse completeLogin(BrokerLoginRequest req);
boolean validateSession(BrokerSession session);   // auth probe (cheap profile call)
HeartbeatResult fetchHeartbeatQuote(BrokerSession session);   // data probe (LTP)
void logout(BrokerSession session);
```

The result is always wrapped in a **broker-agnostic** `BrokerSession`:

| Field | Used for |
|---|---|
| `accessToken` | bearer / auth token for every REST call |
| `refreshToken` | Groww renewal; ignored by Zerodha; Angel One refresh |
| `publicToken` | Zerodha streaming; Angel One feed token |
| `userId` | required in headers for some brokers (e.g. Zerodha auth header) |
| `loginAt` / `expiresAt` | drives `BrokerSessionStore.isValid()` and the 08:00 cron |
| `valid` | quick boolean cached at login time |
| `raw` | the original payload as a `Map<String, Object>` (debugging only) |

---

## LoginOrchestrator

Single source of truth for "am I logged in, and if not, log me in".

```java
Outcome ensureLoggedIn();   // ALREADY_VALID | LOGGED_IN | INTERACTIVE_REQUIRED | FAILED
Outcome forceLogin();       // always re-auth; useful for tests / debug
```

Behaviour:
1. Resolve active adapter via `BrokerLoginManager.active()`.
2. If `AppState.currentSession()` exists and `validateSession()` returns true → `ALREADY_VALID`. **No Telegram.**
3. Else for TOTP brokers (Groww, Angel One) call `completeLogin()` with auto-generated TOTP. On success → `appState.onLoginSuccess(session)` + `notifier.alertLoginSuccess(...)`. On failure → `notifier.alertLoginFailed(...)`.
4. For OAuth brokers (Zerodha) → `INTERACTIVE_REQUIRED` (user must visit `/login/start`).

Used by:
- `LoginScheduler.ensureSessionAtMarketOpen()` (08:00 IST cron)
- `LoginScheduler.heartbeat()` (single recovery attempt per `AUTH_FAIL` transition)
- `backtesting.steps.LoginStep` (preflight for the backtest pipeline)
- Manual UI login does **not** route through the orchestrator — it goes straight through the adapter and writes back via `AppState.onLoginSuccess()`. The orchestrator picks the new session up on the next call.

---

## Per-broker flows

### Zerodha (Kite Connect) — OAuth-style

```
User → GET /login/start
        │
        ▼
  Redirect to https://kite.zerodha.com/connect/login?api_key=…&v=3
        │
        ▼  user enters credentials on Kite's page
        │
Kite → GET /login/callback?request_token=<rt>&action=login&status=success
        │
        ▼
LoginController → ZerodhaLoginService.completeLogin(req with rt)
        │
        ▼  POST https://api.kite.trade/session/token
            body: api_key, request_token, checksum=SHA256(api_key+rt+api_secret)
        │
        ▼  response (snake_case → bound via @JsonNaming)
            { data: { access_token, public_token, user_id, ... } }
        │
        ▼
BrokerSession (accessToken, publicToken, userId)
        │
        ▼
appState.onLoginSuccess(session) → broker_session table
```

- **Token lifetime:** ~24 h, expires daily ~06:00 IST. The user must log in again every trading day.
- **Header for downstream calls:** `Authorization: token <api_key>:<access_token>` + `X-Kite-Version: 3`.
- **Auth probe:** `GET /user/profile`.
- **Data probe:** `GET /quote/ltp?i=NSE:NIFTY 50`.

### Groww — TOTP

```
User → GET /login/start
        │
        ▼ (no hosted page) → /login/manual?broker=GROWW
        │
        ▼ user submits 6-digit TOTP (or leave blank → server generates from broker.groww.totp-secret)
        │
LoginController → GrowwLoginService.completeLogin(req with totp)
        │
        ▼  POST https://api.groww.in/v1/token/api/access
            body: { api_key, totp }
        │
        ▼  response (snake_case)
            { status, payload: { access_token, refresh_token, user_id, expires_in } }
        │
        ▼ BrokerSession (accessToken, refreshToken, expiresAt = now + expires_in)
```

- **Header:** `Authorization: Bearer <access_token>` + `X-API-KEY: <api_key>`.
- **Auth probe:** `GET /v1/user/profile`.
- **Data probe:** `GET /v1/live-data/ltp?segment=CASH&exchange=NSE&trading_symbol=NIFTY`.

### Angel One (SmartAPI) — TOTP

```
User → GET /login/start
        │
        ▼ /login/manual?broker=ANGEL_ONE
        │
        ▼ POST /rest/auth/angelbroking/user/v1/loginByPassword
            headers: X-PrivateKey=<api_key>, X-UserType=USER, X-SourceID=WEB, X-ClientLocalIP, X-ClientPublicIP, X-MACAddress
            body: { clientcode, password, totp }
        │
        ▼ response (camelCase JWT)
            { status, data: { jwtToken, refreshToken, feedToken } }
        │
        ▼ BrokerSession (accessToken=jwtToken, refreshToken, publicToken=feedToken)
```

- **Header for downstream calls:** `Authorization: Bearer <jwtToken>` + the same SmartAPI headers used for login.
- **Token lifetime:** ~24 h.
- **Auth probe:** `GET /rest/secure/angelbroking/user/v1/getProfile`.
- **Data probe:** `POST /rest/secure/angelbroking/order/v1/getLtpData` for NIFTY 50.

---

## Persistence

A single row per broker in `broker_session` (UNIQUE on `broker`). On `BrokerSessionStore.save()`:

1. Existing rows for *other* brokers have `logged_in` flipped to `false` (single-active-broker invariant).
2. Row for the current broker is upserted with new tokens + `logged_in=true` + `login_at=now`.
3. `AppState` is refreshed in-memory in the same call.

`BrokerSessionStore.clear()` (manual logout) flips `logged_in=false` but keeps the row for audit.

---

## Calling broker APIs from new code

Once logged in, downstream services should fetch the session from `AppState`:

```java
BrokerSession s = appState.currentSession()
    .filter(BrokerSession::isValid)
    .orElseThrow(() -> new IllegalStateException("Not logged in"));

// Build broker-appropriate headers — copy from the adapter's validateSession()
HttpHeaders h = new HttpHeaders();
h.set("Authorization", "token " + apiKey + ":" + s.getAccessToken());
h.set("X-Kite-Version", "3");
restTemplate.exchange(url, HttpMethod.GET, new HttpEntity<>(h), …);
```

Each adapter's `validateSession()` is the canonical example to copy when wiring orders / quotes / holdings calls.

