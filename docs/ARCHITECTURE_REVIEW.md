# Architecture review — live/backtest, data, indicators

> A forward-looking design review. Captures the architectural debt and the
> recommended evolution path for **data persistence** and **indicator
> compute** — the two areas where the codebase has half-finished migrations
> that compound complexity per feature added.
>
> Complements [BACKTEST_PERFORMANCE.md](BACKTEST_PERFORMANCE.md) (which
> covers tactical perf phases) and [GAPS.md](GAPS.md) (operational follow-ups).
> Pair this with [SEQUENCING_AND_CACHE.md](SEQUENCING_AND_CACHE.md) for the
> runtime-coordination view.

---

## TL;DR

| # | Recommendation | Priority | Effort |
|---|---|---|---|
| 1 | Persist candles during **live runs**; backtest reads DB first, broker on miss | P0 | M-L |
| 2 | Drop persisted `sma_value*` columns; compute indicators at read-time via an `IndicatorComputeService` with a registry | P1 | M |
| 3 | Generalise `sma_timeframe` → `indicator_binding(tc_id, name, params_json)` so UI can attach any indicator without schema work | P1 | M |
| 4 | Move `SharedData` to a per-session state holder (unblocks day-parallel backtests) | P2 | L |
| 5 | Vectorise the inner backtest loop | P3 | L |

Sections below justify each.

---

## 1. How the application is built

A **single-process Spring Boot monolith**, organised by feature package, with two intentional integration seams:

| Seam | Owner | Contract |
|---|---|---|
| Auth | [`LoginOrchestrator`](../src/main/java/com/moneymaker/login/service/LoginOrchestrator.java) | Single auth code path; both live cron and backtest preflight call it |
| Historical data | [`MarketDataService`](../src/main/java/com/moneymaker/market/service/MarketDataService.java) | Single fetch facade; cache wrap optional |

Three structural choices are worth naming:

- **Schedulers are dumb sequencers; services do the work.** Every `@Scheduled` method delegates into a `*Service` method that backtest replays. This is good design and is the foundation for live/backtest parity.
- **`SharedData` is the cross-cutting state god-object** (static mutable maps for `combinedDto`, market data, strike data, signals queue). The single biggest constraint on every future change — see §3 and [SEQUENCING_AND_CACHE.md](SEQUENCING_AND_CACHE.md).
- **The parity contract is doctrine, not convention.** [`BACKTEST_PERFORMANCE.md`](BACKTEST_PERFORMANCE.md) explicitly forbids `if (backtest)` branches in shared services. Optimisations live behind provider seams.

---

## 2. How live and backtest coexist — the honest picture

