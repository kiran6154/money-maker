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

## 13. Orphan Liquibase changesets — 016 and 017

| | |
|---|---|
| Where | [`016_add_interval_expiry_to_market_data.xml`](../src/main/resources/db/changelog/016_add_interval_expiry_to_market_data.xml), [`017_add_underlying_name_to_market_data.xml`](../src/main/resources/db/changelog/017_add_underlying_name_to_market_data.xml) — both present on disk, neither wired into [`db.changelog-master.xml`](../src/main/resources/db/changelog/db.changelog-master.xml) |
| Why | Both files add columns the team plans to use for the M12 milestone (full live-writes-candles). They sit unwired because the supporting code isn't ready yet. Both files already carry `columnExists` preconditions with `onFail=MARK_RAN`, so they're safe to include in master immediately — production would simply mark them ran without executing. Leaving them unwired risks the same class of bug surfaced in M0.1 (orphan 005): a future test environment or fresh install ends up with inconsistent schema. |
| Fix sketch | Either (a) include both in master now (safe — preconditions handle production), or (b) physically delete the files until M12 needs them. Choose one; the worst option is "leave them sitting there." |
| Effort | **S** |
| Priority | _TBD_ |

> Surfaced during M0.1 while fixing the 005 orphan. Same pattern (changeset on disk, not in master) suggests the team needs a Liquibase pre-commit check.

## 14. No Liquibase changeset master-inclusion guard

| | |
|---|---|
| Where | Build pipeline (none exists) |
| Why | The 005 / 016 / 017 orphans (Gaps #13) prove the team is forgetting to add new changesets to `db.changelog-master.xml`. A linter / unit test that scans `db/changelog/*.xml` and asserts every file (except master itself) is `<include>`d somewhere would catch this at build time, before tests or production. |
| Fix sketch | Small Java test: glob `db/changelog/00*.xml`, parse master, assert every changeset file is referenced. ArchUnit-style. |
| Effort | **S** |
| Priority | _TBD_ |

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

## 19. `Strategy1` scanned every config's legs, not its own — **RESOLVED 2026-08-25**

| | |
|---|---|
| Where | [`Strategy1.keyMatches`](../src/main/java/com/moneymaker/strategy/Strategy1.java), reading [`SharedData.strikeMarketDataByInstrumentAndInterval`](../src/main/java/com/moneymaker/shared/data/SharedData.java) written by [`AnalysisScheduler.toStrikeMarketDataKey`](../src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java) |
| Why | The writer keys each entry `instrumentToken\|interval\|optionType\|strike\|optionToken\|itmDepth\|otmDepth` and contributes only the legs of the config that fetched them. The reader matched a `instrumentToken\|interval\|` **prefix** only — `optionType` and both depths were never compared. `trading_side` reached the strategy solely as the sort direction (`strikeComparator(isCe)`), never as a filter, so every config scanned the union of all configs' legs. |
| Impact | On any day with the normal CE + PE config pair, each signal fired once under each config id and the ledger recorded **every trade twice**, with half the rows carrying an option type contradicting their own config's `trading_side` (e.g. a PE trade booked under a CE config). Realised P&L over such a run is doubled. The `existsByTradeConfigIdAndOptionTokenAndEntryDirectionAndEntryTime` dedupe guard could not catch it — it keys on `tradeConfigId`, so the pairs are legitimately distinct rows. Where several legs fired on one tick the two configs landed on *different* strikes instead of identical ones, because they sort in opposite directions and `no_of_parrellel_trades` cut the scan short at opposite ends — which is why the duplication was not uniform and read as "sometimes the wrong strike". |
| Resolution | `keyMatches` now splits the key and compares `optionType` against the config's resolved `trading_side` plus both depth segments against the config's own. `isCallSide` became `resolveOptionType`, mirroring `AnalysisScheduler.resolveOptionType` including its null-on-unresolved behaviour — the writer skips the fetch for an unresolved side, so defaulting to CE would have made such a config scan someone else's legs. |
| Related | Sibling of [#18](#18-shareddataoptiontokenmap-was-keyed-by-strike-alone--resolved-2026-08-22) — same root shape (a shared cache whose key was less specific than its contents), different map. |
| Effort | **S** |

## 20. `MarketDataProviderFactory.java` is an empty file

| | |
|---|---|
| Where | [`market/provider/MarketDataProviderFactory.java`](../src/main/java/com/moneymaker/market/provider/MarketDataProviderFactory.java) — 0 bytes, no class |
| Why | Provider selection is currently spread across `@ConditionalOnProperty` annotations on each provider, with `ZerodhaMarketDataProvider` declaring `matchIfMissing = true`. That makes the single-provider injection point in `KiteHistoricalFetcher` fragile: any second `MarketDataProvider` bean is ambiguous unless it is `@Primary`. `HistoricalIciciMarketDataProvider` has to carry `@Primary` for exactly this reason. `GrowwMarketDataProvider` and `CustomMarketDataProvider` are both gated on `market.data.provider`, a key that is not in `application.properties` at all, so neither can ever register. |
| Fix sketch | Fill the factory: inject `List<MarketDataProvider>`, select by an explicit property, and have `KiteHistoricalFetcher` depend on the factory rather than on a single bean. Then drop `matchIfMissing` and the `@Primary` workaround, and either wire up or delete the two dead providers. |
| Effort | **M** — touches provider wiring; needs a live-mode start-up check. |
| Priority | _TBD_ |
