# Orders & Positions

How a strategy's `BUY` / `SELL` signal becomes a persisted `TradeOrder` row, gets executed at the broker, monitored for SL / target, and finally closed.

> **Why this lives in one doc.** Strategy → signal → order → position → close is a single value chain. Splitting it across files would force a reader to chase pointers between order placement, position monitoring, and broker factories that share most of their machinery (the broker selector, the dedupe rules, the DB row) anyway. One page is faster.

---

## End-to-end flow

```
                    Strategy emits TradeAction (BUY/SELL/NONE)
                                        │
                                        ▼
                       SharedData.tradeSignals (queue)
                                        │
                                        ▼
                          OrderScheduler tick
                                        │
                                        ▼
                          OrderService.processOrders
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
  open new TradeOrder        close existing OPEN row            skip (dedupe / direction
  (status=OPEN)              (status=CLOSED, exit_*)            mismatch / intraday guard)
        │                               │
        ▼                               ▼
  OrderPlacementFactory.active().place(order, config)
        │
        ▼
   broker SDK / REST   ──→  returns broker_order_id  ──→  saved on the row

       Then, on every PositionScheduler tick:
       PositionService walks OPEN rows
       PositionMonitorFactory.active().currentPrice(order)  ──→  updates peak_profit / peak_loss
       if pnl ≥ target  →  OrderService.closeManually(..., "TARGET")
       if pnl ≤ -stopLoss →  OrderService.closeManually(..., "STOP_LOSS")

       At end of backtest day:
       OrderService.forceCloseOpenPositions(date, dateEnd) — closes leftover intraday opens
```

---

## `trade_order` columns

| Column | Set when | Why |
|---|---|---|
| `id` | open | Surrogate primary key. |
| `trade_config_id` | open | Which config produced the trade. |
| `instrument_name` / `instrument_token` | open | Underlying (e.g. `NIFTY`, token `256265`). |
| `option_strike` / `option_type` / `option_token` | open | Specific option leg. `option_token` is unique per strike+expiry+type and is the dedupe / monitor key. |
| `entry_direction` | open | `BUY` or `SELL`. The leg side at entry. |
| `entry_time` / `entry_price` | open | Strategy's signal time + close-of-candle price. Updated to broker `average_price` if a sync runs after a real fill. |
| `status` | open / close | `OPEN` or `CLOSED`. |
| `entry_broker_order_id` | open (live) | Broker-side order id for the entry leg. Populated only after a successful `placement.place(...)`. |
| `exit_broker_order_id` | close (live) | Same for the exit leg. |
| `fill_status` | open / close | `PENDING` / `COMPLETE` / `REJECTED` / `CANCELLED` / `BACKTEST`. The most-recent leg's broker fill state (refreshed by the sync endpoint). |
| `exit_time` / `exit_price` / `profit` | close | Exit leg fields. `profit` is per-share. |
| `exit_reason` | close | `SIGNAL` / `TARGET` / `STOP_LOSS` / `FORCE_CLOSE`. |
| `peak_profit` / `peak_loss` | each PositionScheduler tick while OPEN | High-water-mark / low-water-mark of unrealised per-share P&L. |
| `last_monitored_price` / `last_monitored_at` | each PositionScheduler tick while OPEN | Most recent quote and tick time. |
| `target_at_entry` / `stop_loss_at_entry` | open | Per-share thresholds **snapshotted from `tradeConfig.target` / `tradeConfig.stopLoss` at entry**. PositionService reads from the row, never from the live config — so a config edit mid-trade can't retroactively close existing positions, and SL/target works even when `SharedData.combinedDto` is stale or empty. |

Liquibase changesets that built this:
- 008 — initial table.
- 009 — broker order ids + fill_status.
- 010 — monitor columns (peak / last-monitored / exit_reason).
- 011 — target / stop-loss snapshot columns.

Open-position lookup index (`idx_trade_order_open_lookup`) covers `(trade_config_id, instrument_token, option_type, status)` from changeset 008. The dedupe key in `OrderService` later moved to `option_token`, which doesn't have a dedicated index — currently a small-N filter, fine until thousands of trades land per day.

