
# Backtesting

> ⚠️ **Sections below "Moving parts" are stale.** They describe a
> `BacktestStep` / `BacktestRunner` / `POST /api/backtest/run` design that is no
> longer in the code. What actually runs today is `BacktestAnalysisService.run(from, to)`
> behind `POST /api/backtest/analysis?fromDate=&toDate=`, which replays each day
> tick-by-tick through the same `AnalysisScheduler` / `OrderScheduler` /
> `PositionScheduler` entry points the live cron uses. The
> **[Data source](#data-source)** section immediately below is current.

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
`historical_option_candles`). `AnalysisScheduler` and `Strategy1` both go through
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
  divisible by 2).
- **No `day` candles**, so `EodDowntrendDetectionService` is skipped for the run;
  its ATR needs daily bars. Auto-downtrend config generation is `BROKER`-only.
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

