# Backtest performance & live-parity plan

> **Status:** Phase 1 implemented (2026-05-25). Phases 2–6 still planned.
> As each lands, mark it ✅ and add a "verified parity" note.

## Why this document exists

Every shortcut taken to make backtest faster is a place where backtest and
live diverge. Divergence is what breaks strategies on go-live: a rule that
worked for 50 backtest days behaves differently the first live day because
the production path computes SMAs differently, fetches data differently, or
sees a different candle than the replay did.

**The rule we hold ourselves to:** *backtest must produce the same trade
decisions live would have produced from the same input data.* "Same input
data" means same candle list, same timestamps, same SMA values at the same
indices. Speed improvements that change any of those are not acceptable
without a deliberate decision recorded here.

This doc lists the planned phases, the speed-up each is expected to give,
and — for each — exactly how it touches the live code path and what the
parity guarantee is. Read this before implementing any phase; update it
when the phase lands.

---

## Baseline

| Metric | Today |
|---|---|
| 2-day backtest wall time | ≈ 3–4 min |
| Broker HTTP calls per day | ≈ 1500 (72 ticks × ~21 calls/tick) |
| Tick increment | 5 min (smallest configured timeframe) |
| Per-tick work | refetch underlying + each strike × each timeframe, recompute SMAs, evaluate strategy, drain orders, walk OPEN positions |

The bottleneck is HTTP: each `MarketDataService.fetchHistoricalData(...)`
call hits Zerodha, blocks on the Resilience4j rate-limiter, and returns the
same window we already fetched on the previous tick.

---

## Live-parity contract

A phase passes the parity bar when **all** of the following hold:

1. **Same call surface.** Strategy code, `OrderService`, and `PositionService`
   keep calling the same provider interfaces. Whatever changes must sit
   behind `MarketDataProvider` / `OrderPlacementService` / `PositionMonitorService`.
2. **Same candle data.** For a given `(symbol, interval, tickAt)`, the candle
   list the strategy sees in backtest is byte-identical to what it would
   have seen in live — same timestamps, same OHLC, same SMA values.
3. **Same scheduler entry points.** `BacktestAnalysisService` keeps calling
   the same `analysisScheduler.calculateIndicator / runStrategies`,
   `orderScheduler.processOrders`, `positionScheduler.processPositions` —
   none of those methods grow a `if (backtest) …` branch.
4. **Reversible.** Reverting the phase restores byte-identical behaviour.

If a phase fails any of (1)–(3), it's a divergence, not an optimisation,
and needs explicit sign-off recorded here.

---

## Phase 1 — Per-day candle cache ✅ implemented

**Expected speedup:** 10–20× (≈ 3-4 min → 20-30 s for 2 days).

### What changes (as built)

Three new/changed components:

- **`com.moneymaker.backtesting.BacktestMarketDataCache`** — keyed by
  `(symbol, interval)`, stores the full day's candle list for a backtest day.
  `beginDay(from, to)` resets state; `slice(symbol, interval, from, to)` returns
  the sub-range; `endDay()` clears.
- **`com.moneymaker.market.service.KiteHistoricalFetcher`** — the original
  throttled HTTP path, lifted out of `MarketDataService` into a sibling
  `@Service` so Spring AOP's `@RateLimiter` / `@Retry` keep firing (a
  self-invocation inside `MarketDataService` would have bypassed them).
- **`MarketDataService.fetchHistoricalData`** — now cache-first:
  1. If the cache is active and a slice exists, return it.
  2. If active and no slice, call `KiteHistoricalFetcher.fetch(...)` with the
     **wide** `[dayFrom, dayTo]` window once, store the result, then slice.
  3. If inactive (live mode), forward the original `[from, to]` straight to
     the throttled fetcher — byte-identical to the pre-Phase-1 path.

`BacktestAnalysisService.run` calls `cache.beginDay(...)` at each day's
start (using `analysisScheduler.computeLookbackCalendarDays()` to derive
`dayFrom`) and `cache.endDay()` in a `finally` so the cache always clears
between days even if the tick loop throws.

