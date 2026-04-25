
# Backtesting

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