### What's clean
- Identical call chain below the scheduler ([BACKTEST_PERFORMANCE.md:351-379](BACKTEST_PERFORMANCE.md#L351-L379)).
- Same auth path. `LoginStep` reuses `LoginOrchestrator`.
- Single seam for data fetch.

### What's leaky

| Issue | Location | Risk |
|---|---|---|
| `SharedData` is static mutable, wiped by hand each backtest day | [BacktestAnalysisService.java:170-175](../src/main/java/com/moneymaker/backtesting/BacktestAnalysisService.java#L170-L175) | New maps need new wipe lines; silent contamination if forgotten |
| Pipeline cron annotations fire even in backtest mode (bodies gated, triggers aren't) | `AnalysisScheduler`, `OrderScheduler`, `PositionScheduler` | Currently harmless; will break the moment a `@Scheduled` method's body changes without a gate |
| Live ingestion path and backtest fetch use different code paths for trade configs | [`TradeConfigScheduler.checkTradeConfigAt916AM`](../src/main/java/com/moneymaker/scheduler/TradeConfigScheduler.java) vs `getConfigsForDate(date)` | Drift possible (same return type, different code) |
| `market_data` table is half-wired — bulk-download writes to it, backtest doesn't read it | [`OptionsBulkDownloadService`](../src/main/java/com/moneymaker/data/download/OptionsDataController.java), [`MarketDataService.fetchHistoricalData`](../src/main/java/com/moneymaker/market/service/MarketDataService.java#L45) | The table costs schema/code for zero benefit today (§4) |
| Indicator persistence is half-done — `MarketData` has SMA columns but indicators are recomputed every tick | [`MarketData.java:39-52`](../src/main/java/com/moneymaker/entity/MarketData.java#L39-L52), [`SMAIndicatorImpl.calculate`](../src/main/java/com/moneymaker/indicator/SMAIndicatorImpl.java#L66-L80) | Both the schema lock-in AND the runtime cost (§5) |

**Pattern.** Every optimisation has been *started* but stopped before finishing the migration, leaving both old and new paths alive. This is the dominant source of architectural debt.

---

## 3. Speeding up backtest — beyond the existing Phase plan

[BACKTEST_PERFORMANCE.md](BACKTEST_PERFORMANCE.md) lays out Phases 1–6. Phase 1 is done; Phases 2-6 are sound but tactical. Three higher-leverage moves the doc doesn't consider:

### 3.1 Vectorise the inner loop
Tick loop walks 72 ticks/day. Strategy re-evaluates rules against a candle whose OHLC+SMA were already known at day-start. Mature backtest engines (zipline, backtrader, vectorbt) **precompute every indicator over the full series once**, then walk the index array applying rules as boolean masks. **10–50× routine wins** for SMA-style strategies.

Larger refactor than Phase 3; only justified once 100-day parameter sweeps become a routine workflow. **P3.**

### 3.2 Day-parallel execution
Backtest days are independent (each force-closes at 15:20). 8-core box → 8× speedup. **Blocker: `SharedData` is static mutable.** Fix requires `BacktestSession`-scoped state — see [SEQUENCING_AND_CACHE.md](SEQUENCING_AND_CACHE.md). **P2.**

### 3.3 Pre-resolve strike sets per day
`calculateStrikesForCandles(...)` runs per-tick. Within a day the active strike set is stable; recomputing per tick is waste. One-day change. **P2.**

### Recommended ordering for the existing Phase plan
1. Finish Phases 2 + 3 (rolling-sum SMA) — small surface, real wins, foundation for §3.1.
2. Pre-resolve strikes per day.
3. Move `market_data` to source of truth (see §4).
4. Then day-parallel.
5. Vectorise only when sweeps become routine.

Skip Phase 4 (parallel strike download) and Phase 6 (in-memory OPEN set) until profiling demands them.

---

## 4. Store candles during live run — yes; separate sync — no

### Current state (the honest reality)
- Live: `AnalysisScheduler` fetches per 5-min tick from broker. **Does not persist.**
- Backtest: routes through `MarketDataService.fetchHistoricalData`, broker fetch + per-day in-memory cache. **Does not persist either.**
- `market_data` is populated only by `OptionsBulkDownloadService` and `LoginScheduler.fetchOptionsData` — a manual ingestion that no primary read path depends on.

The team has built a half-finished data sync that costs schema, code, and operator complexity for zero current benefit.

### Recommendation: live writes are the primary path

1. **Broker rate-limit (3 req/s) is the dominant cost.** Live already pays the fetch; making the side-effect an INSERT is essentially free. Backtest reads disk → no rate limit.
2. **A separate sync doubles surface area.** Two ingestion paths, two failure modes, two consistency stories, two on-call procedures.
3. **Operational compounding.** A month of live runs = free historical corpus; a year = parameter-sweep dataset.

### Specifics

| Concern | Resolution |
|---|---|
| Idempotency | UNIQUE index on `(instrumenttoken, timestamp, interval)` + `INSERT … ON DUPLICATE KEY UPDATE` |
| Backtest cron firing in live mode (Gap #4) | Fix that **first**, otherwise live writes corrupt themselves during replays |
| Failed write must not break analysis | `@Async` writer with try/catch; fire-and-forget; telemetry for persistent failures |
| Gap detection | Daily 16:00 job scans for missing candles in trading hours, triggers targeted backfill via existing `OptionsBulkDownloadService` |
| Backtest reads | New `MarketDataLocalProvider` reads from `market_data`; registered only in backtest. Falls through to broker on miss with a loud log. Eventually flip the default. |

**This is the #1 architectural change for the next quarter.** Every subsequent optimisation compounds from it.

---

## 5. Pre-calculate indicators in DB? No, and remove what you have

### Why the current half-solution is the worst of both worlds

[`MarketData.java:39-52`](../src/main/java/com/moneymaker/entity/MarketData.java#L39-L52) hardcodes five SMA columns. Three bad properties:

1. **Adding SMA-30 = schema migration.** Already happened with changeset 013.
2. **Adding EMA / RSI / Bollinger = more columns or a parallel model.** `RSIIndicatorImpl` and `EMAIndicatorImpl` exist; neither has columns; they don't fit the model.
3. **No-one reads the columns as cache.** `SMAIndicatorImpl.calculate` writes them *and* recomputes on every call. Persistence buys nothing.

You're paying schema + write + migration cost for zero benefit.

### Three options, ranked

#### (A) Don't persist indicators. Compute at read-time, rolling-sum. ✅ **Recommended**
- Zero schema; new indicator = new `Indicator` impl + register.
- O(N) compute per backtest tick — microseconds at 1500 candles.
- Aligns with Phase 3 of the existing perf plan.

#### (B) Persist in a key-value sidecar table.
```sql
CREATE TABLE candle_indicator (
  instrumenttoken VARCHAR(100),
  timestamp DATETIME,
  interval VARCHAR(8),
  indicator_name VARCHAR(32),   -- "SMA", "EMA", "RSI"
  params_json VARCHAR(64),      -- {"period":20,"source":"low"}
  value DOUBLE,
  PRIMARY KEY (instrumenttoken, timestamp, interval, indicator_name, params_json)
);
```
- Open-ended, no schema lock-in per new indicator.
- 5× row count; uglier joins; lookups by `(name, params)` in strategy code.
- Worth it **only when compute dominates the profile** — unlikely at current scale.

#### (C) Keep the current column-per-period model. ❌
- Migration cost compounds per indicator. Avoid.

### Action items for (A)
- Migration to drop `sma_value20`, `sma_value50`, `sma_value100`, `sma_value200`, `sma_value500`.
- Move SMA compute behind `IndicatorComputeService` with per-tick cache.
- Transient `smaXXTrending` fields → value object computed from candle list, not bolted on the entity.

---

## 6. Adding a new indicator — clean model

With recommendation (A) in place, the recipe for **MACD** (or any new indicator):

1. Create `com.moneymaker.indicator.MACDIndicatorImpl implements Indicator`. Stateless. Returns `MACDResult` (record with line / signal / histogram).
2. Register via `IndicatorFactory` (or move to Spring `Map<String, Indicator>` injection).
3. Reference from strategy via `IndicatorComputeService.compute("MACD", candles, MACDConfig.of(12, 26, 9))`.

**No DB change. No migration. No new column. Parity guaranteed** because both live and backtest use the same code path.

For per-strategy indicator parameters, extend the existing `sma_timeframe` → generic `indicator_binding(tc_id, indicator_name, params_json)` so the UI built in the trade-config admin work can attach arbitrary indicators without schema work.

This is the **right abstraction line** — and the codebase is 80% there. The discipline is to **stop persisting indicator values** and let compute live in code.

---

## Recommended sequencing across this doc

| Order | Change | Why first |
|---|---|---|
| 1 | Fix Gap #4 (pipeline crons firing in backtest mode) | Required before §4 is safe |
| 2 | §4 — live writes candles to DB, backtest reads DB first | Removes broker as cold-path dependency; unlocks every multi-day analysis |
| 3 | §5 — drop SMA columns, move to `IndicatorComputeService` | Unblocks every future indicator; removes the schema lock-in |
| 4 | §6 — `indicator_binding` table replaces `sma_timeframe` | UI for arbitrary indicators without schema work |
| 5 | Phases 2 + 3 from BACKTEST_PERFORMANCE | Mechanical wins, low risk |
| 6 | §3.3 pre-resolve strikes per day | Easy, measurable |
| 7 | §3.2 day-parallel execution | Big win once `SharedData` is per-session |
| 8 | §3.1 vectorisation | Only when sweep workloads justify it |

Items 1–4 are the load-bearing ones. They move the codebase from "a backtester that works" to "a research platform" — and each removes a category of bug rather than adding a feature.
