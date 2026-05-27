# Known gaps & follow-ups

Surfaced while building **(a)** the trade-config admin UI and **(b)** the
market-hours gate + end-of-day summary. Captured here as a single backlog so
priorities can be set in one place rather than chasing TODO comments through
the tree.

Each entry: **what** / **where** / **why it matters** / **fix sketch** /
**effort hint**. Priority intentionally left blank — to be filled in by the
user.

Legend for effort:
- **S** — < 1 hour, single file
- **M** — half-day, 2-4 files + a doc update
- **L** — multi-day, schema change or cross-cutting

---

## 1. Live force-close does not place a real broker exit order

| | |
|---|---|
| Where | [`OrderService.forceCloseOpenPositions`](../src/main/java/com/moneymaker/order/service/OrderService.java#L398-L431) — comment at L420-422 |
| Why | `DaySummaryScheduler` (15:31 IST) calls this on live trades that survived market close. Today it only marks the DB row `CLOSED` with `exit_reason=FORCE_CLOSE` and a stale cached price. The actual broker-side position **is still open overnight** — silent risk if the broker rolls it into next-day delivery, or if SEBI auto-squareoff charges hit. |
| Fix sketch | After the local update, call `placementFactory.active().place(...)` with an opposite-side market order; reconcile fill on success, fall back to existing local-only behaviour with an `[ALERT]` Telegram if the broker call fails. |
| Effort | **M** |
| Priority | _TBD_ |

> Linked: the day-summary digest currently reports `force-closed: N` so the gap is at least *visible* every evening.

## 2. Day-summary P/L is per-share, not lot-multiplied

| | |
|---|---|
| Where | [`DaySummaryScheduler.buildSummary`](../src/main/java/com/moneymaker/scheduler/DaySummaryScheduler.java) — `totalPnl.add(pnl)` |
| Why | `trade_order.profit` is per-share (consistent with the orders ledger). The Telegram digest sums those values directly, so `P/L (per-sh): 124.50` is correct as a per-share figure but **not** the rupee-P&L the user actually cares about. |
| Fix sketch | Join through `tradeConfigId → TradeConfig.lotQuantity` (or snapshot `lot_quantity_at_entry` onto `trade_order` to keep it self-contained — preferable, matches the `target_at_entry` pattern from changeset 011). |
| Effort | **S** if join-on-the-fly; **M** if snapshot column (new changeset + write-path update). |
| Priority | _TBD_ |

## 3. Heartbeat runs 24/7

| | |
|---|---|
| Where | [`LoginScheduler.heartbeat`](../src/main/java/com/moneymaker/scheduler/LoginScheduler.java#L62) — `@Scheduled(fixedDelay = 60_000L)` |
| Why | This was left alone in the market-hours work because heartbeat is the only thing that catches token death. But it really only matters during a day window where login/options-fetch crons run — outside ~07:50–15:40 IST the broker session staying valid is moot until tomorrow's 08:00 login. Cost today is small (1 quote/min), but it produces noise in logs and the AUTH_FAIL Telegram could fire at 22:00 on a Friday for no reason. |
| Fix sketch | Add `MarketHoursService.isWithinHeartbeatWindow()` (default 07:50–15:40, configurable), short-circuit `heartbeat()` outside that range. Document the looser window in `HEARTBEAT.md`. |
| Effort | **S** |
| Priority | _TBD_ |

## 4. Pipeline cron annotations fire in backtest mode too

| | |
|---|---|
| Where | `AnalysisScheduler`, `OrderScheduler`, `PositionScheduler` — `@Scheduled(cron = "0 0/5 9-16 …")` |
| Why | `app.mode=backtest` only stops the *body* from running via the gates added in this session. The cron triggers still fire at wall-clock 09:00, 09:05, … 16:55 even when the JVM is doing a multi-day historical replay. Today this is harmless (the gates short-circuit), but the cron metadata being misleading hurts readability and `@Scheduled` proxies do have a tiny per-tick cost. |
| Fix sketch | Either (a) gate each scheduler bean creation with `@ConditionalOnProperty(name="app.mode", havingValue="live", matchIfMissing=true)`, or (b) keep beans but use `Trigger`-based conditional registration. (a) is simpler. |
| Effort | **S** |
| Priority | _TBD_ |

## 5. Day-summary marked-as-sent even when Telegram delivery fails

| | |
|---|---|
| Where | [`DaySummaryScheduler.runEndOfDay`](../src/main/java/com/moneymaker/scheduler/DaySummaryScheduler.java) — `dailyEventGuard.firstTime(...)` runs *before* the Telegram send |
| Why | If the Telegram POST fails (network blip, bot rate limit), the `alert_state` row is already persisted, so the summary is silently lost. Force-close still ran correctly. |
| Fix sketch | Move the `DailyEventGuard` insert to *after* a successful `notifier.alertDaySummary(...)` — but then a force-close failure shouldn't gate the insert either. Cleanest is two guard keys: `day-summary-forceclose` and `day-summary-telegram`, each gated independently so retries on the next cron tick can recover the missing half. (Or: just add a manual re-trigger endpoint — see gap #11.) |
| Effort | **S** for two-key gate; same with manual re-trigger. |
| Priority | _TBD_ |

## 6. No manual re-run for end-of-day work

| | |
|---|---|
| Where | n/a — endpoint doesn't exist |
| Why | If `DaySummaryScheduler` is missed because the JVM was down at 15:31, or it fired before a delayed close, there's no way to replay it from the UI — restart-safe gating means even a manual code call would no-op. Operator has to run a SQL `DELETE FROM alert_state WHERE alert_key='day-summary' AND alert_date='…'` then wait for the next cron. |
| Fix sketch | `POST /api/admin/day-summary?date=…&force=true` on a new admin controller; if `force=true`, bypass `DailyEventGuard`. Mirrors the `/api/backtest/*` style. |
| Effort | **S** |
| Priority | _TBD_ |

## 7. Trade-config delete blocked by `trade_order` history — no soft-delete path

| | |
|---|---|
| Where | [`TradeConfigAdminService.delete`](../src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java) → HTTP 409 |
| Why | Configs that ever fired a trade can't be removed, ever. Operationally fine for audit but the list view will grow forever — and there's no way to mark a config as "retired, do not run anymore today" without changing its `trading_date` to a past day. |
| Fix sketch | New `is_active BOOLEAN` column on `trade_config` (Liquibase 018). `findByTradingDate` becomes `findByTradingDateAndIsActiveTrue`. UI gets a toggle in the row actions; hard delete stays for configs that never traded. |
| Effort | **M** |
| Priority | _TBD_ |

## 8. Trade-config edit silently allowed while OPEN trades exist on that config

| | |
|---|---|
| Where | [`TradeConfigAdminService.update`](../src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java) |
| Why | Target / SL changes are safe (the order has snapshot fields from changeset 011), but changing `transactionType`, `numberOfParallelTrades` or `lotQuantity` mid-day on a config that has 3 open trades will subtly alter the rest of the day's behaviour without warning. |
| Fix sketch | Cheap version: UI checks `existsByTradeConfigId(id) + statusOpen` and shows a yellow banner before the user clicks Save. Stricter version: backend returns 409 unless `?confirm=true` is appended. |
| Effort | **S** for banner; **M** for backend confirm flow. |
| Priority | _TBD_ |

## 9. No "clone yesterday's configs to today" workflow

| | |
|---|---|
| Where | n/a — single-row clone or bulk-clone both not built |
| Why | A user with 8 active configs has to recreate them every morning, or run a manual SQL `INSERT … SELECT … WHERE trading_date='yesterday'`. This is the most-skipped step in real ops. |
| Fix sketch | `POST /api/trade-configs/clone?fromDate=…&toDate=…` (bulk) plus a `⎘ Clone` row action that pre-fills the form for single-row copy with a new date. |
| Effort | **S** for bulk; **M** with UI affordance + dry-run preview. |
| Priority | _TBD_ |

## 10. `TradeConfig.stratergyId` — column name typo

| | |
|---|---|
| Where | [`TradeConfig.java`](../src/main/java/com/moneymaker/entity/TradeConfig.java) line `@Column(name="stratergy_id")`; same name in changeset 003 |
| Why | Annoying every time someone autocompletes; bug-bait. |
| Fix sketch | Liquibase `renameColumn` from `stratergy_id` → `strategy_id`, rename entity field, update grep-able references. ~10 callers per quick scan. |
| Effort | **M** — straightforward but cross-cutting. |
| Priority | _TBD_ |

## 11. `TradeConfigScheduler.dailyTaskAt912AM` is a no-op stub

| | |
|---|---|
| Where | [`TradeConfigScheduler.dailyTaskAt912AM`](../src/main/java/com/moneymaker/scheduler/TradeConfigScheduler.java#L91) |
| Why | Logs a line, does nothing. Either it has a planned job that was never written, or it should be deleted to stop confusing readers. |
| Fix sketch | Delete unless there's intent — happy to remove in a 1-line PR. |
| Effort | **S** |
| Priority | _TBD_ |

## 12. Options-data fetch is Zerodha-only

| | |
|---|---|
| Where | [`LoginScheduler.fetchOptionsData`](../src/main/java/com/moneymaker/scheduler/LoginScheduler.java#L114) — hard-codes `session.getBroker() != Broker.ZERODHA` |
| Why | Violates the "one adapter per broker" invariant. When Groww / Angel One become real adapters, options-data ingest silently breaks because the 09:15 cron skips the session. |
| Fix sketch | Move options-fetch behind a `MarketDataProvider` method (probably `fetchAndSaveDailyOptions()`), implement per broker. Cron stays in `LoginScheduler` or moves to a new `OptionsDataScheduler`. |
| Effort | **M** (per broker that wants it). |
| Priority | _TBD_ |

## 13. Documentation lag from this session's changes

| | |
|---|---|
| Where | `docs/SCHEDULERS.md`, `docs/NOTIFICATIONS.md`, `docs/ORDERS_AND_POSITIONS.md`, `Readme.md`, `CLAUDE.md` |
| Why | New work added: `DaySummaryScheduler`, `MarketHoursService`, `alertDaySummary`, the trade-config admin endpoints + service. Per the doc-hygiene rule in `CLAUDE.md`, each should be reflected in its respective doc. |
| Fix sketch | One PR per doc, or a single docs-update commit. Specifically: |
| | • `SCHEDULERS.md` — add `DaySummaryScheduler` entry + the market-hours gate on the three pipeline schedulers. |
| | • `NOTIFICATIONS.md` — add `alertDaySummary` to the alert catalogue. |
| | • `ORDERS_AND_POSITIONS.md` — short "Trade-config admin" section pointing at the CRUD endpoints + cache invalidation contract. |
| | • `Readme.md` — endpoints table + `app.market.*` config block. |
| | • `CLAUDE.md` — invariant: "trade-config writes go through `TradeConfigAdminService`; never call `tradeConfigRepository.save()` directly from a controller". |
| Effort | **S** per doc; **M** as a bundle. |
| Priority | _TBD_ |
