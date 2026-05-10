# Notifications & Telegram Alerts

How the app surfaces important events (login, broker outage, orders) to Telegram without flooding the channel.

> **Why this exists.** Anything important enough to wake somebody up — login broken, broker rejecting orders, market-data API down — needs a push notification. But the same code paths fire on a loop (every minute heartbeat, every tick fetch, every retried call), so a naive "send on every failure" turns the channel into a denial-of-service. We need a single notification facade that can tell *transitions* from *steady-state* and a *new event* from a *repeat of the last one*.

---

## Where calls go through

```
feature code (LoginScheduler, OrderService, MarketDataService, broker adapters)
                        │
                        ▼
       com.moneymaker.telegram.NotificationService           ← single facade
                        │
            sendIfChanged / sendThrottled
                        │
                        ▼
                TelegramNotifier (HTTP)
```

Other packages depend on `NotificationService`, never on `TelegramNotifier` or the bot HTTP API directly. That gives us:

- One place to add a second channel later (Slack, email, push) without touching call sites.
- One place to enforce dedupe / throttling.
- One place to apply the backtest-mode suppression below.

---

## Wired alerts

| Event | Method | Dedupe strategy | Backtest behaviour |
|---|---|---|---|
| Login success | `alertLoginSuccess(broker, userId)` | Call site (controller / orchestrator) only fires once per success | Fires |
| Login failure | `alertLoginFailed(broker, reason)` | Call site fires once per failed attempt | Fires |
| Session lost (auth fail) | `alertSessionLost(broker, status, reason)` | `LoginScheduler.transitionAndNotify` — fires only on `OK → AUTH_FAIL` | Fires |
| No data (heartbeat) | `alertNoData(broker, reason)` | Same transition guard | Fires |
| Heartbeat recovered | `alertRecovered(broker)` | Same transition guard | Fires |
| Historical-data API failing | `alertMarketDataDown(reason)` | `sendIfChanged("market-data", …)` — same reason fires once until recovery | **Suppressed** |
| Historical-data API recovered | `alertMarketDataUp()` | Fires only if a "down" alert was previously sent | **Suppressed** |
| Order opened | `alertOrderOpened(TradeOrder)` | None — each order id is unique | **Suppressed** |
| Order closed by signal | `alertOrderClosed(TradeOrder)` | None | **Suppressed** |
| Order force-closed at EOD | `alertOrderForceClosed(TradeOrder)` | None | **Suppressed** |
| Broker rejected an order | `alertOrderRejected(broker, orderId, reason)` | `sendIfChanged("order-rejected:<broker>", …)` — identical-reason loops stay quiet | **Suppressed** |

The "backtest behaviour" column reflects `app.mode=backtest`. Login and heartbeat alerts still fire because they're rare and useful in both modes; the noisy event types (per-order, market-data spam) are off so a multi-day replay can't blow up the chat.

---

## Two general-purpose helpers

Both are exposed publicly on `NotificationService` so any feature can use them directly when adding a new alert.

### `sendIfChanged(dedupeKey, message)` — transition style

```java
private final Map<String, String> dedupeState = new ConcurrentHashMap<>();

public void sendIfChanged(String dedupeKey, String message) {
    if (Objects.equals(message, dedupeState.get(dedupeKey))) return;
    dedupeState.put(dedupeKey, message);
    telegram.send(message);
}
```

Use this when the message body itself encodes the state — same body = same state = no resend. Pair with a paired "recovered" call that checks `dedupeState.containsKey(dedupeKey)` before sending the all-clear:

```java
public void alertMarketDataUp() {
    if (!dedupeState.containsKey("market-data")) return;   // never went down — nothing to clear
    dedupeState.remove("market-data");
    telegram.send("[RECOVERED] Market-data API back online …");
}
```

### `sendThrottled(dedupeKey, cooldown, message)` — quiet-period style

```java
private final Map<String, Instant> throttleState = new ConcurrentHashMap<>();

public void sendThrottled(String dedupeKey, Duration cooldown, String message) {
    Instant last = throttleState.get(dedupeKey);
    Instant now = Instant.now();
    if (last != null && Duration.between(last, now).compareTo(cooldown) < 0) return;
    throttleState.put(dedupeKey, now);
    telegram.send(message);
}
```

Use this when the message varies slightly each call (e.g. embeds the current timestamp) so `sendIfChanged` can't dedupe it, but you still want a minimum quiet period between sends.

Both maps are `ConcurrentHashMap` and live on the singleton `NotificationService`, so dedupe state is JVM-wide. Restart resets it — usually desirable; first failure after a restart re-alerts.

---

## Backtest-mode suppression

A single master gate lives inside `TelegramNotifier.send()`:

```java
public TelegramNotifier(TelegramProperties properties,
                        RestTemplate brokerRestTemplate,
                        @Value("${app.mode:live}") String appMode) {
    this.backtestMode = "backtest".equalsIgnoreCase(...);
    ...
}

public void send(String message) {
    if (!properties.isEnabled()) return;                                  // master switch
    if (backtestMode && !properties.isBacktestEnabled()) return;          // backtest gate
    ...
}
```

So when `app.mode=backtest` and `telegram.backtest-enabled=false` (the default), **every** alert in `NotificationService` becomes a no-op — including login and heartbeat. Set `telegram.backtest-enabled=true` to let alerts through during a backtest run (useful when validating the bot setup or stepping through a single day).

