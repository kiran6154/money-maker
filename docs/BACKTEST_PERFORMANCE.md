# Backtest performance & live-parity plan

> **Status:** Phase 1 implemented (2026-05-25). Phase 3 and part of Phase 6
> implemented (2026-08-29). **Phase 2 is withdrawn — it is not safe as written.**
> Phases 4 and 5 still planned. As each lands, mark it ✅ and add a "verified
> parity" note.
>
> Phase 0 below was not in the original list and turned out to matter more than
> any of the numbered phases once the data set grew.

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

Original, before Phase 1 (broker data source):

| Metric | Then |
|---|---|
| 2-day backtest wall time | ≈ 3–4 min |
| Broker HTTP calls per day | ≈ 1500 (72 ticks × ~21 calls/tick) |
| Tick increment | 5 min (smallest configured timeframe) |
| Per-tick work | refetch underlying + each strike × each timeframe, recompute SMAs, evaluate strategy, drain orders, walk OPEN positions |

The bottleneck then was HTTP: each `MarketDataService.fetchHistoricalData(...)`
call hit Zerodha, blocked on the Resilience4j rate-limiter, and returned the
same window already fetched on the previous tick.

Measured 2026-08-29 on `HISTORICAL_ICICI`, 2024-01-02→01-04 (3 days, 219 ticks),
DEBUG logging on (so all of these are inflated by log I/O — see Phase 5):

| | Data set | Wall time |
|---|---|---|
| After Phase 1, before Phase 0/3/6a | ~110k option rows | 26.2 s |
| After Phase 0 + 3 + 6a | ~110k option rows | **19.9 s** |
| After Phase 0 + 3 + 6a | **3.77M option rows** | **8.7–10 s** steady state |

Read those rows carefully — they are not all the same comparison:

- The first two are the honest before/after: same data, same JVM state (both a
  first run after restart), same ledger out. **−24%.**
- The third is on a 34× larger table but is JIT-warm and buffer-pool-warm, so it
  is not comparable to the rows above and does **not** mean "more data is faster."
  It is there to show the absolute steady-state cost after a full import.

The pre-Phase-0 code was never measured on the full data set, because the point of
Phase 0 is that it could not have coped: at 3.65M rows the `UPPER(...)` form of the
per-series fetch plans as a full scan of **3,649,487 rows**, against **378** for the
fixed form — and the expiry query ran ~400 times per backtest day. Direct query
timing at that scale, ~150–450 ms extra per fetch (both figures include ~50 ms of
client startup):

| Query form | Rows examined | Wall |
|---|---|---|
| plain `=` | 378 | 59–170 ms |
| `UPPER(...)` | 3,649,487 | 216–533 ms |

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

## Phase 0 — The historical queries were not using their index ✅ implemented

Not in the original plan, and the largest win once the imported data set grew
from ~100k rows to ~3.8M.

Every `@Query` on `HistoricalOptionCandleRepository` /
`HistoricalSpotCandleRepository` wrapped its key columns in `UPPER(...)`:

```
UPPER(c.stockCode) = UPPER(:stockCode) AND UPPER(c.exchangeCode) = UPPER(:exchangeCode)
```

A function on the leading index column makes the index unusable. `EXPLAIN` on the
same rows, same query, with and without:

| | type | key | rows examined |
|---|---|---|---|
| `UPPER(...)` | `ALL` | `NULL` | 103,585 + filesort |
| plain `=` | `range` | `uk_historical_option_series_time` | **378** |

The `UPPER` was never buying anything: the table collation is
`utf8mb4_0900_ai_ci`, so `=` already compares case-insensitively, and both writers
(`HistoricalChartCsvImportService.normalize`, `HistoricalSymbol.upper`) normalise
to upper case before the value reaches the DB. The same reasoning rules out
Spring Data's `…IgnoreCase…` derived-query keywords on these tables — they
generate the identical `upper()` call.

Three further changes in the same pass:

