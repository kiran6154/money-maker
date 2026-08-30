# Heartbeat

How `LoginScheduler.heartbeat()` decides whether the broker connection is healthy, and when it is allowed to send a Telegram message.

> **Why two probes?** A valid auth token does not prove that market data is flowing. Brokers regularly accept your `validateSession()` call while quietly throttling or dropping LTP feeds. We probe both layers and surface the failure mode separately.

---

## Probes

| Probe | What it does | Failure → status |
|---|---|---|
| **Auth probe** | `BrokerLoginService.validateSession()` (cheap profile call) | `AUTH_FAIL` |
| **Data probe** | `BrokerLoginService.fetchHeartbeatQuote()` (NIFTY 50 LTP) | `NO_DATA` |
| Both succeed | — | `OK` |
| Network / 5xx | unhandled exception while probing | `HTTP_ERROR` |
| No active session | `AppState.currentSession().isEmpty()` | `NO_SESSION` |

Cadence: `@Scheduled(fixedDelay = 60_000L, initialDelay = 30_000L)` — roughly once a minute, **inside the heartbeat window only**.

---

## The heartbeat window

`MarketHoursService.isWithinHeartbeatWindow()` gates the tick: weekdays,
`app.market.heartbeat-start`..`app.market.heartbeat-end` inclusive, **07:50–15:40
IST** by default.

| Property | Default | What it is |
|---|---|---|
| `app.market.heartbeat-start` | `07:50` | First probe of the day. |
| `app.market.heartbeat-end` | `15:40` | Last probe of the day. |

Deliberately **wider than market hours on both sides**, and deliberately
absolute times rather than offsets from `app.market.open`/`close`:

- **The morning margin is the point of the lower bound.** Alerts fire only on
  *transitions*, so a token that died overnight has to be probed — and alerted —
  before the 08:00 login cron runs, or the operator finds out by watching the
  login fail. 07:50 leaves ten minutes. Expressed as an offset from the open,
  the boundary would silently drift past 08:00 the moment someone moved
  `app.market.open`, which is precisely the case where the margin matters.
- **The evening margin** covers the 15:31 `DaySummaryScheduler` sweep, which
  force-closes leftover positions through the broker and therefore wants a
  session it knows is alive.

Startup **refuses** a window that does not contain `[open, close]`
(`IllegalStateException` from `MarketHoursService.init`). The heartbeat is the
only thing that catches token death, so a gate that clipped even a minute of the
trading session would be a regression rather than a cleanup; the check makes
that unrepresentable rather than merely unlikely.

Outside the window nothing is probed at all — no session read, no broker call.
Before this (GAPS #3) the tick ran every minute forever, which cost one quote a
minute and could fire an `AUTH_FAIL` Telegram at 22:00 on a Friday about a
session nothing was going to use until Monday.

The gate lives on the `@Scheduled` wrapper; `LoginScheduler.runHeartbeat()`
underneath has no clock opinion and probes whenever called — the same
wall-clock-wrapper / replayable-method split the pipeline schedulers use.

---

## State machine

```
                ┌────────────┐
                │ NO_SESSION │
                └─────┬──────┘
                      │ login
                      ▼
       ┌──────────► OK ◄───────────┐
       │            │               │
       │       data probe          │
       │       fails                │
       │            ▼               │
       │        NO_DATA             │
       │            │               │
       │       data healthy         │
       │            │               │
       └────────────┘               │
                                    │
       AUTH_FAIL ◄─── auth probe fails (single auto-relogin attempt for TOTP brokers)
            │                       │
            └───── token healed ────┘

       HTTP_ERROR ◄── exception path; treated like AUTH_FAIL for alerting
```

---

## Telegram alert rules

`LoginScheduler.transitionAndNotify(newStatus, …)`:

```java
HeartbeatStatus prev = appState.getLastHeartbeatStatus();
appState.onHeartbeat(newStatus, tickAt, reason);
if (prev == newStatus) return;            // single transition guard
// dispatch alert based on newStatus
```

| Transition | Telegram |
|---|---|
| `* → OK` (steady) | 0 messages while OK persists |
| `OK → AUTH_FAIL` | 1× `alertSessionLost` + (TOTP brokers) at most 1× recovery message from the single `LoginOrchestrator.ensureLoggedIn()` attempt |
| `AUTH_FAIL → AUTH_FAIL` (every minute) | **0** — explicitly suppressed, both for the alert and for the auto-relogin call |
| `AUTH_FAIL → OK` | 1× `alertRecovered` |
| `OK → NO_DATA` | 1× `alertNoData` |
| `NO_DATA → NO_DATA` | 0 |
| `* → HTTP_ERROR` | 1× `alertSessionLost` |
| Manual login via UI | 1× `alertLoginSuccess` from the controller |
| 08:00 cron, session already valid | 0 |

---

## Auto-recovery

When the heartbeat detects an `AUTH_FAIL` transition (i.e. `prev != AUTH_FAIL`):

1. For **TOTP brokers** (`GROWW`, `ANGEL_ONE`) the scheduler invokes `LoginOrchestrator.ensureLoggedIn()` exactly once.
2. The orchestrator generates a fresh TOTP, calls `completeLogin()`, persists the new session, and emits `alertLoginSuccess` / `alertLoginFailed` via `NotificationService`.
3. For **OAuth brokers** (`ZERODHA`) the orchestrator returns `INTERACTIVE_REQUIRED` — the scheduler logs a hint, no further alert is sent (the `alertSessionLost` already fired).

Subsequent ticks while the session remains broken stay silent (`prev == newStatus`).

---

## Persisted columns (`broker_session`)

Every heartbeat tick updates:

- `last_heartbeat_at` — `Instant.now()`
- `last_heartbeat_status` — `OK | AUTH_FAIL | NO_DATA | HTTP_ERROR | NO_SESSION`
- `last_data_at` — last successful tick timestamp from the data probe
- `data_healthy` — `last_heartbeat_status == OK`
- `logged_in` — `false` when `last_heartbeat_status == AUTH_FAIL` (after the single recovery attempt fails)

These mirror the in-memory fields on `AppState` so a fresh JVM restart picks up the previous run's last known status.

---

## When to add a new heartbeat status

Don't, unless you have a genuinely new failure mode. The existing five statuses cover:

- `OK` — auth + data both healthy
- `AUTH_FAIL` — token rejected (re-login required)
- `NO_DATA` — token accepted, market data dead/throttled
- `HTTP_ERROR` — transient network / 5xx
- `NO_SESSION` — never logged in this run

If you do add one:
1. Extend `HeartbeatStatus` enum.
2. Add a case in `LoginScheduler.transitionAndNotify`.
3. Add an alert helper to `NotificationService` if a Telegram message is appropriate (otherwise leave it silent).

