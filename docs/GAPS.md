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
| Depends on | ~~Zerodha `resolveTradingSymbol` is a stub returning `null`~~ — **cleared 2026-08-31.** The contract is now resolved by `instrument_details` primary-key lookup on `trade_order.option_token` (a lookup, never a formatter — NFO weekly and monthly symbols for the same strike are `NIFTY2660223400CE` vs `NIFTY26JUN23400CE`, and no single rule produces both). Live force-close on Zerodha now reaches the broker; the per-row alert fires only on a real failure. See [Zerodha contract resolution](ORDERS_AND_POSITIONS.md#zerodha-contract-resolution). |
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

## 3. Heartbeat runs 24/7 -- **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`LoginScheduler.heartbeat`](../src/main/java/com/moneymaker/scheduler/LoginScheduler.java) — `@Scheduled(fixedDelay = 60_000L)` |
| Why | This was left alone in the market-hours work because heartbeat is the only thing that catches token death. But it really only matters during a day window where login/options-fetch crons run — outside ~07:50–15:40 IST the broker session staying valid is moot until tomorrow's 08:00 login. Cost today is small (1 quote/min), but it produces noise in logs and the AUTH_FAIL Telegram could fire at 22:00 on a Friday for no reason. |
| Resolution | The fix sketch as written. `MarketHoursService.isWithinHeartbeatWindow()` returns true on weekdays between `app.market.heartbeat-start` and `app.market.heartbeat-end` inclusive, defaulting to the 07:50-15:40 this entry proposed; `LoginScheduler.heartbeat()` short-circuits outside it and does not read the session or touch the broker. The probe moved to a package-private `runHeartbeat()` with no clock opinion, so the `@Scheduled` method holds only the wall-clock concern -- the same wrapper/method split GAPS #4 applied to the pipeline schedulers. |
| Why absolute times and not offsets | The other derived session times in `MarketHoursService` (close-signal, replay bounds) are offsets from open/close, and these deliberately are not. What the lower bound has to clear is the **08:00 login cron**, not the session open: alerts fire on transitions, so a token that died overnight must be probed before login runs for the alert to reach a human in time. An offset from `app.market.open` would drift past 08:00 the moment someone moved the open, which is exactly the case where the margin matters. |
| Live parity | Unchanged during trading hours, and not merely by inspection: `MarketHoursService.init` throws if the configured window does not contain `[open, close]`, so a window that clipped the session cannot start the app. A test also walks every minute of 09:15-15:30 and asserts the gate is open. |
| New properties | `app.market.heartbeat-start` (07:50), `app.market.heartbeat-end` (15:40). |
| Not changed | The 08:00 login cron, the 09:15 options fetch, the state machine, and the alert rules. Only *when the probe runs*. |
| Tests | [`HeartbeatWindowTest`](../src/test/java/com/moneymaker/scheduler/HeartbeatWindowTest.java) — tick inert outside / probing inside, `runHeartbeat()` unaffected by the window, boundary inclusivity, the 08:00 cron covered, full session coverage, weekends out, and both directions of the startup validation. |

## 4. Pipeline cron annotations fire in backtest mode too — **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`AnalysisScheduler`](../src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java), [`OrderScheduler`](../src/main/java/com/moneymaker/scheduler/OrderScheduler.java), [`PositionScheduler`](../src/main/java/com/moneymaker/scheduler/PositionScheduler.java) — `@Scheduled(cron = "0 0/5 9-16 * * MON-FRI")` |
| Why | The cron triggers fire at wall-clock 09:00, 09:05, … 16:55 even when the JVM is doing a multi-day historical replay. |
| **This entry's premise was wrong, and the bug was not cosmetic** | It read "today this is harmless (the gates short-circuit)". The gate it refers to is `if ("live".equalsIgnoreCase(appMode) && !marketHours.isOpenNow())` — it short-circuits **only in live mode**. With `app.mode=backtest` the condition is false, so the body ran in full. A replay started on a weekday between 09:00 and 16:55 IST therefore had a second, wall-clock-driven pipeline running against the same static state on the scheduler thread: `AnalysisScheduler` fetching *today's* candles into the same `SharedData.strikeMarketDataByInstrumentAndInterval` map the replay reads, `OrderScheduler` draining `SharedData.tradeSignals` out from under the replay's own `processOrders()`, and `PositionScheduler` marking the replay's OPEN rows against wall-clock quotes. No real broker order was ever at risk (`OrderPlacementFactory` returns `BACKTESTING` in backtest mode), but the ledger a replay produced was not purely a function of the replayed window. See [STRATEGY_ANALYSIS_TODO.md S11](STRATEGY_ANALYSIS_TODO.md#s11-wall-clock-scheduler-threads-mutate-replay-state-mid-run) for what that means for measurements already recorded. |
| Resolution | Neither branch of the fix sketch. **(a) is not available**: `BacktestAnalysisService` injects all three beans and calls them per tick, so `@ConditionalOnProperty(havingValue="live")` would delete the replay's own pipeline, not just its cron. Instead the `@Scheduled` method became a thin wall-clock wrapper holding *only* wall-clock concerns — the backtest gate and the existing live market-hours gate — delegating to the replayable method underneath. That is the split invariant 8 already asks for. `AnalysisScheduler.analyzeMarketData()` was already that wrapper and just gained the gate; `OrderScheduler` and `PositionScheduler` had the cron annotation sitting directly on `processOrders()` / `processPositions()` — the very methods the replay calls — so each grew a `scheduledTick()` wrapper above the unchanged method. |
| Mode source | `@Value("${app.mode:live}")`, the same key `TelegramNotifier`'s backtest-suppression gate reads, moved from field to constructor injection on all three so a unit test can build the bean in either mode. No new property. |
| Live parity | Byte-for-byte. The market-hours guard kept its exact original expression (`"live".equalsIgnoreCase(appMode) && !isOpenNow()`) rather than being simplified to `!isOpenNow()`, so a mode that is neither `live` nor `backtest` behaves as it did. Same cron expressions, same cadence, same delegation order. |
| Not fixed here | The cron **trigger** still fires in backtest — it is the body that is now inert. Removing the trigger needs either bean-level conditioning (ruled out above) or a `SchedulingConfigurer` / `Scheduled.CRON_DISABLED` property, and the latter would mean inventing a new key. The per-tick cost of a no-op trigger is the "tiny" one this entry originally described. |
| Also unfixed, deliberately | [`TradeConfigScheduler`](../src/main/java/com/moneymaker/scheduler/TradeConfigScheduler.java)'s `0 16 9 * * MON-FRI` cron is **not** gated — this entry names three schedulers and that is not one of them. It assigns `SharedData.combinedDto` from the live DB, which a replay reassigns per tick, so the exposure is a narrower cross-thread race rather than a standing clobber. Filed as [S11](STRATEGY_ANALYSIS_TODO.md#s11-wall-clock-scheduler-threads-mutate-replay-state-mid-run) because it decides which configs get dispatched. Its `0 12 9` sibling only logged, and was deleted 2026-08-31 under GAPS #11. `LoginScheduler` (bean-level `@ConditionalOnProperty`) and `DaySummaryScheduler` (live-only guard) were already gated. |
| Tests | [`PipelineCronBacktestGateTest`](../src/test/java/com/moneymaker/scheduler/PipelineCronBacktestGateTest.java) — per scheduler: cron inert in backtest, cron runs in live with the market open, live market-hours gating unchanged, and the explicit call the replay makes unaffected by mode. |

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

## 6. No manual re-run for end-of-day work -- **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`DaySummaryAdminController`](../src/main/java/com/moneymaker/admin/controller/DaySummaryAdminController.java) |
| Where | n/a — endpoint doesn't exist |
| Resolution | `POST /api/admin/day-summary?date=&force=`, exactly the sketch. Calls `DaySummaryScheduler.runEndOfDayFor(date, force)` -- the method GAPS #5 split out for this purpose -- which now takes the force flag and returns the number of positions it closed. `date` defaults to today in `app.market.timezone`; a weekend date is rejected 400 with the reason rather than returning a silent success the caller has to interpret. |
| Idempotency is inherited, not written | Without `force` this needed **no new logic**: the two-key sent-marker gate from GAPS #5 already records which half completed, so a plain re-run executes the pending half and skips the finished one. A missed 15:31 runs both halves; a failed Telegram re-sends the digest and does *not* force-close twice; a completed day does nothing, however many times it is called. `force` bypasses the markers and exists for the one case they cannot see -- the digest was delivered and it was wrong, because it fired before a delayed close. |
| Also fixed here | The caveat GAPS #5 left on `runEndOfDayFor`: the close moment came from `marketHours.marketCloseToday()`, so a back-dated re-run would have stamped a past day's exits with today's close. New `MarketHoursService.marketCloseOn(date)` / `marketOpenOn(date)` make it date-aware. For `date = today` the value is identical, so the 15:31 cron is byte-for-byte unchanged -- worth doing before shipping the endpoint rather than after, because the exit timestamp is what every downstream report reads. |
| Not mode-gated | Unlike the cron, on purpose: an operator hitting this asked for it explicitly, and in backtest `TelegramNotifier` suppresses the send while `OrderPlacementFactory` resolves to `BACKTESTING`, so nothing reaches a broker. |
| Left open | No authentication. The endpoint sits behind whatever fronts the app, the same as `/api/orders/purge` and `/api/trade-configs/auto/delete` -- a standing gap for the whole admin surface, not this endpoint's to solve. |
| Tests | [`DaySummaryManualRerunTest`](../src/test/java/com/moneymaker/admin/controller/DaySummaryManualRerunTest.java) -- drives the real `DaySummaryScheduler` through the controller rather than mocking it, so the idempotency claim is exercised rather than restated: missed run replays both halves, completed day is a no-op (including under repeated calls), only the pending half replays, force bypasses both markers, a back-dated run uses that day's close, and the weekend rejection. |

## 7. Trade-config delete blocked by `trade_order` history -- no soft-delete path -- **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`TradeConfigAdminService.setActive`](../src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java), `POST /api/trade-configs/{id}/active?value=` |
| Where | [`TradeConfigAdminService.delete`](../src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java) → HTTP 409 |
| Why | Configs that ever fired a trade can't be removed, ever. Operationally fine for audit but the list view will grow forever — and there's no way to mark a config as "retired, do not run anymore today" without changing its `trading_date` to a past day. |
| Resolution | The fix sketch, at changeset **037** rather than 018 (018 was already taken twice). `trade_config.is_active BOOLEAN NOT NULL DEFAULT TRUE`, backfilled TRUE, and `fetchCombinedByTradingDate` -- the query that builds `SharedData.combinedDto`, i.e. the actual dispatch list -- gained `AND COALESCE(tc.is_active, TRUE) = TRUE`. A retired config keeps its id, its `sma_timeframe` children and every `trade_order` row, and simply stops being scanned. `findByTradingDate` was deliberately **not** narrowed: the admin list has to show retired configs or you cannot reinstate one. |
| Behaviour on deploy | Unchanged. Everything is active until someone retires it, and `COALESCE` rather than a bare `= TRUE` means a row that somehow carries NULL still dispatches -- "unknown" must mean active, because the alternative is silently retiring every config on the day 037 lands. |
| UI | Row action in `trade-configs.html`: **Retire** / **Reinstate**, with retired rows dimmed so they cannot be misread as trading today. Hard delete is unchanged for configs that never traded, and its 409 message now names the retire endpoint instead of leaving the operator at a dead end. |
| **Retiring is refused while trades are OPEN** | Found while building this, and it is the interesting part. A retired config leaves `SharedData.combinedDto` -- and `OrderService.findConfig` reads exactly that list to size an **exit**. With no DTO the exit is not dispatched: the row is marked `CLOSED` and the broker position stays open, which is one of the four paths GAPS #1's `alertForceCloseExitFailed` exists for. A confirmation dialog does not make that outcome less wrong, so `setActive(id, false)` refuses and says to close the trades first. Reinstating is never blocked. |
| Filed, not fixed (Rule 0) | The underlying resolution bug is **older than this feature** -- editing `tradingDate` into the past does the same thing, and that is the very workaround this entry set out to replace. Filed as [S13](STRATEGY_ANALYSIS_TODO.md#s13-a-config-that-leaves-shareddatacombineddto-mid-day-strands-its-open-trades-broker-exits) because it decides whether an open trade actually gets closed at the broker. When S13 lands, this refusal can relax to a warning. |
| Tests | [`TradeConfigRetireAndConfirmTest`](../src/test/java/com/moneymaker/tradeconfig/service/TradeConfigRetireAndConfirmTest.java) -- retire keeps the row and deletes nothing, refuses with open trades, allows once flat, reinstate is never blocked, a pre-037 NULL reads as active, and the delete message names the alternative. |

## 8. Trade-config edit silently allowed while OPEN trades exist on that config -- **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`TradeConfigAdminService.update`](../src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java) |
| Why | Target / SL changes are safe (the order has snapshot fields from changeset 011), but changing `transactionType`, `numberOfParallelTrades` or `lotQuantity` mid-day on a config that has 3 open trades will subtly alter the rest of the day's behaviour without warning. |
| Resolution | The **stricter** half of the fix sketch, because the cheap banner cannot know what the user is about to change -- it can only say "this config has open trades", which is the kind of standing warning people stop reading. `PUT /api/trade-configs/{id}` returns **409 with `confirmRequired: true`** and the list of changes; the same request with `?confirm=true` applies it. It is a warning, not a block: nothing is refused, and the UI dialog names each change (`lotQuantity: 75 -> 150`) rather than asking a generic "are you sure?". |
| The rule for what counts | One line: **a field is consequential unless the order snapshotted it at entry.** Target / stop-loss / their percentage forms / the max-SL cap / the trailing ladder are all absent from the gate, because changesets 011 / 036 snapshot them onto `trade_order` precisely so a mid-day edit cannot re-price an open position. Warning about those would be false and would train the operator to click through. What is left, and therefore gated: `transactionType`, `tradingSide`, `lotQuantity`, `numberOfTradesPerDay`, `numberOfParallelTrades`, `strategyId`, `instrument`, `tradingDate`. |
| Wider than the entry's three | The entry named `transactionType`, `numberOfParallelTrades` and `lotQuantity`. The rule above pulls in five more for the same reason those three qualify: `tradingSide` picks the leg, `numberOfTradesPerDay` is the other lifecycle cap, `strategyId` is half the `(config, strategy)` identity the caps are counted against, and `instrument` / `tradingDate` make it a different config wearing the same id. Enumerating three of eight would have been arbitrary. |
| Why `lotQuantity` matters despite changeset 029 | `trade_order.quantity` **is** snapshotted, but the placement services size an order from the *config* (`ZerodhaOrderPlacementService.quantity`), so an open trade would exit at a different size than it entered -- a partial close or an accidental reversal, not a resize. |
| Only OPEN trades gate | A config with a hundred closed trades and nothing live edits freely; `countByTradeConfigIdAndStatus(id, "OPEN")` is the check, not `existsByTradeConfigId`. |
| Tests | [`TradeConfigRetireAndConfirmTest`](../src/test/java/com/moneymaker/tradeconfig/service/TradeConfigRetireAndConfirmTest.java) -- no open trades means no gate, bracket-only and no-op edits never ask, `lotQuantity` asks and writes nothing, all eight fields report at once, `confirm=true` applies, and closed-only history does not gate. |

## 9. No "clone yesterday's configs to today" workflow -- **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`TradeConfigAdminService.cloneDay`](../src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java), `POST /api/trade-configs/clone?fromDate=&toDate=&dryRun=` |
| Where | n/a — single-row clone or bulk-clone both not built |
| Resolution | Both halves of the fix sketch. The **bulk** endpoint is new; the `⧉ Clone` **row action** already existed in `trade-configs.html` (it pre-fills the form from an existing config), so only the day-level copy was missing. The toolbar gained a `Clone a day…` button that previews and then confirms. |
| Why the SQL workaround was worse than tedious | `INSERT ... SELECT ... WHERE trading_date='yesterday'` bypasses `TradeConfigAdminService`, and therefore the cache-invalidation contract of invariant 10: the rows exist in MySQL while `TradeConfigScheduler`'s date cache and `SharedData.combinedDto` keep the old snapshot, so the running pipeline does not see them until the next restart. Going through the service is the whole point of the endpoint, not just convenience. |
| Dry run by default | Same shape as the bulk delete: a caller who omits `dryRun` gets a preview with the server's real counts, and the UI confirms against those rather than its own guess. |
| Three decisions | **(a) Retired configs are not cloned** -- `is_active=false` means "do not run this", and carrying it forward as active would resurrect exactly what someone retired. Counted and named in the summary rather than quietly missing. **(b) Clones are stamped `MANUAL`, whatever the source was.** Keeping `AUTO_DOWNTREND` would hand the row to `EodDowntrendDetectionService`'s dedupe key, which reads "a config already exists for this (day, strategy)" as "I already generated" -- so cloning an AUTO config forward would silently suppress the detector's own output for that day. **(c) Cloning a day onto itself is rejected**: it could only duplicate every config. |
| Idempotency | Re-running is safe. A source config is skipped when the destination already carries an equivalent one -- same instrument, trading side, transaction type and primary strategy. That tuple is **not** a database key, so this is deliberately best-effort: a hand-built config that happens to match is treated as already-cloned and reported as skipped rather than silently doubled. Doubling configs doubles positions, so the ambiguity is resolved toward the recoverable failure. |
| The copy is longhand | `copyForDate` lists every column by name rather than reflecting or serialising. A new column nobody adds there is silently dropped from every clone, and a compile-time list is the only thing that makes the omission visible -- the same reason `applyForm` / `toView` are longhand, and the same trap documented in ORDERS_AND_POSITIONS about a column missing from one of the four places. |
| Tests | [`TradeConfigCloneDayTest`](../src/test/java/com/moneymaker/tradeconfig/service/TradeConfigCloneDayTest.java) -- clones a day and invalidates the cache, carries every field including the 027/036 bracket columns, copies `sma_timeframe` children as new rows, stamps MANUAL, leaves retired configs behind, skips what the destination already has, collapses duplicate sources, dry-run writes nothing, self-clone rejected, empty source reported. |

## 10. `TradeConfig.stratergyId` — column name typo

| | |
|---|---|
| Where | [`TradeConfig.java`](../src/main/java/com/moneymaker/entity/TradeConfig.java) line `@Column(name="stratergy_id")`; same name in changeset 003 |
| Why | Annoying every time someone autocompletes; bug-bait. |
| Fix sketch | Liquibase `renameColumn` from `stratergy_id` → `strategy_id`, rename entity field, update grep-able references. Note `trade_config.strategy_ids`, `trade_order.strategy_id` and `strategy_defaults.strategy_id` all already use the correct spelling, so after the rename the odd one out disappears — but the native `fetchCombinedByTradingDate` query and its positional mapper must move in the same commit. |
| Effort | **M** — straightforward but cross-cutting. |
| Priority | _TBD_ |

## 11. `TradeConfigScheduler.dailyTaskAt912AM` is a no-op stub -- **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | `TradeConfigScheduler.dailyTaskAt912AM` — `@Scheduled(cron = "0 12 9 * * MON-FRI")` |
| Why | Logs a line, does nothing. Either it has a planned job that was never written, or it should be deleted to stop confusing readers. |
| Resolution | **Deleted**, the fix sketch's default. No intent was found: grep across `src/`, `docs/` and the templates turned up no caller, no test, and no design note describing a job for the 09:12 slot — only this entry, its `IMPLEMENTATION_PLAN` / `MILESTONE_DETAILS` restatements (M5.4, which reached the same conclusion), and the passing mention in GAPS #4 confirming it "only logs". A comment is left in its place so the next reader knows the 09:12 slot was empty by decision rather than by omission. |
| Not touched | The `0 16 9` sibling (`checkTradeConfigAt916AM`) and its mode-gating question, which is a separate open item — see GAPS #4's "Also unfixed, deliberately" row and [S11](STRATEGY_ANALYSIS_TODO.md#s11-wall-clock-scheduler-threads-mutate-replay-state-mid-run). |
| Tests | None — a deletion with no callers. `mvn test` green covers the compile. |

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
| Found in the same pass | A **third**, pre-existing orphan: `005_create_market_data_table.xml`. Unlike 016/017 it is not dead — `market_data` is a live table — but it predates this project's Liquibase discipline and could not be safely wired in without a verification pass (see Gap #23). Left untouched here; **resolved 2026-08-31** under its own entry. |

> Surfaced during an earlier (unmerged) M0.1 pass while fixing a since-superseded copy of the 005 orphan. Same pattern (changeset on disk, not in master) is why Gap #14 exists.

## 14. No Liquibase changeset master-inclusion guard — **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | Build pipeline (none existed) |
| Why | The 005 / 016 / 017 orphans (Gap #13) prove the team was forgetting to add new changesets to `db.changelog-master.xml`. A linter / unit test that scans `db/changelog/*.xml` and asserts every file (except master itself) is `<include>`d somewhere catches this at build time, before tests or production. |
| Resolution | Added [`LiquibaseMasterInclusionTest`](../src/test/java/com/moneymaker/architecture/LiquibaseMasterInclusionTest.java) — pure file I/O, no Spring context. Three tests: every `NNN_*.xml` under `db/changelog/` is either `<include>`d by the master or named in an explicit `ALLOWLIST` (with a comment pointing at the GAPS entry that explains why); the allowlist itself can't go stale (fails if an allowlisted file is deleted or later included); and every `<include>` in the master resolves to a real file on disk (catches a rename/delete that forgot to update the master the other way). |
| Allowlist today | **Empty as of 2026-08-31.** Its only entry, `005_create_market_data_table.xml`, was removed when Gap #23 was resolved and the file was wired into the master. |
| Grew a fourth test 2026-08-31 | `schema_locations_resolve_to_a_bundled_xsd` -- every changeset must declare an XSD that the liquibase-core on the classpath actually ships. Added because resolving Gap #23 turned up a changeset naming a nonexistent `dbchangelog-4.23.0.xsd`; with `secureParsing=true` that is a hard parse failure at startup, not a silent fallback. Same class of bug as the orphan itself: harmless only while nothing reads the file. |
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

## 16. M10 strike caching -- design premise contradicted by actual code -- **CLOSED 2026-08-31 (option (c))**

| | |
|---|---|
| Where | [`AnalysisScheduler.calculateStrikesForCandles:222`](../src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java#L222) |
| Why | M10 in MILESTONE_DETAILS proposed per-(date, configId) caching, justified by "strikes anchored on first candle of the day → stable intraday." The implementation actually anchors on `marketDataList.get(marketDataList.size()-1)` — the LAST candle (latest tick's close). Spot moves intraday → ATM base shifts → strike set shifts. Naively caching would change live behavior, not just performance. |
| Decision needed | Three paths: **(a)** Change anchor to first-of-day candle — real behavior change (strikes fixed at 09:15 spot for the day; matches the M10 spec but needs strategy-owner sign-off because it alters what gets traded). **(b)** Memoise by `(date, configId, lastCandleTimestamp)` — pure caching but the inner key changes per tick so there's no real saving. **(c)** Skip M10 entirely — accept that strike compute is intentionally per-tick and the "stable within day" claim was wrong. |
| Decision (approved by the user 2026-08-31) | **(c) -- skip M10 entirely. No code change.** Strike computation is *intentionally* per-tick, and the M10 premise that the active strike set is stable within a day was simply wrong. |
| What the code actually does | `calculateStrikesForCandles` anchors on `marketDataList.get(marketDataList.size() - 1)` -- the **latest** candle's close -- and derives `baseStrike = floor(close / strikePoints) * strikePoints`, then walks ITM/OTM outward from it. NIFTY moving 200 points intraday therefore shifts the ATM base by four 50-point strikes and the whole set with it. Re-verified against the code on 2026-08-31 before closing. |
| Why the premise survived review | `MILESTONE_DETAILS.md` M10 records the architect asking exactly the right question -- *"is the strike set REALLY stable within a day?"* -- and the engineer answering *"uses the first candle of the day to anchor ATM ... Confirmed stable"*. That answer was wrong, and no one opened the file. The milestone was then approved on it. The design was sound given the premise; the premise was never checked. |
| Why not (a) | Changing the anchor to the first candle of the day would make the cache correct, but it is a **behaviour change, not an optimisation**: strikes would be fixed at the 09:15 spot for the whole session, so a config would keep trading strikes that are far ITM/OTM by 14:00. That decides what gets traded and is Rule 0 -- it needs the strategy owner and a before/after, which is a much larger piece of work than the caching it was meant to enable. |
| Why not (b) | Memoising by `(date, configId, lastCandleTimestamp)` is pure caching with no behaviour change, but the inner key changes on every tick by construction, so it caches nothing. It would add a map, an eviction policy and a lifecycle to save zero work. |
| What was actually costing anything | Nothing measured. The compute is arithmetic over one candle -- a floor division and `itmDepth + otmDepth` additions per config per tick. M10's 0.5-day budget was never justified against a profile; it was on the list because the premise made it look free. |
| If this is ever revisited | It is a *strategy* question, not a performance one: **should a day's strike set be anchored once at the open, or track spot through the session?** File it in `STRATEGY_ANALYSIS_TODO.md`, not here. Related and already filed: [S8](STRATEGY_ANALYSIS_TODO.md#s8-a-strike-that-leaves-the-configs-atm-window-keeps-trading-on-its-last-cached-bar-for-the-rest-of-the-day) is about what happens to a strike that leaves the window as the base moves, which is the other half of the same behaviour. |
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

## 20. `MarketDataProviderFactory.java` is an empty file -- **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`market/provider/MarketDataProviderFactory.java`](../src/main/java/com/moneymaker/market/provider/MarketDataProviderFactory.java) — 0 bytes, no class |
| Why | Provider selection is currently spread across `@ConditionalOnProperty` annotations on each provider, with `ZerodhaMarketDataProvider` declaring `matchIfMissing = true`. That makes the single-provider injection point in `KiteHistoricalFetcher` fragile: any second `MarketDataProvider` bean is ambiguous unless it is `@Primary`. `HistoricalIciciMarketDataProvider` has to carry `@Primary` for exactly this reason. `GrowwMarketDataProvider` and `CustomMarketDataProvider` are both gated on `market.data.provider`, a key that is not in `application.properties` at all, so neither can ever register. |
| Resolution | The fix sketch in full. The factory injects `List<MarketDataProvider>`, resolves once at `@PostConstruct`, and `KiteHistoricalFetcher` now takes the factory rather than a single `MarketDataProvider` bean. The rule, in order: **(1)** `market.data.provider` if set (case- and whitespace-insensitive against `getName()`); **(2)** the only registered provider; **(3)** `DEFAULT_PRECEDENCE` -- `HISTORICAL_ICICI`, then `ZERODHA`; **(4)** otherwise fail startup naming the candidates. A `market.data.provider` that matches nothing fails startup rather than falling through, which is what the key should always have done. |
| `@Primary` dropped | Yes, and provably safe rather than hopefully safe. `@Primary` existed **only** to arbitrate the single-provider injection point in `KiteHistoricalFetcher`; once that parameter became the factory, no `MarketDataProvider`-typed injection point remained (the other consumer, `MarketDataService`, injects `ObjectProvider<HistoricalIciciMarketDataProvider>` by concrete type, which `@Primary` never affected). The preference it encoded did not disappear -- it became `DEFAULT_PRECEDENCE`, one readable line with the reason next to it. |
| `matchIfMissing` kept | Deliberately. It is a **registration** concern -- whether `ZerodhaMarketDataProvider` becomes a bean when `broker.active` is absent -- and the factory changes only **selection**. Removing it would deregister the provider in any deployment or test context that does not set `broker.active`, which is a behaviour change with nothing to do with this entry. Left alone and documented rather than swept up. |
| Proof, not assertion | [`MarketDataProviderFactoryTest.resolution_is_unchanged_under_the_shipped_properties`](../src/test/java/com/moneymaker/market/provider/MarketDataProviderFactoryTest.java) loads the real `application.properties`, asserts the two `@ConditionalOnProperty` gates still hold (`broker.active=ZERODHA`, `backtest.data-source=HISTORICAL_ICICI`), builds the factory with exactly the providers those values register, and asserts it resolves `HISTORICAL_ICICI` -- the same bean `@Primary` was choosing. It reads the file rather than restating it, so it keeps meaning something after someone edits the properties. |
| Why HISTORICAL_ICICI outranks the broker | Now a stated rule rather than an annotation: with the historical source active the operator has asked to replay imported candles, and any path still reaching the fetcher must read those instead of quietly calling a live broker API. A replay that mixes in today's real quotes is not a function of the replayed window -- the class of bug GAPS #4 and S11 were about. |
| Dead providers deleted | `GrowwMarketDataProvider` and `CustomMarketDataProvider`, the sketch's "either wire up or delete". Not merely dormant: each needs a constructor bean (`GrowwApiClient` / `CustomDataSource`) that is a plain nested class nobody registers, so setting `market.data.provider=GROWW` would have **failed startup**; and if it had not, the client's `getHistoricalData` returns an empty response, so the provider would have served zero candles silently. A provider that always returns nothing is worse than one that errors. Same call as GAPS #15 made on the EMA/RSI stubs. |
| Also | `ZerodhaMarketDataProvider.NAME` became public (it is the selection key), and `market.data.provider=` is now present-but-blank in `application.properties` with the rule written above it, so the key is discoverable instead of being a name that appears only inside annotations. |
| Tests | [`MarketDataProviderFactoryTest`](../src/test/java/com/moneymaker/market/provider/MarketDataProviderFactoryTest.java) -- the parity proof above, precedence independent of list order, single-provider, explicit override, lenient formatting, and four loud failures (unknown name, no providers, an ambiguous set with nothing in the precedence, duplicate names). |

## 21. `Strategy2`'s SMA-20 slope filter is inert when the slope is unknown *(moved)*

> Strategy gaps now live in **[STRATEGY_ANALYSIS_TODO.md](STRATEGY_ANALYSIS_TODO.md)**.
> This entry is [S1](STRATEGY_ANALYSIS_TODO.md#s1-strategy2s-sma-20-slope-filter-is-inert-when-the-slope-is-unknown--parked-2026-08-30).

## 22. Session-window constants are hardcoded while `app.market.*` already exists *(moved)*

> Strategy gaps now live in **[STRATEGY_ANALYSIS_TODO.md](STRATEGY_ANALYSIS_TODO.md)**.
> This entry is [S5](STRATEGY_ANALYSIS_TODO.md#s5-session-window-constants-are-hardcoded-while-appmarket-already-exists).
> Filed here first by mistake before Rule 0 landed; number kept so a later #23 does not collide.

## 23. Orphan Liquibase changeset — 005_create_market_data_table.xml -- **RESOLVED 2026-08-31**

| | |
|---|---|
| Where | [`005_create_market_data_table.xml`](../src/main/resources/db/changelog/005_create_market_data_table.xml) — present on disk, not `<include>`d in [`db.changelog-master.xml`](../src/main/resources/db/changelog/db.changelog-master.xml) (master's only `005_*` include is `005_create_broker_session_table.xml`) |
| Why | Discovered while resolving Gap #13/#14: [`LiquibaseMasterInclusionTest`](../src/test/java/com/moneymaker/architecture/LiquibaseMasterInclusionTest.java) scans every numbered changeset, not just the two named in Gap #13, and this one is a genuine third orphan — unrelated to 016/017, and older (its `createTable` predates them). Unlike 016/017 it is **not** dead: `market_data` is the live table every SMA/analysis/backtest read hits. It has survived unwired this whole time because `spring.jpa.hibernate.ddl-auto=update` (`application.properties`) creates the table straight from the `MarketData` JPA entity on every boot, so Liquibase never had to. |
| Risk | Unlike 016/017, this changeset carries **no** `preConditions` guard — it's an unconditional `<createTable tableName="market_data">`. Wiring it into master as-is would throw "table already exists" against every environment that has ever booted this app (i.e. all of them), since Hibernate already created the table. That is the hard-constraint failure mode this whole cleanup was trying to avoid, so it was left alone rather than "fixed" in the same pass. |
| Resolution | The fix sketch as written. The changeset gained `<preConditions onFail="MARK_RAN"><not><tableExists tableName="market_data"/></not></preConditions>` and is now `<include>`d in the master between 006 and `007_add_sma_value_to_market_data.xml`, ahead of both changesets that `ALTER` the table (007 and 013). Editing the file was safe for exactly the reason it was a gap: it had never been `<include>`d, so no `DATABASECHANGELOG` row exists for it on any database and nothing was rewritten under a live schema. |
| **The verification found a second, worse bug** | The entry budgeted time for verification and it earned it. The file's `xsi:schemaLocation` read `dbchangelog-4.23.0.xsd` -- an XSD that does not exist. liquibase-core 4.24.0 bundles `dbchangelog-4.23.xsd`, and it runs with `secureParsing=true`, so an unbundled name is **not** fetched over the network: parsing fails outright. Including the file with that typo intact would have killed startup at parse time, before any precondition was ever evaluated -- a strictly worse failure than the "table already exists" one this entry was written about, and invisible until wired in, because an orphan is never parsed. Changed to `dbchangelog-latest.xsd`, matching the 27 other changesets. |
| Verification | [`LiquibaseMasterAppliesOnH2Test`](../src/test/java/com/moneymaker/architecture/LiquibaseMasterAppliesOnH2Test.java) -- a throwaway in-memory H2 schema per test, no MySQL touched. Two runs that actually execute the migration rather than assert about it: **fresh database** (005 is `EXECUTED`, creates the table, 007/013 land on it) and **Hibernate got there first** (`market_data` pre-created, 005 must be recorded `MARK_RAN`). A third test pins the master's ordering. The changesets run are read out of the real master in the master's own order, so moving the include after 007 fails the migration test, not just the ordering one. |
| Why a slice and not the whole master | `032_backfill_trade_order_strategy_id.xml` uses MySQL's `UPDATE ... JOIN ... SET` form, which H2 rejects. The test runs only the changesets that touch `market_data`, filtered out of the real master. Making the whole changelog H2-portable is a separate, larger question and was not attempted here. |
| Recurrence guard | `LiquibaseMasterInclusionTest` gained a fourth test, `schema_locations_resolve_to_a_bundled_xsd`, asserting every changeset's declared XSD is one the liquibase-core on the classpath actually ships. It reads the `schemaLocation` attribute rather than the file text, so a comment mentioning a bad name is not a false positive. |
| Allowlist | `LiquibaseMasterInclusionTest.ALLOWLIST` is now **empty** -- 005 was its only entry. |

## 24. EOD force-close writes no journal EXIT row

| | |
|---|---|
| Where | The end-of-day force-close path (`OrderService.forceCloseOpenPositions`) versus the journal EXIT writes on the normal exit flow; `journal_observation` kind `EXIT`. |
| Why | On the full-2024 Strategy1 replay (run `bt-2024-01-01_2024-12-31-1788159770820`), exactly the 3 `FORCE_CLOSE` trades (ids 1814 / 1904 / 1916, all closed by the 15:20 sweep) have ENTRY and MONITOR rows but no EXIT row -- 158 EXIT vs 161 ENTRY. Every SIGNAL / TARGET / STOP_LOSS / TRAIL_SL exit journals correctly (counts reconcile 1:1 with `trade_order.exit_reason`). Any journal-based exit analysis silently drops force-closed trades. |
| Fix sketch | Emit the EXIT observation from the force-close path with the same feature set as the normal exits (or an explicit marker if context candles are unavailable at sweep time). Journal completeness only -- no trading behaviour involved. |
| Effort | **S** |
| Priority | _TBD -- filed 2026-08-31 from the full-2024 insights pass._ |

## 25. `journal_observation.selected` is never true on CANDIDATE rows

| | |
|---|---|
| Where | The CANDIDATE recorder call path (`AnalysisScheduler` -> journal writer); `journal_observation.selected`. |
| Why | [`OBSERVATION_JOURNAL.md`](OBSERVATION_JOURNAL.md) documents `selected` on CANDIDATE as "was this leg actually traded at this tick", which is what makes the counterfactual "how would the other strikes have done" query answerable directly. On the full-2024 run all 125,985 CANDIDATE rows carry `selected=0` -- including the 195 rows that provably match an actual ENTRY on `(observed_at, option_token)`. The doc's query design currently requires a join-based reconstruction instead. Either the wiring never sets the flag or the doc overstates it; needs a code check. |
| Fix sketch | Set the flag where the entry is admitted, or correct the doc if the flag was deliberately dropped. |
| Effort | **S** |
| Priority | _TBD -- filed 2026-08-31 from the full-2024 insights pass._ |

## 26. `trade_order.lot_quantity_at_entry` is 0 on every row

| | |
|---|---|
| Where | `trade_order.lot_quantity_at_entry` versus the entry write path in `OrderService`. |
| Why | All 161 rows of the full-2024 replay carry 0 while `quantity` is correctly 75 everywhere (and `trade_config.lot_quantity` is 75). Any consumer multiplying by `lot_quantity_at_entry` gets zero P&L. Dead-or-broken column: either it was never wired at entry or it is redundant with `quantity`. |
| Fix sketch | Populate it at entry alongside `quantity`, or drop the column via a new changeset if `quantity` already covers the need. |
| Effort | **S** |
| Priority | _TBD -- filed 2026-08-31 from the full-2024 insights pass._ |
