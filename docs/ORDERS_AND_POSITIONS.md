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
       trail_sl_at = highest trail_ladder rung peak_profit has reached (ratchet, never lowers)
       if pnl ≥ target  →  OrderService.closeManually(..., "TARGET")
       if pnl ≤ trail floor →  OrderService.closeManually(..., "TRAIL_SL")
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
| `strategy_id` | open | Which strategy produced the trade, snapshotted from the emitting `TradeSignal` so a later re-tag can't restate history (changeset 015). Since 031 this is **not** decorative: `(trade_config_id, strategy_id)` is the ledger identity every cap and dedupe rule below is keyed on, because one config can be tagged with several strategies. |
| `instrument_name` / `instrument_token` | open | Underlying (e.g. `NIFTY`, token `256265`). |
| `option_strike` / `option_type` / `option_token` | open | Specific option leg. `option_token` is unique per strike+expiry+type and is the dedupe / monitor key. |
| `entry_direction` | open | `BUY` or `SELL`. The leg side at entry. |
| `entry_time` / `entry_price` | open | Strategy's signal time + close-of-candle price. Updated to broker `average_price` if a sync runs after a real fill. |
| `status` | open / close | `OPEN` or `CLOSED`. |
| `entry_broker_order_id` | open (live) | Broker-side order id for the entry leg. Populated only after a successful `placement.place(...)`. |
| `exit_broker_order_id` | close (live) | Same for the exit leg. |
| `fill_status` | open / close | `PENDING` / `COMPLETE` / `REJECTED` / `CANCELLED` / `BACKTEST`. The most-recent leg's broker fill state (refreshed by the sync endpoint). |
| `exit_time` / `exit_price` / `profit` | close | Exit leg fields. `profit` is per-share. |
| `exit_reason` | close | `SIGNAL` / `TARGET` / `STOP_LOSS` / `TRAIL_SL` / `TIME_STOP` / `FLATTEN` / `FORCE_CLOSE`. `TRAIL_SL` is the trailing floor (036) and is deliberately not folded into `STOP_LOSS` — it is the opposite outcome, since a trailed exit closes green. `TIME_STOP` and `FLATTEN` are the two clock exits (043) and are likewise kept apart from `FORCE_CLOSE`: those two mean the strategy closed on its own schedule, `FORCE_CLOSE` means the run ended with the position still open. |
| `max_hold_minutes_at_entry` | open | Minutes from `entry_time` after which `PositionService` closes the trade as `TIME_STOP`. NULL = no time stop, which is every row before 043 and every config that leaves `trade_config.max_hold_minutes` unset. Snapshotted for the same reason the bracket is: shortening the limit at 13:00 must not instantly breach every position opened before 12:00. |
| `flatten_at_entry` | open | Time-of-day at which the trade is closed as `FLATTEN` regardless of P&L. NULL = no intraday flatten. A TIME, not a timestamp — the row carries its own `entry_time` and these are intraday strategies, so the date is never ambiguous. |
| `peak_profit` / `peak_loss` | each PositionScheduler tick while OPEN | High-water-mark / low-water-mark of unrealised per-share P&L. |
| `last_monitored_price` / `last_monitored_at` | each PositionScheduler tick while OPEN | Most recent quote and tick time. |
| `quantity` | open | Order quantity in units (75 = one NIFTY lot), **snapshotted at entry** from `tradeConfig.lotQuantity` — the same value the placement services send. Snapshotted for the same reason the bracket is: it is what the broker order actually carried, and editing the config's lot size later must not restate history. Before changeset 029 it was not persisted at all, so rupee P&L could not be derived from the ledger. Null on pre-029 rows, which `TradeChargeService` reports as uncosted rather than assuming a lot size. |
| `target_at_entry` / `stop_loss_at_entry` | open | Per-share thresholds **snapshotted at entry** by `OrderService.bracketAtEntry`, from whichever column the strategy's `strategy_defaults.target_mode` / `sl_mode` names (changeset 041): `entryPrice × tradeConfig.targetPct` under `PERCENT`, the absolute `tradeConfig.target` / `tradeConfig.stopLoss` under `POINTS`. Each mode falls back to the other column when its own is unset, because a null threshold reads as "never breaches" downstream. PositionService reads from the row, never from the live config — so a config edit mid-trade can't retroactively close existing positions, and SL/target works even when `SharedData.combinedDto` is stale or empty. |
| `trail_ladder_at_entry` | open | Trailing rungs **snapshotted at entry** from `tradeConfig.trailLadder`, canonicalised by `TrailLadder.canonical`. Null = this trade does not trail. Snapshotted for the same reason the bracket is: editing a ladder at 13:00 must not re-floor a trade opened at 09:20. A ladder that fails to parse at entry is logged and degrades to null — the trade opens on its fixed stop rather than not opening at all. |
| `trail_sl_at` | each PositionScheduler tick while OPEN | The latched trailing floor in **signed** premium points — `+2` is a stop two points into profit. Null until the first rung is reached. Only ever moves up (`PositionService.applyTrail`), so on a closed row it records the best floor the trade earned and explains a `TRAIL_SL` exit. |

