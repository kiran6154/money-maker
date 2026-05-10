# Broker Rate Limiting & Resilience

How the app stays within Zerodha's `/historical-data` rate limits, and the staged plan to make backtests fast and live trading resilient.

> **Why this exists.** Zerodha's documented limit on `/historical-data` is ~3 req/sec; quotes ~1 req/sec; orders ~10/sec. Our scheduler used to fan out one fetch per `(instrument × timeframe × strike)` and the backtest looped that 60–80 times per market day, so a single backtest day comfortably overran the limit and surfaced as `Failed to fetch market data: Failed to fetch historical data from Zerodha: Too many requests`. We need a layered defense — throttle, retry, coalesce, cache, reshape — that keeps the broker happy in both modes without rewriting calling code.

---

## Where calls go through

```
strategy / scheduler ──┐
                       ▼
            MarketDataService.fetchHistoricalData(...)        ← single choke-point
                       │
                  Resilience4j @RateLimiter("kiteHistorical") ← PR-1
                       │
                  Resilience4j @Retry      ("kiteHistorical") ← PR-1 (only on KiteRateLimitException)
                       │
                       ▼
              MarketDataProvider (Zerodha / Groww / Angel-One)
```

All caching, coalescing, and reshape work happens *inside* `MarketDataService` so callers (`AnalysisScheduler`, `BacktestAnalysisService`, controllers) stay broker-agnostic and can keep calling `fetchHistoricalData(symbol, from, to, interval)` unchanged.

---

## Layered design

| # | Layer | Purpose | Done in |
|---|---|---|---|
| 1 | **Throttle** (RateLimiter) | Hard cap on outbound rps; blocks if needed | **PR-1 ✅** |
| 2 | **Retry with backoff** | Absorb transient `Too many requests` after the limiter | **PR-1 ✅** |
| 3 | **In-flight coalescing** | Same `(token, interval, from, to)` requested twice → one network call | PR-2 ⏳ |
| 4a | **In-memory cache** | Closed candle buckets are immutable; serve from Caffeine | PR-2 ⏳ |
| 4b | **DB cache** | Persist into existing `market_data` table; survive restarts | PR-4 ⏳ |
| 5 | **Backtest reshape** | One fetch per `(token, interval, day)`; per-tick slice from cache | PR-3 ⏳ |
| 6 | **Realtime incremental** | Each tick fetches only `[lastFetchedAt, now]` | PR-5 ⏳ |
| 7 | **Circuit breaker** | Sustained broker outage stops hammering; transition-only Telegram alert | PR-5 ⏳ |

Each layer is independently shippable. PR-1 alone stops the immediate error.

---

## PR-1 — what was implemented

### Files

| File | Change |
|---|---|
| [pom.xml](../pom.xml) | Added `spring-boot-starter-aop` and `io.github.resilience4j:resilience4j-spring-boot3:2.2.0`. AOP is required for the annotations to be proxied. |
| [src/main/java/com/moneymaker/market/exception/KiteRateLimitException.java](../src/main/java/com/moneymaker/market/exception/KiteRateLimitException.java) | New `RuntimeException` subclass. Sole purpose is to be a precise retry trigger so auth/symbol errors don't get retried. |
| [src/main/java/com/moneymaker/market/service/MarketDataService.java](../src/main/java/com/moneymaker/market/service/MarketDataService.java) | `@RateLimiter(name = "kiteHistorical")` and `@Retry(name = "kiteHistorical")` on `fetchHistoricalData`. Catch block now classifies via `isRateLimit(Throwable)` (walks the cause chain looking for `"too many requests"` or `"429"`). Rate-limit hits rewrap as `KiteRateLimitException`; everything else keeps the original `RuntimeException` wrap. |
| [src/main/resources/application.properties](../src/main/resources/application.properties) | New `resilience4j.ratelimiter.instances.kiteHistorical.*` and `resilience4j.retry.instances.kiteHistorical.*` blocks. |

### Effective behaviour

- **Steady state.** Every `fetchHistoricalData` acquires one of 3 permits/sec from the bucket. Bucket is refilled every second. If the bucket is empty the caller blocks up to 60s for a permit (60s × 3 = 180 dispatches max while waiting — comfortably above any realistic burst).
- **Broker-side rate limit still slips through.** Resilience4j retries up to 4 attempts (1 initial + 3 retries) with exponential backoff: ~200ms → 400ms → 800ms (capped at 5s, jittered). After exhaustion the original `KiteRateLimitException` propagates out and `AnalysisScheduler.calculateIndicator` logs/handles it as before.
- **Auth or symbol errors.** Not classified as rate-limit, fail fast on the first attempt.

### Annotation order

