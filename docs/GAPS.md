# Known gaps & follow-ups

Surfaced while building **(a)** the trade-config admin UI and **(b)** the
market-hours gate + end-of-day summary. Captured here as a single backlog so
priorities can be set in one place rather than chasing TODO comments through
the tree.

> **Strategy gaps do not belong in this file.** Anything that changes *what trades
> get taken* — a `Strategy` bean, its rules, the signals it emits — goes in
> **[STRATEGY_ANALYSIS_TODO.md](STRATEGY_ANALYSIS_TODO.md)** instead. This file is
> infrastructure debt: schedulers, wiring, schema, delivery. Entries #19 and #21
> were moved there and left as stubs so the numbering and inbound links still work.

Each entry: **what** / **where** / **why it matters** / **fix sketch** /
**effort hint**. Priority intentionally left blank — to be filled in by the
user.

Legend for effort:
- **S** — < 1 hour, single file
- **M** — half-day, 2-4 files + a doc update
- **L** — multi-day, schema change or cross-cutting

---

## 1. Live force-close does not place a real broker exit order — **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`OrderService.forceCloseOpenPositions`](../src/main/java/com/moneymaker/order/service/OrderService.java) |
| Why | `DaySummaryScheduler` (15:31 IST) calls this on live trades that survived market close. It only marked the DB row `CLOSED` with `exit_reason=FORCE_CLOSE` and a stale cached price. The actual broker-side position **was still open overnight** — silent risk if the broker rolls it into next-day delivery, or if SEBI auto-squareoff charges hit. |
| Resolution | The ledger update still runs first (invariant: the row is persisted before any broker call). After it, live mode sends the exit through the same `OrderPlacementService.place(order, config)` call `closeOrder` / `closeManually` already use — the row is `CLOSED` by then, which is how the placement service knows to invert the side. A returned broker id lands on `exit_broker_order_id` and moves `fill_status` to `PENDING`. Backtest mode is branched out by placement name (`BACKTESTING`) and does nothing new, so a replay's rows are byte-for-byte what they were. |
| Failure handling | The row still ends up `CLOSED` when the exit cannot be dispatched — that is unchanged — but it is no longer silent: `NotificationService.alertForceCloseExitFailed(order, reason)` fires per stranded row, naming the row and telling the operator to square off by hand. Four paths reach it: broker returned no order id, broker threw, no cached `TradeConfigCombinedDTO` (quantity unknown — placing at the fallback quantity of 1 against a 75-unit lot would open a position rather than close one), and `OrderPlacementFactory.active()` itself unresolvable. None of them abort the sweep for the remaining rows. |
| Depends on | **Zerodha `resolveTradingSymbol` is still a stub returning `null`** (its own pending item in [ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md#things-that-are-still-pending)), so on Zerodha today every live force-close exit takes the "no order id returned" path. That is the intended interim state: the alert is the deliverable until the NFO instrument-dump lookup lands. Implementing that broker client was out of scope here. |
| Left open | **(a)** Whether a failed exit should keep the row `OPEN` with a new `EXIT_FAILED` fill status instead of closing it locally — `MILESTONE_DETAILS.md` T3.2 proposes that, this change deliberately kept the existing local-close semantics per the fix sketch above; it is a ledger-semantics decision for the user. **(b)** The M3 roadmap's `app.market.force-close-time` property (a 15:25 sweep separate from the 15:31 digest) is still undecided — this change reuses the caller's `closeAt` and introduces no new timing. **(c)** Order type is whatever the placement service already sends for an exit (MARKET on Zerodha); no new variant was invented. |
| Tests | [`OrderServiceForceCloseTest`](../src/test/java/com/moneymaker/order/service/OrderServiceForceCloseTest.java) — backtest-unchanged, live-places-and-reconciles, and the four failure paths. |

> Linked: the day-summary digest reports `force-closed: N`, so the count was at least *visible* every evening even before this.

> **Noticed while fixing this, not fixed:** the sweep selects rows by
> `findByStatusAndEntryTimeBetween(OPEN, startOfToday, endOfToday)` — it only
> ever sees positions *entered today*. A row left `OPEN` by a previous day (JVM
> down at 15:31, or an exit that failed and was never squared off) is invisible
> to every subsequent sweep, so it is never force-closed and never alerted, and
> it keeps counting against `numberOfParallelTrades` for its config. The same
> carryover case is flagged from the UI side in `MILESTONE_DETAILS.md` (the
> open-trade banner should show carryover rows separately from today's).
> Widening the selector is a one-line change but it decides whether a stale row
> gets a market exit at today's price — a real-money call, so it needs the user,
> not a guess. **Impact | Unquantified.**

## 2. Day-summary P/L is per-share, not lot-multiplied — **PARTLY RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`DaySummaryScheduler.buildSummary`](../src/main/java/com/moneymaker/scheduler/DaySummaryScheduler.java) |
| Why | `trade_order.profit` is per-share (consistent with the orders ledger). The Telegram digest summed those values directly, so `P/L (per-sh): 124.50` was correct as a per-share figure but **not** the rupee-P&L the user actually cares about. |
| Resolution | Join-on-the-fly, the **S** half of the fix sketch. `lotQuantitiesFor(trades)` resolves `tradeConfigId → TradeConfig.lotQuantity` in one `findAllById` and the digest gained a `P/L (net)` line beside the existing per-share one; `by config` is now in net, and `best winner` / `worst loser` print both units (`pnl/sh=… net=…`). `lotQuantity` is the right multiplier because it is the same number the placement services hand the broker as the order quantity (`ZerodhaOrderPlacementService.quantity`, seeded from `Instrument.lotQty` by `EodDowntrendDetectionService`) — so the reported P&L and the size actually traded cannot drift apart. |
| Unknown multipliers | A config that was force-deleted, or whose `lot_quantity` is null / non-positive, has no multiplier. Those trades are **excluded** from net and declared on a `no lot qty : N trade(s) excluded from net — config(s) #9` line rather than folded in at ×1, which would print a number that looks like rupees and isn't. |
| Left open | **The snapshot column.** No `lot_quantity_at_entry` exists on `trade_order`, so the multiplier is read live. Editing a config's `lotQuantity` between a trade's entry and 15:31 makes the digest use the *edited* size — the same class of staleness `target_at_entry` (changeset 011) exists to prevent, and the **M** half of the original fix sketch. Not done here: it needs a new changeset, and Liquibase numbering was being reworked in parallel. Also unaddressed: brokerage / STT / slippage — `net` is gross premium × quantity, not what settles. |
| Effort remaining | **M** — snapshot column + write-path update in `OrderService.openOrder`. |
| Priority | _TBD_ |
| Tests | [`DaySummaryLotMultipliedPnlTest`](../src/test/java/com/moneymaker/scheduler/DaySummaryLotMultipliedPnlTest.java). |

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

## 5. Day-summary marked-as-sent even when Telegram delivery fails — **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`DaySummaryScheduler.runEndOfDay`](../src/main/java/com/moneymaker/scheduler/DaySummaryScheduler.java) — `dailyEventGuard.firstTime(...)` ran *before* the Telegram send |
| Why | If the Telegram POST failed (network blip, bot rate limit), the `alert_state` row was already persisted, so the summary was silently lost — and the guard then reported the day as done forever after. Force-close still ran correctly. |
| Resolution | The two-key gate from the fix sketch. `day-summary-forceclose` is written after `forceCloseOpenPositions` returns cleanly; `day-summary-telegram` only after Telegram confirms. Each half checks its own key with `alreadyFired(...)` first, so a retry re-sends the digest **without** force-closing a second time, and a delivered digest is never re-sent. A force-close that throws leaves its key unwritten and still lets the digest go out. |
| Delivery signal | `TelegramNotifier.send` now returns a boolean and `NotificationService.alertDaySummary` propagates it. The value answers one question only — *is there anything a retry could fix?* `false` means a POST was attempted and threw; disabled / backtest-suppressed / unconfigured all return `true`, because retrying those produces the same non-send. Every other caller ignores the return, so no other alert changed behaviour. |
| Backward compatibility | The old single `day-summary` key is still consulted. A deploy landing at 16:00, after the previous build already fired and marked the day, reads it as "both halves done" rather than as "the two new keys were never written" — otherwise the upgrade itself would re-send. |
| Left open | With the default once-a-day cron there is **no second tick** to retry on. The gate now makes a repeating `app.market.summary-cron` (e.g. every 5 min through the 15:30-16:00 window) safe to set — idempotent in both halves — but choosing that schedule is an operator decision, and the proper fix is still the manual re-run endpoint of gap #6. `runEndOfDay()` was split into a package-private `runEndOfDayFor(LocalDate)` partly to give that endpoint something to call. |
| Tests | [`DaySummarySentMarkerTest`](../src/test/java/com/moneymaker/scheduler/DaySummarySentMarkerTest.java). |

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
| Partly addressed 2026-08-25 | The bulk delete now takes `force`, which removes traded configs **and their `trade_order` rows** — see [EOD_DOWNTREND.md](EOD_DOWNTREND.md#force-deleting-configs-that-have-trades). That covers "clear out configs I no longer want", including `source: MANUAL` ones. It does **not** cover the retire-without-deleting case below: the single-config `DELETE` still 409s, and there is still no way to keep a config's history while stopping it from running. |
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
| Fix sketch | Liquibase `renameColumn` from `stratergy_id` → `strategy_id`, rename entity field, update grep-able references. Note `trade_config.strategy_ids`, `trade_order.strategy_id` and `strategy_defaults.strategy_id` all already use the correct spelling, so after the rename the odd one out disappears — but the native `fetchCombinedByTradingDate` query and its positional mapper must move in the same commit. |
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

## 13. Orphan Liquibase changesets — 016 and 017 — **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | `016_add_interval_expiry_to_market_data.xml`, `017_add_underlying_name_to_market_data.xml` — both present on disk, neither wired into [`db.changelog-master.xml`](../src/main/resources/db/changelog/db.changelog-master.xml) |
| Why | Both files add columns the team once planned to use for the M12 milestone (full live-writes-candles, [deferred to demand](MILESTONE_DETAILS.md)). They sat unwired because the supporting code was never built. |
| Investigation | Grepped the full `src/main/java` tree for `candle_interval`, `expiryDate`/`expiry_date` on `market_data`, and `underlyingName`/`underlying_name` — zero references anywhere; the `MarketData` entity has no fields for any of the three columns 016/017 would have added. The M12 use case they targeted never shipped. What *did* ship instead is a different design: changeset `018_create_historical_chart_tables.xml` (wired into master) creates dedicated `historical_spot_candles` / `historical_option_candles` tables with their own `expiry_date`/`exchange_code` columns, actively used throughout `com.moneymaker.chart.*` and `com.moneymaker.market.historical.*` (see [`HISTORICAL_CHART_DATA_PLAN.md`](HISTORICAL_CHART_DATA_PLAN.md)). 016/017's bolt-columns-onto-`market_data` approach is superseded, not merely deferred. |
| Resolution | **Deleted both files.** Neither had ever been `<include>`d in `db.changelog-master.xml` on this branch's history (confirmed via `git log`), so no Liquibase `DATABASECHANGELOG` row exists for either id on any real database — deleting them changes nothing about what any existing database has applied or will apply. Master was already correct (no edit needed). |
| Verification | New guard test (Gap #14, `LiquibaseMasterInclusionTest`) plus full `mvn test` green after the deletion — see Gap #14 below. |
| Found in the same pass | A **third**, pre-existing orphan: `005_create_market_data_table.xml`. Unlike 016/017 it is not dead — `market_data` is a live table — but it predates this project's Liquibase discipline and can't be safely wired in today (see new Gap #23). Left untouched; out of this entry's scope. |

> Surfaced during an earlier (unmerged) M0.1 pass while fixing a since-superseded copy of the 005 orphan. Same pattern (changeset on disk, not in master) is why Gap #14 exists.

## 14. No Liquibase changeset master-inclusion guard — **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | Build pipeline (none existed) |
| Why | The 005 / 016 / 017 orphans (Gap #13) prove the team was forgetting to add new changesets to `db.changelog-master.xml`. A linter / unit test that scans `db/changelog/*.xml` and asserts every file (except master itself) is `<include>`d somewhere catches this at build time, before tests or production. |
| Resolution | Added [`LiquibaseMasterInclusionTest`](../src/test/java/com/moneymaker/architecture/LiquibaseMasterInclusionTest.java) — pure file I/O, no Spring context. Three tests: every `NNN_*.xml` under `db/changelog/` is either `<include>`d by the master or named in an explicit `ALLOWLIST` (with a comment pointing at the GAPS entry that explains why); the allowlist itself can't go stale (fails if an allowlisted file is deleted or later included); and every `<include>` in the master resolves to a real file on disk (catches a rename/delete that forgot to update the master the other way). |
| Allowlist today | `005_create_market_data_table.xml` only, pointing at Gap #23 — the pre-existing orphan found while resolving Gap #13 (see above). After deleting 016/017 there was nothing left from Gap #13 itself to allowlist. |
| Effort | **S** — shipped as a single test class, no build-plugin changes. |

> Companion to Gap #13. Together these are the "stop the next orphan from happening" fix.

## 15. EMA and RSI indicator implementations are stubs returning 0.0 — **RESOLVED 2026-05-28**

| | |
|---|---|
| Resolution | **Option (a) — deleted both stub files** + their tests. `IndicatorFactory` no longer registers `"EMA"` or `"RSI"`; calling `create("EMA")` now throws `IllegalArgumentException("Unknown indicator: EMA")`. |
| Why this option | Grep confirmed zero production callers ever asked for `"EMA"` or `"RSI"` — `AnalysisScheduler.java:457` is the only `IndicatorService.calculate` caller and it hardcodes `"SMA"`. Stubs returning 0.0 with no callers were pure dead code; tests pinning them were maintenance overhead for no value. |
| Re-adding later | When a strategy actually needs EMA / RSI: implement using the `SMAIndicatorImpl` ta4j pattern (real calculation, not a stub), add the `registry.put(...)` line back, write real tests (not stub-pinning). The factory comment block documents the contract. |
| Test outcome | `IndicatorFactoryTest.EMA_and_RSI_no_longer_registered_after_gap_15_resolution` pins the new contract so anyone re-registering without removing this test gets a clear failure. |
| Shipped | Commit `_M1.5_` (see CHANGELOG). |

## 16. M10 strike caching — design premise contradicted by actual code

| | |
|---|---|
| Where | [`AnalysisScheduler.calculateStrikesForCandles:222`](../src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java#L222) |
| Why | M10 in MILESTONE_DETAILS proposed per-(date, configId) caching, justified by "strikes anchored on first candle of the day → stable intraday." The implementation actually anchors on `marketDataList.get(marketDataList.size()-1)` — the LAST candle (latest tick's close). Spot moves intraday → ATM base shifts → strike set shifts. Naively caching would change live behavior, not just performance. |
| Decision needed | Three paths: **(a)** Change anchor to first-of-day candle — real behavior change (strikes fixed at 09:15 spot for the day; matches the M10 spec but needs strategy-owner sign-off because it alters what gets traded). **(b)** Memoise by `(date, configId, lastCandleTimestamp)` — pure caching but the inner key changes per tick so there's no real saving. **(c)** Skip M10 entirely — accept that strike compute is intentionally per-tick and the "stable within day" claim was wrong. |
| Recommendation | (a) is the right move IF the strategy owner agrees to the locked-anchor semantics. (c) is the cheap close. Don't ship without that decision. |
| Surfaced | While trying to implement M10 in the "complete all" session — the architect-engineer debate during planning had assumed (a) but neither party verified against code. |

## 17. Documentation lag from this session's changes — **RESOLVED 2026-08-16**

| | |
|---|---|
| Where | `docs/SCHEDULERS.md`, `docs/NOTIFICATIONS.md`, `docs/ORDERS_AND_POSITIONS.md`, `Readme.md`, `CLAUDE.md`, `AGENTS.md` |
| Why | New work added: `DaySummaryScheduler`, `MarketHoursService`, `alertDaySummary`, the trade-config admin endpoints + service. Per the doc-hygiene rule in `CLAUDE.md`, each should be reflected in its respective doc. |
| Resolution | All five bullets below landed in the same documentation pass that also resolved this merge conflict and added [`docs/WORKFLOWS.md`](WORKFLOWS.md): |
| | • `SCHEDULERS.md` — added `DaySummaryScheduler` entry + the market-hours gate on the three pipeline schedulers. |
| | • `NOTIFICATIONS.md` — added `alertDaySummary` + `alertNoActiveSession` to the alert catalogue. |
| | • `ORDERS_AND_POSITIONS.md` — added a "Trade-config admin" section pointing at the CRUD endpoints + cache invalidation contract. |
| | • `Readme.md` — refreshed the endpoints table, package map, and feature list to match current code. |
| | • `CLAUDE.md` / `AGENTS.md` — added the invariant: "trade-config writes go through `TradeConfigAdminService`; never call `tradeConfigRepository.save()` directly from a controller". |
| Effort | **S** per doc; **M** as a bundle. |

## 18. `SharedData.optionTokenMap` was keyed by strike alone — **RESOLVED 2026-08-22**

| | |
|---|---|
| Where | [`SharedData.optionTokenMap`](../src/main/java/com/moneymaker/shared/data/SharedData.java), consumed by [`AnalysisScheduler.fetchAndShareStrikeMarketData`](../src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java) |
| Why | The map cached `strike → optionToken` with `Map<Integer, String>`. A strike is not a contract. On any day that has both a CE and a PE `trade_config` — which is the normal shape, and exactly what `AUTO_DOWNTREND` generates in pairs — both configs walk the same strike list, so whichever ran first populated the entry and the second silently reused it. The result was a CE config analysing PE candles: `[strikes]` showed `21800 CE` and `21800 PE` at an identical premium. It also collided across expiries on a multi-day run, and the map was never cleared between backtest days. |
| Impact | Pre-existing in broker mode too, not introduced by the historical data source — that source only made it obvious, because the two legs' prices are visibly wrong side-by-side. Any multi-config backtest or live day before this fix could have entered on the wrong leg's signal. |
| Resolution | Key is now `expiry\|strike\|optionType` via `SharedData.optionTokenKey(...)`, and `BacktestAnalysisService` clears the map in its day-end `finally` block alongside the other per-day caches. |
| Effort | **S** |

## 19. `Strategy1` scanned every config's legs, not its own — **RESOLVED 2026-08-25** *(moved)*

> Strategy gaps now live in **[STRATEGY_ANALYSIS_TODO.md](STRATEGY_ANALYSIS_TODO.md)**.
> This entry is [S2](STRATEGY_ANALYSIS_TODO.md#s2-strategy1-scanned-every-configs-legs-not-its-own--resolved-2026-08-25).
> Number kept so #20 and the [#18] cross-reference still resolve.

## 20. `MarketDataProviderFactory.java` is an empty file

| | |
|---|---|
| Where | [`market/provider/MarketDataProviderFactory.java`](../src/main/java/com/moneymaker/market/provider/MarketDataProviderFactory.java) — 0 bytes, no class |
| Why | Provider selection is currently spread across `@ConditionalOnProperty` annotations on each provider, with `ZerodhaMarketDataProvider` declaring `matchIfMissing = true`. That makes the single-provider injection point in `KiteHistoricalFetcher` fragile: any second `MarketDataProvider` bean is ambiguous unless it is `@Primary`. `HistoricalIciciMarketDataProvider` has to carry `@Primary` for exactly this reason. `GrowwMarketDataProvider` and `CustomMarketDataProvider` are both gated on `market.data.provider`, a key that is not in `application.properties` at all, so neither can ever register. |
| Fix sketch | Fill the factory: inject `List<MarketDataProvider>`, select by an explicit property, and have `KiteHistoricalFetcher` depend on the factory rather than on a single bean. Then drop `matchIfMissing` and the `@Primary` workaround, and either wire up or delete the two dead providers. |
| Effort | **M** — touches provider wiring; needs a live-mode start-up check. |
| Priority | _TBD_ |

## 21. `Strategy2`'s SMA-20 slope filter is inert when the slope is unknown *(moved)*

> Strategy gaps now live in **[STRATEGY_ANALYSIS_TODO.md](STRATEGY_ANALYSIS_TODO.md)**.
> This entry is [S1](STRATEGY_ANALYSIS_TODO.md#s1-strategy2s-sma-20-slope-filter-is-inert-when-the-slope-is-unknown--parked-2026-08-30).

## 22. Session-window constants are hardcoded while `app.market.*` already exists *(moved)*

> Strategy gaps now live in **[STRATEGY_ANALYSIS_TODO.md](STRATEGY_ANALYSIS_TODO.md)**.
> This entry is [S5](STRATEGY_ANALYSIS_TODO.md#s5-session-window-constants-are-hardcoded-while-appmarket-already-exists).
> Filed here first by mistake before Rule 0 landed; number kept so a later #23 does not collide.

## 23. Orphan Liquibase changeset — 005_create_market_data_table.xml

| | |
|---|---|
| Where | [`005_create_market_data_table.xml`](../src/main/resources/db/changelog/005_create_market_data_table.xml) — present on disk, not `<include>`d in [`db.changelog-master.xml`](../src/main/resources/db/changelog/db.changelog-master.xml) (master's only `005_*` include is `005_create_broker_session_table.xml`) |
| Why | Discovered while resolving Gap #13/#14: [`LiquibaseMasterInclusionTest`](../src/test/java/com/moneymaker/architecture/LiquibaseMasterInclusionTest.java) scans every numbered changeset, not just the two named in Gap #13, and this one is a genuine third orphan — unrelated to 016/017, and older (its `createTable` predates them). Unlike 016/017 it is **not** dead: `market_data` is the live table every SMA/analysis/backtest read hits. It has survived unwired this whole time because `spring.jpa.hibernate.ddl-auto=update` (`application.properties`) creates the table straight from the `MarketData` JPA entity on every boot, so Liquibase never had to. |
| Risk | Unlike 016/017, this changeset carries **no** `preConditions` guard — it's an unconditional `<createTable tableName="market_data">`. Wiring it into master as-is would throw "table already exists" against every environment that has ever booted this app (i.e. all of them), since Hibernate already created the table. That is the hard-constraint failure mode this whole cleanup was trying to avoid, so it was left alone rather than "fixed" in the same pass. |
| Fix sketch | Add a `<preConditions onFail="MARK_RAN"><not><tableExists tableName="market_data"/></not></preConditions>` block (same pattern 016/017 used for `columnExists`), matching how Hibernate + Liquibase already coexist elsewhere in this schema. Then include it in master, positioned before `007_add_sma_value_to_market_data.xml` (which `ALTER`s the table). Needs a real verification pass (H2 fresh-install boot, or a scratch MySQL) before landing — this doc's author did not attempt it, per the hard constraint on GAPS #13/#14 not to touch what Liquibase applies without that verification. |
| Effort | **S** for the precondition + include; the verification is the part worth budgeting time for. |
| Priority | _TBD_ |

> The `LiquibaseMasterInclusionTest` allowlist (Gap #14) names this file explicitly, pointing back at this entry, so the guard test stays green without silently hiding the gap.