- **`findAvailableExpiriesOnOrAfter` → `findNearestExpiryOnOrAfter`.** Both callers
  only ever took the first element, but the `SELECT DISTINCT … ORDER BY` had to
  walk the whole index and sort it (`Using temporary; Using filesort`) to build
  the list. As `MIN(expiryDate)` MySQL reports **`Select tables optimized away`** —
  answered from index metadata, zero rows touched.
- **`HistoricalOptionInstrumentResolver` memoises expiry per `(stockCode, date)`.**
  `AnalysisScheduler.fetchAndShareStrikeMarketData` calls `resolveExpiry` once per
  *(config × timeframe)* per tick — ~400 times a backtest day for an answer that
  cannot change during a run.
- **`028_drop_duplicate_historical_indexes.xml`.** `018` created an `idx_*_lookup`
  on each historical table whose column list and order were *identical* to the
  table's unique constraint. It could never win a plan the unique key didn't
  already serve, and it doubled per-row write cost during import — index bytes
  already exceeded data bytes (17.1 MB vs 10.5 MB).

**Live impact:** none. Both repositories are only reachable with
`backtest.data-source=HISTORICAL_ICICI`, which `HistoricalDataSourceGuard` refuses
in live mode, plus the historical chart dashboard.

**Parity:** the queries return the same rows in the same order; only the access
path changed. Verified by the Phase 3 ledger diff below, which exercised all of it.

---

## Phase 1 — Per-day candle cache ✅ implemented

**Expected speedup:** 10–20× (≈ 3-4 min → 20-30 s for 2 days).

### What changes (as built)

Three new/changed components:

- **`com.moneymaker.backtesting.BacktestMarketDataCache`** — keyed by
  `(symbol, interval)`, stores the full day's candle list for a backtest day
  **together with the window it was fetched over**. `beginDay(from, to)` resets
  state; `slice(symbol, interval, from, to)` returns the sub-range, or `null`
  when the request reaches outside the stored window; `endDay()` clears.
- **`com.moneymaker.market.service.KiteHistoricalFetcher`** — the original
  throttled HTTP path, lifted out of `MarketDataService` into a sibling
  `@Service` so Spring AOP's `@RateLimiter` / `@Retry` keep firing (a
  self-invocation inside `MarketDataService` would have bypassed them).
- **`MarketDataService.fetchHistoricalData`** — now cache-first:
  1. If the cache is active and a slice exists, return it.
  2. If active and no slice, call `KiteHistoricalFetcher.fetch(...)` once with
     the **union** of `[dayFrom, dayTo]` and the caller's `[from, to]`, store
     the result against that window, then slice.
  3. If inactive (live mode), forward the original `[from, to]` straight to
     the throttled fetcher — byte-identical to the pre-Phase-1 path.

  > The union — rather than `[dayFrom, dayTo]` outright — is what keeps a caller
  > with a longer lookback than the tick loop honest. `EodDowntrendDetectionService`
  > wants ~30 calendar days for its ATR and up to 35 for its SMA grid; narrowing
  > to the day window handed it a few days and a partial average, with no miss
  > and no log line. For the tick loop, whose windows already sit inside the day
  > window, the union *is* the day window — same single fetch, same result.

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

## Phase 2 — Skip redundant strategy runs per timeframe ❌ withdrawn

**The premise was right, the justification was wrong, and investigating it
surfaced a live-parity bug that has nothing to do with performance.** Read this
section before re-proposing the optimisation.

### What it proposed

The tick loop advances by the smallest timeframe (5 min). At 09:30, 09:35, 09:40
and 09:45 the 15-min strategy is re-run against what looks like the same candle.
Keep a `Map<(tradeConfigId, interval, strike), LocalDateTime>` in `Strategy1` and
skip the rule evaluation when the last candle's timestamp hasn't advanced.

### Why it was called trivially equivalent, and why that reasoning fails

The original argument was "the inputs are byte-identical, so the signal is the
same." Whether that holds depends on something the argument never checked:
whether a bar's *contents* can change while its *timestamp* stays put.