Both `@RateLimiter` and `@Retry` are on the same method. Resilience4j's default decoration order is:

```
Retry  →  RateLimiter  →  method
```

So a retry attempt re-acquires a permit before re-dispatching. That's intentional — we don't want a stuck caller hogging a permit during backoff.

### Configuration

```properties
# RateLimiter
resilience4j.ratelimiter.instances.kiteHistorical.limit-for-period=3
resilience4j.ratelimiter.instances.kiteHistorical.limit-refresh-period=1s
resilience4j.ratelimiter.instances.kiteHistorical.timeout-duration=60s
resilience4j.ratelimiter.instances.kiteHistorical.register-health-indicator=false

# Retry
resilience4j.retry.instances.kiteHistorical.max-attempts=4
resilience4j.retry.instances.kiteHistorical.wait-duration=200ms
resilience4j.retry.instances.kiteHistorical.enable-exponential-backoff=true
resilience4j.retry.instances.kiteHistorical.exponential-backoff-multiplier=2
resilience4j.retry.instances.kiteHistorical.exponential-max-wait-duration=5s
resilience4j.retry.instances.kiteHistorical.retry-exceptions=com.moneymaker.market.exception.KiteRateLimitException
```

Tightening dial: if the broker still 429s through the limiter, drop `limit-for-period` to `2` — the spec says 3/sec but in practice the moving window is sometimes stricter.

### How to verify

1. Run a backtest: the historical "Too many requests" failure should no longer abort a tick.
2. Look for `Provider rate-limit hit for symbol=… — will retry` warn lines. Their presence is normal under load — they prove the retry path is engaging.
3. If a fetch genuinely fails after retries, you'll still see the existing error from `AnalysisScheduler.calculateIndicator` — the throttle/retry are best-effort, not a guarantee.

### What PR-1 does *not* fix

- Per-tick refetch waste in backtest. ~74 ticks × N configs × M strikes × T timeframes = still 100s of API calls per backtest day. The throttle just spaces them out — total volume unchanged.
- No caching: identical fetches still cost API calls.
- No protection from a sustained broker outage (no circuit breaker yet).

---

## Pending work

### PR-2 — coalesce + in-memory cache

> **Why.** Two trade configs sharing NIFTY 5-minute should hit the broker once, not twice. Closed candle buckets are immutable; we shouldn't refetch them next tick.

| Layer | Plan |
|---|---|
| 3 (coalesce) | `MarketDataService` keeps `ConcurrentHashMap<Key, CompletableFuture<List<MarketData>>>`. First caller for `(token, interval, from, to)` fires; concurrent callers await the same future. |
| 4a (in-memory cache) | Add Caffeine. TTL: long for buckets where `now > bucketEnd + freezeThreshold` (default 60s past close), no caching for the live bucket. |

No DB schema change. Big speedup for backtest (same configs hit the cache after first day pass).

**Open question to confirm before implementing.** Cache key normalization — should `from`/`to` be snapped to the interval grid? Right now callers pass arbitrary minutes; without snapping, two requests for "the same" data could miss each other.

### PR-3 — backtest fetch reshape

> **Why.** This is the single biggest API-volume reduction. The backtest currently calls `calculateIndicator(now)` every 5 minutes inside the day loop, and each call refetches the full lookback window. Restructuring to fetch the day once and slice per tick drops API volume by ~100×.

Plan:

1. Hoist the data fetch out of `runForDateTime`. Once per backtest day per `(token, interval)`, fetch `[startOfLookback, endOfDay]` and stash on `SharedData` (or a dedicated cache).
2. Per tick, slice the cached list to `[startOfLookback, currentTick]` — no network.
3. SMA recomputation inside `AnalysisScheduler.calculateIndicator` keeps working unchanged because it operates on `List<MarketData>`.

Touches `BacktestAnalysisService.run` and `AnalysisScheduler.calculateIndicator`. Probably ~80 LOC.

### PR-4 — DB-backed cache

> **Why.** Persist the cache so backtests survive a JVM restart and can be replayed offline. The `market_data` table already exists; we just need to read-then-fetch-the-missing-tail.

Plan:

1. New repository method `findByInstrumentTokenAndIntervalAndTimestampBetween(...)` (interval may need a column — see open question).
2. `MarketDataService.fetchHistoricalData`:
   - Look up coverage in DB.
   - If covered, return DB rows.
   - If partially covered, fetch only the missing prefix/suffix from broker.
   - Persist newly-fetched rows.
3. Add a "seed cache" CLI/controller endpoint so the user can warm the cache for a date range without running a backtest.

