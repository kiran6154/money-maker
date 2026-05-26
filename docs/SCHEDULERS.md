# Schedulers

Every `@Scheduled` bean in the app, what it does, when it runs, and what it depends on. The same beans are also the entry points the backtest replays in tick order, so this page doubles as a "live vs backtest call graph" reference.

> **Why one page for all of them?** The schedulers are tightly coupled by data flow — `AnalysisScheduler` produces signals into `SharedData.tradeSignals`, `OrderScheduler` drains that queue and writes `trade_order` rows, `PositionScheduler` walks open `trade_order` rows and updates monitor columns. Documenting them separately would hide that pipeline. One page makes the order of operations and the contract between them explicit.

---

## Inventory

| Scheduler | Package | Cadence (live) | Replays in backtest? | Reads | Writes |
|---|---|---|---|---|---|
| [`LoginScheduler`](#loginscheduler) | `com.moneymaker.scheduler` | `0 0 8 * * MON-FRI` (08:00 IST) + `fixedDelay=60s` heartbeat | No (controller-driven) | `AppState`, `BrokerLoginManager` | `broker_session`, Telegram |
| [`TradeConfigScheduler`](#tradeconfigscheduler) | `com.moneymaker.scheduler` | `ApplicationReadyEvent` (live, weekday) + `0 16 9 * * MON-FRI` | Yes (per-day fetch) | `trade_config`, `instrument`, `sma_timeframe` | `SharedData.combinedDto` |
| [`AnalysisScheduler`](#analysisscheduler) | `com.moneymaker.scheduler` | `0 0/5 9-16 * * MON-FRI` | Yes (every backtest tick) | Broker historical data | `SharedData.strikeMarketDataByInstrumentAndInterval`, `SharedData.tradeSignals` |
| [`OrderScheduler`](#orderscheduler) | `com.moneymaker.scheduler` | `0 0/5 9-16 * * MON-FRI` | Yes (after `AnalysisScheduler` each tick) | `SharedData.tradeSignals` | `trade_order`, broker order endpoints, Telegram |
| [`PositionScheduler`](#positionscheduler) | `com.moneymaker.scheduler` | `0 0/5 9-16 * * MON-FRI` | Yes (after `OrderScheduler` each tick) | OPEN `trade_order` rows, broker LTP | `trade_order` (peak/last-monitored/exit), Telegram |

Live cadence stays inside NSE trading hours (`9-16` Mon-Fri). Off-hours the cron just doesn't fire.

---

## Pipeline (per tick)

```
                    ┌───────────────────────┐
                    │  TradeConfigScheduler │   loads SharedData.combinedDto from MySQL
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │   AnalysisScheduler   │   fetches OHLC, computes SMAs, runs strategies
                    └───────────┬───────────┘
                                │  appends → SharedData.tradeSignals (queue)
                                ▼
                    ┌───────────────────────┐
                    │    OrderScheduler     │   drains queue, dedupes, persists trade_order,
                    │                       │   delegates broker call via OrderPlacementFactory
                    └───────────┬───────────┘
                                │
                                ▼
                    ┌───────────────────────┐
                    │   PositionScheduler   │   walks OPEN rows, updates peak P&L,
                    │                       │   triggers SL/target close via OrderService
                    └───────────────────────┘
```

`LoginScheduler` runs independently on its own cadence — its job is to keep the broker session alive so the four pipeline schedulers above have a token to use.

---

## LoginScheduler

[`com.moneymaker.scheduler.LoginScheduler`](../src/main/java/com/moneymaker/scheduler/LoginScheduler.java)

- **08:00 IST cron** — first auto-login of the day. Calls `LoginOrchestrator.ensureLoggedIn()` for the active broker.
- **1-minute heartbeat (`fixedDelay = 60_000L`)** — runs auth probe + data probe, records `last_heartbeat_status` on `broker_session`, and emits transition-only Telegram alerts via `LoginScheduler.transitionAndNotify(prev, new)`.

Mode gating: live only. In `app.mode=backtest` the bean is registered (so manual probes from controllers still work) but the cron + heartbeat are inert. The backtest controller (`POST /api/backtest/login`) drives the orchestrator manually instead.

Detailed state machine and alert-rule matrix live in [HEARTBEAT.md](HEARTBEAT.md).

---

## TradeConfigScheduler

[`com.moneymaker.scheduler.TradeConfigScheduler`](../src/main/java/com/moneymaker/scheduler/TradeConfigScheduler.java)

- Loads `TradeConfig` + `Instrument` + `InstrumentDetails` + `SmaTimeframe` for a given trading date and assembles them into `List<TradeConfigCombinedDTO>`.
- Stashes the result on `SharedData.combinedDto` so downstream schedulers can read configs without hitting the DB on every tick.
- Has a `@Scheduled(cron = "0 16 9 * * MON-FRI")` job that does the live 09:16 IST load.
- Also has an `ApplicationReadyEvent` listener (`seedConfigsOnStartup`) that does the same load once at boot in `app.mode=live` on weekdays. This covers the case where the JVM is started after 09:16 — without it, `SharedData.combinedDto` would stay empty until the next day's 09:16 cron and the Analysis/Order/Position pipeline would idle. Idempotent with the cron (date-keyed cache + `DailyEventGuard` on the Telegram report). Skipped in backtest mode — `BacktestAnalysisService` manages `combinedDto` per-day in its own loop.

### Single entry point: `getConfigsForDate(date)`

All callers (live cron, backtest outer loop, backtest's `getUniqueTimePeriods`, controllers) **must** go through `getConfigsForDate(LocalDate)`. It is a date-keyed cache on top of the raw `fetchTradeConfigsByDate(date)` DB query — the same date never hits the DB more than once per JVM lifetime. Use `invalidateConfigsCache()` if you need to force a refresh; otherwise restart the JVM to pick up DB edits.

### Once-per-day report

After the live cron stores configs into `SharedData`, and at the top of each backtest day's outer loop, `reportConfigsForDay(date, configs)` runs. It logs an `INFO` line with each config's key fields (id, instrument, direction, target / SL, lot count, trade caps, timeframes) and emits a Telegram message with the same content. Fires **at most once per `(alertKey, date)` across JVM restarts** — gating is delegated to [`DailyEventGuard`](../src/main/java/com/moneymaker/state/DailyEventGuard.java) which writes to the `alert_state` table (Liquibase 012). See [NOTIFICATIONS.md](NOTIFICATIONS.md).

---

## AnalysisScheduler

[`com.moneymaker.scheduler.AnalysisScheduler`](../src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java)

- **Cron `0 0/5 9-16 * * MON-FRI`** — every 5 minutes during NSE hours.
- For each `TradeConfigCombinedDTO` and each timeframe in `SharedData.allTimeFrameMap` (`5min` / `10min` / `15min`):
  1. `MarketDataService.fetchHistoricalData(...)` for the underlying.
  2. `calculateStrikesForCandles(...)` to derive active strikes.
  3. For each active strike, fetch the option chain candles and stash them in `SharedData.strikeMarketDataByInstrumentAndInterval` keyed by `<instrumentToken>|<interval>|<optionType>|<strike>|<optionToken>|<itmDepth>|<otmDepth>`.
  4. Compute SMA columns on each list (50, 100, 200, 500 — see [`AllTimeFramedto`](../src/main/java/com/moneymaker/dto/AllTimeFramedto.java)).
- Then `runStrategies()` invokes every `Strategy` bean — currently `Strategy1` — which writes `TradeSignal`s into `SharedData.tradeSignals`.

Inside `MarketDataService.fetchHistoricalData` the call is wrapped by Resilience4j RateLimiter + Retry — see [RATE_LIMITING.md](RATE_LIMITING.md) for the throttle / retry policy and the planned cache layers.

In backtest mode, `BacktestAnalysisService.runForDateTime` calls `analysisScheduler.calculateIndicator(currentDateTime)` and then `analysisScheduler.runStrategies()` directly per tick — bypassing the cron.

---

## OrderScheduler

[`com.moneymaker.scheduler.OrderScheduler`](../src/main/java/com/moneymaker/scheduler/OrderScheduler.java)

- **Cron `0 0/5 9-16 * * MON-FRI`** — same cadence as `AnalysisScheduler`, intentionally. Each tick: analysis writes signals, orders drain them.
- Delegates to `OrderService.processOrders()` which:
  1. `SharedData.tradeSignals.poll()` until empty.
  2. For each signal, looks up the active broker via `OrderPlacementFactory` (selects `BACKTESTING` when `app.mode=backtest`, otherwise `broker.active`).
  3. Applies dedupe + intraday + transactionType rules — see [ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md).
  4. Persists a `TradeOrder` row, then fires the broker `place(order, config)` call. Broker order id is captured back onto the row.

Wraps each signal in `try/catch` so a single bad signal doesn't kill the rest of the queue.

In backtest, `BacktestAnalysisService` calls `orderScheduler.processOrders()` directly after `analysisScheduler.runStrategies()` each tick.

---

## PositionScheduler

[`com.moneymaker.scheduler.PositionScheduler`](../src/main/java/com/moneymaker/scheduler/PositionScheduler.java)

- **Cron `0 0/5 9-16 * * MON-FRI`** — same cadence again. Tick order: analysis → orders → positions.
- Delegates to `PositionService.processPositions()` which:
  1. `tradeOrderRepository.findByStatus("OPEN")`.
  2. For each open row, calls `PositionMonitorFactory.active().currentPrice(order)` — broker-specific live quote (Zerodha LTP, backtest cached candle, Groww/AngelOne TODO).
  3. Updates `peak_profit`, `peak_loss`, `last_monitored_price`, `last_monitored_at`.
  4. Compares unrealised P&L against `tradeConfig.target` / `tradeConfig.stopLoss`. On breach, calls `OrderService.closeManually(orderId, price, now, "TARGET" | "STOP_LOSS")` — full close path (DB update + broker exit + Telegram alert).

Fields and SL/target semantics documented in [ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md).

In backtest, `BacktestAnalysisService` calls `positionScheduler.processPositions()` directly after `orderScheduler.processOrders()` each tick.

---

## Backtest replay vs live cron

`BacktestAnalysisService.run(fromDate, toDate)` walks each backtest day in 5-minute increments and **calls the same scheduler methods directly**. The cron annotations are inert in `app.mode=backtest`. Per tick, the call order is:

1. `analysisScheduler.calculateIndicator(currentDateTime)`  (data fetch + SMAs)
2. `analysisScheduler.runStrategies()`                       (strategy → signals)
3. `orderScheduler.processOrders()`                         (signals → orders)
4. `positionScheduler.processPositions()`                   (open orders → monitoring)

At end of each backtest day the runner additionally calls `orderService.forceCloseOpenPositions(date, dateEnd)` to clean up any intraday position whose strike fell out of the active-strike set before the close-signal could fire.

End-of-run cleanup: `SharedData.tradeSignals.clear()` so a subsequent backtest / live tick starts with an empty queue.

---

## Adding a new scheduler

1. New `@Component` class in `com.moneymaker.scheduler`. Match the existing file shape: constructor-injected dependencies + `@Scheduled` method that delegates to a separate service.
2. Pick a cron that matches the operational window — `0 0/N 9-16 * * MON-FRI` for market-hours, `fixedDelay = …` for always-on probes.
3. Wrap the body in `try/catch` so an exception in one tick doesn't poison the schedule.
4. If you want backtest replay, **don't put the work in the `@Scheduled` method**. Put it on the underlying service so `BacktestAnalysisService` can call it directly per tick.
5. Wire any new persistence into `application.properties` for sensitivity (toggles), Liquibase for schema (numbered changeset), and `NotificationService` for alerts (use `sendIfChanged` / `sendThrottled` to avoid spam — see [NOTIFICATIONS.md](NOTIFICATIONS.md)).
6. **Update this page.** Every new scheduler gets a row in the inventory table and a section below.

---

## When *not* to add a scheduler

- A piece of work that runs once per HTTP request → put it in a service called from a controller. Don't schedule it.
- Something that needs to react to data flow → consider a producer/consumer pattern over `SharedData` collections (the existing `tradeSignals` queue) instead of polling.
- Reactions to broker state changes → use the heartbeat transition guard, not a separate poller.