For a genuinely forming bar they can — and that is exactly what live does. A
broker asked for `[start, 09:39]` returns a **partial** 15-min bar stamped 09:30,
carrying only the 09:30 and 09:35 five-minute candles. Five minutes later the
same timestamp carries more. A timestamp-keyed skip would freeze the strategy on
the first partial bar and never see the bar close.

### The bug this exposed ✅ fixed 2026-08-29

In backtest the bar did not change between ticks — for a reason that was itself a
defect.

Phase 1 had `MarketDataService` fetch the **wide** `[dayFrom, dayTo]` window once
per `(symbol, interval)` per day. `HistoricalIciciMarketDataProvider.aggregate`
therefore built the 10/15-minute bars over the *entire day*, and
`BacktestMarketDataCache.slice` then filtered by bar timestamp. For a 15-minute
series, bucket 1 is `{09:30, 09:35, 09:40}` stamped `09:30`. At the 09:35 tick
`slice(to=09:35)` kept that bar — **already complete, already carrying 09:40's
data.** A broker asked for `to=09:35` returns it partial.

So on any timeframe coarser than the tick increment, the backtest strategy saw up
to `interval - 5` minutes into the future and live did not, breaking parity rule 2
("same candle data ... byte-identical to what it would have seen in live").

Measured on 2024-01-04 across the 26 option series a mid-band config would walk,
comparing the last bar the strategy sees under each ordering:

| Interval | Ticks where the last bar differed | Max close error |
|---|---|---|
| 10-minute | 883 / 1898 (46.5%) | ₹18.80 |
| 15-minute | 1183 / 1898 (62.3%) | ₹17.20 |

On ~₹200 premiums that is up to ~9% on `close` — the field the entry gate tests
(`open > sma && close < sma`) and the one that becomes `entry_price`.

**The fix: cache the base series, aggregate after slicing.**
`HistoricalIciciMarketDataProvider` now exposes `fetchBaseCandles(...)` and
`aggregateTo(...)` separately, and `MarketDataService.fromBaseCache` caches the
raw 5-minute rows for the day, slices them to the caller's window, and rolls up
only then. The trailing bucket comes out partial, exactly as the broker returns it.

Phase 1's win is kept: still one fetch per symbol per day. It is in fact now
**one cache entry per symbol rather than per (symbol, interval)** — the 5-, 10-
and 15-minute views of a strike are three roll-ups of the same cached rows.

Cost: 10/15-minute roll-ups build fresh `MarketData` objects each tick, so they
cannot carry Phase 3's SMA stamps across ticks and are recomputed. Measured
8.7–10 s → 11.7–13.1 s on the 3-day run. Correctness over speed; if it ever
matters, cache the aggregated series too and rebuild only the trailing bucket.

> **Still unfixed, and a separate decision.** At the 09:35 tick the *5-minute*
> path returns the candle **stamped** 09:35, whose close is the 09:40 price —
> because `slice` is inclusive of `to` and a candle stamped T covers `[T, T+5)`.
> So there is a one-bar look-ahead at the base interval too, on every trade's
> entry price, on both data sources. Whether a tick at time T should see the
> candle stamped T or the one that *closed* at T is a tick-semantics decision
> that shifts every historical result, so it is deliberately left alone here.

### The broker data source has the same defect

`backtest.data-source=BROKER` still caches whatever the broker returned for the
wide window at the requested interval, and slices that. Fixing it the same way
means fetching at a base interval and rolling up locally, which changes what the
broker path even asks for. Not done; `HISTORICAL_ICICI` is the configured source.

### If Phase 2 is revisited

Key the skip on the last bar's `(timestamp, close)` rather than timestamp alone —
now genuinely necessary, because after the fix above a forming bar really does
change between ticks while keeping its timestamp. Note the CPU it saves is much
smaller after Phase 3.

---

## Phase 3 — Incremental SMA ✅ implemented

**Measured:** 26.2 s → 19.9 s for a 3-day / 219-tick run (with Phase 0), on a
~110k-row data set where Phase 0's index win is barely exercised. Ledger
identical.

### What changed (as built)