Eliminates 99% of broker HTTP calls (~72 → 1 per `(symbol, interval)` per day).

### Live impact

| Component | Affected? | Notes |
|---|---|---|
| `MarketDataService` | Behind an interface | The caching wrapper is registered **only when `app.mode=backtest`**. Live mode binds the existing pass-through provider. |
| Live cron path | No | `AnalysisScheduler.calculateIndicator` keeps calling `marketDataService.fetchHistoricalData` exactly as today. |
| Strategy / Order / Position services | No | They don't touch the provider directly. |
| Rate-limiter | Indirect win in backtest, untouched in live | Live still respects Zerodha's 3 req/s limit via Resilience4j. |

### Parity guarantee

- The cached slice is *literally* the union of windows the broker would have
  returned over the day's ticks (with the same daily lookback). For any
  `(symbol, interval, tickAt)`, the returned list is identical to what a
  fresh broker call at that instant would return.
- Verification: run a single day with and without the cache, diff the
  `trade_order` rows. Must be identical (same entry_time, entry_price,
  exit_time, exit_price, profit).

### Risks

- **Memory.** ~1500 candles × 6 strikes × 3 timeframes × 8 bytes/field
  ≈ a few MB per day. Negligible.
- **Stale data on intra-day config changes.** Backtest doesn't allow
  mid-day config edits anyway (covered by `TradeConfigScheduler`'s
  day-keyed cache); no new exposure.

---

## Phase 2 — Skip redundant strategy runs per timeframe

**Expected speedup:** 2–3× on top of Phase 1.

### What changes

The tick loop advances by the smallest timeframe (5 min). At 09:30, 09:35,
09:40, 09:45 the 15-min strategy is re-run against the **same** candle
(09:15→09:30). Add a small `Map<(tradeConfigId, interval, strike), LocalDateTime>`
inside `Strategy1.execute` and skip the gate / rule evaluation when the
last candle's timestamp hasn't advanced since the previous tick.

### Live impact

| Component | Affected? | Notes |
|---|---|---|
| Live cron path | No | Live's `AnalysisScheduler` fires on a 5-min cron and evaluates every candle. The skip is keyed by candle-timestamp, not by clock — in live the cron tick *always* sees a new candle for at least the 5-min timeframe. |
| Strategy code | Yes, but the skip predicate works identically in live | When a 5-min cron runs, 15-min's last candle has indeed not advanced 3 of every 4 fires — so the same skip helps live too (small CPU win, no behaviour change). |

### Parity guarantee

- Strategy decisions depend only on the last candle's OHLC + SMA. Skipping
  the re-evaluation of the *same* candle produces the same signal (`NONE`),
  because the inputs are byte-identical. Trivially equivalent.
- Verification: same as Phase 1 — diff the `trade_order` ledger before/after.

### Risks

- None for correctness. The risk is a stale skip-map carrying entries from
  the previous day; the day-loop must clear it at day-start.

---

## Phase 3 — Incremental SMA at day-start

**Expected speedup:** 1.5–2× on top of Phases 1–2.

### What changes

