# Workflows — the system-level map

Every other doc in this folder explains one feature in depth. This one is different: it's the map of **every independent workflow running in the app**, what triggers each one, and — the part no single feature doc can show — **which workflows write data that another workflow reads**, including the non-obvious cases (a one-day delay, or "looks related but isn't wired at all").

> **Read this first if you're new to the codebase.** Then go deep on the specific workflow via the per-feature doc it links to.

---

## The 11 workflows, at a glance

```
 SETUP / CONFIG                    TRADING PIPELINE                  EOD / OPS
┌─────────────────┐          ┌───────────────────────────┐     ┌──────────────────┐
│ ① Login &        │          │ ⑤ Analysis → Order →       │     │ ⑦ Day summary     │
│   Heartbeat       │          │   Position (5-min ticks)   │     │   (15:31 IST)      │
└────────┬─────────┘          └──────────────┬─────────────┘     └─────────┬──────────┘
         │ broker_session                    │ trade_order                 │ reads trade_order
         │                                    │                             │ force-closes it
┌────────▼─────────┐          ┌──────────────▼─────────────┐              │
│ ② Trade-config    │─────────▶│  SharedData.combinedDto     │              │
│   daily load       │  feeds  │  (pipeline's only input gate)│             │
└────────▲─────────┘          └──────────────▲─────────────┘              │
         │ same-day refresh                  │ drives                     │
┌────────┴─────────┐          ┌──────────────┴─────────────┐              │
│ ③ Trade-config    │          │ ⑥ Backtest orchestration    │──────────────┘
│   admin (CRUD)     │          │   (replays ②+⑤, triggers ④) │  force-closes EOD itself
└────────▲─────────┘          └──────────────┬─────────────┘
         │ next-day rows                     │ calls after each day
┌────────┴─────────┐                          │
│ ④ EOD downtrend   │◀─────────────────────────┘
│   auto-config      │
└───────────────────┘

 MARKET DATA & CHARTS (isolated from the trading pipeline above)
┌───────────────────┐    ┌────────────────────┐    ┌──────────────────┐
│ ⑨ Options bulk      │    │ ⑩ Historical ICICI    │    │ ⑧ Chart dashboard  │
│   download           │───▶│    CSV import          │──▶│   (read-only)      │
│   (market_data)       │    │  (historical_*_candles)│   │                    │
└───────────────────┘    └────────────────────┘    └──────────────────┘
        ✗ NOT read by ⑤/⑥ — see the cross-workflow table below

 ⑪ Notifications — the shared sink for ①, ⑤, ⑦, and ②'s report (not shown above, fans in from everywhere)
```

---

## ① Login & Heartbeat