Not "a single pass at day-start" as originally sketched — that would have needed
a backtest-only hook into the day loop. Instead `SMAIndicatorImpl` itself became
incremental, which leaves the call surface untouched and works in both modes.

Two things were wrong with the old implementation, and only the second one was in
the original plan:

1. **It rebuilt a ta4j `BaseBarSeries` on every call** — every candle re-wrapped
   as a `BaseBar` of `DecimalNum`s — before computing anything. In a backtest that
   is per *(strike × timeframe × SMA period)* per tick, thousands of times a day,
   rebuilding an identical series each time.
2. **It recomputed every index from scratch**, including the ones whose value
   cannot have changed.

The replacement computes the same arithmetic directly and skips candles that
already carry a value for that period. The `MarketData` instances behind
`BacktestMarketDataCache.slice` are shared across ticks, so a candle stamped on
one tick is the same object the next tick sees.

### Parity guarantee

Exact reproduction of ta4j's arithmetic, not an approximation: the same ascending
summation order, the same `MathContext(32, HALF_UP)` that `DecimalNum` defaults
to, and the same `min(period, index+1)` divisor in the warm-up region.

**The reuse boundary is load-bearing.** A stamped value is only trusted at
`index >= period - 1`. Above that boundary the window is the same `period`
absolute candles no matter how many candles have been trimmed off the *left* of
the list — and the left edge does move during a backtest day, because
`AnalysisScheduler` derives its `from` bound from the advancing tick time. Below
it, ta4j averages however many bars happen to precede the candle, which is a
different number once the list has been trimmed, so the warm-up region is always
recomputed. That costs one pass, because there the window is a pure prefix and a
running sum reproduces ta4j's loop term for term.

In live mode every fetch builds fresh `MarketData` objects with null SMA fields,
so nothing is ever skipped — same numbers as before, minus the `BaseBar`
allocation.

Verified two ways before the swap, both against **real imported candles** (six
series, 367–391 bars, periods 20/50/100/200/500):

1. Whole-list: 9,096 values compared, **0 mismatches** on exact `Double.compare`.
2. Tick-loop simulation — slice grows on the right, left edge creeps forward,
   stamps shared by object identity: 4,491 ticks compared on the last candle (the
   one the strategy actually reads), **0 mismatches**.

Then the `trade_order` ledger diff for 2024-01-02→01-04: identical on every
column of the checklist below.

### Risks

- **Floating point.** Unchanged from before: the sum is `BigDecimal` under a fixed
  `MathContext`. The warm-up running sum is not a rolling sum (nothing is ever
  subtracted), so there is no cancellation drift to accumulate.
- **A mutated candle list would go stale.** If a caller ever mutates OHLC on a
  candle already stamped, the cached SMA is wrong. Nothing does today: the
  historical provider builds fresh transient rows per fetch, and a wider refetch
  replaces the cached series with new objects rather than editing the old ones.

### Live impact

| Component | Affected? | Notes |
|---|---|---|
| `IndicatorService` / `SMAIndicatorImpl` | Replaced internally | Public interface unchanged. Live gets fresh objects every cron tick, so it computes the full list — same numbers, no ta4j series build. |
| Strategy code | No | Reads `lastCandle.getSmaValueN()` exactly as today. |
| `MarketData` entity | No schema change | The `sma_value*` columns already exist. |
| ta4j dependency | Still used by `EMAIndicatorImpl` / `RSIIndicatorImpl` | Only the SMA path moved off it. |

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

## Phase 6a — Stop re-reading the ledger every tick ✅ implemented

Cheaper and safer than the in-memory OPEN set below, and it removes the part of
the cost that actually grew with run length.

- **`BacktestAnalysisService.safeCountClosed()`** ran
  `findByStatusAndEntryTimeBetween("CLOSED", 1970, 9999).size()` — materialising
  **every CLOSED trade ever written** into the persistence context, twice per
  tick, to print a delta on a DEBUG line. Now `countByStatus("CLOSED")`.
  `countTradeOrdersOnDate` had the same shape and is now two counts.