Liquibase changesets that built this:
- 008 — initial table.
- 009 — broker order ids + fill_status.
- 010 — monitor columns (peak / last-monitored / exit_reason).
- 043 — `max_hold_minutes_at_entry` / `flatten_at_entry`, the two clock exits (Pressure; see [PRESSURE_STRATEGY.md](PRESSURE_STRATEGY.md#exits)).
- 011 — target / stop-loss snapshot columns.
- 036 — trailing stop-loss (`trail_ladder_at_entry`, `trail_sl_at`) + the `max_sl_points` ceiling on `trade_config`.
- 048 — `trail_atr_distance_at_entry`, the chandelier distance (Strategy 8), plus `strategy_defaults.trail_atr_multiple` and the `NONE` bracket mode. See [Chandelier trail](#chandelier-trail-changeset-048).
- 029 — `trade_order.quantity`, plus the `charge_rate` table (date-effective brokerage / statutory rates). See [Charges and net P&L](#charges-and-net-pl).
- 027 — `trade_config.target_pct` / `sl_pct`, the premium-relative bracket the snapshot resolves. Nullable: null keeps the absolute columns. See [EOD_DOWNTREND.md](EOD_DOWNTREND.md).
- 041 — `strategy_defaults.target_mode` / `sl_mode`, the per-strategy switch that decides which of 027's two shapes each bracket side resolves from. Default `PERCENT` on every row reproduces the pre-041 rule exactly, so the changeset ships inert. Parsed only by `com.moneymaker.util.BracketMode`.
- 031 / 035 — lets one config be run by several strategies: 031 added a `trade_config_strategy` tag table, 035 replaced it with the `trade_config.strategy_ids` CSV column. See [STRATEGIES.md](STRATEGIES.md#how-a-config-reaches-a-strategy).
- 032 — backfills `trade_order.strategy_id` on rows written before 015.
- 038 — `trade_config.max_parallel_per_side`: the per-side (CE/PE) parallel cap, seeded 1. See gate 5 above. Required by 031: the gates below put `strategy_id` in the predicate, and `strategy_id = 1` is never true for a NULL, so an un-backfilled pre-015 row would drop out of every cap and let an already-capped config re-enter.

Open-position lookup index (`idx_trade_order_open_lookup`) covers `(trade_config_id, instrument_token, option_type, status)` from changeset 008. The dedupe key in `OrderService` later moved to `option_token` and, from 031, also carries `strategy_id` — neither has a dedicated index. Currently a small-N filter, fine until thousands of trades land per day; the fan-out multiplies row count by the number of tags, so it gets there sooner than it used to.

---

## Price sources used by the pipeline

| Stage | Price source |
|---|---|
| Strategy gate (cross detection) | candle's **open** + **close** (`RuleEngine.decide`) |
| `entry_price` saved on the row | candle's **close** at the moment of signal |
| `exit_price` on signal-driven close | candle's **close** at the moment of the close-signal |
| `exit_price` on TARGET / STOP_LOSS | next candle's **close** picked up by the position monitor |
| `exit_price` on EOD force-close | last cached candle's **close** at-or-before market close, from the finest cached interval (`SharedData.latestCachedCandle`) |
| **SMA values the gate compares against** | candle's **low** — see note below |

**SMA-on-lows is intentional.** [`SMAIndicatorImpl`](../src/main/java/com/moneymaker/indicator/SMAIndicatorImpl.java) wraps `LowPriceIndicator`, not `ClosePriceIndicator`. Because `SMA(low) ≤ SMA(close)`, the "rejection at SMA" gate (`open > SMA && close < SMA`) is more permissive — the candle's open more easily clears the SMA and the close more easily sits below it, surfacing intraday rejection candles a close-based SMA would miss. **Don't change this without consulting the strategy author.**

---

## Open / close decision rules

> **The ledger identity is `(trade_config_id, strategy_id)`, not the config alone.**
> Since changeset 031 a config can be tagged with several strategies (see
> [STRATEGIES.md → How a config reaches a strategy](STRATEGIES.md#how-a-config-reaches-a-strategy)),
> so every rule below is scoped to the strategy that emitted the signal —
> carried on `TradeSignal.strategyId` and stamped onto `trade_order.strategy_id`
> at open. Each tagged strategy gets its own caps, its own realised-loss budget,
> and its own position on a given leg. A config tagged with one strategy behaves
> exactly as it did before.

`OrderService.handleSignal(signal, placement)` evaluates rules in this order:

1. **Existing OPEN row for the same `(tradeConfigId, strategyId, optionToken)`?**
   - Same direction → skip (true duplicate).
   - Opposite direction → close it via `closeOrder(...)`.
   - Scoped by strategy so one strategy's exit signal can't close a position another strategy opened on the same leg.
2. **No open row, signal direction matches `tradeConfig.transactionType`?**
   - Yes → continue.
   - No → skip ("BUY signal arrived but config is SELL-only — exit-only signal suppressed").
3. **Hit the per-day cap?** (`tradeConfig.numberOfTradesPerDay`)
   - Counts **all** entries this strategy made from this config today (every strike, OPEN + CLOSED).
   - `null` / `<= 0` → no cap. Re-entries on the same strike after a CLOSED trade earlier in the day are allowed.
   - Cap reached → skip.
   - Per strategy, not shared: two strategies on one config would otherwise share one budget, and whichever fired first would silence the other for the day.
4. **Hit the parallel-direction cap?** (`tradeConfig.numberOfParallelTrades`)
   - Counts **OPEN** trades for this `(config, strategy)` in the **same direction** as the incoming signal (BUY / SELL).
   - `null` / `<= 0` → no cap.
   - Cap reached → skip. Once one of those open trades exits, a fresh signal can take its place.
5. **Hit the same-SIDE cap?** (`tradeConfig.maxParallelPerSide`, changeset 038 — user decision 2026-08-31)
   - Counts **OPEN** trades for this `(config, strategy)` on the incoming signal's **option side** (CE / PE), **regardless of strike** — the gate above counts by BUY/SELL direction and happily stacked two CE SELLs on different strikes (orders 1941/1942, 2024-02-01).
   - Seeded **1** on every config: one CE and one PE may run in parallel, the same side never stacks. "Parallel trades" means both sides, not the same side twice.
   - `null` / `<= 0` → no side cap (the total/direction cap above still applies). New entities default to 1; a blank form field keeps the current value.
6. **Stop-loss lock?** (`Strategy.stopLossLocksBookForDay()` — strategy identity, not a config field; only `Strategy6` declares it)
   - When the emitting strategy declares the lock, a `STOP_LOSS` exit on any trade this `(config, strategy)` entered today closes its book: every further entry that session is skipped.
   - Read from `trade_order` (`existsBy…ExitReason…EntryTimeBetween`), not remembered in-process, so a restart mid-session cannot forget it.
   - `TRAIL_SL` does not lock — a trailed exit is the opposite outcome. Strategies that do not declare the lock (1–4) re-enter after a stop exactly as before; a service built without a `StrategyFactory` (unit tests) has no policy at all.
7. **Exact duplicate?** (`(tradeConfigId, strategyId, optionToken, entryDirection, entryTime)`)
   - True when a row already exists with this same key — re-running the same backtest, or the same signal getting queued twice within one tick. Skipped to keep the ledger idempotent.
   - Legitimate re-entries on the same strike later in the day fire at a *different* `entryTime`, so this guard doesn't block them.
   - `strategyId` is in the key because two strategies tagged on one config can legitimately cross on the same leg at the same candle. Without it the second one's entry would be discarded as a duplicate and the strategy would look like it never fired.

The dedupe key is `option_token`, **not** `(instrument_token, option_type)`. Earlier the broader key collided across strikes — a 24100 BUY would close an open 24200 SELL because both are CE on NIFTY. The narrower key fixed that.

---

## Close paths (which one?)

| Path | Trigger | Sets `exit_reason` | Calls broker exit? |
|---|---|---|---|
| `OrderService.closeOrder(...)` | Strategy signal of opposite direction matches an open row | `SIGNAL` | Yes |
| `OrderService.closeManually(...)` | `PositionService` detects target / trailing-floor / stop-loss breach | `TARGET` / `TRAIL_SL` / `STOP_LOSS` (caller passes) | Yes |
| `OrderService.forceCloseOpenPositions(date, closeAt)` | End-of-day cleanup — `BacktestAnalysisService` per replay day, `DaySummaryScheduler` at 15:31 live | `FORCE_CLOSE` | **Live: yes.** Backtest: no (the simulated placement has no venue) |

All three persist the row before any broker call so the ledger is always the source of truth.

### Force-close: live vs backtest

`forceCloseOpenPositions` runs one loop for both modes. The ledger update — exit
time, exit price, profit, `status=CLOSED`, `exit_reason=FORCE_CLOSE` — is
identical, and happens first. What follows differs:

- **Backtest** (placement name `BACKTESTING`) — nothing. The persisted row *is*
  the backtest ledger, and this branch is byte-for-byte what the method did
  before the live exit was wired, so re-running a range produces the same rows.
  `exit_broker_order_id` stays null and `fill_status` stays `BACKTEST`.
- **Live** — the opposite-side exit goes out through the same
  `OrderPlacementService.place(order, config)` the other two close paths use. The
  row is already `CLOSED` when placement sees it, which is how the service knows
  to invert the side (`transactionType(order)` in the broker adapter). A returned
  broker id lands on `exit_broker_order_id` and `fill_status` moves to `PENDING`.

When the live exit can't be dispatched the row still ends up `CLOSED` — the local
ledger and the broker have diverged, and the point is that this is now **loud**
rather than silent. `NotificationService.alertForceCloseExitFailed(order, reason)`
fires per stranded row and says to square off manually. Four things reach it:

| Cause | Why it doesn't just place anyway |
|---|---|
| Broker returned no order id | Not logged in, or the contract could not be resolved. On Zerodha the second case now means a real data problem — `instrument_details` has no row for the ledger's `option_token`, or it has one describing a different contract. See [Zerodha contract resolution](#zerodha-contract-resolution). |
| Broker threw | Network / API failure. Caught per row so one bad leg doesn't strand the rest of the batch as OPEN. |
| No cached `TradeConfigCombinedDTO` for the row's config | Quantity comes off the config; placement services fall back to quantity `1`. One unit against a 75-unit lot is a *new position*, not a close. Not closing is recoverable by hand; closing the wrong size isn't. |
| `OrderPlacementFactory.active()` unresolvable | A misconfigured `broker.active`. Resolved once, defensively — "close nothing" would be the worse answer than "close the ledger and shout". |

---

## Zerodha contract resolution

`ZerodhaOrderPlacementService.resolveContract(order)` turns a `trade_order` row
into the `(tradingsymbol, exchange)` pair Kite's `OrderParams` needs. It is a
**lookup, never a formatter**.

**Why.** Kite's NFO tradingsymbols are not derivable from
`(underlying, expiry, strike, type)` by one rule. Two rows from the bundled dump,
same underlying, same strike, same option type:

| instrument_token | tradingsymbol | expiry |
|---|---|---|
| `14598658` | `NIFTY2660223400CE` | 2026-06-02 (weekly — 2-digit year, *single* char month, day) |
| `20401922` | `NIFTY26JUN23400CE` | 2026-06-30 (monthly — 2-digit year, 3-letter month, no day) |

October/November/December weeklies use `O`/`N`/`D` for the month character, and a
month-end weekly is published in the monthly form. Any formatter would be a guess
that fires a real market order at a symbol the exchange may not list.

**The key.** `trade_order.option_token` is the broker instrument token
`TokenOptionInstrumentResolver` wrote when the leg was chosen — i.e. the primary
key of `instrument_details`. One `findById` is the whole resolution, and it
cannot drift from the leg the strategy analysed, because it *is* that leg's row.

**Refusals.** Every one of these returns `null`, so `place(...)` skips rather
than sending a wrong order (on the force-close path that raises
`alertForceCloseExitFailed`):

| Case | Meaning |
|---|---|
| `option_token` null / blank | Ledger row predates the token being written. |
| `option_token` isn't numeric | It's a `HISTORICAL_ICICI` natural key (`NIFTY\|NFO\|2024-01-04\|23400\|CE`). That source is replay-only; live placement needs `backtest.data-source=BROKER`. |
| No `instrument_details` row | The local dump is stale relative to the ledger — reload it. |
| Row has no `tradingsymbol` | Malformed dump row. |
| Row's strike / type disagrees with the ledger's | The dump was re-seeded and the token now names a *different* contract. Placing would trade the wrong leg. |

`exchange` is read off the row rather than hardcoded to `NFO`, so a BFO contract
(BANKEX / SENSEX) isn't routed to the wrong exchange; `NFO` remains the fallback
when the column is empty. Pinned by
[`ZerodhaTradingSymbolResolutionTest`](../src/test/java/com/moneymaker/broker/zerodha/ZerodhaTradingSymbolResolutionTest.java).

> **Prerequisite:** `instrument_details` must be populated for the expiries being
> traded. It is the same table `TokenOptionInstrumentResolver` reads to pick the
> leg in the first place, so if analysis produced a signal, the row placement
> needs is by construction already there.

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
| [Backtesting](../src/main/java/com/moneymaker/backtesting/BacktestingPositionMonitorService.java) | `SharedData.latestCachedCandle(optionToken, null)` — newest cached candle for the contract, taken from the **finest interval** cached for it |
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

# Ratchet the trailing floor up to whatever rung the PEAK has earned (never down).
lock = highest trail_ladder_at_entry rung whose trigger <= peak_profit
if lock != null and lock > trail_sl_at: trail_sl_at = lock

# Read thresholds from the snapshot on the row, NOT from SharedData / live config.
floor  = max(-order.stop_loss_at_entry, order.trail_sl_at)   # whichever is TIGHTER
reason = "TRAIL_SL" if the trail supplied the floor else "STOP_LOSS"

if pnl >= order.target_at_entry → OrderService.closeManually(id, price, now, "TARGET")
if pnl <= floor                 → OrderService.closeManually(id, price, now, reason)
else                            → save row

# After the decision above is settled, never before it:
PositionJournal.observe(order, asOf, pnl, decision)   # MONITOR row + any EVENT rows
```

**The journal write is observation, not a step.** It runs after
`thresholdBreach` has answered, takes that answer as an argument, and is wrapped
so that a journal failure cannot abort the tick or change an exit. It sits on
`PositionService` rather than `PositionScheduler` so a backtest replays it
identically (CLAUDE.md invariant 8). What it records — one `MONITOR` row per
evaluated tick, plus an `EVENT` row per BOS / CHoCH that became knowable while
the trade was running — is described in
[`OBSERVATION_JOURNAL.md`](OBSERVATION_JOURNAL.md#the-during-position-timeline).
Ticks skipped above (no quote, or the same-candle guard) write nothing.

**Why the two stops are collapsed into one floor instead of checked in sequence.**
A candle can gap through both at once. If they were checked one after the other,
the *order of the two `if`s* would decide the exit reason on exactly those ticks
— and the reason is the only thing that distinguishes a trailed exit from a
stopped-out one afterwards. Taking the higher floor and labelling it by whichever
put it there makes the answer independent of evaluation order. A trail sitting
*exactly* on the fixed stop reports `STOP_LOSS`, because it moved nothing.

### Chandelier trail (changeset 048)

A second trailing shape, per strategy rather than per config. When
`strategy_defaults.trail_atr_multiple` is set, `OrderService.openOrder` freezes
`multiple × TradeSignal.atr` (the ATR the strategy measured on its signal bar)
onto `trade_order.trail_atr_distance_at_entry` and nulls
`trail_ladder_at_entry` for that trade — one trail per trade, and nothing
beyond the row is needed after a restart. A signal without an ATR opens on the
fixed stop only and is logged once.

`PositionService.applyTrail` then sets `trail_sl_at = peak_profit − distance`
whenever that is higher than the current floor. The floor may be negative (a
stop that is still a loss); `thresholdBreach` already honours a trailed floor
whenever it is tighter than the fixed stop, so the first effective stop is
`entry + distance` or the `sl_pct` / `max_sl_points` cap, whichever is nearer,
and it only ever tightens. Exit reason `TRAIL_SL`, filled at the floor in force
when the breach was seen — on the exit tick the chandelier does **not** ratchet
first (the ladder still does, unchanged). Pinned in
`PositionServiceAtrTrailTest`.

`BracketMode.NONE` (also 048) is the third value of `target_mode` / `sl_mode`:
`bracketAtEntry` returns null for that side, which the monitor reads as "never
breaches". Strategy 8 seeds it for the target; nothing else uses it.

### Trailing stop-loss (changeset 036)

`trade_config.trail_ladder` holds ascending `trigger:lock` pairs in premium
points — `"25:2,50:25,75:50,100:75"` reads as "once the trade has been 25 points
in profit the stop moves to +2; at 50 it moves to +25". Parsed **only** by
`com.moneymaker.util.TrailLadder`, which is strict: a malformed rung is rejected
at the admin form and refused at entry, never silently trimmed. (Contrast
`StrategyIds`, which skips bad fragments — a dropped strategy id stops trades
visibly, a dropped rung changes exits invisibly.)

Three properties worth keeping in mind:

- **It latches off `peak_profit`, not current P&L.** Touching +50 fixes the +25
  floor even if price falls straight back to +30. That is the entire point: it
  converts excursion the trade actually achieved into a floor.
- **It only ever tightens.** `parse` rejects a ladder whose locks decrease, and
  `applyTrail` refuses to lower a floor already set.
- **A rung cannot close the trade on the tick it arms.** `parse` requires
  `lock < trigger`, so P&L at the moment of arming is always above the new floor.
  A rung with `lock == trigger` would be a take-profit, which `target_at_entry`
  already is.

The first rung must be reachable *before* the target or the ladder never arms.
With `target_pct = 0.20`, an 80-point leg targets 16 — below a 25-point first
rung — so the ladder is inert at the cheap end of the premium band. That is why
the rungs are per-config data rather than a constant.

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
| Force-close exit not placed (live) | `alertForceCloseExitFailed(o, reason)` | none — deliberately. Each stranded row is its own manual square-off, so a missed message is worse than a repeated one. |
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
| PUT | `/api/trade-configs/{id}?confirm=` | Update — `409 confirmRequired` while trades are open, see [Editing a config with live trades](#editing-a-config-with-live-trades) |
| DELETE | `/api/trade-configs/{id}` | Delete — `409` if any `trade_order` references the config |
| POST | `/api/trade-configs/{id}/active?value=` | Retire / reinstate without deleting, see [Retiring a config](#retiring-a-config) |
| POST | `/api/trade-configs/clone?fromDate=&toDate=&dryRun=` | Bulk-clone a day's configs onto another date, see [Cloning a day](#cloning-a-day) |
| GET | `/api/trade-configs/range?from=&to=&source=` | Every config in a trading-date window (unpaged). API-only companion to the backtest `configIds` scope for scripted runs — the UI selects by strategy instead |
| GET/PUT | `/api/downtrend-rules`, `/api/downtrend-rules/{id}/grid` | Detection rules panel: per-rule SMA grid / timeframes / indicator / enabled — see [EOD_DOWNTREND.md](EOD_DOWNTREND.md#skipping-smas--adding-a-different-indicator-rule) |
| POST | `/api/trade-configs/auto/bulk-update` | One field-set applied to every matching config at once, see [Bulk-editing many configs](#bulk-editing-many-configs) |
| GET | `/api/trade-configs/instruments` | Instrument dropdown source |
| GET | `/api/trade-configs/strategies` | Strategy dropdown source |

### Cloning a day

`POST /api/trade-configs/clone?fromDate=&toDate=&dryRun=` (GAPS #9) copies every
runnable config from one trading date to another, with its `sma_timeframe`
children. The toolbar's **Clone a day…** button previews first and then
confirms; the per-row `⧉ Clone` action is a different thing — it pre-fills the
create form from one existing config.

`dryRun` defaults to **true**, the same shape the bulk delete uses.

What it replaces is not just tedium. The workaround was
`INSERT … SELECT … WHERE trading_date='yesterday'`, which **bypasses
`TradeConfigAdminService`** and therefore the cache-invalidation contract of
invariant 10: the rows land in MySQL while `TradeConfigScheduler`'s date cache
and `SharedData.combinedDto` keep the old snapshot, so the running pipeline
cannot see them until the next restart.

| Decision | Why |
|---|---|
| Retired configs are not cloned | `is_active=false` means "do not run this". Carrying it forward as active resurrects exactly what someone retired. Counted and named in the summary rather than quietly missing. |
| Clones are stamped `MANUAL`, whatever the source was | Keeping `AUTO_DOWNTREND` would hand the row to `EodDowntrendDetectionService`'s dedupe key, which reads "a config already exists for this (day, strategy)" as "I already generated" — so cloning an AUTO config forward would silently suppress the detector's own output for that day. |
| Cloning a day onto itself is rejected | It could only duplicate every config. |
| Skip-if-present, not upsert | A source config is skipped when the destination already carries the same instrument + side + transaction type + primary strategy. That tuple is *not* a database key, so this is deliberately best-effort: a hand-built config that happens to match is reported as skipped rather than silently doubled. Doubling configs doubles positions, so the ambiguity resolves toward the recoverable failure. |

> `copyForDate` lists every column longhand. A new column nobody adds there is
> silently dropped from every clone — same failure mode as the `applyForm` /
> `toView` note below, and the same reason for not reflecting it away.

### Retiring a config

`is_active` (changeset 037, GAPS #7) is the retire-without-deleting state. A
config that has ever traded cannot be hard-deleted — the ledger references it —
and before this the only way to silence one was to shove its `tradingDate` into
the past, which falsifies the record of what the config was for.

Retired means **dropped from dispatch**:
`TradeConfigRepository.fetchCombinedByTradingDate` — the query that builds
`SharedData.combinedDto` — filters on `COALESCE(tc.is_active, TRUE) = TRUE`. The
row, its `sma_timeframe` children and all its `trade_order` history stay exactly
where they are. `findByTradingDate` is deliberately *not* filtered: the admin
list must show retired configs or you cannot reinstate one.

`COALESCE` rather than `= TRUE` on purpose — a NULL must read as active. The
alternative is silently retiring every config on the day the changeset lands.

**Retiring is refused while the config has OPEN trades**, and this is the part
worth remembering. A retired config leaves `SharedData.combinedDto`, and
`OrderService.findConfig` reads exactly that list to size an **exit**. With no
DTO the exit is never dispatched: the row is marked `CLOSED` while the broker
position stays open — one of the four paths `alertForceCloseExitFailed` exists
for. Close the trades first (or let the 15:31 sweep close them), then retire.
Reinstating is never blocked.

> The underlying resolution bug is older than the retire feature — editing
> `tradingDate` to another day does the same thing — and is filed as
> [`STRATEGY_ANALYSIS_TODO.md` S13](STRATEGY_ANALYSIS_TODO.md#s13-a-config-that-leaves-shareddatacombineddto-mid-day-strands-its-open-trades-broker-exits).
> When that lands, the refusal can relax to a warning.

### Editing a config with live trades

`PUT /api/trade-configs/{id}` returns **409 with `confirmRequired: true`** — not
an error — when the config has OPEN trades *and* the edit touches something
those trades still read (GAPS #8). The body lists each change
(`lotQuantity: 75 -> 150`) so the dialog can name them; `?confirm=true` applies
the same edit. It is a warning, not a block.

The rule for what counts is one line: **a field is consequential unless the
order snapshotted it at entry.**

| | Fields | Why |
|---|---|---|
| **Never asks** | `target`, `stopLoss`, `targetPct`, `slPct`, `maxSlPoints`, `trailLadder`, the premium band | Snapshotted onto `trade_order` at entry by changesets 011 / 036, precisely so a mid-day edit cannot re-price an open position. Warning here would be false, and would train the operator to click through. |
| **Asks** | `transactionType`, `tradingSide`, `lotQuantity`, `numberOfTradesPerDay`, `numberOfParallelTrades`, `strategyId`, `instrument`, `tradingDate` | Read live for the rest of the day. |

`lotQuantity` is the one that surprises people: `trade_order.quantity` *is*
snapshotted (changeset 029), but the placement services size an order from the
**config** (`ZerodhaOrderPlacementService.quantity`), so an open trade would exit
at a different size than it entered. That is a partial close or an accidental
reversal, not a resize.

Only `OPEN` trades gate — a config with a hundred closed trades and nothing live
edits freely.

[`TradeConfigAdminController`](../src/main/java/com/moneymaker/tradeconfig/controller/TradeConfigAdminController.java) is a thin HTTP layer; [`TradeConfigAdminService`](../src/main/java/com/moneymaker/tradeconfig/service/TradeConfigAdminService.java) is the **single owner** of trade-config writes — controllers and other feature code must call it rather than `TradeConfigRepository` directly (see the CLAUDE.md / AGENTS.md invariant).

> **`toView` must map every column the form can edit.** The form is rendered from
> the view DTO and posted back whole, so a column the DTO drops comes back as a
> blank and is written as one. Until 2026-08-30 `toView` never set `target_pct`,
> `sl_pct`, `min_option_price` or `max_option_price`: the list's bracket column
> showed points only, and **every edit through the UI silently cleared the
> percentage bracket**, reverting the config to the absolute points bracket that
> changeset 027 exists to replace. Fixed alongside 036, whose two new columns
> would have inherited the same bug. When adding a config column, add it in three
> places — `TradeConfigFormDTO`, `TradeConfigViewDTO`, **and both directions of
> `TradeConfigAdminService`** (`applyForm` *and* `toView`) — or the round trip
> quietly destroys it.

> **And a fourth place: the native combined query.** `SharedData.combinedDto` is
> built by `TradeConfigRepository.fetchCombinedByTradingDate` — a native query
> consumed **positionally** by `TradeConfigScheduler.mapToTradeConfig`. A column
> that is not in that SELECT list and not in that mapper is **null on every DTO
> the pipeline sees**, so the feature reading it silently never runs, in live and
> backtest alike, with nothing logged. This bit changeset 036 (`max_sl_points` /
> `trail_ladder` were inert until the query was fixed) and still bites changeset
> 027 (`target_pct` / `sl_pct` — see [S6](STRATEGY_ANALYSIS_TODO.md)). Append to
> the **end** of the column's own block, bump the two later mapper offsets, and
> extend `TradeConfigCombinedQueryContractTest`, which pins the whole ordering.

### Bulk-editing many configs

`POST /api/trade-configs/auto/bulk-update` applies **one field-set to every
config matching a selector in a single call** — the provision for retuning an
auto-generated fleet's SL / target without opening rows one by one. The
**✎ Bulk edit configs** panel on `/trade-configs` (collapsed, below bulk delete)
drives it.

```bash
# preview: what would a 25% SL and a 40-point cap touch on strategy 2's AUTO configs?
curl -X POST http://localhost:8080/api/trade-configs/auto/bulk-update \
     -H 'Content-Type: application/json' \
     -d '{"strategyId":2,"fromDate":"2024-01-01","toDate":"2024-01-31","slPct":0.25,"maxSlPoints":40}'

# commit — dryRun defaults to true, so committing is the explicit case
curl -X POST http://localhost:8080/api/trade-configs/auto/bulk-update \
     -H 'Content-Type: application/json' \
     -d '{"strategyId":2,"fromDate":"2024-01-01","toDate":"2024-01-31","slPct":0.25,"maxSlPoints":40,"dryRun":false}'
```

The contract, point by point:

- **It is a patch, not a replacement.** A field that is `null` (blank in the UI)
  is left untouched on every row. The one field needing a "clear" spelling is
  `trailLadder`: an empty string removes the ladder (the fixed stop then
  applies); the UI has a separate "Remove trail ladder" tick for it.
- **The panel prefills from the fleet's current state**
  (`GET /api/trade-configs/auto/bulk-update/prefill?source=&strategyId=`, same
  selector the apply uses): a field every matched config agrees on shows its
  value (numbers compared by value, not scale), a field the fleet disagrees on
  stays blank with a "mixed" placeholder and is named in the summary line. The
  UI dirty-tracks against that baseline, so **only fields you actually changed
  are sent** — a prefilled value left as-is is not rewritten, and clearing a
  prefilled number means "don't touch this field". *↺ Reset* reloads the
  baseline; a successful apply refreshes it.
- **Selector**: `source` defaults to `AUTO_DOWNTREND` (MANUAL is the same
  explicit opt-in the bulk delete requires), plus an optional `strategyId`
  (matches `strategy_ids` tags, or the primary for untagged rows — the same
  resolution dispatch uses) and an optional `fromDate`/`toDate` trading-date
  window (both or neither). **The UI panel deliberately offers no date window**
  (user decision 2026-08-31): its job is "all entries at once", so it always
  addresses every trading date of the source; the date filter is API-only, for
  scripted use.
- **Fields offered**: `target`, `stopLoss`, `targetPct`, `slPct`,
  `maxSlPoints`, `maxLoss`, `minOptionPrice`, `maxOptionPrice`, `trailLadder` —
  and deliberately nothing else. Everything here is either snapshotted onto the
  order at entry (the bracket) or an entry gate, so applying it with trades
  open cannot re-price an open position, which is why there is **no
  `confirmRequired` flow**: the fields that would need one (side, quantities,
  caps, strategy) are simply not offered — that is what the single-config edit
  is for.
- **Same value rules as the form** (`targetPct` in (0, 1), positive `slPct` /
  `maxSlPoints`, ladder parsed by `TrailLadder`), plus a per-row band check: a
  patch that would leave any matched config with an inverted premium band
  rejects the **whole batch**, naming the config — one transaction, never a
  partial apply.
- **`dryRun` defaults to true**; the UI previews and confirms against the
  server's own count.
- Runs through `afterMutation` per affected date, so the
  [cache-invalidation contract](#the-cache-invalidation-contract) holds.
- **Side effect**: every updated row gets a fresh `updated_date`, so the bulk
  *delete* panel's "generation run" clustering will show the edit as its own
  run, and pre-edit run selections no longer match these rows.

### The cache-invalidation contract

Every create / update / delete runs through `afterMutation(affectedDate)`, which:

1. **Always** calls `TradeConfigScheduler.invalidateConfigsCache()` — the date-keyed cache described in [SCHEDULERS.md](SCHEDULERS.md#single-entry-point-getconfigsfordatedate) would otherwise keep serving the pre-edit snapshot for the rest of the JVM's life.
2. **If** the affected date is *today* and `app.mode=live`, additionally rebuilds `SharedData.combinedDto` synchronously by calling `tradeConfigScheduler.getConfigsForDate(today)` and reassigning it — so the next 5-min `AnalysisScheduler` tick sees the edit immediately, without waiting for tomorrow's 09:16 cron or a JVM restart.

Edits to a *past* or *future* date, or any edit while `app.mode=backtest`, only invalidate the cache — there's no live `SharedData.combinedDto` to refresh outside of today.

### Auto-generated (`AUTO_DOWNTREND`) configs

Bulk operations scoped by `source` — the calendar view, the "which generation run was this" grouping, and the bulk-delete endpoint — are a separate, more specialized part of the same controller/service. They're documented in full in [EOD_DOWNTREND.md](EOD_DOWNTREND.md#deleting-generated-configs) rather than duplicated here, since they only make sense alongside the detector that produces those rows.

Two opt-ins there reach past the defaults, and both are off unless explicitly set: `force` also deletes configs that have `trade_order` rows (**and those trade rows**), and `source: MANUAL` aims the whole panel at hand-written configs instead of regenerable detector output. The single-config `DELETE /api/trade-configs/{id}` has neither and still refuses a traded config outright with a 409.

---

## Option premium band (`min_option_price` / `max_option_price`)

`itm_depth` / `otm_depth` decide **which strikes are scanned**; this band decides
**which of them are worth entering**. The two are not substitutes — a strike one
step OTM can be worth 200 points in the morning and 6 near expiry.

Both bounds are inclusive and independent (Liquibase
[`024`](../src/main/resources/db/changelog/024_add_option_price_range_to_trade_config.xml)).
`TradeConfigAdminService.validate` rejects a negative bound or `max < min` with a
400, since an inverted band matches nothing and would read as a dead strategy.

**The standing band is 80–250** ([`025`](../src/main/resources/db/changelog/025_default_option_price_range.xml)).
A config that leaves a bound blank gets the default, not "unbounded" — an
unbounded config is what produced 6-point entries against a 30-point target. The
value lives in three places that must be kept in step: the DB default,
`TradeConfigAdminService.DEFAULT_M{IN,AX}_OPTION_PRICE`, and the form's
`DEFAULT_M{IN,AX}_PRICE`. The duplication is deliberate — Hibernate names every
column in its INSERT, so a null field is written as an explicit NULL and the DB
default never fires on a JPA insert (the same trap that made `source` break every
create through the admin service).

> The DB-level default does not survive on a live instance. `spring.jpa.hibernate.ddl-auto=update`
> re-issues `MODIFY COLUMN` when the entity's declared precision differs from the
> table's, and MySQL drops the column default as a side effect — observed here:
> after startup the columns read `decimal(12,4)` with `Default: NULL`. This costs
> nothing in practice, because JPA inserts never consult the DB default anyway;
> the service constant is the one that decides. Do not "fix" it by removing the
> entity precision — that just trades a dead default for a schema mismatch.

A `NULL` in the column is still read as unbounded on that side, so rows predating
this change keep working; the admin path just never writes one.

### Why it exists

`target` and `stop_loss` are **absolute per-share points**, compared straight
against P&L in `PositionService.thresholdBreach`. That is incoherent across the
premium range a single config scans. Selling a 6.35 option the entire possible
gain is 6.35 — premium decaying to zero — so a 30-point target can never fire,
while a 30-point stop is 472% of premium. On the same tick the deep-ITM leg at
254 carries that same 30-point stop at 12%, i.e. ordinary noise. The band is the
control that keeps a config on legs where its thresholds mean something.

### Where it is enforced — and why not in `OrderService`

In [`AbstractSmaCrossStrategy.outsidePriceBand`](../src/main/java/com/moneymaker/strategy/AbstractSmaCrossStrategy.java),
at signal generation, against the leg's premium on that candle — the same value
that becomes `entry_price`. Not at strike-selection time, because a leg out of
band at 09:20 can be in band by noon.

Legs are scanned **highest premium first** (`AbstractSmaCrossStrategy.premiumComparator`), so
when a cap allows only one entry the dearest in-band leg wins it. This replaced
a strike-based proxy — ascending strike for CE, descending for PE, on the
assumption that deeper ITM is always dearer — which breaks down near expiry and
across the itm/otm span a single config scans. Ties break on the cache key, since
without an explicit tie-breaker a stable sort falls back to `ConcurrentHashMap`
iteration order and the same backtest picks a different strike each run.

**Only entry signals are filtered.** A strategy here is one-sided: an entry
carries the config's own `transactionType`, and the opposite direction is
exit-only — the rule `OrderService` already applies when deciding whether a
signal opens or closes. Filtering exits too would be actively harmful on a SELL
config, where a *falling* premium is the profit: a `minOptionPrice` would then
suppress precisely the winning exits and strand the position until stop-loss or
the end-of-day force-close. The direction check is what makes the gate
exit-safe by construction.

Suppressed signals log at debug as `[signal] SUPPRESSED … outside band [min, max]`
so a config that stops trading is diagnosable rather than silently idle.

---

## Adding a new broker

1. Per existing convention (see [Readme](../Readme.md)), add `BrokerLoginService` impl in `com.moneymaker.broker.<name>` first.
2. **Order placement.** Add `<Name>OrderPlacementService implements OrderPlacementService` in the same package. Implement both `place` (real broker order) and `syncFill` (broker order history → `FillSnapshot`). Use `getName()` matching the broker's enum value.
3. **Position monitor.** Add `<Name>PositionMonitorService implements PositionMonitorService` in the same package. Implement `currentPrice(TradeOrder)` against the broker's quote API.
4. Both factories auto-discover the new beans via Spring's `List<…>` injection — no factory edits required.
5. **Update this doc.** Add rows to the per-broker tables above.

---

## Adding a new exit reason

1. Pick an UPPER_SNAKE name. Currently used: `SIGNAL`, `TARGET`, `STOP_LOSS`, `TRAIL_SL`, `TIME_STOP`, `FLATTEN`, `FORCE_CLOSE`.
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
| Max trades per `(config, strategy)` per day (across all strikes, all statuses) | `tradeConfig.numberOfTradesPerDay` |
| Max simultaneous OPEN trades per `(config, strategy)` per direction | `tradeConfig.numberOfParallelTrades` |
| **Which bracket column the target resolves from** | `strategy_defaults.target_mode` (changeset 041) — `PERCENT` (default) takes `tradeConfig.targetPct` × entry premium, `POINTS` takes the absolute `tradeConfig.target`. Keyed by **strategy**, not by config, so one config named by several strategies can bracket differently under each. Switchable from `/trade-configs` → Bulk edit configs → ⚖️ Strategy bracket — see [EOD_DOWNTREND.md](EOD_DOWNTREND.md#strategy-bracket-panel) |
| **Which bracket column the stop resolves from** | `strategy_defaults.sl_mode` — same two values, resolved independently of the target so a points target with a percentage stop is expressible |
| Profit target (per share) | `tradeConfig.targetPct` × entry premium or `tradeConfig.target`, per `target_mode` above → snapshotted to `target_at_entry` at open. Either mode falls back to the other column when its own is unset — a null here reads as "never breaches" in `PositionService` |
| Stop loss (per share, positive) | `tradeConfig.slPct` × entry premium or `tradeConfig.stopLoss`, per `sl_mode` → snapshotted to `stop_loss_at_entry` at open, then capped by the ceiling below |
| Ceiling on the stop loss, in points (whichever is lower applies) | `tradeConfig.maxSlPoints` — applied at open, so `stop_loss_at_entry` already carries the capped value. Blank on the admin form resolves to the standing 60 (`TradeConfigAdminService.DEFAULT_MAX_SL_POINTS`), **not** to uncapped |
| Where the stop moves as profit accrues | `tradeConfig.trailLadder` → snapshotted to `trail_ladder_at_entry` at open; blank = no trailing |
| Lot quantity | `tradeConfig.lotQuantity` |
| Tradeable premium band at signal time (default 80–250) | `tradeConfig.minOptionPrice` / `tradeConfig.maxOptionPrice` |
| Which in-band leg wins when a cap allows one | highest premium first — `AbstractSmaCrossStrategy.premiumComparator` |
| Whether a stop-loss closes the book for the day | `Strategy.stopLossLocksBookForDay()` — declared per strategy (identity, like a rule set), enforced here as gate 6. Only `Strategy6` declares it; promoting it to a `TradeConfig` column is an open question in [S21](STRATEGY_ANALYSIS_TODO.md) |
| Active broker | `broker.active` (application property) |
| Backtest replay window | `fromDate` / `toDate` from the `/api/backtest/analysis` request |

When a new trading rule is needed and no `TradeConfig` field exists, **ask the user first** — they will either point at an existing column with a different name than expected, or sanction a new Liquibase changeset to add one. Do not guess at a default and do not embed a constant.

### What MAY stay hardcoded (technical / correctness)

- **Same-candle guard** in `PositionService.handleOne` — a trade cannot exit on the same candle that opened it. Correctness invariant.
- **Exact-duplicate guard** in `OrderService.handleSignal` — `(configId, strategyId, optionToken, direction, entryTime)` uniquely identifies one ledger row. Re-runs and same-tick repeats are deduplicated. Idempotency.
- **`STATUS_OPEN` / `STATUS_CLOSED`, `FILL_PENDING` / `FILL_BACKTEST` / `FILL_COMPLETE`** — internal lifecycle vocabulary. Not user-tunable.
- **Per-share P&L formula** — direction-aware subtraction. A formula, not a parameter.

### What is technically hardcoded but probably should move to config later

- **NSE market open `09:20`, market close `15:30`** in `BacktestAnalysisService.run` — market-wide constants today; would need to move to a `MarketProperties` if a non-NSE market is ever added.
- **`15:15` "market close time" rule** in `CommonRules.isMarketCloseTime` — same caveat.

These aren't trading-behaviour rules per se (they're broker / exchange constants), so they don't violate the principle today. But flagging them so the next contributor knows.

---

## Things that are still pending

- ~~**Zerodha tradingsymbol resolution.**~~ **Done 2026-08-31** — resolved by `instrument_details` primary-key lookup on `trade_order.option_token`, not by formatting a symbol. See [Zerodha contract resolution](#zerodha-contract-resolution) for why the lookup is the only sound shape and what each refusal means. The originally sketched `(name, expiry, strike, optionType)` lookup was not needed: the token *is* that tuple's already-resolved answer, and it comes off the same row the strategy analysed.
- **Groww + Angel One real REST clients** for both `OrderPlacementService` and `PositionMonitorService`.
- (Live force-close now places a real broker exit — see "Force-close: live vs backtest" above. On Zerodha it is no longer gated behind symbol resolution; the per-row alert now only fires on a genuine failure. GAPS #1.)
- (Both `numberOfTradesPerDay` and `numberOfParallelTrades` are now enforced — see steps 3 and 4 in "Open / close decision rules" above.)
- **Lot-size aware quantity** — `quantity()` in placement services treats `tradeConfig.lotQuantity` as raw quantity. Multiplying by lot size (50 for NIFTY etc.) needs a data source decision. The end-of-day digest's net P&L uses the *same* number as its multiplier (GAPS #2), deliberately — so if this bullet is ever resolved, the digest has to move with it or the two will disagree.
- **`lot_quantity_at_entry` snapshot.** `trade_order` has no lot-size snapshot, so the day-summary net P&L joins `TradeConfig.lotQuantity` live. Editing a config's lot quantity mid-day therefore re-prices trades that already closed — the staleness `target_at_entry` (changeset 011) exists to prevent. Remaining half of GAPS #2.
- ~~**Per-position audit trail** — peak / last-monitored is overwritten each tick. If we ever need a full price-vs-time history per trade, an `order_monitor_history` table is the next step.~~ **Covered as of 2026-08-31, in a different place than this bullet proposed:** the observation journal's `MONITOR` rows are that per-tick history, written to `journal_observation` rather than a new table, so a closed trade can be replayed tick by tick against its structure and OI context. See [`OBSERVATION_JOURNAL.md` → the during-position timeline](OBSERVATION_JOURNAL.md#the-during-position-timeline). The row on `trade_order` is still overwritten — the ledger keeps one line per trade, on purpose.

---

## Charges and net P&L

`trade_order.profit` is **per share**. Rupee economics come from
`TradeChargeService`, which costs a row from `quantity` and the `charge_rate`
table and returns a `TradeCharges` alongside it on `GET /api/orders`.

### Computed on read, never stored

Nothing is written back onto `trade_order`. The seeded rates are documented but
**unverified**, so the first real contract note will probably correct one — and
when it does, every historical trade should re-cost itself rather than carry a
number frozen from a wrong rate. Charges are a view over the ledger, not part of
it. Correcting a rate is an `UPDATE`, not a code change or a backfill.

### Rates are date-effective

`charge_rate` is keyed `(charge_type, segment, effective_from)`, and a trade is
costed with the rates in force on **its own entry date**. This is not
future-proofing — the 2024 backtest range already spans a change:

| Charge | Until 2024-09-30 | From 2024-10-01 |
|---|---|---|
| `STT_SELL_PCT` | 0.0625% of premium | **0.1%** of premium |
| `EXCHANGE_TXN_PCT` | 0.053% of premium | **0.03503%** of premium |

Measured effect on the 2024 ledger: ₹25.72 average charge per trade before the
change, ₹31.14 after. A single flat rate would misstate roughly a quarter of the
trades, in the direction that flatters the earlier ones.

### The formula

Turnover for an option leg is `premium × quantity` — premium turnover, not
notional, because F&O statutory charges are levied on premium.

| Component | Basis |
|---|---|
| Brokerage | per leg: `min(BROKERAGE_FLAT_PER_ORDER, BROKERAGE_PCT_OF_TURNOVER × legTurnover)` |
| STT | sell leg only |
| Exchange transaction | both legs |
| SEBI turnover fee | both legs |
| Stamp duty | buy leg only |
| GST | on (brokerage + exchange transaction + SEBI) |

### Assumptions

- **Both legs execute on the entry date.** True for these intraday strategies —
  `forceCloseOpenPositions` squares off at 15:20 — but a positional variant would
  need the exit date too.
- **A row that cannot be costed reports `null`, not zero.** An OPEN position has
  no exit leg; a pre-029 row has no quantity. The ledger totals count these
  separately rather than folding them in, so a total never quietly understates cost.
- **A missing rate contributes zero and logs a warning** rather than throwing, so
  charges visibly understate instead of aborting a ledger read.

> **The seeded Zerodha rates are unverified.** Every row carries `UNVERIFIED` in
> its `notes` column and the ledger UI repeats it. STT dominates option selling —
> if you verify one number against a contract note, verify that one.