| | |
|---|---|
| Trigger | `0 0 8 * * MON-FRI` (first login) + `fixedDelay=60s` (heartbeat) + `0 15 9 * * MON-FRI` (options fetch) |
| Code | [`LoginScheduler`](../src/main/java/com/moneymaker/scheduler/LoginScheduler.java) → [`LoginOrchestrator`](../src/main/java/com/moneymaker/login/service/LoginOrchestrator.java) → per-broker `BrokerLoginService` |
| Reads | `broker.active` config, `AppState.currentSession()` |
| Writes | `broker_session` (session + heartbeat status), `AppState`, `market_data`/`options_data` (09:15 fetch, Zerodha only) |
| Downstream | Every other live-mode workflow depends on a valid `broker_session` existing before it can do anything broker-facing. The 09:15 options fetch feeds workflow ⑨'s data into ⑧. |
| Full detail | [LOGIN_FLOW.md](LOGIN_FLOW.md), [HEARTBEAT.md](HEARTBEAT.md), [SCHEDULERS.md#loginscheduler](SCHEDULERS.md#loginscheduler) |

---

## ② Trade-config daily load

| | |
|---|---|
| Trigger | `0 16 9 * * MON-FRI` (09:16 IST) + `ApplicationReadyEvent` at boot (live, weekday) |
| Code | [`TradeConfigScheduler.getConfigsForDate(date)`](../src/main/java/com/moneymaker/scheduler/TradeConfigScheduler.java) |
| Reads | `trade_config` (incl. `strategy_ids`), `instrument`, `instrument_details`, `sma_timeframe` |
| Writes | `SharedData.combinedDto` (date-keyed in-JVM cache) + a once-per-day Telegram report (`reportConfigsForDay`, gated by `DailyEventGuard`) |
| Fan-out | Emits **one DTO per (config x tagged strategy)**, so a config tagged with two strategies appears twice — same `tradeConfig`, different `strategyId`. The list length is pairs, not configs. Untagged configs fall back to `stratergy_id` and behave as before (changeset 031). |
| Downstream | `SharedData.combinedDto` is **the sole input gate** for workflow ⑤ — if it's empty (e.g. JVM restarted after 09:16 with no `ApplicationReadyEvent` seed, or no configs exist for today), the entire trading pipeline silently has nothing to evaluate. |
| Full detail | [SCHEDULERS.md#tradeconfigscheduler](SCHEDULERS.md#tradeconfigscheduler) |

---

## ③ Trade-config admin (CRUD)

| | |
|---|---|
| Trigger | HTTP — `/trade-configs` UI, `/api/trade-configs*` |
| Code | [`TradeConfigAdminController`](../src/main/java/com/moneymaker/tradeconfig/controller/TradeConfigAdminController.java) → [`TradeConfigAdminService`](../src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java) |
| Reads | `trade_config`, `sma_timeframe`, `instrument`, `trade_order` (delete guard) |
| Writes | `trade_config`, `sma_timeframe` |
| Downstream (same-workflow-family effect) | Every mutation calls `afterMutation(date)`: **always** invalidates ②'s cache; if the date is *today* and `app.mode=live`, **also** rebuilds `SharedData.combinedDto` synchronously — so an edit made through this UI at 11:00 AM changes what the 11:05 AM tick of workflow ⑤ trades, with no restart. Edits to other dates only take effect the next time ② loads that date. |
| Full detail | [ORDERS_AND_POSITIONS.md#trade-config-admin](ORDERS_AND_POSITIONS.md#trade-config-admin) |

---

## ④ EOD downtrend auto-config generation

| | |
|---|---|
| Trigger | Called from workflow ⑥ (backtest), once per simulated day, after 15:20 force-close |
| Code | [`EodDowntrendDetectionService.runForDay(date)`](../src/main/java/com/moneymaker/tradeconfig/generation/EodDowntrendDetectionService.java) |
| Reads | `sma_downtrend_rule`, `sma_downtrend_rule_strategy`, `strategy_defaults`, option-leg candles via `MarketDataService` (broker fetch, not `market_data` table) |
| Writes | `trade_config` (`source='AUTO_DOWNTREND'`, with `strategy_ids`) + `sma_timeframe`, for the **next** trading day only |
| Strategy tagging | Which strategies a rule generates for is DB-driven (`sma_downtrend_rule_strategy`, changeset 034); the `trade_config` field block comes from `strategy_defaults` (033). One scan produces **one** config carrying one tag per strategy — two configs only when two strategies' default blocks differ. |
| Downstream | **Delayed cross-workflow effect**: the row it writes today is invisible to everything until workflow ② loads *tomorrow's* date. It cannot bootstrap a config chain from nothing, but since the 2026-08-29 decoupling it **does** run on every trading day, including days with no active config — that is what lets the chain restart after a day that generated nothing. Previously one empty day was terminal: a 31-day range stopped after 5. Reachable/reversible via workflow ③'s bulk-delete API (`/api/trade-configs/auto/*`). |
| Full detail | [EOD_DOWNTREND.md](EOD_DOWNTREND.md) |

---

## ⑤ Analysis → Order → Position pipeline

| | |
|---|---|
| Trigger | `0 0/5 9-16 * * MON-FRI`, three schedulers on the same cadence, gated by `MarketHoursService.isOpenNow()` in live mode |
| Code | [`AnalysisScheduler`](../src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java) → [`OrderScheduler`](../src/main/java/com/moneymaker/scheduler/OrderScheduler.java) → [`PositionScheduler`](../src/main/java/com/moneymaker/scheduler/PositionScheduler.java) |
| Reads | `SharedData.combinedDto` (from ②/③), broker OHLC (live fetch, not persisted), OPEN `trade_order` rows |
| Strategy dispatch | `runStrategies` walks every DTO, so each tagged strategy scans independently; the market-data fetch loop de-duplicates on `trade_config.id` so the fan-out does not double broker calls. Ledger identity downstream is `(trade_config_id, strategy_id)`. |
| Writes | `SharedData.strikeMarketData*`, `SharedData.tradeSignals`, `trade_order` (open/close), broker order calls, Telegram (order open/close/force-close) |
| Downstream | This is the workflow every other config-producing workflow (②③④) ultimately feeds. Its own output (`trade_order`) feeds workflow ⑦. |
| Full detail | [SCHEDULERS.md](SCHEDULERS.md), [ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md) |

---

## ⑥ Backtest orchestration

| | |
|---|---|
| Trigger | HTTP — `POST /api/backtest/analysis?fromDate=&toDate=` |
| Code | [`BacktestAnalysisService`](../src/main/java/com/moneymaker/backtesting/BacktestAnalysisService.java) / [`BacktestController`](../src/main/java/com/moneymaker/backtesting/BacktestController.java) |
| Reads/Writes | Drives the **same service methods** as ② and ⑤ per simulated day/tick — not a parallel implementation. Also calls ④ once per day, and `OrderService.forceCloseOpenPositions(date, dateEnd)` at each day's end. |
| Downstream | Writes the same `trade_order` ledger as ⑤, but through no-op broker adapters (`BacktestingOrderPlacementService` / `BacktestingPositionMonitorService`) so nothing hits a real broker. Telegram is suppressed by default (`telegram.backtest-enabled=false`). |
| Full detail | [BACKTESTING.md](BACKTESTING.md), [BACKTEST_PERFORMANCE.md](BACKTEST_PERFORMANCE.md) |

---

## ⑦ Day summary (EOD)

| | |
|---|---|
| Trigger | `0 31 15 * * MON-FRI` (15:31 IST), live only |
| Code | [`DaySummaryScheduler`](../src/main/java/com/moneymaker/scheduler/DaySummaryScheduler.java) |
| Reads | `trade_order` (today's rows), `MarketHoursService` |
| Writes | Force-closes leftover OPEN `trade_order` rows via `OrderService`, then one Telegram digest |
| Downstream | Nothing downstream — this is a terminal workflow. It shares the `DailyEventGuard`/`alert_state` once-per-day mechanism with ②'s report, and its force-close is the live-mode equivalent of what ⑥ does per backtest day. |
| Full detail | [SCHEDULERS.md#daysummaryscheduler](SCHEDULERS.md#daysummaryscheduler) |

---

## ⑧ Chart dashboard

| | |
|---|---|
| Trigger | HTTP — `GET /charts/dashboard` (UI), `GET /api/charts/market-data` (data) |
| Code | [`ChartDashboardApiController`](../src/main/java/com/moneymaker/chart/controller/ChartDashboardApiController.java) → `ChartDashboardService` (`TOKEN_BASED`) or `HistoricalIciciChartDashboardService` (`HISTORICAL_ICICI`) |
| Reads | `market_data` **or** `historical_spot_candles`/`historical_option_candles` (user picks the source), plus `instrument`/`instrument_details`/`expiry_dates` |
| Writes | Nothing — read-only |
| Downstream | Purely a consumer of workflows ⑨ and ⑩. **Read-only, has no effect on any other workflow.** |
| Full detail | [CHART_DASHBOARD.md](CHART_DASHBOARD.md) |

---

## ⑨ Options bulk data download

| | |
|---|---|
| Trigger | `0 15 9 * * MON-FRI` (09:15 IST, via `LoginScheduler.fetchOptionsData`, Zerodha-only) + manual `OptionsDataController` endpoints |
| Code | [`ZerodhaMarketDataService`](../src/main/java/com/moneymaker/data/download/ZerodhaMarketDataService.java), [`OptionsBulkDownloadService`](../src/main/java/com/moneymaker/data/download/OptionsBulkDownloadService.java) |
| Reads | Broker options-chain API |
| Writes | `market_data`, `options_data` |
| Downstream | **Feeds workflow ⑧ only.** This is the non-obvious one: it is easy to assume this data reaches the trading pipeline (⑤/⑥) since it's "market data," but `MarketDataService.fetchHistoricalData` (the pipeline's actual data source) always fetches fresh from the broker and never reads the `market_data` table — a real architectural gap, already flagged in `ARCHITECTURE_REVIEW.md` §4. |
| Full detail | [SCHEDULERS.md#loginscheduler](SCHEDULERS.md#loginscheduler) |

---

## ⑩ Historical ICICI CSV import

| | |
|---|---|
| Trigger | HTTP — `POST /api/charts/historical/import/{spot,options}` (manual, multipart CSV upload) |
| Code | [`HistoricalChartImportController`](../src/main/java/com/moneymaker/chart/controller/HistoricalChartImportController.java) → `HistoricalChartCsvImportService` |
| Reads | Uploaded CSV files |
| Writes | `historical_spot_candles`, `historical_option_candles` (natural-key upsert) |
| Downstream | Feeds **workflow ⑧** when the dashboard's data-source selector is `HISTORICAL_ICICI`, and **the backtest workflow** when `backtest.data-source=HISTORICAL_ICICI` — in that mode these tables replace the broker as the candle source for the whole analysis→order→position pipeline. Still deliberately isolated from `market_data`/`instrument*`: no `instrumenttoken` anywhere in this path, and the backtest reaches the rows through `HistoricalSymbol` natural-key strings rather than tokens. |
| Format | Tolerant importer — `datetime`/`expiry_date` in either `yyyy-MM-dd` or `dd-MM-yyyy` layout, CE/PE column headed `right` or `option_right`. |
| Writer | Plain JDBC `INSERT … ON DUPLICATE KEY UPDATE` in 5000-row batches, **not** JPA: both entities use `GenerationType.IDENTITY`, which disables Hibernate insert batching outright. Needs `rewriteBatchedStatements=true` on the JDBC URL to actually batch. Commits per chunk, so an interrupted import resumes by re-running. |
| Response | `{"rows": N}` — rows upserted. Re-importing a file is a no-op on row count. |
| Full detail | [HISTORICAL_CHART_DATA_PLAN.md](HISTORICAL_CHART_DATA_PLAN.md), [BACKTESTING.md → Data source](BACKTESTING.md#data-source), [BACKTESTING.md → Importing a full ICICI export](BACKTESTING.md#importing-a-full-icici-export) |

---

## ⑪ Notifications fan-in

| | |
|---|---|
| Trigger | Called from every other workflow's feature code, never scheduled itself |
| Code | [`NotificationService`](../src/main/java/com/moneymaker/telegram/NotificationService.java) → [`TelegramNotifier`](../src/main/java/com/moneymaker/telegram/TelegramNotifier.java) |
| Reads | Whatever the calling workflow passes in |
| Writes | Telegram messages (or nothing, if disabled/suppressed) |
| Downstream | Terminal — every workflow's "tell a human" step ends here. Single chokepoint (`TelegramNotifier.send`) enforces the backtest-suppression gate, so workflow ⑥ doesn't need its own suppression logic. |
| Full detail | [NOTIFICATIONS.md](NOTIFICATIONS.md) |

---

## Cross-workflow data map

The table every per-feature doc is missing: one row per shared resource, which workflow(s) write it, which read it, and the catch if there is one.

| Resource | Written by | Read by | Catch |
|---|---|---|---|
| `trade_config` (+ `sma_timeframe`) | ③ (admin UI), ④ (auto-downtrend, backtest only) | ② (daily loader, which feeds ⑤/⑥) | ③'s edits to *today* reach ⑤ within one tick (live). ④'s writes reach ② only on the **next calendar day** — same-day bootstrap is impossible by design. |
| `SharedData.combinedDto` | ② (cron/boot), ③ (same-day live refresh only) | ⑤, ⑥ | The pipeline's only input gate. Empty means the pipeline silently trades nothing — no error, no log spam, just zero signals. |
| `SharedData.tradeSignals` | ⑤'s `AnalysisScheduler` (via every tagged `Strategy`) | ⑤'s `OrderScheduler` (same tick) | Drained to empty every tick; also cleared at backtest run-end. Not a durable store — never read cross-day. |
| `trade_order` | ⑤ and ⑥ (same code path, different broker adapters) | ⑤'s `PositionScheduler` (OPEN rows), ⑦ (today's rows), ③ (delete guard) | ⑥ writes through no-op broker adapters — the ledger looks identical to a live day's, but no real order was placed. |
| `market_data` | ⑨ (bulk download, Zerodha-only) | ⑧ (`TOKEN_BASED` source only) | **Never read by ⑤/⑥.** The trading pipeline always fetches OHLC live from the broker; this table is a dead end for anything except charting. |
| `historical_spot_candles` / `historical_option_candles` | ⑩ (CSV import) | ⑧ (`HISTORICAL_ICICI` source only) | Fully isolated from `market_data` / `instrument*` — natural keys only. Never touches the trading pipeline either. |
| `alert_state` | ② (`reportConfigsForDay`), ⑦ (`day-summary`) | Same two, via `DailyEventGuard` | Shared restart-safety mechanism — a JVM restart between the write and the "did I already send this" check won't double-fire either alert. |
| `broker_session` | ① | Every live-mode workflow's broker calls (⑤, ⑦'s force-close, ⑨) | If ① hasn't produced a valid session, ⑤/⑦/⑨'s broker calls fail (or short-circuit, in ⑨'s case) — but ⑥ (backtest) doesn't need one at all past its own login preflight. |

---

## Two things worth internalizing

1. **The "market data" naming is a trap.** Three completely separate things are called "market data" in this codebase: (a) what `AnalysisScheduler`/`BacktestAnalysisService` fetch live from the broker for the trading pipeline — never persisted; (b) the `market_data` table, written by workflow ⑨, read only by the chart dashboard; (c) `historical_*_candles`, written by workflow ⑩, also only read by the chart dashboard. None of the three feed each other.
2. **Config production has two producers, one consumer, one delay.** Workflows ③ and ④ both write to `trade_config`, the table workflow ② is the sole reader of. ③'s writes can take effect the same day (live); ④'s writes never can (backtest-only, next-day-only, by design — see the "Not a bootstrap" note in EOD_DOWNTREND.md).

---

## See also

[`WORKFLOWS.html`](WORKFLOWS.html) — a self-contained HTML companion (open it directly in a browser, no server needed) that renders the diagrams above interactively, with expandable per-workflow detail. This doc is the durable reference the two diagrams and the card grid are sourced from — regenerate the page from here if either drifts.