- The whole counter block is behind `log.isDebugEnabled()`. Nothing else in that
  method reads it, and at INFO it was four DB round trips per tick bought for a
  line that is never printed.
- **`AnalysisScheduler.withOpenPositionStrikes`** ran `findByStatus("OPEN")` once
  per *(config × timeframe)* per tick. Hoisted to once per `calculateIndicator`.
  Nothing between those calls writes to `trade_order` — orders are drained by
  `OrderScheduler` after `calculateIndicator` returns — so every repeat read saw
  identical rows.

**Live impact:** the `AnalysisScheduler` hoist applies in live too (one query per
cron tick instead of N); same rows, same order. The rest is backtest-only code.

**Parity:** covered by the same ledger diff as Phase 3.

---

## Phase 6b — Position-monitor in-memory OPEN set

**Expected speedup:** Marginal — small DB SELECT savings cumulative over
multi-day runs. Consider only if a profile still shows `findByStatus("OPEN")`
after Phase 6a.

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

1. ~~**Phase 1**~~ ✅ done — biggest single win at the time, fully isolated behind
   the `MarketDataProvider` interface.
2. ~~**Phase 0**~~ ✅ done — do this before anything else if the historical tables
   are large. It is a one-line-per-query change with no behaviour surface, and it
   is worth more than every numbered phase combined once the table passes ~1M rows.
3. ~~**Phase 3 + Phase 6a**~~ ✅ done together, verified with one ledger diff.
4. ~~**Phase 2**~~ ❌ withdrawn — see that section; it also documents a live-parity
   bug in the 10/15-minute aggregation that is still open.
5. **Phase 5** — config-only, zero code; flip when benchmarking. Note the
   properties file currently ships with DEBUG on for six `com.moneymaker`
   packages, so **any timing taken without setting `logging.level.com.moneymaker=INFO`
   is measuring log I/O as much as compute.**
6. **Phase 4** — meaningful for long runs (50+ days); skip for short debugging runs.
7. **Phase 6b** — only if the OPEN-set query still shows up in a profile after
   Phase 6a. The complexity isn't worth a marginal win otherwise.

### Still open

- **The 10/15-minute look-ahead** documented under Phase 2. This is a correctness
  bug, not a performance one, and it changes historical results when fixed — so it
  needs a deliberate decision. It is the highest-value item left in this document.