**Open questions.**
- The `market_data` table stores `instrumenttoken` but **does not store `interval`** today. We probably need a new column (`interval VARCHAR(16)`) and an index on `(instrumenttoken, interval, timestamp)`. Liquibase changeset 009.
- Retention: 50 strikes × 4 intervals × 30 days × ~75 candles ≈ 450K rows/month. Probably fine but consider a TTL job.

### PR-5 — realtime hardening

> **Why.** Live mode shouldn't refetch 10 days of data every 5 minutes; one new candle is plenty. And a degraded broker shouldn't get hammered for hours — pause, alert, recover.

| Layer | Plan |
|---|---|
| 6 (incremental fetch) | Track `lastFetchedAt` per `(token, interval)` in `SharedData`. On each scheduler tick, fetch `[lastFetchedAt, now]` and append-merge into the cached list. |
| 7 (circuit breaker) | Resilience4j `CircuitBreaker` outside the retry. Open after N consecutive failures, half-open after a backoff window. Wire transition-only Telegram alerts via the existing `NotificationService` (matches the heartbeat alerting pattern in [HEARTBEAT.md](HEARTBEAT.md)). |

---

## Mode summary

| Layer | Backtest weight | Realtime weight |
|---|---|---|
| 1 throttle | safety net | **critical** (broker contract) |
| 2 retry | covers occasional misses | **critical** |
| 3 coalesce | useful when configs share data | useful |
| 4 cache | **critical** (huge re-read pattern) | **critical** for back-history |
| 5 backtest reshape | **critical** — biggest single win | n/a |
| 6 incremental fetch | n/a | **critical** |
| 7 circuit breaker | optional | recommended |

---

## Configuration knobs (today + planned)

```properties
# --- PR-1 (live) ---
resilience4j.ratelimiter.instances.kiteHistorical.limit-for-period=3
resilience4j.ratelimiter.instances.kiteHistorical.limit-refresh-period=1s
resilience4j.ratelimiter.instances.kiteHistorical.timeout-duration=60s
resilience4j.retry.instances.kiteHistorical.max-attempts=4
resilience4j.retry.instances.kiteHistorical.wait-duration=200ms
resilience4j.retry.instances.kiteHistorical.enable-exponential-backoff=true
resilience4j.retry.instances.kiteHistorical.exponential-backoff-multiplier=2
resilience4j.retry.instances.kiteHistorical.exponential-max-wait-duration=5s
resilience4j.retry.instances.kiteHistorical.retry-exceptions=com.moneymaker.market.exception.KiteRateLimitException

# --- PR-2 (planned) ---
broker.cache.in-memory.enabled=true
broker.cache.in-memory.max-size=10000
broker.cache.in-memory.freeze-threshold-seconds=60

# --- PR-4 (planned) ---
broker.cache.db.enabled=true
broker.cache.db.retention-days=30

# --- PR-5 (planned) ---
resilience4j.circuitbreaker.instances.kiteHistorical.failure-rate-threshold=50
resilience4j.circuitbreaker.instances.kiteHistorical.minimum-number-of-calls=10
resilience4j.circuitbreaker.instances.kiteHistorical.wait-duration-in-open-state=2m
```

---

## Trade-offs and decisions

- **Library: Resilience4j (chosen)** vs Spring Retry vs Guava. Resilience4j composes RateLimiter + Retry + CircuitBreaker cleanly into the same instance name and is the standard for this stack on Spring Boot 3. Spring Retry is annotation-only (no rate limiter), Guava is no longer maintained as actively.
- **JVM-wide rate limiter, not per-thread.** If we ever scale to multiple JVMs behind a load balancer, this throttle is per-process; broker quotas are per-account. Single process today, so fine. Easy to swap to a Redis-backed limiter later if needed.
- **Match by exception class, not message regex inside Resilience4j.** We classify the broker error by message *once* inside `MarketDataService`, then throw `KiteRateLimitException`. Resilience4j only sees the exception class. This means renaming the exception class also requires updating `retry-exceptions` in properties — Spring won't fail at startup, the Retry just silently won't match.
- **Cache freeze threshold (PR-2/4).** A 5-minute candle for 09:20 isn't immutable until 09:25. We treat it as immutable only after `now > bucketEnd + freezeThreshold`. Default 60s. Strict alternative: don't cache the live bucket at all — costs us one extra fetch per tick but eliminates the staleness window entirely.
- **No tests in PR-1.** Wiring is annotation-driven and the meaningful surface is `isRateLimit(Throwable)`. If you want it covered, a unit test on that helper plus a small integration test that injects a mock provider returning a 429 for the first 2 calls and success on the 3rd is enough — happy to add as a follow-up.

---

## Owners / next step

PR-1 is in. Recommend landing PR-3 next (biggest backtest win), then PR-2 (cheap memory cache), then PR-4 (DB cache + persistence), then PR-5 (realtime hardening).