Today `SmaTrendCalculator.compute(...)` and `IndicatorService` recompute
SMA-{20,50,100,200,500} from scratch on every call, summing `period`
candles each time. Move SMA population to a **single pass** at day-start
(right after Phase 1's pre-fetch). Walk each candle list once with a
rolling sum: on each new candle, subtract the dropped-out tail and add
the new head. Each `MarketData` row's `smaValueN` is then stamped once,
and Strategy1 reads precomputed values.

### Live impact

| Component | Affected? | Notes |
|---|---|---|
| `IndicatorService` / `SMAIndicatorImpl` | Replaced internally with a rolling-sum implementation | Public interface unchanged. Live cron fetches data once per 5-min tick and computes SMA on the fly — same rolling-sum implementation produces the same numbers, just faster. |
| Strategy code | No | Reads `lastCandle.getSmaValueN()` exactly as today. |
| `MarketData` entity | No schema change | The `sma_value*` columns already exist. |

### Parity guarantee

- Rolling-sum SMA is **mathematically identical** to recompute-from-scratch
  SMA — it's the same formula with O(1) update instead of O(period). No
  floating-point order-of-operations difference because each new SMA value
  is computed from the same `period` consecutive candles.
- Verification: pick a long candle list, compute SMA both ways, assert
  byte-equal `BigDecimal`s with the same scale.

### Risks

- **Floating point.** If we ever switch from `BigDecimal` to `double`,
  rolling-sum drift can accumulate. As long as we stay on `BigDecimal` with
  fixed scale, exact equivalence holds.
- **Re-entry edge case.** If a candle list is mutated after SMA is stamped
  (e.g. broker re-emits a corrected candle), the cached SMA goes stale. In
  live this can't happen within a single 5-min window; in backtest the
  per-day cache is immutable.

---

## Phase 4 — Bulk strike download at day-start (parallel)

**Expected speedup:** day-start latency 20 s → 2–3 s (parallel within
rate-limiter), independent of Phases 1–3.

### What changes

Use the existing `OptionsBulkDownloadService` (already used by the bulk
download tool) to pull all strikes for the day in one batched flow at
day-start, instead of per-strike sequential `fetchHistoricalData` calls.
The bulk service already respects the rate-limiter.

### Live impact

| Component | Affected? | Notes |
|---|---|---|
| Live cron path | No | Live's `AnalysisScheduler` fetches a *single* tick's worth of data per 5-min cron — it doesn't batch. Backtest needs the entire day at once; live doesn't. |
| `OptionsBulkDownloadService` | Same code, new caller | The service is already production-ready; nothing changes inside it. |

### Parity guarantee

- The bulk fetch returns the same candle lists per `(symbol, interval)`
  as N sequential calls would have. The broker API is the same.
- Verification: diff the per-day cache populated by sequential vs bulk —
  must be identical.

### Risks

- Bulk calls amplify quota errors. Phase 1 already collapses 1500 calls/day
  to ~20; running Phase 4 on top is fine because we're well under the
  rate-limiter ceiling.

---

## Phase 5 — Downsample DEBUG logging during runs

**Expected speedup:** 1.2–1.5× when measured cold.

### What changes

The tick narrative (`[index]`, `[tick]`, `[position]`, `[order]`) is
extremely useful for debugging but produces hundreds of lines per tick. On
Windows console + file I/O this is non-trivial.

Two options, pick one:

1. **Operational:** document `logging.level.com.moneymaker=INFO` as the
   default for performance benchmarks; DEBUG only when investigating.
2. **Code:** demote the `[tick]` lines to TRACE so DEBUG stays usable
   but the firehose is opt-in.

Recommend option (1) — zero code change, same effect.

### Live impact

| Component | Affected? | Notes |
|---|---|---|
| Live log level | Operator decides | The application.properties block already documents the levels (`[Backtest]` quick-start preset enables DEBUG; live ops typically run INFO). |

### Parity guarantee

- Trivially identical; logging doesn't affect decisions.

### Risks

- None.

---

## Phase 6 — Position-monitor in-memory OPEN set

**Expected speedup:** Marginal — small DB SELECT savings cumulative over
multi-day runs.

### What changes

`PositionService.processPositions()` runs `findByStatus("OPEN")` every
tick. Replace with an in-memory `Set<Long> openOrderIds` maintained by
`OrderService.openOrder` / `closeOrder` / `closeManually` /
`forceCloseOpenPositions` (every place that flips status). PositionService
walks the in-memory set, hydrating each via `findById` only when needed.

### Live impact

| Component | Affected? | Notes |
|---|---|---|
| `OrderService` | Yes — adds set-mutation calls in 4 places | Live and backtest both benefit. Slight increased coupling. |
| `PositionService` | Walks the in-memory set | Same logic, different source. |
| Crash recovery | **Important** | On JVM restart, the in-memory set is empty. It must be hydrated from `findByStatus("OPEN")` on startup. Without this, OPEN trades after a restart are no longer monitored. |

### Parity guarantee

- The set is a cache of the DB's source of truth. As long as every
  status-mutating path updates the set in the same transaction as the DB
  row, equivalence holds.
- Verification: restart the JVM with OPEN trades on disk, confirm
  position monitor picks them up on first tick.

### Risks

- **Most error-prone phase.** Cache invalidation across 4 call sites is
  classic regression territory. Save for last; only do if measurable wins
  remain after Phases 1–4.

---

## Recommended sequencing

1. **Phase 1** alone — biggest single win, lowest risk, fully isolated
   behind the `MarketDataProvider` interface. Gets the user from 3-4 min
   to ~20-30 s for a 2-day run.
2. **Phase 2 + Phase 3** together — both are pure refactors with
   mathematical equivalence guarantees. Pair them in one PR so the parity
   verification (diff `trade_order` rows) runs once for both.
3. **Phase 5** — config-only, zero code; flip when benchmarking.
4. **Phase 4** — meaningful for long runs (50+ days); skip for 2-day
   debugging.
5. **Phase 6** — only if the OPEN-set query shows up in a profile after
   Phases 1–4. The complexity isn't worth a marginal win otherwise.

## What we will NOT do

- **No `if (backtest)` branches in live services.** Anything backtest-only
  must live in `com.moneymaker.backtesting` or behind a provider
  registered only in backtest mode.
- **No parallel strike evaluation inside a tick.** `SharedData` is mutable
  static; threading it would invent a class of bugs we don't have.
- **No SMA approximations (e.g. double instead of BigDecimal).** Speed must
  not change numbers.
- **No skipping `Liquibase` / Spring startup for backtest.** Startup cost
  is paid once; per-day work dominates.

---

## Parity verification checklist

Before merging any phase, run this two-step check:

1. **Identical inputs.** Pick a date with active configs and known signals.
   Run backtest with the phase **disabled** (revert toggle / new
   provider not registered). Dump `trade_order` rows for that date.
2. **Identical outputs.** Re-run with the phase **enabled**. Diff the
   `trade_order` rows. Must be identical on:
   - `entry_time`, `entry_price`, `entry_reason`
   - `exit_time`, `exit_price`, `exit_reason`
   - `profit`, `peak_profit`, `peak_loss`
   - The set of `strategy_id` × `option_strike` × `option_type` rows.

Any non-identity is a divergence. Record it here under the relevant phase
and either fix the divergence or get explicit sign-off.

---

## Live ↔ backtest call-graph reference

Keep this picture in mind when judging a phase's parity risk. The two
modes share everything below `Service`:

```
LIVE                                         BACKTEST
─────────────────────────────────────        ─────────────────────────────────────
@Scheduled crons                             BacktestAnalysisService.run
  AnalysisScheduler.analyzeMarketData          loop tick(t):
     calculateIndicator(now)                     calculateIndicator(t)
     runStrategies()                             runStrategies()
  OrderScheduler.processOrders                   orderScheduler.processOrders()
  PositionScheduler.processPositions             positionScheduler.processPositions()
  TradeConfigScheduler.checkTradeConfigAt916AM   tradeConfigScheduler.reportConfigsForDay
  LoginScheduler                                 (one-shot login at run start)
                ↓ same methods ↓
        AnalysisScheduler.calculateIndicator(LocalDateTime)
        AnalysisScheduler.runStrategies()
        OrderService.processOrders()
        PositionService.processPositions()
        Strategy1.execute(config)
        RuleEngine.decide(ctx, sell, buy)
        OrderService.openOrder / closeOrder / closeManually / forceCloseOpenPositions
        TradeOrderRepository / TradeConfigRepository (JPA, MySQL)
        MarketDataProvider (← Phase 1 inserts cache only on this seam)
        OrderPlacementService (factory dispatches on app.mode)
        PositionMonitorService (factory dispatches on app.mode)
```

Phase 1, 4, 6 only touch the bottom row. Phases 2, 3, 5 are inside the
shared services but produce mathematically identical outputs.
