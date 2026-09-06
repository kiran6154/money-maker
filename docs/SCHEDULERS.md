# Schedulers

Every `@Scheduled` bean in the app, what it does, when it runs, and what it depends on. The same beans are also the entry points the backtest replays in tick order, so this page doubles as a "live vs backtest call graph" reference.

> **Why one page for all of them?** The schedulers are tightly coupled by data flow — `AnalysisScheduler` produces signals into `SharedData.tradeSignals`, `OrderScheduler` drains that queue and writes `trade_order` rows, `PositionScheduler` walks open `trade_order` rows and updates monitor columns. Documenting them separately would hide that pipeline. One page makes the order of operations and the contract between them explicit.

---

## Inventory

| Scheduler | Package | Cadence (live) | Mode gate on the cron | Replays in backtest? | Reads | Writes |
|---|---|---|---|---|---|---|
| [`LoginScheduler`](#loginscheduler) | `com.moneymaker.scheduler` | `0 0 8 * * MON-FRI` (08:00 IST) + `fixedDelay=60s` heartbeat (07:50–15:40 window) + `0 15 9 * * MON-FRI` (09:15 IST) options fetch | Bean-level `@ConditionalOnProperty(app.mode=live)` — not registered at all in backtest | No (controller-driven) | `AppState`, `BrokerLoginManager` | `broker_session`, `market_data`/`options_data`, Telegram |
| [`TradeConfigScheduler`](#tradeconfigscheduler) | `com.moneymaker.scheduler` | `ApplicationReadyEvent` (live, weekday) + `0 16 9 * * MON-FRI` | Startup seed: live only. **09:16 cron: none** — see the warning under [Mode + market-hours gating](#mode--market-hours-gating) | Yes (per-day fetch) | `trade_config` (incl. `strategy_ids`), `instrument`, `sma_timeframe` | `SharedData.combinedDto` |
| [`AnalysisScheduler`](#analysisscheduler) | `com.moneymaker.scheduler` | `0 0/5 9-16 * * MON-FRI`, gated by [`MarketHoursService.isOpenNow()`](#mode--market-hours-gating) | `analyzeMarketData()` no-ops in backtest | Yes (every backtest tick) | Broker historical data | `SharedData.strikeMarketDataByInstrumentAndInterval`, `SharedData.tradeSignals` |
| [`OrderScheduler`](#orderscheduler) | `com.moneymaker.scheduler` | `0 0/5 9-16 * * MON-FRI`, gated by [`MarketHoursService.isOpenNow()`](#mode--market-hours-gating) | `scheduledTick()` no-ops in backtest | Yes (after `AnalysisScheduler` each tick) | `SharedData.tradeSignals` | `trade_order`, broker order endpoints, Telegram |
| [`PositionScheduler`](#positionscheduler) | `com.moneymaker.scheduler` | `0 0/5 9-16 * * MON-FRI`, gated by [`MarketHoursService.isOpenNow()`](#mode--market-hours-gating) | `scheduledTick()` no-ops in backtest | Yes (after `OrderScheduler` each tick) | OPEN `trade_order` rows, broker LTP | `trade_order` (peak/last-monitored/exit), Telegram |
| [`DaySummaryScheduler`](#daysummaryscheduler) | `com.moneymaker.scheduler` | `0 31 15 * * MON-FRI` (15:31 IST), live only | `runEndOfDay()` returns unless `app.mode=live` | No (`BacktestAnalysisService` force-closes per day itself) | `trade_order`, `trade_config` (lot quantity), `MarketHoursService` | Force-closed `trade_order` rows **+ live broker exits**, Telegram digest |

Live cadence stays inside NSE trading hours (`9-16` Mon-Fri). Off-hours the cron just doesn't fire.

### Mode + market-hours gating

Both gates are **wall-clock concerns**, and both live at the `@Scheduled` entry point — never on the service method underneath it. That is invariant 8 in practice: the replay calls the method underneath directly with a simulated timestamp, so a mode or clock check placed there would silence the backtest itself.

```java
@Scheduled(cron = "0 0/5 9-16 * * MON-FRI")
public void scheduledTick() {                    // wall-clock wrapper: gates only
    if ("backtest".equalsIgnoreCase(appMode)) {
        return;                                  // the simulated clock drives the pipeline
    }
    if ("live".equalsIgnoreCase(appMode) && !marketHours.isOpenNow()) {
        return;                                  // outside the configured trading window
    }
    processOrders();                             // replayable: no mode branch, ever
}
```

- **The backtest gate** (`GAPS.md` #4, 2026-08-31) stops the wall clock from running a second pipeline alongside a replay. Before it, the market-hours guard was the only gate and it short-circuits *only in live mode* — so in `app.mode=backtest` these three crons ran their bodies in full, on the scheduler thread, against the same statics the replay was using. The mode string comes from `@Value("${app.mode:live}")`, the same key `TelegramNotifier`'s backtest suppression reads.
- **The market-hours gate** is unchanged. [`MarketHoursService`](../src/main/java/com/moneymaker/market/service/MarketHoursService.java) is the single source of truth for the trading window — default `09:15–15:30 IST, MON-FRI`, overridable via `app.market.open` / `app.market.close` / `app.market.timezone`. It applies in live mode only; the replay supplies its own time axis. `DaySummaryScheduler` also depends on `MarketHoursService` — not for gating (its own cron already only fires once a day) but to anchor `marketCloseOn(date)` / `marketOpenOn(date)` in the force-close timestamp and the summary text. `LoginScheduler`'s heartbeat uses it for a third window, `isWithinHeartbeatWindow()` — see [HEARTBEAT.md](HEARTBEAT.md#the-heartbeat-window).

The **trigger** still fires in backtest for the three pipeline crons; it is the body that is inert. Removing the trigger would need bean-level `@ConditionalOnProperty`, which is not available here — `BacktestAnalysisService` injects all three beans and calls them per tick, so conditioning the bean away would delete the replay's pipeline, not just its cron. (`LoginScheduler` *can* use it, and does, because nothing in the replay path needs that bean.)

> ⚠️ **`TradeConfigScheduler`'s `0 16 9 * * MON-FRI` cron is still ungated.** It assigns `SharedData.combinedDto` from *today's* DB rows on the scheduler thread; a replay reassigns that field at the top of every tick, so the exposure is a cross-thread race rather than a standing clobber — but it decides which configs get dispatched, so it is filed as [STRATEGY_ANALYSIS_TODO.md S11](STRATEGY_ANALYSIS_TODO.md#s11-wall-clock-scheduler-threads-mutate-replay-state-mid-run) and needs sign-off before being gated. (Its `0 12 9` sibling, which only logged, was deleted 2026-08-31 — GAPS #11.)

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

**Time gating on the heartbeat (GAPS #3).** The tick short-circuits outside `MarketHoursService.isWithinHeartbeatWindow()` — weekdays, `app.market.heartbeat-start`..`app.market.heartbeat-end`, **07:50–15:40 IST** by default. Wider than market hours on both sides on purpose: the morning margin exists so a dead token is probed (and, since alerts are transition-only, alerted) before the 08:00 login cron, and the evening margin covers the 15:31 day-summary sweep. Startup refuses a window that does not contain `[open, close]`, so the gate cannot suppress a probe during trading hours. Same wrapper/method split the pipeline schedulers use: the gate is on the `@Scheduled` method, and `runHeartbeat()` underneath probes whenever called. Full rationale in [HEARTBEAT.md](HEARTBEAT.md#the-heartbeat-window).

Mode gating: live only, and unlike the pipeline schedulers it is gated at the **bean** — `@ConditionalOnProperty(name = "app.mode", havingValue = "live", matchIfMissing = true)`. In `app.mode=backtest` the bean does not exist, so neither the cron nor the heartbeat is registered at all. That option is open here precisely because nothing in the replay path injects `LoginScheduler`; the backtest controller (`POST /api/backtest/login`) drives `LoginOrchestrator` directly.

Detailed state machine and alert-rule matrix live in [HEARTBEAT.md](HEARTBEAT.md).

**`fetchOptionsData()` — `0 15 9 * * MON-FRI` (09:15 IST).** Bulk-downloads the day's NIFTY and BANKNIFTY options chain via `ZerodhaMarketDataService.fetchAndSaveOptionsData(...)`, writing to `market_data`/`options_data`. Hardcodes `session.getBroker() != Broker.ZERODHA` as a skip condition — Groww/Angel One sessions never trigger this fetch, a known gap (see `docs/GAPS.md` #12). **This data is not read by the live/backtest trading pipeline** (`MarketDataService.fetchHistoricalData` always hits the broker fresh) — its only consumer today is the chart dashboard's `TOKEN_BASED` source (see [CHART_DASHBOARD.md](CHART_DASHBOARD.md) and [WORKFLOWS.md](WORKFLOWS.md)).

---

## TradeConfigScheduler

[`com.moneymaker.scheduler.TradeConfigScheduler`](../src/main/java/com/moneymaker/scheduler/TradeConfigScheduler.java)

- Loads `TradeConfig` + `Instrument` + `InstrumentDetails` + `SmaTimeframe` for a given trading date and assembles them into `List<TradeConfigCombinedDTO>`.
- **Fans each config out into one DTO per strategy named in `trade_config.strategy_ids`** (changesets 031/035) — same `tradeConfig`, different `strategyId`. This is the only place the fan-out happens, which is what lets `StrategyFactory` keep dispatching exactly one strategy per DTO. A config with a blank column yields a single DTO carrying its `stratergy_id`, so an untagged database behaves exactly as before. See [STRATEGIES.md](STRATEGIES.md#how-a-config-reaches-a-strategy).
  - **The list length is the number of `(config, strategy)` pairs, not configs.** Anything reporting `combinedDto.size()` as a config count (the backtest day log, the Telegram digest header) counts pairs.
  - Siblings share one `TradeConfig` instance and one timeframe list — they differ in nothing but `strategyId`. Nothing downstream writes to either; a caller that needs to mutate a config per strategy must copy first.
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

- **Cron `0 0/5 9-16 * * MON-FRI`** on `analyzeMarketData()` — every 5 minutes during NSE hours. That method is the wall-clock wrapper (backtest + market-hours gates, then `calculateIndicator(LocalDateTime.now())`); the replayable work is `calculateIndicator(asOf)` + `runStrategies(asOf)`, neither of which knows the mode.
- For each `TradeConfigCombinedDTO` and each timeframe **that config's own `sma_timeframe` rows name** (`timePeriodsOf(dto)`):
  1. `MarketDataService.fetchHistoricalData(...)` for the underlying.
  2. `calculateStrikesForCandles(...)` to derive active strikes.
  3. For each active strike, fetch the option chain candles and stash them in `SharedData.strikeMarketDataByInstrumentAndInterval` keyed by `<instrumentToken>|<interval>|<optionType>|<strike>|<optionToken>|<itmDepth>|<otmDepth>`.
  4. Compute SMA columns on each list — **every** period registered for that timeframe in `allTimeFrameMap` (20, 50, 100, 200, 500 — see [`AllTimeFramedto`](../src/main/java/com/moneymaker/dto/AllTimeFramedto.java)), not just the one the config trades on. That is what lets a strategy filter on an SMA period other than its own, as `Strategy2` does with SMA-20.
- **Only configured intervals are fetched.** This loop used to iterate `allTimeFrameMap`'s keys (`5` / `10` / `15`) regardless of what the day's configs asked for, so every tick cached a 10-minute series no strategy scans — `sma_timeframe` only ever holds 5- and 15-minute rows. That was not merely wasted work: `OrderService.lastPriceFor` and the backtest position monitor resolved a quote by option token alone and could land on it, which is how targets and stop-losses ended up priced off a 10-minute bar. A timeframe with no periods registered in `allTimeFrameMap` is skipped with a warning, which is what used to happen implicitly by never being fetched.
- The data-fetch loop **de-duplicates by `trade_config.id`**. Since 031 `SharedData.combinedDto` holds one entry per `(config × tagged strategy)`, and what this loop fetches depends only on the config — so without the guard a config tagged with two strategies would issue every rate-limited `MarketDataService` call twice for identical data.
- Then `runStrategies(asOf)` walks **every** DTO — including each tag of a fanned-out config — and invokes the `Strategy` bean that DTO was scoped to (`TradeConfigCombinedDTO.getStrategyId()`, falling back to `stratergy_id`) — see [STRATEGIES.md](STRATEGIES.md) — which writes `TradeSignal`s into `SharedData.tradeSignals`. Each signal carries the emitting `strategyId`.

> **Confirmation timeframes.** A strategy may read an interval it does not
> trade on: `Strategy.confirmationTimeframes()` (only `Strategy6` declares
> one — 15 minutes) is unioned into the fetch set of every config the strategy
> is tagged on, via `AnalysisScheduler.confirmationTimeframesByConfig`,
> gathered across *all* tags **before** the once-per-config loop — otherwise a
> config tagged `1,6` would fetch on strategy 1's turn and never see strategy
> 6's series. The extra series is keyed, SMA-stamped and tick-stamped exactly
> like a traded interval; the strikes it covers are derived from that
> interval's own underlying bar, so at the rare tick where the 15-minute and
> 5-minute ATM differ a leg may lack its confirmation series and the rule
> reads "unknown" — see [STRATEGIES.md](STRATEGIES.md#strategy-6--strategy-2-with-higher-timeframe-confirmation-an-entry-cut-off-and-a-stop-loss-lock).
> The tick cadence is unaffected: `BacktestAnalysisService` still derives it
> from the configs' own `sma_timeframe` rows.

> **Entry legs are also filtered by premium.** `AbstractSmaCrossStrategy` drops an entry signal
> whose leg premium falls outside `trade_config.min_option_price` /
> `max_option_price` — see
> [ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md#option-premium-band-min_option_price--max_option_price).
> Exit-direction signals are never filtered.

> **The cache is global; the key is the ownership record.** Every config for the
> day writes into the same map, so a strategy reading it back must match *every*
> segment the write pinned — `optionType` and the two depths included, not just
> `<instrumentToken>|<interval>`. `AbstractSmaCrossStrategy.keyMatches` does this. Matching only
> the prefix makes a CE config scan the PE config's legs and vice versa, and
> since a CE + PE pair per day is the normal shape, every signal then fires once
> per config and the ledger records each trade twice.

Inside `MarketDataService.fetchHistoricalData` the call is wrapped by Resilience4j RateLimiter + Retry — see [RATE_LIMITING.md](RATE_LIMITING.md) for the throttle / retry policy and the planned cache layers.

In backtest mode, `BacktestAnalysisService.runForDateTime` calls `analysisScheduler.calculateIndicator(currentDateTime)` and then `analysisScheduler.runStrategies(currentDateTime)` directly per tick — bypassing the cron.

### Symbol + expiry resolution

`AnalysisScheduler` does not resolve instruments itself. It delegates to an
[`OptionInstrumentResolver`](../src/main/java/com/moneymaker/market/instrument/OptionInstrumentResolver.java),
which supplies three things: the underlying symbol, the expiry, and each option
leg's symbol.

| Implementation | Active when | Symbols | Expiry from |
|---|---|---|---|
| `TokenOptionInstrumentResolver` | default | Zerodha instrument tokens, from `instrument_details` | `expiry_dates` (nearest `>=` the analysis date) |
| `HistoricalOptionInstrumentResolver` | `backtest.data-source=HISTORICAL_ICICI` | `HistoricalSymbol` natural keys, e.g. `HIST:NIFTY:NFO:2024-01-04:21700:CE` | `historical_option_candles` (nearest available `expiry_date >=` the date) |

Two consequences worth knowing:

- **The strategies use the same resolver.** Its cache-key prefix filter must match
  what the scheduler wrote at position 0 of the key. Deriving that prefix from
  `instrumentDetails` independently — as it once did — matches nothing the moment
  the symbol is not a broker token, and the strategy silently evaluates zero
  strikes.
- **Neither resolver distinguishes weekly from monthly expiry.** Both take the
  *nearest* expiry available; which one that is depends entirely on the data
  seeded into `expiry_dates` (or imported into `historical_option_candles`). See
  [BACKTESTING.md → Expiry](BACKTESTING.md#expiry).

`SharedData.optionTokenMap` caches the resolved leg symbol per **contract**
(`expiry|strike|optionType`), not per strike — a CE and a PE config on the same
day walk identical strikes, so a strike-only key made the second config reuse the
first one's leg. Use `SharedData.optionTokenKey(...)` when touching it.

---

## OrderScheduler

[`com.moneymaker.scheduler.OrderScheduler`](../src/main/java/com/moneymaker/scheduler/OrderScheduler.java)

- **Cron `0 0/5 9-16 * * MON-FRI`** on `scheduledTick()` — same cadence as `AnalysisScheduler`, intentionally. Each tick: analysis writes signals, orders drain them. `scheduledTick()` holds the backtest + market-hours gates and nothing else; `processOrders()` below it is the replayable method and carries no mode branch.
- Delegates to `OrderService.processOrders()` which:
  1. `SharedData.tradeSignals.poll()` until empty.
  2. For each signal, looks up the active broker via `OrderPlacementFactory` (selects `BACKTESTING` when `app.mode=backtest`, otherwise `broker.active`).
  3. Applies dedupe + intraday + transactionType rules — see [ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md).
  4. Persists a `TradeOrder` row, then fires the broker `place(order, config)` call. Broker order id is captured back onto the row.

Wraps each signal in `try/catch` so a single bad signal doesn't kill the rest of the queue.

In backtest, `BacktestAnalysisService` calls `orderScheduler.processOrders()` directly after `analysisScheduler.runStrategies(asOf)` each tick.

---

## PositionScheduler

[`com.moneymaker.scheduler.PositionScheduler`](../src/main/java/com/moneymaker/scheduler/PositionScheduler.java)

- **Cron `0 0/5 9-16 * * MON-FRI`** on `scheduledTick()` — same cadence again, same wrapper split as `OrderScheduler`. Tick order: analysis → orders → positions.
- Delegates to `PositionService.processPositions()` which:
  1. `tradeOrderRepository.findByStatus("OPEN")`.
  2. For each open row, calls `PositionMonitorFactory.active().currentPrice(order)` — broker-specific live quote (Zerodha LTP, backtest cached candle, Groww/AngelOne TODO).
  3. Updates `peak_profit`, `peak_loss`, `last_monitored_price`, `last_monitored_at`.
  4. Ratchets `trail_sl_at` up to the highest `trail_ladder_at_entry` rung `peak_profit` has reached (changeset 036). The floor never moves down.
  5. Compares unrealised P&L against the thresholds **snapshotted on the row** (`target_at_entry` / `stop_loss_at_entry` / `trail_sl_at`), not the live config. On breach, calls `OrderService.closeManually(orderId, price, now, "TARGET" | "TRAIL_SL" | "STOP_LOSS")` — full close path (DB update + broker exit + Telegram alert).

Fields and SL/target semantics documented in [ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md).

In backtest, `BacktestAnalysisService` calls `positionScheduler.processPositions()` directly after `orderScheduler.processOrders()` each tick.

---

## DaySummaryScheduler

[`com.moneymaker.scheduler.DaySummaryScheduler`](../src/main/java/com/moneymaker/scheduler/DaySummaryScheduler.java)

- **Cron `0 31 15 * * MON-FRI`** (configurable via `app.market.summary-cron`) — one minute after the configured close, giving the last 15:30 `PositionScheduler` tick time to settle first.
- **Live only.** `runEndOfDay()` returns immediately unless `app.mode=live`, then delegates to `runEndOfDayFor(LocalDate, boolean force)` — the date is a parameter rather than an ambient `LocalDate.now(...)`, which is what the tests drive and what the manual re-run endpoint (below) calls. Skipped on Sat/Sun.
- Steps, in order:
  1. `OrderService.forceCloseOpenPositions(date, marketHours.marketCloseOn(date))` — closes any `trade_order` row still `OPEN` at close, so the ledger is complete before summarizing. **In live mode this now places a real broker exit per row** (GAPS #1) — see [ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md#force-close-live-vs-backtest). Exceptions are caught and logged; a force-close failure does not stop the summary from being built.
  2. `buildSummary(today, forceClosed)` — aggregates the day's `trade_order` rows into a compact text digest: trade/closed/open-left counts, win/loss/scratch counts, **both** the per-share and the lot-multiplied (net) P&L, biggest winner/loser in both units, exit-reason breakdown, per-config net P&L. The net multiplier is `TradeConfig.lotQuantity`, joined per config; trades whose config no longer resolves are excluded from net and declared on a `no lot qty` line rather than counted at ×1 (GAPS #2).
  3. `NotificationService.alertDaySummary(body)` — one Telegram message.

### Two guard keys, not one

Both halves are gated by [`DailyEventGuard`](../src/main/java/com/moneymaker/state/DailyEventGuard.java) (same `alert_state`-backed mechanism as `TradeConfigScheduler.reportConfigsForDay`), but with **separate keys**, because they fail for unrelated reasons:

| Key | Written when | Effect of it being missing |
|---|---|---|
| `day-summary-forceclose` | `forceCloseOpenPositions` returned cleanly | The next tick force-closes again. Safe — the method only ever selects rows still `OPEN`. |
| `day-summary-telegram` | `alertDaySummary` reported the message actually went out | The next tick re-sends the digest **only** — it does not force-close again. |
| `day-summary` (legacy) | The pre-split build wrote this before doing anything | Still read. If present, both halves are treated as done, so deploying this change mid-afternoon doesn't re-send a summary the old build already delivered. |

Previously a single `day-summary` key was written *up front*, so one failed Telegram POST lost the day's digest permanently while the guard reported the day as done (GAPS #5). Delivery is now confirmed — `TelegramNotifier.send` returns whether a retry could help; see [NOTIFICATIONS.md](NOTIFICATIONS.md#delivery-confirmed-sends).

With the default once-a-day cron there is no second tick to retry on. The gate does make a repeating `app.market.summary-cron` safe to set (both halves are idempotent), but that's an operator choice; the intended recovery path is the manual re-run below.

### Manual re-run — `POST /api/admin/day-summary` (GAPS #6)

[`DaySummaryAdminController`](../src/main/java/com/moneymaker/admin/controller/DaySummaryAdminController.java).

| Param | Default | Meaning |
|---|---|---|
| `date` | today, in `app.market.timezone` | Which trading date to re-run. A Saturday/Sunday is rejected with 400 and a reason rather than silently doing nothing. |
| `force` | `false` | Bypass the sent markers and run both halves regardless. |

**Idempotency is free, not new code.** Without `force`, the two-key gate above already knows which half completed, so a plain re-run executes the pending half and skips the finished one. That covers the cases the endpoint exists for: the JVM was down at 15:31 (nothing marked, so both halves run), or the Telegram POST failed (`day-summary-telegram` unmarked, so the digest re-sends and the force-close does *not* run twice). Calling it repeatedly on a completed day does nothing at all.

`force` is the deliberate override for the one case the marker cannot see: **the digest was delivered and it was wrong** — it fired before a delayed close, so the day it summarised was not over. It is safe on the force-close half too, since `forceCloseOpenPositions` only selects rows still `OPEN`.

**Back-dated re-runs are correct now.** The close moment comes from `marketHours.marketCloseOn(date)`, so replaying last Friday stamps exits with *Friday's* close rather than this afternoon's. For `date = today` that is the same value `marketCloseToday()` returned, so the 15:31 cron's behaviour is byte-for-byte unchanged.

Unlike the cron, the endpoint is **not** mode-gated: an operator hitting it has asked for it explicitly, and in backtest mode `TelegramNotifier` suppresses the send while `OrderPlacementFactory` resolves to `BACKTESTING`, so nothing reaches a broker.

- **Not replayed in backtest.** `BacktestAnalysisService` already calls `orderService.forceCloseOpenPositions(date, dateEnd)` at the end of every simulated day (see below), so a second live-style digest per backtest day isn't needed — and would spam Telegram on every backtest boot if it were wired the same way.

---

## Backtest replay vs live cron

`BacktestAnalysisService.run(fromDate, toDate)` walks each backtest day in 5-minute increments and **calls the same scheduler methods directly**. The cron *bodies* are inert in `app.mode=backtest` — true since 2026-08-31 (`GAPS.md` #4); before that they ran in full and a replay started during market hours shared its state with a live wall-clock pipeline. Per tick, the call order is:

1. `analysisScheduler.calculateIndicator(currentDateTime)`  (data fetch + SMAs)
2. `analysisScheduler.runStrategies(asOf)`                   (strategy → signals)
3. `orderScheduler.processOrders()`                         (signals → orders)
4. `positionScheduler.processPositions()`                   (open orders → monitoring)

At end of each backtest day the runner additionally calls `orderService.forceCloseOpenPositions(date, dateEnd)` to clean up any intraday position whose strike fell out of the active-strike set before the close-signal could fire.

End-of-run cleanup: `SharedData.tradeSignals.clear()` so a subsequent backtest / live tick starts with an empty queue.

---

## Adding a new scheduler

1. New `@Component` class in `com.moneymaker.scheduler`. Match the existing file shape: constructor-injected dependencies + `@Scheduled` method that delegates to a separate service.
2. Pick a cron that matches the operational window — `0 0/N 9-16 * * MON-FRI` for market-hours, `fixedDelay = …` for always-on probes.
3. Wrap the body in `try/catch` so an exception in one tick doesn't poison the schedule.
4. If you want backtest replay, **don't put the work in the `@Scheduled` method**. Put it on the underlying service so `BacktestAnalysisService` can call it directly per tick. Keep the `@Scheduled` method to wall-clock concerns only — the mode gate and any market-hours guard — and let the replay call past it. A mode check on the replayable method silences the replay; a wall-clock cron with no mode check runs a second pipeline against the replay's state.
5. Wire any new persistence into `application.properties` for sensitivity (toggles), Liquibase for schema (numbered changeset), and `NotificationService` for alerts (use `sendIfChanged` / `sendThrottled` to avoid spam — see [NOTIFICATIONS.md](NOTIFICATIONS.md)).
6. **Update this page.** Every new scheduler gets a row in the inventory table and a section below.

---

## When *not* to add a scheduler

- A piece of work that runs once per HTTP request → put it in a service called from a controller. Don't schedule it.
- Something that needs to react to data flow → consider a producer/consumer pattern over `SharedData` collections (the existing `tradeSignals` queue) instead of polling.
- Reactions to broker state changes → use the heartbeat transition guard, not a separate poller.
