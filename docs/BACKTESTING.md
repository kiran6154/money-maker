
# Backtesting

> ⚠️ **Sections below "Moving parts" are stale.** They describe a
> `BacktestStep` / `BacktestRunner` / `POST /api/backtest/run` design that is no
> longer in the code. What actually runs today is `BacktestAnalysisService.run(from, to)`
> behind `POST /api/backtest/analysis?fromDate=&toDate=`, which replays each day
> tick-by-tick through the same `AnalysisScheduler` / `OrderScheduler` /
> `PositionScheduler` entry points the live cron uses. The
> **[Data source](#data-source)** section immediately below is current.

## Running a backtest — two separate operations (since 2026-08-31)

A replay and `AUTO_DOWNTREND` config generation are **decoupled** (user
request): a backtest run no longer writes configs as a side effect, so a
measurement run can never mutate the config set it is measuring.

```powershell
# 1. (fresh window only) generate AUTO_DOWNTREND configs for the window —
#    no replay, no ledger writes; idempotent, skips days whose configs exist
curl.exe -X POST "http://localhost:8080/api/backtest/generate-configs?fromDate=2024-01-01&toDate=2024-01-31"

# 2. replay the window (uses whatever configs exist; generates nothing)
curl.exe -X POST "http://localhost:8080/api/backtest/analysis?fromDate=2024-01-01&toDate=2024-01-31"

# legacy combined behaviour, explicit opt-in only:
curl.exe -X POST "http://localhost:8080/api/backtest/analysis?fromDate=2024-01-01&toDate=2024-01-31&generateConfigs=true"
```

Before re-running the **same** window, clear `trade_order` (the ledger's
dedupe key suppresses identical re-entries) — `analysis/db-scripts/wipe-ledger.bat`
does it, or the `/api/orders/purge` endpoint.

---

## Data source

A backtest reads its candles from one of two places, selected by
`backtest.data-source` in `application.properties`:

| Value | Candles come from | Needs a broker session? |
|---|---|---|
| `BROKER` (default) | the active broker, via `ZerodhaMarketDataProvider` | yes — and subject to the `kiteHistorical` rate limiter |
| `HISTORICAL_ICICI` | `historical_spot_candles` / `historical_option_candles` — the ICICI CSVs imported through `POST /api/charts/historical/import/{spot,options}` | no market-data calls are made |

`HISTORICAL_ICICI` exists so a run is reproducible and offline: same imported
rows in, same `trade_order` rows out, no rate limit, no live token.

**The flag is refused in live mode.** `HistoricalDataSourceGuard` fails startup
on `app.mode=live` + `HISTORICAL_ICICI`, because trading live off replay prices
would place real orders at stale levels.

### How it plugs in

Both paths converge on `MarketDataService.fetchHistoricalData(symbol, from, to, interval)`.
When the historical source is active, `MarketDataService` calls
`HistoricalIciciMarketDataProvider` directly instead of `KiteHistoricalFetcher` —
that fetcher's rate limiter and retry exist to protect the broker API and would
only throttle local DB reads. `BacktestMarketDataCache` still wraps the call, so
per-day windowing is unchanged.

> **Which provider does `KiteHistoricalFetcher` use?**
> `MarketDataProviderFactory` decides, and it is the only place that decides
> (GAPS #20 — the class was an empty file, and selection was an emergent
> property of `@ConditionalOnProperty` plus a `@Primary`). Order: an explicit
> `market.data.provider`, else the only registered provider, else the default
> precedence `HISTORICAL_ICICI` > `ZERODHA`. That precedence matters here: with
> the historical source active, any path that still reaches the fetcher reads
> imported candles rather than quietly calling the broker, so a replay cannot mix
> live quotes into its ledger.

The historical tables carry no instrument tokens by design (see
[`HISTORICAL_CHART_DATA_PLAN.md`](HISTORICAL_CHART_DATA_PLAN.md)), so the pipeline's
`symbol` string becomes a natural key produced by `HistoricalSymbol`:

```
spot    HIST:NIFTY:NSE:SPOT
option  HIST:NIFTY:NFO:2024-01-04:21700:CE
```

`OptionInstrumentResolver` decides which shape is produced —
`TokenOptionInstrumentResolver` (broker tokens, from `instrument_details` +
`expiry_dates`) or `HistoricalOptionInstrumentResolver` (natural keys, from
`historical_option_candles`). `AnalysisScheduler` and the strategies both go through
it, so the symbol written into a cache key is always the symbol read back out.

> The separator is `:` and never `|`, because `SharedData` strike keys are
> `token|interval|optionType|strike|optionToken|itmDepth|otmDepth` and are split
> on `\|` downstream.

### Expiry

The historical resolver picks the **nearest `expiry_date >= trading date` present
in the imported data** — no weekday rule. This matters: `ChartExpiryResolver`
hard-filters NIFTY to Tuesday, which is today's NSE convention but would match
nothing in the 2024 sample files, whose weeklies expire on **Thursday**
(2024-01-04, 2024-01-11). Nothing anywhere in the codebase selects weekly vs
monthly deliberately — see the note in [`ORDERS_AND_POSITIONS.md`](ORDERS_AND_POSITIONS.md).

### Limits when `HISTORICAL_ICICI` is active

- **5-minute base only.** `10minute` / `15minute` are aggregated from the 5-minute
  rows, bucketed by wall-clock from the session open (not by list position, which
  would drift across days — an NSE session is 75 five-minute candles, not
  divisible by 2). The roll-up happens **after** the candles are narrowed to the
  caller's window, so the trailing bucket comes back partial exactly as a broker
  would return it. Doing it the other way round gave the strategy up to
  `interval - 5` minutes of look-ahead — see
  [`BACKTEST_PERFORMANCE.md` → Phase 2](BACKTEST_PERFORMANCE.md).
- **`day` candles are rolled up, not stored.** One bar per trading date —
  open = the session's first candle, high/low = the session's extremes,
  close = the last candle. `EodDowntrendDetectionService` runs against this
  source (it did not before), but its ATR and SMA grid only see the days that
  have actually been imported: expect `SMA(200)` / `SMA(500)` to keep being
  dropped by the sufficiency gate until enough history is loaded.
- **A wholly missing series aborts the run** with HTTP 422 and the series named,
  rather than quietly trading on partial data. Gaps *inside* a present series are
  normal (illiquid deep-ITM strikes start late) and do not trip it.
- A `broker_session` row is still required — `BacktestAnalysisService` reads it
  each tick — even though no market-data calls are made.

### Running one

```powershell
# import once (all five sample files under docs/)
curl.exe -F "file=@docs/NIFTY_2024-01-04_SPOT_5minute.csv" http://localhost:8080/api/charts/historical/import/spot
curl.exe -F "file=@docs/NIFTY_2024-01-04_CE_5minute.csv"   http://localhost:8080/api/charts/historical/import/options
curl.exe -F "file=@docs/NIFTY_2024-01-04_PE_5minute.csv"   http://localhost:8080/api/charts/historical/import/options
curl.exe -F "file=@docs/NIFTY_2024-01-11_CE_5minute.csv"   http://localhost:8080/api/charts/historical/import/options
curl.exe -F "file=@docs/NIFTY_2024-01-11_PE_5minute.csv"   http://localhost:8080/api/charts/historical/import/options

# then, with app.mode=backtest and backtest.data-source=HISTORICAL_ICICI
curl.exe -X POST "http://localhost:8080/api/backtest/analysis?fromDate=2024-01-02&toDate=2024-01-04"
```

Each import call answers `{"rows": N}` — the number of CSV rows upserted. Re-running
a file is a no-op on row count, because rows are written with
`INSERT … ON DUPLICATE KEY UPDATE` on the natural key.

`trade_order` rows come back with `fill_status='BACKTEST'` and an
`option_token` like `HIST:NIFTY:NFO:2024-01-04:21700:CE`.

**Data coverage of the samples:** the spot CSV covers 2023-12-29 → 2024-01-04
only, and ATM resolution is driven off the underlying series, so the
2024-01-11 expiry week cannot be replayed until a matching spot file is
imported. Usable window is **2024-01-02 → 2024-01-04**, with 2023-12-29 as
lookback. Note also that `computeLookbackCalendarDays()` asks for 35 calendar
days by default (15min × 500-SMA), far more than the samples contain, so the
longer SMAs stay null — configure shorter `sma_timeframe` periods or import more
history.

### Importing a full ICICI export

The sample files under `docs/` are two expiry cycles. A full export is one folder
per weekly expiry — `<year>/<expiry>/NIFTY_<expiry>_{SPOT,CE,PE}_5minute.csv` plus
a `manifest.json` — and the whole tree loads through the same two endpoints:

```powershell
$root = "C:\path\to\nifty_options"
$base = "http://localhost:8080/api/charts/historical/import"
Get-ChildItem $root -Recurse -File -Filter *.csv | Sort-Object FullName | ForEach-Object {
    $ep = if ($_.Name -match '_SPOT_') { "$base/spot" } else { "$base/options" }
    curl.exe -s -F "file=@$($_.FullName)" $ep
}
```

Two things to check in the export before loading it:

- **A cycle with no SPOT file cannot be replayed.** ATM resolution reads the
  underlying series, so CE/PE without spot imports fine and then fails at strike
  selection. `manifest.json` names the underlying file, or reports why it is missing.
- **Option series are truncated to their own expiry cycle — by the exporter, not
  by the market.** A weekly contract trades for weeks before its cycle starts, but
  the export windows each expiry to `cycle_start .. expiry`, so that history was
  never fetched. Measured over a full export: **0 of 10,918 option series carry a
  candle from before their own cycle**, and the longest series in the set is 456
  five-minute candles.

  Consequences, given `SMAIndicatorImpl` returns null and stamps nothing when
  `period > size` — i.e. these fail silently as "no signal":

  | Timeframe × SMA | Series that can resolve it |
  |---|---|
  | `5min × 50` | 10,877 / 10,918 |
  | `5min × 100` | 10,799 / 10,918 |
  | `5min × 200` | 10,616 / 10,918 (97%), and only from ~day 3 of each cycle |
  | `5min × 500` | **0** — needs 500 candles, longest series is 456 |

  Spot is continuous across cycles and unaffected. To make long option SMAs
  usable, re-export with a wider per-expiry window; nothing in this codebase can
  recover history the export does not contain.

**Operator note — buffer pool.** A full export is ~3.8M option rows, roughly
380 MB of data plus 310 MB of index. MySQL's default
`innodb_buffer_pool_size` is 128 MB, which puts the working set on disk and makes
every backtest day pay I/O. Raise it in `my.ini` (2 GB is comfortable) and restart
MySQL before a long run.

---

The backtest pipeline is a thin sequencer that runs every `BacktestStep` Spring bean in `order()` ascending. Today it has **exactly one step** — `LoginStep` — which reuses the live `LoginOrchestrator` so backtest preflight is byte-for-byte identical to live trading.

> **Design rule:** the backtest must never duplicate live logic. If you find yourself writing a "test login" or "mock data fetch" path, stop and refactor the live class to be reusable instead.

---

## Moving parts

```
com.moneymaker.backtesting
├── BacktestStep        (interface)   — one stage; name() + order() + execute(ctx)
├── BacktestRunner      (component)   — autowires List<BacktestStep>, sorts, runs
├── BacktestContext     (POJO)        — mutable bag of attributes shared between steps
├── StepResult          (POJO)        — SUCCESS | SKIPPED | FAILED + timing + message
├── BacktestReport      (POJO)        — aggregate of all StepResults + total timing
├── BacktestController  (REST)        — POST /api/backtest/run
├── BacktestViewController (MVC)      — GET /backtest (Thymeleaf console)
└── steps/
    └── LoginStep       (order = 0)   — calls LoginOrchestrator.ensureLoggedIn()
```

---

## Pipeline contract

```java
public interface BacktestStep {
    String name();
    int order();                         // lower = earlier; login is fixed at 0
    StepResult execute(BacktestContext ctx);
}
```

Rules enforced by `BacktestRunner`:

1. Discover every `BacktestStep` bean via component scan, sort by `order()`.
2. Execute sequentially. Each step gets the same `BacktestContext`.
3. On `StepResult.FAILED`, mark all subsequent steps `SKIPPED` and return early.
4. Aggregate everything into a `BacktestReport`.

---

## Today's pipeline

```
BacktestRunner.run()
   └── LoginStep (order 0)
         └── LoginOrchestrator.ensureLoggedIn()
               ├── ALREADY_VALID  → StepResult.SUCCESS ("session already valid")
               ├── LOGGED_IN      → StepResult.SUCCESS ("logged in fresh")
               ├── INTERACTIVE_REQUIRED → StepResult.FAILED ("manual login required")
               └── FAILED         → StepResult.FAILED  (broker error message)
```

Nothing else is registered. Strategy / order placement / P&L stages are intentionally **not** wired yet.

---

## Triggering a run

### REST
```powershell
curl -X POST http://localhost:8080/api/backtest/run | ConvertFrom-Json
```

Response:
```json
{
  "success": true,
  "startedAt": "...",
  "finishedAt": "...",
  "durationMs": 412,
  "steps": [
    { "name": "login", "status": "SUCCESS", "message": "session already valid", "durationMs": 12 }
  ]
}
```

### UI
Open `http://localhost:8080/backtest`, click **Run backtest**. Each step appears as a row with its status badge (PASSED / FAILED / SKIPPED), duration, and message. Clear button resets the UI.

### Programmatic (e.g. from a test)
```java
@Autowired BacktestRunner runner;
BacktestReport report = runner.run();
```

### Clearing the ledger between runs

Every replay **appends** to `trade_order`; re-running the same date range gives
you two sets of rows for the same days, not one. The **Clear ledger** button on
`/backtest` purges the rows the table is currently showing (the same date range
the run form uses), previewing the count first. See
[ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md#purging-the-ledger).

Deleting trade configs does *not* clear the ledger — there is no FK between the
two tables, and the bulk config delete only reaches trades belonging to configs
it matched. Purge the ledger for trade rows; use the config panel for configs.

---

## Adding a new stage

1. Create `com.moneymaker.backtesting.steps.MyStep`:
   ```java
   @Component
   @RequiredArgsConstructor
   class MyStep implements BacktestStep {
       public String name()  { return "my-step"; }
       public int    order() { return 100; }    // 100, 200, 300… leaves room to splice
       public StepResult execute(BacktestContext ctx) {
           Instant start = Instant.now();
           try {
               // do work; share data via ctx.put("key", value)
               return StepResult.success(name(), "done", start);
           } catch (Exception e) {
               return StepResult.failed(name(), e.getMessage(), start);
           }
       }
   }
   ```
2. That's it — `BacktestRunner` will pick it up on the next restart, sort it after `LoginStep`, and the `/backtest` UI will render the new row automatically.

### Conventions
- **Order numbers in increments of 100** so you can always splice a new step between existing ones without renumbering.
- **Read shared state via `ctx.get(key)`** rather than re-querying the DB — earlier steps should write everything downstream needs.
- **Never re-implement live logic.** If a step needs trade configs, get them from `AppState.tradeConfigs()`. If it needs broker calls, go through the same client classes used in production.
- **Keep steps idempotent** so re-running the pipeline is safe.

---

## When to grow beyond a single pipeline

If you eventually need multiple variants (e.g. `LiveRunner`, `WalkForwardRunner`, `ParameterSweepRunner`) the natural extension is:

- Promote `BacktestStep` to a generic `PipelineStep`.
- Make `BacktestRunner` accept a `List<PipelineStep>` filtered by a discriminator (e.g. `step.tags().contains("backtest")`).
- Add per-pipeline config beans (`@ConfigurationProperties("pipeline.<name>")`).

Until then, the single-runner / single-step setup is deliberately minimal — easier to reason about than a framework with no users.

---

## Trading days come from the data, not from Mon-Fri

`TradingCalendar` answers "which *dates* does the market trade" - the companion
to `MarketHoursService`, which answers "which *times* within a date".

| Implementation | Active when | Source of truth |
|---|---|---|
| `HistoricalTradingCalendar` | `backtest.data-source=HISTORICAL_ICICI` (`@Primary`) | distinct dates in `historical_spot_candles` |
| `WeekdayTradingCalendar` | otherwise (`matchIfMissing`) | Mon-Fri |

Assuming weekday == trading day is wrong in **both** directions, and January 2024
contains one of each:

- **Saturday 2024-01-20 traded** - NSE ran a special session. A weekday rule skips
  a real session.
- **Monday 2024-01-22 did not** - market holiday. A weekday rule targets it, and
  the day is then "replayed" against whatever candles the lookback window happens
  to end on, i.e. the previous session's.

The historical calendar loads its date set lazily and does not cache an empty
result, so it starts working as soon as CSVs are imported without a restart.

> **Live still uses the weekday calendar** and therefore still does not know about
> holidays. That is a live/backtest deviation, deliberately left rather than
> silently switched, because it changes which days live generates configs for.

## Only settled bars reach the strategy

`MarketDataService.dropIncompleteBars` removes any trailing bar whose period has
not closed by the request's `to`, on **all** paths - historical, broker, and live.

This is the highest-impact behaviour change in the codebase's recent history:
full-year 2024 went from **+401.10 to -238.90** per share when it landed, because
the previous behaviour let the strategy read a bar that had not finished forming.
Full reasoning, worked boundary examples, and the measured breakdown are in
[`BACKTEST_PERFORMANCE.md` -> The settled-bar rule](BACKTEST_PERFORMANCE.md).