- **Option SMA lookback is capped by the expiry cycle.** An imported option series
  never spans more than its own weekly cycle (~375 five-minute candles), so
  `5min × SMA(500)` can never resolve on an option leg and `5min × SMA(200)` only
  starts around day 3 of each cycle. `SMAIndicatorImpl` returns null and stamps
  nothing when `period > size`, so this shows up as "no signal", silently. See
  [`BACKTESTING.md`](BACKTESTING.md#importing-a-full-icici-export).

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

Before merging any phase, run this check. It is cheap and it is the only thing
standing between "faster" and "different".

> **A ledger produced before the stale-bar fix is not a valid baseline.** Two
> correctness fixes deliberately change which trades exist and what they close
> at, so an unchanged-ledger diff against pre-fix rows will show differences that
> are the fix working, not a regression:
>
> - `AbstractSmaCrossStrategy` now skips a decision bar from an earlier session
>   (see [STRATEGIES.md](STRATEGIES.md#the-shared-engine)). Coarse timeframes no
>   longer signal before their first bucket of the day settles.
> - `SharedData.latestCachedCandle` pins quote resolution to the finest cached
>   interval, so monitor-driven exits (`TARGET` / `STOP_LOSS` / `FORCE_CLOSE`) are
>   priced off a 5-minute bar instead of whichever interval hashed first.
>
> Re-baseline by replaying the range once with both fixes in place, then diff
> subsequent phases against that.

**Reset between runs.** Both runs must start from the same ledger, or the
second one sees the first one's positions and diverges for reasons that have
nothing to do with the change:

```sql
DELETE FROM trade_order WHERE fill_status='BACKTEST';
```

Back the table up first (`mysqldump moneymath trade_order trade_config sma_timeframe`).
Also confirm `trade_config` row count is unchanged between runs — a backtest's
`EodDowntrendDetectionService` writes `AUTO_DOWNTREND` configs for the next day.
It is idempotent, so a repeat run should add none; if the count moves, the runs
were not comparable.

1. **Identical inputs.** Pick a date range with active configs and known signals.
   Run with the change **absent**, then dump the ledger:

   ```sql
   SELECT strategy_id, option_type, option_strike, option_token,
          entry_time, entry_price, entry_reason,
          exit_time, exit_price, exit_reason,
          profit, peak_profit, peak_loss, status, fill_status
   FROM trade_order
   WHERE entry_time >= :from AND entry_time < :to
   ORDER BY entry_time, option_type, option_strike, option_token, strategy_id;
   ```

   The explicit `ORDER BY` matters — without it MySQL is free to return rows in a
   different order and the diff reports noise.

2. **Identical outputs.** Reset, re-run with the change **present**, dump again,
   diff the two files. Must be byte-identical.

Any non-identity is a divergence. Record it here under the relevant phase and
either fix it or get explicit sign-off.

**A ledger diff is necessary, not sufficient.** It only catches differences large
enough to flip a decision. For a numerical change — Phase 3 being the example —
also compare the computed values directly against the old implementation across a
range of real series and periods, asserting exact equality rather than a
tolerance. Phase 3's harness did 9,096 whole-list values plus 4,491 simulated
ticks before the ledger diff was trusted.

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

---

## The settled-bar rule (2026-08-29)

> **Do not "optimise" this away.** It looks like the pipeline is throwing data
> out. It is. Removing it inflates every backtest result.

`MarketDataService.dropIncompleteBars(bars, asOf, interval)` drops any trailing
bar whose period has not finished by the request's `to`. It is applied on **all
three paths** - historical backtest, broker backtest, and live - so there is one
rule, not a backtest special case.

### Why

A bar stamped `T` covers `[T, T + width)`. In imported data that bar is
*complete*, so including it at tick `T` handed the strategy five minutes of price
action that had not happened yet, and then stamped the resulting trade at `T`.

Assuming `close(09:35) == open(09:40)` does **not** rescue it. That argument only
covers the fill price. The *decision* reads the bar's whole shape - open, high,
low, close, and the SMA computed over it - none of which exists at 09:35:00.

| At tick 09:35 | Newest admissible bar | Its close is |
|---|---|---|
| 5-minute | 09:30 (closed 09:35) | the 09:35 price |
| 15-minute | 09:15 (closed 09:30) | the 09:30 price |

The newest admissible bar closed exactly at `T`, so its close *is* the price
transactable at `T` - the fill stays realistic while the decision uses only
settled data.

### Measured impact

Full-year 2024, the same 88-entry configuration:

| | Net per share |
|---|---|
| Before | **+401.10** |
| After | **-238.90** |

A **-640 swing**, concentrated in `SIGNAL` exits (+235.75 to -447.55) - the exits
that leaned hardest on the not-yet-formed bar. **The strategy's apparent edge was
the look-ahead.** Any analysis produced before this date was computed on inflated
data.

### Live is not exempt

A broker asked for data "up to now" returns the current bar partially formed, and
the gate reads its open and close - so whether a signal fires depended on how far
into the bar the 5-minute cron happened to land. Two identical live days could
disagree. Dropping the forming bar removes that non-determinism as well as the
backtest look-ahead.

`day` intervals are deliberately exempt: `EodDowntrendDetectionService` asks for
them at 15:20 for its ATR, and the session's own bar is exactly what it wants.

### Still open

The `BROKER` data source keeps the *aggregation* defect described under Phase 2 -
it caches whatever the broker returned for the wide window at the requested
interval and slices that. `dropIncompleteBars` limits the damage to the trailing
bar, but the fix (fetch at a base interval and roll up locally) is not done.
`HISTORICAL_ICICI` is the configured source.