---

## Price sources used by the pipeline

| Stage | Price source |
|---|---|
| Strategy gate (cross detection) | candle's **open** + **close** (`RuleEngine.decide`) |
| `entry_price` saved on the row | candle's **close** at the moment of signal |
| `exit_price` on signal-driven close | candle's **close** at the moment of the close-signal |
| `exit_price` on TARGET / STOP_LOSS | next candle's **close** picked up by the position monitor |
| `exit_price` on EOD force-close | last cached candle's **close** at-or-before market close |
| **SMA values the gate compares against** | candle's **low** — see note below |

**SMA-on-lows is intentional.** [`SMAIndicatorImpl`](../src/main/java/com/moneymaker/indicator/SMAIndicatorImpl.java) wraps `LowPriceIndicator`, not `ClosePriceIndicator`. Because `SMA(low) ≤ SMA(close)`, the "rejection at SMA" gate (`open > SMA && close < SMA`) is more permissive — the candle's open more easily clears the SMA and the close more easily sits below it, surfacing intraday rejection candles a close-based SMA would miss. **Don't change this without consulting the strategy author.**

---

## Open / close decision rules

`OrderService.handleSignal(signal, placement)` evaluates rules in this order:

1. **Existing OPEN row for the same `(tradeConfigId, optionToken)`?**
   - Same direction → skip (true duplicate).
   - Opposite direction → close it via `closeOrder(...)`.
2. **No open row, signal direction matches `tradeConfig.transactionType`?**
   - Yes → continue.
   - No → skip ("BUY signal arrived but config is SELL-only — exit-only signal suppressed").
3. **Hit the per-day cap?** (`tradeConfig.numberOfTradesPerDay`)
   - Counts **all** entries for this config today (every strike, OPEN + CLOSED).
   - `null` / `<= 0` → no cap. Re-entries on the same strike after a CLOSED trade earlier in the day are allowed.
   - Cap reached → skip.
4. **Hit the parallel-direction cap?** (`tradeConfig.numberOfParallelTrades`)
   - Counts **OPEN** trades for this config in the **same direction** as the incoming signal (BUY / SELL).
   - `null` / `<= 0` → no cap.
   - Cap reached → skip. Once one of those open trades exits, a fresh signal can take its place.
5. **Exact duplicate?** (`(tradeConfigId, optionToken, entryDirection, entryTime)`)
   - True when a row already exists with this same key — re-running the same backtest, or the same signal getting queued twice within one tick. Skipped to keep the ledger idempotent.
   - Legitimate re-entries on the same strike later in the day fire at a *different* `entryTime`, so this guard doesn't block them.

The dedupe key is `option_token`, **not** `(instrument_token, option_type)`. Earlier the broader key collided across strikes — a 24100 BUY would close an open 24200 SELL because both are CE on NIFTY. The narrower key fixed that.

---

## Close paths (which one?)

| Path | Trigger | Sets `exit_reason` | Calls broker exit? |
|---|---|---|---|
| `OrderService.closeOrder(...)` | Strategy signal of opposite direction matches an open row | `SIGNAL` | Yes |
| `OrderService.closeManually(...)` | `PositionService` detects target / stop-loss breach | `TARGET` / `STOP_LOSS` (caller passes) | Yes |
| `OrderService.forceCloseOpenPositions(date, closeAt)` | End-of-day cleanup from `BacktestAnalysisService` | `FORCE_CLOSE` | No (local-only — live force-close needs a separate broker exit, deferred PR) |

All three persist the row before any broker call so the ledger is always the source of truth.

---

## Broker factories

Two factories, identical shape:

| Factory | Picks | Used by |
|---|---|---|
| [`OrderPlacementFactory`](../src/main/java/com/moneymaker/order/service/OrderPlacementFactory.java) | `OrderPlacementService` impl | `OrderService` for entry / exit / sync calls |
| [`PositionMonitorFactory`](../src/main/java/com/moneymaker/position/service/PositionMonitorFactory.java) | `PositionMonitorService` impl | `PositionService` for live-quote lookups |