This means feature code calls alert methods unconditionally. The decision of whether the message actually goes out is made at the chokepoint, controlled by configuration.

| `app.mode` | `telegram.enabled` | `telegram.backtest-enabled` | Alerts fire? |
|---|---|---|---|
| live | true | (any) | Yes |
| live | false | (any) | No |
| backtest | true | true | Yes |
| backtest | true | false | No (default) |
| backtest | false | (any) | No |

---

## Where each alert is wired

- `LoginController` / `LoginScheduler` — login + heartbeat (existing, unchanged).
- [`OrderService.openOrder`](../src/main/java/com/moneymaker/order/service/OrderService.java) → `alertOrderOpened`.
- [`OrderService.closeOrder`](../src/main/java/com/moneymaker/order/service/OrderService.java) → `alertOrderClosed`.
- [`OrderService.forceCloseOpenPositions`](../src/main/java/com/moneymaker/order/service/OrderService.java) → `alertOrderForceClosed` per row.
- [`MarketDataService.fetchHistoricalData`](../src/main/java/com/moneymaker/market/service/MarketDataService.java) → `alertMarketDataUp` on success, `alertMarketDataDown` on non-rate-limit failure (after Resilience4j retries — see [RATE_LIMITING.md](RATE_LIMITING.md)).
- [`ZerodhaOrderPlacementService.place`](../src/main/java/com/moneymaker/broker/zerodha/ZerodhaOrderPlacementService.java) → `alertOrderRejected` on `KiteException` / `IOException`.

Groww and Angel One adapters are still skeletons; when their REST clients land, add the same `notifier.alertOrderRejected(NAME, orderId, reason)` call in the catch block — same shape, same key, automatic dedupe.

---

## How to add a new alert

1. **Decide the dedupe shape.**
   - One-shot per event (each event is unique, e.g. order id) → no dedupe, just `telegram.send(...)`.
   - Transition (down/up state) → `sendIfChanged` paired with a recovery method that checks `dedupeState.containsKey(...)`.
   - Quiet period (message varies, want quiet for N minutes) → `sendThrottled`.

2. **Add a method on `NotificationService`** following the existing pattern:
   ```java
   public void alertMyThing(MyDto x) {
       if (!liveMode) return;            // optional — only if backtest could spam this
       sendIfChanged("my-thing-key",
           String.format("[ALERT] my thing: %s", safe(x.toString())));
   }
   ```

3. **Call it from the feature code.** Don't wrap it in `if (telegram.enabled) {…}` — the notifier already handles the disabled case (`telegram.enabled=false` in `application.properties` means `TelegramNotifier.send` is a no-op).

4. **Pick a dedupe key carefully.** Too narrow (e.g. include orderId) → no dedupe. Too broad (e.g. just `"orders"`) → drops different-reason events. The right level is "the bucket where two messages mean the same thing operationally". For broker rejections, that's "this broker is rejecting" → `order-rejected:<broker>`.

---

## Configuration

```properties
# Set telegram.enabled=true and provide bot-token / chat-id to actually send.
telegram.enabled=false
telegram.bot-token=
telegram.chat-id=
telegram.api-base-url=https://api.telegram.org

# app.mode=backtest suppresses market-data and per-order alerts (login/heartbeat
# still fire). app.mode=live (default) lets everything through.
app.mode=backtest
```

When `telegram.enabled=false` everything degrades to debug-level log lines — the rest of the app doesn't change behaviour, you just don't get push notifications.

---

## Trade-offs and decisions

- **Why a single facade?** So adding Slack later, or rate-limiting Telegram itself, is a one-class change. Call sites stay broker-agnostic the same way they're auth-agnostic via `LoginOrchestrator`.
- **Why dedupe inside the notifier instead of at call sites?** A few existing alerts (heartbeat) already dedupe at the call site via the transition guard, and that's fine because the state machine lives there anyway. New alerts (market-data, broker rejections) don't have a state machine in their feature code — adding one just for telegram is overkill. The notifier-level dedupe is cheap (`ConcurrentHashMap.get`) and keeps feature code call-and-forget.
- **Why suppress in backtest?** A 5-day backtest with 5-min ticks across 50 strikes and 4 timeframes can produce thousands of order events in seconds. That breaks Telegram (rate-limit on send) and trains people to ignore the channel. Login + heartbeat are useful even during a backtest because they tell you the broker session is alive while you replay.
- **Why JVM-wide dedupe instead of persisted?** Restart-resets-state is the right default for an on-call alerting layer. If a process is restarted, you *want* the next failure to re-alert because operators may not have seen the previous one.
- **No tests added.** The alert-decision logic is small (`equals`, map check) and the failure mode (extra Telegram calls) is benign. If you want coverage, the highest-leverage tests are: (a) `sendIfChanged` collapses repeats, (b) `alertMarketDataUp` is a no-op without a prior down, (c) `liveMode=false` skips the right methods.

---

## When to add a new dedupe key

Don't, unless the new key represents a genuinely new state machine. The existing keys are:

- `"market-data"` — historical-data API up/down.
- `"order-rejected:<broker>"` — one bucket per broker for placement rejections.

If you add one, document it in this file (the table at the top) and pick a colon-namespaced name (`feature:scope`) so the keyspace stays organised.
