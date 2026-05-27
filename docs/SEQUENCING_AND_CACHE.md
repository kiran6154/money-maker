# Scheduler sequencing &amp; cache hygiene

> The runtime-coordination companion to
> [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md). Answers two operational
> questions the current design is silent on:
>
> 1. **How are the pipeline schedulers ordered, and what breaks if they aren't?**
> 2. **Why do repeated backtests sometimes produce different results, and what's the cache-hygiene contract we need?**
>
> Conclusions, then evidence, then the proposed fix. See the
> "Implementation plan" at the bottom.

---

## TL;DR

| # | Recommendation | Priority | Effort |
|---|---|---|---|
| 1 | Collapse `AnalysisScheduler` / `OrderScheduler` / `PositionScheduler` `@Scheduled` triggers into one `TradingPipelineScheduler` that calls the three services in order | P0 | S |
| 2 | Add a non-blocking pipeline lock so an over-running tick can't be re-entered if the scheduler pool size is ever raised | P0 | S |
| 3 | Make every `SharedData` map iteration deterministic (sort keys; or move maps to `LinkedHashMap`) | P0 | S |
| 4 | Add `POST /api/backtest/reset?fromDate=&toDate=` that purges `trade_order` + `alert_state` rows + in-memory caches; auto-invoke before each backtest run when `backtest.auto-reset=true` | P0 | M |
| 5 | Replace `SharedData` (static mutable) with a per-`BacktestSession` state holder, share the same interface with a singleton `LiveSession` in live mode | P2 | L |
| 6 | Add a daily 08:00 "reset live caches" hook for unbounded `SharedData` maps (`optionTokenMap`, `strikesByInstrumentAndInterval`, notification dedupe) | P1 | S |

---

## 1. How data flows between schedulers (current state)

### The intended pipeline (per 5-min tick)

```
TradeConfigScheduler  → loads SharedData.combinedDto       (once at 09:16)
                ↓
AnalysisScheduler     → fetches OHLC, runs strategies,
                        appends to SharedData.tradeSignals
                ↓
OrderScheduler        → drains tradeSignals, dedupes,
                        writes trade_order, places broker order
                ↓
PositionScheduler     → walks OPEN trade_order rows,
                        updates peak/last-monitored,
                        triggers SL/target closes
```

Documented in [SCHEDULERS.md](SCHEDULERS.md). **This contract is the foundation of every strategy decision.**

### How that contract is currently enforced

It **isn't**, beyond convention. Three separate `@Scheduled` beans each carry `cron = "0 0/5 9-16 * * MON-FRI"`. At 09:05:00 Spring fires all three. The actual order of execution depends on:

1. **The scheduler pool size.** Spring Boot's default `ThreadPoolTaskScheduler` is **pool size 1** unless `spring.task.scheduling.pool.size` is set. The codebase doesn't set it, so today all three serialise through one thread.
2. **The order Spring queues the tasks.** Triggered in bean-registration order, which is component-scan order, which is alphabetical: `AnalysisScheduler` → `OrderScheduler` → `PositionScheduler`. **By coincidence this matches the intended order.**

### What breaks under common changes

| Change | Effect |
|---|---|
| Rename `PositionScheduler` → `ActivePositionScheduler` | Alphabetical order flips: `ActivePositionScheduler` runs before `AnalysisScheduler`. Position monitor walks open trades **before** strategy could close them. SL/target decisions act on stale prices. |
| Bump `spring.task.scheduling.pool.size=4` (looks innocuous) | All three run in parallel. `OrderScheduler` drains `tradeSignals` before `AnalysisScheduler` has finished producing them → signals lost. `PositionScheduler` reads a row mid-transition while `OrderService.closeOrder` is inside its transaction → inconsistent peak/profit updates. |
| Add a new `@Scheduled` bean whose name sorts before `AnalysisScheduler` | Same as the rename. |
| `AnalysisScheduler` tick takes >5 min on a slow broker | Next tick is queued; meanwhile `OrderScheduler` / `PositionScheduler` for the **next** 5-min boundary fire on incomplete state. |

The current behaviour is **correct by luck**, not by design. None of the three classes documents the dependency.

### What backtest does

[`BacktestAnalysisService.runForDateTime`](../src/main/java/com/moneymaker/backtesting/BacktestAnalysisService.java) calls the **services** in order explicitly (`analysisScheduler.calculateIndicator → analysisScheduler.runStrategies → orderScheduler.processOrders → positionScheduler.processPositions`). Backtest is the **canonical sequencing**; live should match.

### Recommendation — collapse to one pipeline scheduler