Selection logic (both factories):

```
if (app.mode == "backtest") → BACKTESTING
else                          → broker.active   (ZERODHA / GROWW / ANGEL_ONE)
```

So a backtest run never hits a live broker even with `broker.active=ZERODHA`.

### `OrderPlacementService` implementations

| Impl | `place(order, config)` | `syncFill(brokerOrderId)` |
|---|---|---|
| [Backtesting](../src/main/java/com/moneymaker/backtesting/BacktestingOrderPlacementService.java) | no-op (returns `null`) — DB row is the ledger | returns `BACKTEST` snapshot |
| [Zerodha](../src/main/java/com/moneymaker/broker/zerodha/ZerodhaOrderPlacementService.java) | real `kiteConnect.placeOrder(...)`. **Tradingsymbol resolution still TODO** — currently returns `null` so no real order goes out until that lands | real `kiteConnect.getOrderHistory(...)` → `FillSnapshot{status, averagePrice, filledQuantity}` |
| [Groww](../src/main/java/com/moneymaker/broker/groww/GrowwOrderPlacementService.java) | skeleton — TODO | skeleton — TODO |
| [Angel One](../src/main/java/com/moneymaker/broker/angelone/AngelOneOrderPlacementService.java) | skeleton — TODO | skeleton — TODO |

### `PositionMonitorService` implementations

| Impl | `currentPrice(order)` |
|---|---|
| [Backtesting](../src/main/java/com/moneymaker/backtesting/BacktestingPositionMonitorService.java) | walks `SharedData.strikeMarketDataByInstrumentAndInterval`, finds latest cached candle whose key has `optionToken` in segment 4 |
| [Zerodha](../src/main/java/com/moneymaker/broker/zerodha/ZerodhaPositionMonitorService.java) | `kiteConnect.getLTP(new String[]{optionToken})` — bails on null when not logged in |
| [Groww](../src/main/java/com/moneymaker/broker/groww/GrowwPositionMonitorService.java) | skeleton — TODO |
| [Angel One](../src/main/java/com/moneymaker/broker/angelone/AngelOnePositionMonitorService.java) | skeleton — TODO |

---

## Position monitoring (per `PositionScheduler` tick)

For every row with `status='OPEN'`:

```
quote = monitor.currentQuote(order)               # → {price, asOf}
if quote == null:           skip this tick (e.g. strike fell out of active-set in backtest)
if asOf <= order.entry_time: skip this tick (the candle that opened the trade
                              cannot also close it — see "Same-candle guard" below)

pnl = perShareProfit(entry_direction, entry_price, quote.price)
peak_profit = max(peak_profit, pnl)
peak_loss   = min(peak_loss,   pnl)
last_monitored_price = price
last_monitored_at    = now

# Read thresholds from the snapshot on the row, NOT from SharedData / live config.
if pnl >=  order.target_at_entry      → OrderService.closeManually(id, price, now, "TARGET")
if pnl <= -order.stop_loss_at_entry   → OrderService.closeManually(id, price, now, "STOP_LOSS")
else                                   → save row
```

**Why read from the row, not the live config:**

1. **No silent miss when `SharedData.combinedDto` isn't loaded.** In live mode `TradeConfigScheduler` populates `SharedData.combinedDto` at the 09:16 cron — `PositionScheduler` ticks before that would otherwise see no thresholds and silently leave positions unprotected.
2. **No retroactive close on config edit.** Editing `tradeConfig.target` from 10 → 5 only affects *new* trades, not ones already running.
3. **Audit trail.** Each `trade_order` row records the exact threshold it was opened against.

`stop_loss_at_entry` is stored as a positive number representing max loss per share, hence the `pnl <= stopLossAtEntry.negate()` comparison.

### Same-candle guard

`PositionService` skips any monitor tick whose `quote.asOf <= order.entry_time`. The reason: in backtest, the same tick that opens the trade also runs the position monitor against the same cached candle — without this guard, a target / stop-loss could fire instantly with `exit_time == entry_time`. The first legitimate monitoring opportunity is the **next** candle. In live mode this guard is effectively a no-op (a fresh LTP timestamp is always after the candle that triggered entry).

Today `entry_time` is set to the trigger candle's start timestamp (e.g. `09:15:00` for the 5-minute candle covering 09:15–09:20). If you ever switch to a more realistic "enter at next bar's open" semantic, set `entry_time` to the next candle's start (`09:20:00`) in `OrderService.openOrder`. The guard works correctly either way.

---

## Sync (broker fill resolution)

`POST /api/orders/{id}/sync` → `OrderService.syncOrder(id)`:

1. Pick the leg to sync from `status` (OPEN → entry, CLOSED → exit).
2. Call `placement.syncFill(brokerOrderId)`.
3. If `averagePrice` came back, update the right leg's price column.
4. Recompute `profit` against the (possibly updated) entry/exit pair.
5. Persist `fill_status` from the snapshot (`COMPLETE` / `REJECTED` / etc.).

Backtesting rows have `fill_status='BACKTEST'` and no broker id — sync is a no-op for them. The UI hides the sync button.

---

## Purging the ledger

`POST /api/orders/purge` -> `OrderService.purge(request)`. The ledger is
append-only everywhere else — every backtest replay of a range adds another set
of rows — so this is the one supported way to clear it.

```jsonc
{ "fromDate": "2024-01-02",   // optional, inclusive, matched against entry_time
  "toDate":   "2024-01-04",   // optional, inclusive; omit both to clear everything
  "dryRun":   true,           // DEFAULT — a caller that omits it gets a preview
  "includeOpen": false }      // DEFAULT — OPEN rows are skipped, see below
```

It lives on `OrderService` rather than the controller because that service is
the single owner of the order lifecycle (CLAUDE.md invariant 7) — `trade_order`
is its table.

**OPEN rows are skipped unless `includeOpen` is set.** In live mode an OPEN row
is a real broker position `PositionScheduler` is still walking each tick;
deleting it makes the app forget a position that is still in the market, with no
error anywhere to say so. Skipped ids come back as `skippedOpen` / `skippedIds`,
so the caller finds out before rather than after.