```java
@Component
@RequiredArgsConstructor
@Slf4j
public class TradingPipelineScheduler {

    private final AnalysisScheduler analysis;
    private final OrderScheduler orders;
    private final PositionScheduler positions;
    private final MarketHoursService marketHours;
    private final ReentrantLock pipelineLock = new ReentrantLock();

    @Value("${app.mode:live}") private String appMode;

    @Scheduled(cron = "0 0/5 9-15 * * MON-FRI", zone = "Asia/Kolkata")
    public void tick() {
        if ("live".equalsIgnoreCase(appMode) && !marketHours.isOpenNow()) return;
        if (!pipelineLock.tryLock()) {
            log.warn("[pipeline] previous tick still running — skipping");
            return;
        }
        try {
            analysis.analyzeMarketData();   // <- pull body out of analysisScheduler's @Scheduled
            orders.processOrders();
            positions.processPositions();
        } finally {
            pipelineLock.unlock();
        }
    }
}
```

Then drop `@Scheduled` annotations from the three existing schedulers (their methods stay, called by both this coordinator and `BacktestAnalysisService`). Net change: ~30 lines, removes three crons, adds one with explicit ordering + tick-overrun protection.

---

## 2. What happens if all schedulers fire in parallel

A second defence-in-depth note. Today the single-threaded pool implicitly serialises everything; the lock above survives a config bump.

| Resource | Type | Concurrent-write hazard |
|---|---|---|
| `SharedData.tradeSignals` | `ConcurrentLinkedQueue` | Safe per-element; **not** safe for "produce-then-drain" semantics — drain can race ahead of produce. |
| `SharedData.marketDataByInstrumentAndInterval` | `ConcurrentHashMap` | Map ops safe; the **list values are mutable**. AnalysisScheduler appends candles; if Strategy1 iterates during append, `ConcurrentModificationException`. |
| `SharedData.strikeMarketDataByInstrumentAndInterval` | `ConcurrentHashMap` | Same. |
| `trade_order` rows | DB row | OrderService writes with no row lock; PositionService reads. Possible to see a row mid-status-flip. Today's logic tolerates this because PositionService re-checks status, but it's fragile. |
| `NotificationService.dedupeState` / `throttleState` | `ConcurrentHashMap` | Map ops safe; **stateful semantics** ("only fire if different") can fire twice if two threads race. |