This is the mirror image of the bulk config delete: this one starts from
`trade_order` and never touches configs; that one starts from `trade_config` and
can take the trades with it (see
[EOD_DOWNTREND.md](EOD_DOWNTREND.md#force-deleting-configs-that-have-trades)).
Neither reaches the other's rows implicitly, so "the configs are gone but the
ledger still has rows" is an expected state, not a bug — the two tables are only
linked by `trade_config_id`, with no FK.

The **Clear ledger** button on `/backtest` drives it, scoped to the same date
range the ledger table is filtered by, previewing first.

---

## Telegram alerts

| Event | Method | Dedupe |
|---|---|---|
| Order opened | `alertOrderOpened(o)` | none — every order id is unique |
| Order closed (signal) | `alertOrderClosed(o)` | none |
| Order closed (target / SL) | `alertOrderClosed(o)` (via `closeManually`) | none |
| Order force-closed (EOD) | `alertOrderForceClosed(o)` | none |
| Broker rejected an order | `alertOrderRejected(broker, id, reason)` | `sendIfChanged("order-rejected:<broker>", ...)` |

Backtest mode is gated at `TelegramNotifier.send()` — `telegram.backtest-enabled=false` (default) silences everything. See [NOTIFICATIONS.md](NOTIFICATIONS.md).

---

## Trade-config admin

`com.moneymaker.tradeconfig` is the CRUD surface behind the `/trade-configs` UI — the mechanism CLAUDE.md invariant #9 ("no hardcoded trading-behaviour rules — they come from `TradeConfig`") depends on actually being usable day to day.

| Method | Path | Purpose |
|---|---|---|
| GET | `/trade-configs` | Thymeleaf admin page |
| GET | `/api/trade-configs?date=&page=&size=` | Paged list, optionally filtered by trading date |
| GET | `/api/trade-configs/{id}` | Single config + its `sma_timeframe` rows |
| POST | `/api/trade-configs` | Create |
| PUT | `/api/trade-configs/{id}` | Update |
| DELETE | `/api/trade-configs/{id}` | Delete — `409` if any `trade_order` references the config |
| GET | `/api/trade-configs/instruments` | Instrument dropdown source |
| GET | `/api/trade-configs/strategies` | Strategy dropdown source |

[`TradeConfigAdminController`](../src/main/java/com/moneymaker/tradeconfig/controller/TradeConfigAdminController.java) is a thin HTTP layer; [`TradeConfigAdminService`](../src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java) is the **single owner** of trade-config writes — controllers and other feature code must call it rather than `TradeConfigRepository` directly (see the CLAUDE.md / AGENTS.md invariant).

### The cache-invalidation contract

Every create / update / delete runs through `afterMutation(affectedDate)`, which:

1. **Always** calls `TradeConfigScheduler.invalidateConfigsCache()` — the date-keyed cache described in [SCHEDULERS.md](SCHEDULERS.md#single-entry-point-getconfigsfordatedate) would otherwise keep serving the pre-edit snapshot for the rest of the JVM's life.
2. **If** the affected date is *today* and `app.mode=live`, additionally rebuilds `SharedData.combinedDto` synchronously by calling `tradeConfigScheduler.getConfigsForDate(today)` and reassigning it — so the next 5-min `AnalysisScheduler` tick sees the edit immediately, without waiting for tomorrow's 09:16 cron or a JVM restart.

Edits to a *past* or *future* date, or any edit while `app.mode=backtest`, only invalidate the cache — there's no live `SharedData.combinedDto` to refresh outside of today.

### Auto-generated (`AUTO_DOWNTREND`) configs

Bulk operations scoped by `source` — the calendar view, the "which generation run was this" grouping, and the bulk-delete endpoint — are a separate, more specialized part of the same controller/service. They're documented in full in [EOD_DOWNTREND.md](EOD_DOWNTREND.md#deleting-generated-configs) rather than duplicated here, since they only make sense alongside the detector that produces those rows.

Two opt-ins there reach past the defaults, and both are off unless explicitly set: `force` also deletes configs that have `trade_order` rows (**and those trade rows**), and `source: MANUAL` aims the whole panel at hand-written configs instead of regenerable detector output. The single-config `DELETE /api/trade-configs/{id}` has neither and still refuses a traded config outright with a 409.

---

## Adding a new broker

1. Per existing convention (see [Readme](../Readme.md)), add `BrokerLoginService` impl in `com.moneymaker.broker.<name>` first.
2. **Order placement.** Add `<Name>OrderPlacementService implements OrderPlacementService` in the same package. Implement both `place` (real broker order) and `syncFill` (broker order history → `FillSnapshot`). Use `getName()` matching the broker's enum value.
3. **Position monitor.** Add `<Name>PositionMonitorService implements PositionMonitorService` in the same package. Implement `currentPrice(TradeOrder)` against the broker's quote API.
4. Both factories auto-discover the new beans via Spring's `List<…>` injection — no factory edits required.
5. **Update this doc.** Add rows to the per-broker tables above.

---

## Adding a new exit reason

1. Pick an UPPER_SNAKE name. Currently used: `SIGNAL`, `TARGET`, `STOP_LOSS`, `FORCE_CLOSE`.
2. Pass it as the `reason` arg to `OrderService.closeManually(...)` (or wherever the new close path lives).
3. **Update this doc.** The Close-paths table above is the registry.

---

## Adding a new monitored field

1. Liquibase changeset under `src/main/resources/db/changelog/` — `<addColumn tableName="trade_order">…`. Don't edit committed changesets.
2. Add the JPA field on `TradeOrder` with `@Column(name="…")`.
3. Update `PositionService.handleOne(...)` to populate it each tick.
4. **Update this doc.** Add a row in the `trade_order` columns table.

---

## Hardcoded vs config-driven

Trading-behaviour parameters — anything that controls *when* a trade enters, *when* it exits, *how many* trades fire — must come from `TradeConfig` (or equivalent configuration). They are **never** hardcoded in services. Idempotency guards and correctness invariants are a separate category and may stay in code.

> **History note.** An earlier version of `OrderService.handleSignal` carried a hardcoded "1 entry per strike per day" guard (the `alreadyClosedToday` check). It was removed in favour of `tradeConfig.numberOfTradesPerDay` (config-driven, per config) plus `tradeConfig.numberOfParallelTrades` (config-driven, per direction). Re-adding any similar hardcoded cap is forbidden — see the principle below.

### What MUST come from config

| Behaviour | Config field |
|---|---|
| Entry direction allowed (BUY-only / SELL-only) | `tradeConfig.transactionType` |
| Max trades per config per day (across all strikes, all statuses) | `tradeConfig.numberOfTradesPerDay` |
| Max simultaneous OPEN trades per direction | `tradeConfig.numberOfParallelTrades` |
| Profit target (per share) | `tradeConfig.target` → snapshotted to `target_at_entry` at open |
| Stop loss (per share, positive) | `tradeConfig.stopLoss` → snapshotted to `stop_loss_at_entry` at open |
| Lot quantity | `tradeConfig.lotQuantity` |
| Active broker | `broker.active` (application property) |
| Backtest replay window | `fromDate` / `toDate` from the `/api/backtest/analysis` request |

When a new trading rule is needed and no `TradeConfig` field exists, **ask the user first** — they will either point at an existing column with a different name than expected, or sanction a new Liquibase changeset to add one. Do not guess at a default and do not embed a constant.

### What MAY stay hardcoded (technical / correctness)

- **Same-candle guard** in `PositionService.handleOne` — a trade cannot exit on the same candle that opened it. Correctness invariant.
- **Exact-duplicate guard** in `OrderService.handleSignal` — `(configId, optionToken, direction, entryTime)` uniquely identifies one ledger row. Re-runs and same-tick repeats are deduplicated. Idempotency.
- **`STATUS_OPEN` / `STATUS_CLOSED`, `FILL_PENDING` / `FILL_BACKTEST` / `FILL_COMPLETE`** — internal lifecycle vocabulary. Not user-tunable.
- **Per-share P&L formula** — direction-aware subtraction. A formula, not a parameter.

### What is technically hardcoded but probably should move to config later

- **NSE market open `09:20`, market close `15:30`** in `BacktestAnalysisService.run` — market-wide constants today; would need to move to a `MarketProperties` if a non-NSE market is ever added.
- **`15:15` "market close time" rule** in `CommonRules.isMarketCloseTime` — same caveat.

These aren't trading-behaviour rules per se (they're broker / exchange constants), so they don't violate the principle today. But flagging them so the next contributor knows.

---

## Things that are still pending

- **Zerodha tradingsymbol resolution.** `ZerodhaOrderPlacementService.resolveTradingSymbol` returns `null`, so live `place(...)` short-circuits before hitting Kite. Needs a cached NFO instruments dump fetched at login + a `(name, expiry, strike, optionType)` lookup. Once that lands, the rest of the pipeline is wired.
- **Groww + Angel One real REST clients** for both `OrderPlacementService` and `PositionMonitorService`.
- **Live force-close.** `forceCloseOpenPositions` updates the local row but does not place a real broker exit. For live mode, that needs a per-row `closeManually(...)` call so the broker actually unwinds.
- (Both `numberOfTradesPerDay` and `numberOfParallelTrades` are now enforced — see steps 3 and 4 in "Open / close decision rules" above.)
- **Lot-size aware quantity** — `quantity()` in placement services treats `tradeConfig.lotQuantity` as raw quantity. Multiplying by lot size (50 for NIFTY etc.) needs a data source decision.
- **Per-position audit trail** — peak / last-monitored is overwritten each tick. If we ever need a full price-vs-time history per trade, an `order_monitor_history` table is the next step. Not added today because it would explode write volume for marginal benefit.