The proposed pipeline lock (#1 above) sidesteps all of these. The longer-term answer is to **drop static mutable state entirely** (see §4 and ARCHITECTURE_REVIEW.md #4).

---

## 3. Why repeated backtests produce different results

The user-observed symptom: same dates, same configs, different `trade_order` rows across runs. Five candidate causes, in order of likelihood:

### 3.1 `ConcurrentHashMap` iteration is non-deterministic ⭐ most likely cause
Already called out at [BacktestAnalysisService.java:166-169](../src/main/java/com/moneymaker/backtesting/BacktestAnalysisService.java#L166-L169):
> *Without this, leftover entries in SharedData's strike maps cause Strategy1 to evaluate stale strikes and — because ConcurrentHashMap iteration is non-deterministic — picks a different "first" strike across runs even for identical inputs.*

The wipe is in place, but **iteration order over the freshly-populated map is still non-deterministic** within a single tick. If `Strategy1` picks the "first" strike that satisfies a gate condition, the strike returned varies run-to-run.

**Fix.** Replace `ConcurrentHashMap` with `LinkedHashMap` (insertion order) or sort keys at every iteration site:
```java
strikeMarketDataMap.keySet().stream().sorted().forEach(key -> { ... });
```

### 3.2 Persisted `trade_order` rows from prior runs ⭐ likely contributor
- Dedupe key: `(tradeConfigId, optionToken, entryDirection, entryTime)`. Idempotent if the run produces identical timestamps. But:
- If a previous partial run left rows in `OPEN` status (because the JVM was killed before force-close at 15:20), the next run sees them as open and a fresh signal **closes** instead of **opens** → different ledger.
- If you delete `trade_order` rows manually but not `alert_state`, the trade-config Telegram won't re-fire, but trades will re-create normally.
- `numberOfTradesPerDay` cap counts prior runs' rows.
- `maxLoss` daily cap sums prior runs' realised P&L.

**Fix.** A reset endpoint that purges both tables for the run's date range.

### 3.3 `TradeConfigScheduler.configsCache` retains stale entries
Date-keyed; once populated for a date, stays for the JVM lifetime. If trade configs are edited mid-day **between** two backtest runs of the same date, the second run uses the first run's cached snapshot.

**Fix.** Invalidate at the start of each backtest run.

### 3.4 `DailyEventGuard` rows in `alert_state`
`DaySummaryScheduler`, `TradeConfigScheduler.reportConfigsForDay` and any future once-per-day alert won't re-fire on the second backtest for the same date. **Doesn't change trade decisions** but changes logs/Telegram which can confuse "is this run correct?"

**Fix.** Reset endpoint deletes these for the date range.

### 3.5 `NotificationService.dedupeState` / `throttleState`
JVM-lifetime maps that suppress duplicate alerts. Across two consecutive backtest runs in the same JVM, second run produces fewer alerts. Same effect as 3.4.

**Fix.** Reset endpoint clears them; consider auto-clear at backtest run start.

---

## 4. Full cache inventory

The truth-table of every cache in the system. Use this when adding a new cache: pick a row to attach to or explicitly justify why your cache doesn't fit.

### In-memory (JVM-scoped)

| # | Cache | Type | Cleared by | Lifecycle (live) | Lifecycle (backtest) | Hazard |
|---|---|---|---|---|---|---|
| C1 | `SharedData.combinedDto` | `List` (static) | Reassignment | 09:16 cron + ApplicationReadyEvent + UI write-through (`TradeConfigAdminService`) | Per-day reassignment in `BacktestAnalysisService` | Static; no parallelism |
| C2 | `SharedData.marketDataByInstrumentAndInterval` | `ConcurrentHashMap` | `.clear()` | Never | Per-day `finally` in `BacktestAnalysisService` | Unbounded growth in live |
| C3 | `SharedData.strikeMarketDataByInstrumentAndInterval` | `ConcurrentHashMap` | `.clear()` | Never | Per-day `finally` | Same; **iteration non-deterministic** (§3.1) |
| C4 | `SharedData.strikesByInstrumentAndInterval` | `ConcurrentHashMap` | Never explicitly cleared | Never | Never | Unbounded growth |
| C5 | `SharedData.strikeList` | `List` (static) | Overwritten | Per-tick overwrite | Per-tick overwrite | OK |
| C6 | `SharedData.tradeSignals` | `ConcurrentLinkedQueue` | `.clear()` + drain | Drained per-tick by OrderScheduler | Per-day `finally` + run-end | Produce-then-drain race if parallel (§2) |
| C7 | `SharedData.optionTokenMap` | `ConcurrentHashMap` | Never | Never | Never | Unbounded growth |
| C8 | `SharedData.allTimeFrameMap` | `HashMap` | Static initialiser only | Never re-initialised | Never re-initialised | Stale if config timeframes change |
| C9 | `TradeConfigScheduler.configsCache` | `ConcurrentHashMap<LocalDate, ...>` | `invalidateConfigsCache()` | UI write-through (existing); restart | Should reset per run (not today) | Stale on second backtest for same date |
| C10 | `BacktestMarketDataCache.seriesByKey` | `ConcurrentHashMap` | `endDay()` | `isActive()` = false in live | Per-day | OK |
| C11 | `NotificationService.dedupeState` | `ConcurrentHashMap` | `clearDedupe(key)` | Never automatically | Never automatically | Stale across long live runs and across backtest runs |
| C12 | `NotificationService.throttleState` | `ConcurrentHashMap` | `clearDedupe(key)` | Never | Never | Same |
| C13 | Hibernate L1 (per-tx session cache) | JPA built-in | Tx commit | Per tick | Per tick | OK |
| C14 | Hibernate L2 | Not configured | n/a | n/a | n/a | OK |
| C15 | KiteConnect HTTP connection pool | OkHttp / Apache | Per-process | App stop | App stop | OK |

### Database-backed

| # | Table | Cleared by | Lifecycle | Hazard |
|---|---|---|---|---|
| D1 | `trade_order` | Manual / migration | Accumulates forever | **Backtest re-runs accumulate ledger** (§3.2) |
| D2 | `alert_state` | Manual | Accumulates forever | **Backtest re-runs see prior days' guards** (§3.4) |
| D3 | `market_data` | `OptionsBulkDownloadService` idempotent delete | Targeted re-fetch | Idempotent today; will need attention when live writes (ARCH_REVIEW §4) |
| D4 | `broker_session` | `LoginOrchestrator` | Per login | Stale row on crash; current heartbeat heals |
| D5 | `options_data` | `OptionsBulkDownloadService` | Bulk-download window | Same as D3 |

---

## 5. The cache-clearing contract we need

A simple, **explicit**, two-mode contract.

### Live mode

| Trigger | What clears | What persists | Why |
|---|---|---|---|
| App start | All in-memory caches start empty; D1-D5 persist | Persists durable state | Fresh JVM picks up where DB left off |
| `LoginScheduler.ensureSessionAtMarketOpen` (08:00) | **New**: clear C7 (`optionTokenMap`), C4 (`strikesByInstrumentAndInterval`) | Everything else | Prevents day-over-day growth of unbounded maps |
| 09:16 cron / UI trade-config write | C1 (combinedDto), C9 (configsCache for affected date) | Everything | Already implemented (UI write-through from prior PR) |
| Per-tick | C2/C3 *accumulate* (live re-reads broker each tick) | n/a | Acceptable for live's intraday scale |
| `DaySummaryScheduler` (15:31) | None | Everything; alert_state row guards repeat | Once-per-day Telegram |

### Backtest mode

| Trigger | What clears | What persists | Why |
|---|---|---|---|
| `POST /api/backtest/analysis` start | When `backtest.auto-reset=true`: clear C1, C2, C3, C4, C6, C9, C11, C12; delete D1/D2 rows in `[fromDate, toDate]` | C7, C8, C10 (managed by their own lifecycle); D3 (market_data is shared corpus) | Make every backtest run from a clean slate |
| Per-day in run | C2, C3, C6 cleared in `finally`; C10 cleared in `endDay()` | C1, C9 (date-keyed cache) | Already implemented |
| Run end | C6 cleared | Other caches keep last-day state | Doesn't matter — next run resets |

### Single source of truth — `CacheRegistry`

A coordinating service that owns the inventory programmatically:

```java
public interface ClearableCache {
    String name();
    EnumSet<Scope> scopes();    // LIVE_DAILY, BACKTEST_RUN_START, BACKTEST_DAY_END, …
    void clear();
}
```
- Every cache (`SharedData` fields wrapped as beans, `TradeConfigScheduler.configsCache`, `NotificationService.dedupeState`, etc.) implements this.
- `CacheRegistry.clearScope(Scope)` is called from the relevant lifecycle hook.
- Adding a new cache without naming a scope **fails the build** (annotation processor or unit test).
- Solves the "new map needs to be added to the wipe block" trap noted in BacktestAnalysisService.

This is the architecturally clean fix; the reset endpoint (#4) is the immediate one.

---

## 6. Reproducibility prescription (immediate, low-risk)

Even before the bigger refactors, three changes make backtest results reproducible run-to-run **today**:

1. **Sort iteration keys** at every site that walks `strikeMarketData…` or `marketData…`. ~5 sites. ~15-line change.
2. **Add `/api/backtest/reset?fromDate=&toDate=`** that runs:
   ```sql
   DELETE FROM trade_order  WHERE entry_time BETWEEN :from AND :to;
   DELETE FROM alert_state  WHERE alert_date BETWEEN :from AND :to;
   ```
   plus clears C9 (`configsCache.clear()`), C11, C12.
3. **Wire `backtest.auto-reset=true`** (default) so `POST /api/backtest/analysis` calls the reset above before its own loop. Operator can disable with the flag to inspect cumulative state.

After these three, identical inputs produce identical `trade_order` rows. Verifiable with a one-line `diff` of `mysqldump trade_order` between runs.

---

## 7. Long-term — `BacktestSession` replaces `SharedData`

Static mutable state is the root cause of both the parallelism block (ARCHITECTURE_REVIEW §3.2) and the cache-hygiene fragility (§4 above). Two-step migration:

1. **Define `RunSession`** — holds `combinedDto`, `marketDataByInstrumentAndInterval`, `strikeMarketDataByInstrumentAndInterval`, `tradeSignals`, etc. as instance fields.
2. **Inject it everywhere `SharedData.X` is read** (sites are concentrated in `AnalysisScheduler`, `Strategy1`, `OrderService`, `PositionService`).
3. Live wires a `@Singleton` instance; backtest wires a `BacktestSessionFactory` that returns a fresh instance per run (and per parallel day, eventually).
4. Delete `SharedData`.

This is a **large** mechanical change (~20-30 files) with no behaviour change if done correctly. Verifiable via the same `diff trade_order` parity check.

---

## Implementation plan

Cross-referenced with [ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md) and [GAPS.md](GAPS.md).

| # | Change | Priority | Effort | Unblocks |
|---|---|---|---|---|
| **A** | Sort iteration keys in all `SharedData` map walks | **P0** | S | Reproducibility |
| **B** | `POST /api/backtest/reset` + `backtest.auto-reset=true` | **P0** | M | Reproducibility |
| **C** | Collapse three pipeline schedulers into `TradingPipelineScheduler` with `tryLock` | **P0** | S | Sequencing safety; closes Gap #4 |
| **D** | Daily 08:00 reset of unbounded live caches (C4, C7, C11, C12) | **P1** | S | Prevents week-long live memory creep |
| **E** | `CacheRegistry` + `ClearableCache` interface | **P2** | M | Prevents future "forgot to clear" bugs |
| **F** | `RunSession` replaces `SharedData` | **P3** | L | Unblocks day-parallel backtests |

Items **A**, **B**, **C** together resolve the immediate operational pain (reproducibility + sequencing) in **~1 day of focused work**. **D** is a 1-hour add. **E** is the architecturally right cleanup once **A-D** are stable. **F** is the precondition for the ARCHITECTURE_REVIEW §3.2 day-parallel work.
