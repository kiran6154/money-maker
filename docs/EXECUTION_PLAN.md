# Execution plan — milestone-by-milestone runbook

> The operational counterpart to [`MILESTONE_DETAILS.md`](MILESTONE_DETAILS.md).
> That doc was the *design* (what each milestone does and why); this doc is the
> *runbook* (the exact PRs, commits, verification commands, and doc updates).
>
> **One milestone at a time.** No milestone starts until the prior one's
> done-definition is fully met. Each milestone produces one or more PRs that
> each leave `main` green.

---

## Execution model

### Workflow conventions

| Step | What |
|---|---|
| **Branch from** | `main` (always; never branch from a feature branch) |
| **Branch naming** | `mN-<short-description>` (e.g. `m0-test-skeleton`, `m1-pipeline-scheduler`) |
| **Commits** | Conventional: `feat:` `fix:` `chore:` `test:` `docs:` `refactor:` — present tense |
| **PR title** | `[Mn.x] Short description` — easy to grep |
| **PR description** | Lists: (a) what changed, (b) tests added, (c) doc files updated |
| **Merge** | Squash + merge into `main` |
| **After merge** | Update [`CHANGELOG.md`](../CHANGELOG.md) `[Unreleased]` block in the same PR. When the milestone is fully done, promote `[Unreleased]` into a dated `[Mn — title]` release block. |

### Pre-flight checklist (before starting any milestone)

- [ ] Prior milestone's done-definition fully met (every box ticked).
- [ ] `main` is green (`mvn verify` passes; M2+ also runs `BacktestParityTest`).
- [ ] Any milestone-specific prerequisites listed in §"Prerequisites" satisfied.
- [ ] [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) status table: prior milestone marked ☑; current one being kicked off marked 🔧.

### Done-definition (every milestone)

- [ ] All PRs in the milestone merged to `main`.
- [ ] `mvn verify` green on `main`.
- [ ] M2+ only: `BacktestParityTest` green (no fixture diffs).
- [ ] `CHANGELOG.md` has the milestone's `[Mn — title]` release block with all entries.
- [ ] `IMPLEMENTATION_PLAN.md` status: milestone ☑ with link to changelog block.
- [ ] No `.bt-cache` / `target/` artefacts committed.
- [ ] Doc updates per the milestone's "Docs touched" section.

### Failure handling

| Situation | Action |
|---|---|
| `mvn verify` fails on a PR | Don't merge. Fix on branch. |
| `BacktestParityTest` fails unexpectedly (output changed without intent) | Treat as a bug. Investigate before updating fixtures. Architect's rule: fixtures change only when the behaviour change is intentional and documented in the commit. |
| `BacktestParityTest` fails *expectedly* (behaviour change is the intent) | Update expected fixture in same PR. Commit message must explain why. |
| Mid-milestone you discover the scope is wrong | Pause. Update `MILESTONE_DETAILS.md` with the discovery; either renegotiate the architect's approval or split the work into a new milestone. Don't quietly expand scope. |
| Liquibase migration fails on a real DB | Rollback. Liquibase changesets must always have a `<rollback>` block. Verify before merging. |

---

## Sequence

```
 M0 ─→ M1 ─→ M2 ─→ [M3 blocked* ] ─→ M4 ─→ M5 ─→ M6 ─→ M7 ─→ M8 ─→ M9 ─→ M10
                                                                              │
                                                                              ▼
                                                            (M11 deferred 90 days)
                                                            (M12, M13, M14 deferred to demand)
```

\* M3 blocked on user decision: force-close order-type variant + `app.market.force-close-time`. **Either decide now or skip M3 temporarily and execute M4→M5 first.** Engineer's recommendation: decide now, do M3 in order, since it's the only money-risk item.

---

# M0 — Test harness infrastructure

## Prerequisites

- [ ] Docker Desktop running (for Testcontainers).
- [ ] Working Kite session in dev for one-time fixture capture (M0.PR2 only).
- [ ] ~3 days of focused engineering time available.

## PR breakdown

### Decision pivot — H2 + JUnit (2026-05-28)

> **Original plan:** Testcontainers MySQL + JUnit. **Revised:** H2 in MySQL-compatibility mode + JUnit 5.
> **Reason:** no Docker available in the dev environment.
> **Trade-off accepted:** H2's `BETWEEN` + index behaviour can drift from MySQL on edge cases; we mitigate by (a) using `MODE=MySQL` compatibility flag, (b) keeping a periodic manual re-verification against real MySQL until CI runs both.
> **Cucumber considered, rejected:** parity tests are data-in/data-out; Gherkin adds ceremony for no readability win.

### PR M0.1 — H2 test scaffold + canary
**Branch:** `M0` (already created)
**Estimated:** 0.5 day

Steps:
1. `pom.xml` — no changes needed. H2 already declared (runtime scope works for tests); `spring-boot-starter-test` already declared (bundles JUnit 5 + AssertJ + Mockito).
2. Create `src/test/resources/application-test.properties` with H2 in MySQL mode + `backtest.auto-reset=true`.
3. Create `src/test/java/com/moneymaker/backtesting/BacktestParityTest.java` with the canary test only:
   ```java
   @Test void canary_must_fail() { assertEquals(1, 2); }
   ```
4. Create `src/test/java/com/moneymaker/backtesting/support/FixtureLoader.java` (skeleton — `loadSql(Path)`).
5. Create `src/test/java/com/moneymaker/backtesting/support/TradeOrderSnapshot.java` (skeleton — `snapshot(List<TradeOrder>) → JSON string`).

Verification:
```powershell
mvn -Dtest=BacktestParityTest test
# expect: canary fails. Other tests don't exist yet.
```

Commits:
- `chore(test): add Testcontainers + assertj`
- `feat(test): scaffold BacktestParityTest with canary`
- `feat(test): scaffold FixtureLoader + TradeOrderSnapshot`

Docs:
- `CHANGELOG.md` [Unreleased] / Added: scaffold entry.

---

### PR M0.2 — MarketDataCaptureCli + capture fixtures
**Branch:** `m0-fixture-capture`
**Estimated:** 1 day

Steps:
1. Create `src/test/java/com/moneymaker/backtesting/support/MarketDataCaptureCli.java` — main class. Args: `--date 2026-04-01 --symbol NIFTY --interval 5min --output src/test/resources/fixtures/data/market_data_2026-04-01.sql`. Writes header comment with provenance.
2. Run the CLI for 6 captures (5 unique dates + the parallel-trades scenario reused on 2026-04-01):
   - 2026-04-01: target exit (T0.1), parallel-trades (T0.7)
   - 2026-04-02: stop-loss exit (T0.2)
   - 2026-04-03: force-close (T0.3)
   - 2026-04-04: trades-per-day cap (T0.4)
   - 2026-04-05: max-loss cap (T0.5)
   - 2026-04-08: opposite-signal close (T0.6)
3. Create `src/test/resources/fixtures/data/configs.sql` with the 3 trade configs needed across the seven scenarios.
4. Verify all SQL files load against a Testcontainers MySQL via FixtureLoader.

Verification:
```powershell
mvn -Dtest=FixtureLoaderTest test
# expect: all 7 fixtures load without error
```

Commits:
- `feat(test): MarketDataCaptureCli for fixture generation`
- `test(fixtures): capture six market-data days`
- `test(fixtures): trade configs covering 7 scenarios`

Docs:
- `CHANGELOG.md` [Unreleased] / Added: fixture pack.

---

### PR M0.3 — Diagnostic test runner
**Branch:** `m0-diagnostic-runner`
**Estimated:** 1 day

Steps:
1. Implement the seven scenario tests in `BacktestParityTest` (T0.1–T0.7). Each test:
   - `@BeforeEach { resetService.resetAll(); fixtureLoader.load(scenarioFiles); }`
   - Runs `BacktestAnalysisService.run(date, date)`.
   - Captures snapshot.
   - Writes JSON to `target/test-output/trade_order_<scenario>_actual.json`.
   - Logs diff vs (empty) expected file at WARN.
   - **No `assertEquals` yet** — that's M2.
2. Implement `TradeOrderSnapshot`:
   - Serialise rows sorted by `(entry_time, instrument_token, option_strike, option_type, entry_direction)`.
   - `BigDecimal` fields use `toPlainString()`.
   - Drop `id` from output (DB artefact).
   - Lenient mode: extra fields in actual tolerated unless `--strict`.
3. Verify the canary still fails (sanity check that the harness can detect failures).

Verification:
```powershell
mvn verify
# expect: 8 tests run. 1 canary fails (expected). 7 scenarios pass (no assertions).
#         7 JSON files in target/test-output/, viewable for sanity.
```

Commits:
- `feat(test): seven scenario tests in diagnostic mode`
- `feat(test): deterministic snapshot serialiser`

Docs:
- `CHANGELOG.md` [Unreleased] / Added: BacktestParityTest with 7 scenarios in diagnostic mode.
- `IMPLEMENTATION_PLAN.md`: mark M0 in progress 🔧.

## Done definition for M0

- [ ] PRs M0.1, M0.2, M0.3 merged.
- [ ] `mvn verify` shows 7 scenario tests pass + canary fails.
- [ ] Snapshots present in `target/test-output/` after a run.
- [ ] No `expected/*.json` files exist yet (M2's job).
- [ ] `CHANGELOG.md` has the M0 entries under `[Unreleased]`.
- [ ] `IMPLEMENTATION_PLAN.md` M0 row shows 🔧 → ready to flip to ☑ at end of M2.
- [ ] Engineer can run the same test 5 times in a row and observe **whether outputs differ** (the diagnostic).

---

# M1 — Reproducibility fix

## Prerequisites

- [ ] M0 done-definition met.
- [ ] M0's diagnostic mode confirms non-determinism (running 5× shows different snapshots at least once). If reproducibility is already perfect, M1 scope shrinks to just the pipeline scheduler and reset endpoint.

## PR breakdown

### PR M1.1 — Deterministic iteration
**Branch:** `m1-deterministic-iteration`
**Estimated:** 0.5 day

Steps:
1. Locate every `SharedData` map iteration (5 sites confirmed):
   - `AnalysisScheduler.calculateIndicator` — `timeframes.keySet()` iteration
   - `AnalysisScheduler.runStrategies` — `combinedDto` iteration (already a List, but order matters)
   - `Strategy1.execute` — `strikeMarketData.keySet()` (or `entrySet()`)
   - `Strategy2.execute` — same
   - `BacktestAnalysisService.runForDateTime` — any iteration over SharedData maps
2. At each site, sort the key set before iteration:
   ```java
   strikeMarketData.keySet().stream()
       .sorted(Comparator.nullsLast(Comparator.naturalOrder()))
       .forEach(key -> { ... });
   ```
3. Add unit test `DeterministicIterationTest` that constructs an unsorted-insertion map, iterates via the new code, asserts sorted order.

Verification:
```powershell
mvn verify
# 7 scenario tests + canary + new DeterministicIterationTest.
# Run BacktestParityTest 5 times in a row → snapshots should now be identical run-to-run.
```

Commits:
- `fix(scheduler): sort SharedData iteration keys for determinism`
- `test: DeterministicIterationTest`

Docs:
- `CHANGELOG.md` [Unreleased] / Fixed.

---

### PR M1.2 — TradingPipelineScheduler with tryLock
**Branch:** `m1-pipeline-scheduler`
**Estimated:** 0.5 day

Steps:
1. Create `src/main/java/com/moneymaker/scheduler/TradingPipelineScheduler.java`:
   - `@Scheduled(cron = "0 0/5 9-15 * * MON-FRI", zone = "Asia/Kolkata")`
   - `ReentrantLock` + `tryLock()`; on skip log WARN with skip counter.
   - Calls `analysisScheduler.analyzeMarketData()` → `orderScheduler.processOrders()` → `positionScheduler.processPositions()`.
   - Gates on `app.mode=live` + `marketHours.isOpenNow()`.
2. Remove `@Scheduled` annotation from `AnalysisScheduler.analyzeMarketData`, `OrderScheduler.processOrders`, `PositionScheduler.processPositions`. Methods stay public.
3. Unit tests:
   - `TradingPipelineSchedulerTest.tick_runs_services_in_order` (mock the three services, verify order).
   - `TradingPipelineSchedulerTest.tick_skips_when_locked` (simulate slow tick, second tick skips with WARN).

Verification:
```powershell
mvn verify
# Including 2 new tests.
```

Commits:
- `feat(scheduler): TradingPipelineScheduler with tryLock guard`
- `refactor(scheduler): remove @Scheduled from individual pipeline schedulers`
- `test: pipeline scheduler ordering + skip behaviour`

Docs:
- `CHANGELOG.md` [Unreleased] / Changed.

---

### PR M1.3 — Backtest reset endpoint
**Branch:** `m1-backtest-reset`
**Estimated:** 0.5 day

Steps:
1. Create `src/main/java/com/moneymaker/backtesting/BacktestResetService.java`:
   - `resetAll()` — calls `resetRange(MIN, MAX)`.
   - `resetRange(LocalDate from, LocalDate to)` — `DELETE FROM trade_order WHERE entry_time BETWEEN ...`, `DELETE FROM alert_state WHERE alert_date BETWEEN ...`, `tradeConfigScheduler.invalidateConfigsCache()`, clears `NotificationService.dedupeState/throttleState`.
2. Create `BacktestResetController` — `POST /api/backtest/reset?fromDate=&toDate=`. Validation: `toDate ≤ today`, returns 400 otherwise.
3. Update `BacktestController.runAnalysis` to auto-invoke reset when `backtest.auto-reset=true`.
4. `application.properties`: default `backtest.auto-reset=false` (engineer's concession to architect).
5. `application-test.properties`: `backtest.auto-reset=true`.
6. Unit tests:
   - `BacktestResetServiceTest` — seeds rows, calls reset, asserts deletion.
   - `BacktestResetControllerTest` — invalid toDate returns 400.

Verification:
```powershell
mvn verify
```

Commits:
- `feat(backtest): BacktestResetService for date-range purge`
- `feat(backtest): POST /api/backtest/reset endpoint with validation`
- `feat(backtest): auto-reset hook in BacktestController`
- `test: reset service + controller`

Docs:
- `CHANGELOG.md` [Unreleased] / Added.
- `IMPLEMENTATION_PLAN.md`: M1 row flips to ☑ once merged.

## Done definition for M1

- [ ] PRs M1.1, M1.2, M1.3 merged.
- [ ] `mvn verify` green.
- [ ] Diagnostic run: `BacktestParityTest` run 5× in a row produces byte-identical snapshots.
- [ ] `CHANGELOG.md` updated.
- [ ] `IMPLEMENTATION_PLAN.md`: M0 + M1 ☑.

---

# M2 — Lock down golden outputs

## Prerequisites

- [ ] M1 done-definition met.
- [ ] Diagnostic run snapshots are visually inspected by engineer for *correctness* (not just stability) — the golden outputs are about to become regression truth, so they need to actually be correct first.

## PR breakdown

### PR M2.1 — Lock fixtures and turn assertions on
**Branch:** `m2-lock-fixtures`
**Estimated:** 0.5 day

Steps:
1. Run `BacktestParityTest` to generate all 7 actual snapshots.
2. Visually inspect each — does the trade_order content match what the strategy *should* produce for that scenario?
3. Copy each `target/test-output/trade_order_<scenario>_actual.json` to `src/test/resources/fixtures/expected/trade_order_<scenario>.json`.
4. Modify `BacktestParityTest`:
   - Replace `log.warn(diff)` with AssertJ `assertThat(actual).usingRecursiveComparison().isEqualTo(expected)`.
   - Remove the `canary_must_fail` test.
5. Add the `-Dupdate-fixtures=true -Dconfirm-fixture-update=$today` two-key flag for intentional fixture regeneration (architect's footgun protection).
6. Add `ColumnCoverageTest` — asserts every `TradeOrder` column appears in at least one expected fixture (architect's schema-level coverage requirement).

Verification:
```powershell
mvn verify
# 7 scenarios pass with assertions; canary gone; column coverage green.
# Deliberately tweak Strategy1 logic temporarily; verify a fixture diff fails clearly.
```

Commits:
- `test: lock golden outputs for 7 scenarios`
- `test: turn BacktestParityTest assertions on; remove canary`
- `test: ColumnCoverageTest for schema-level coverage`

Docs:
- `CHANGELOG.md`: promote `[Unreleased]` entries into a dated `[M0–M2 — Test foundation] — YYYY-MM-DD` release block.
- `IMPLEMENTATION_PLAN.md`: M0, M1, M2 all ☑.

## Done definition for M2

- [ ] PR M2.1 merged.
- [ ] `mvn verify` green; `BacktestParityTest` asserts pass.
- [ ] Deliberately introducing a strategy bug fails the test with a readable JSON diff.
- [ ] `CHANGELOG.md` has the M0–M2 release block.
- [ ] **The harness is now load-bearing.** Every subsequent PR must keep it green.

---

# M3 — Force-close real broker exit

> **🛑 BLOCKED ON USER DECISION** — see top of doc. Either decide and execute in order, or skip and do M4 → M5 first. **Engineer recommends decide-and-execute** because this is the only money-risk milestone.

## Prerequisites

- [ ] M2 done-definition met.
- [ ] **User decision:** force-close order-type variant (recommend (a) market at 15:25).
- [ ] **User decision:** `app.market.force-close-time` value (recommend `15:25`).
- [ ] Paper-trading account available for sandbox verification.

## PR breakdown

### PR M3.1 — placeExit interface + impls
**Branch:** `m3-place-exit-interface`
**Estimated:** 1 day

Steps:
1. Add `placeExit(TradeOrder) → Optional<FillSnapshot>` to `OrderPlacementService` interface.
2. Implement in:
   - `ZerodhaOrderPlacement` — opposite-side market order.
   - `GrowwOrderPlacement` — same.
   - `AngelOneOrderPlacement` — same.
   - `BacktestingOrderPlacement` — returns `Optional.of(synthetic FillSnapshot with last cached candle close, fillStatus=BACKTEST)`.
3. Unit tests per impl (use existing patterns).

Commits:
- `feat(order): placeExit interface for forced exits`
- `feat(broker): placeExit impl in zerodha/groww/angelone/backtesting`

Docs: CHANGELOG / Added.

---

### PR M3.2 — OrderService.forceCloseOpenPositions wires placeExit
**Branch:** `m3-force-close-wiring`
**Estimated:** 0.5 day

Steps:
1. Modify `OrderService.forceCloseOpenPositions`:
   - For each OPEN row: call `placement.placeExit(row)`.
   - On success: update row with broker fill + status CLOSED.
   - On failure: leave row OPEN, set `fill_status=EXIT_FAILED`, fire `notifier.alertOrderExitFailed`.
2. Add `app.market.force-close-time=15:25` property.
3. `DaySummaryScheduler` reports `exit-failed: N` count.
4. New alert: `NotificationService.alertOrderExitFailed`.
5. Tests:
   - `OrderServiceForceCloseTest` — happy path verifies correct broker call args.
   - `OrderServiceForceCloseFailureTest` — broker throws; row stays OPEN, alert fired.
   - `OrderServiceForceClosePartialTest` — 2 OPEN trades, 1 succeeds, 1 fails; correct state per row.
   - **`BacktestParityTest` must still pass byte-identically** — backtest is unaffected because `BacktestingOrderPlacement.placeExit` is no-op.

Verification:
```powershell
mvn verify
# Including 3 new force-close tests + parity test green.
```

Commits:
- `feat(order): forceCloseOpenPositions calls placeExit before CLOSE`
- `feat(order): EXIT_FAILED fill_status + alertOrderExitFailed`
- `feat(scheduler): day-summary reports exit-failed count`
- `test: force-close success/failure/partial`

Docs:
- `CHANGELOG.md` / Added + Changed + a **bold migration note** ("requires `app.market.force-close-time` property; defaults to 15:25").
- `docs/ORDERS_AND_POSITIONS.md` — update `fill_status` enum, add `placeExit` to broker capability table.
- `docs/NOTIFICATIONS.md` — add `alertOrderExitFailed`.

---

### PR M3.3 — Sandbox verification
**Branch:** N/A (runbook step, not code)
**Estimated:** 0.5 day

Steps (manual):
1. Deploy to paper-trading sandbox.
2. Open a position in NIFTY 5-min strategy.
3. Wait through to 15:25 IST.
4. Verify:
   - Broker order placed (visible in Kite logs).
   - `trade_order` row CLOSED with `exit_reason=FORCE_CLOSE`.
   - Telegram digest fires at 15:31 with the row.
5. Force a failure (e.g. invalid product type); verify `EXIT_FAILED` + alert.

Docs:
- `CHANGELOG.md` — add a `### Verified` subsection noting sandbox results.

## Done definition for M3

- [ ] PRs M3.1, M3.2 merged.
- [ ] Sandbox verification (PR M3.3 steps) green.
- [ ] `CHANGELOG.md` has M3 release block with sandbox verification note.
- [ ] `IMPLEMENTATION_PLAN.md`: M3 ☑.
- [ ] `BacktestParityTest` green throughout.

---

# M4 — Live trading polish *(medium detail)*

Five sub-items; each is its own PR. Suggested order: M4.5 (rename) **first** because it's the multi-deploy migration that takes 3 calendar days of hold time. The other four can land in any order during that hold.

| Sub | Branch | Effort | Key risk |
|---|---|---|---|
| M4.5a | `m4-strategy-id-step1-add` | 2 hours | dual-write JPA |
| M4.5b | `m4-strategy-id-step2-backfill` (after 1-day soak) | 1 hour | transaction safety |
| M4.5c | `m4-strategy-id-step3-drop` (after 1-day soak) | 1 hour | irreversible |
| M4.1 | `m4-rupee-pnl` | 4 hours | column migration backfill |
| M4.3 | `m4-is-active-flag` | 4 hours | filter applied everywhere |
| M4.2 | `m4-clone-yesterday` (after M4.3) | 4 hours | dedupe key |
| M4.4 | `m4-open-trade-banner` | 2 hours | low |

Each PR follows the same pattern: branch from main, implement, test (including parity), update CHANGELOG, merge. Detailed steps for each will be expanded **at start-of-milestone** rather than now — the gist matches MILESTONE_DETAILS.md §M4 already.

## Done definition for M4

- [ ] All 7 sub-PRs merged.
- [ ] 3 calendar days of hold time observed for the rename migration.
- [ ] All M4-specific tests added; parity green.
- [ ] `CHANGELOG.md` release block `[M4 — Live trading polish]` with the seven entries.
- [ ] `IMPLEMENTATION_PLAN.md`: M4 ☑.

---

# M5 — Operational hardening *(medium detail)*

Five small items; can bundle into 2 PRs.

| PR | Sub-items | Branch | Effort |
|---|---|---|---|
| PR M5.A | M5.1 (two-key guard) + M5.2 (manual re-trigger) | `m5-daysummary-recovery` | 3 hours |
| PR M5.B | M5.3 (heartbeat windowing) + M5.4 (delete stub) + M5.5 (LiveCacheJanitor) | `m5-ops-hardening` | 5 hours |

Each PR includes its tests and CHANGELOG entries.

## Done definition for M5

- [ ] PRs M5.A, M5.B merged.
- [ ] Parity green throughout.
- [ ] `CHANGELOG.md` release block `[M5 — Ops hardening]`.
- [ ] `IMPLEMENTATION_PLAN.md`: M5 ☑.

---

# M6 — IndicatorComputeService *(medium detail)*

**One PR, not split** (architect's requirement). Branch `m6-indicator-compute-service`. Effort: **4 days**.

Steps (high level):
1. Create `IndicatorComputeService`, `IndicatorRegistry`, `IndicatorCacheKey` (hash-over-all-closes per architect).
2. Implement `try (var tick = service.startTick()) { ... }` AutoCloseable pattern.
3. Rolling-sum SMA implementation; explicit `setScale(4)`.
4. Migrate `Strategy1`, `Strategy2` to use the compute service.
5. Keep `SMAIndicatorImpl.calculate` writing the SMA columns (dual-write for parity).
6. Deprecate `IndicatorService.calculate` static method with once-per-JVM WARN.
7. Add ArchUnit test: nothing outside `IndicatorComputeService` reads `MarketData.getSmaValue*` (architect's M11 pre-condition).
8. Tests:
   - T6.1 rolling-sum equals from-scratch for periods 5/20/50/100/200.
   - T6.2 cache hit avoids recompute.
   - T6.3 cache miss on changed candle content.
   - T6.4 cache key stable across runs.
   - T6.5 parity test green.
   - T6.6 deprecated method logs WARN once.
9. Profile a backtest before/after; record speed improvement in CHANGELOG.

## Done definition for M6

- [ ] PR merged.
- [ ] All M6 tests green.
- [ ] Parity green.
- [ ] Profile shows SMA compute is no longer a tick-time bottleneck.
- [ ] ArchUnit guard active.
- [ ] `CHANGELOG.md` release block `[M6 — IndicatorComputeService]`.
- [ ] `IMPLEMENTATION_PLAN.md`: M6 ☑.

---

# M7 — SharedData lint + indicator_binding *(medium detail)*

Two PRs (architect's split for risk).

### PR M7.A — ArchUnit SharedData lint
**Branch:** `m7-sharedData-lint`. Effort: 4 hours.

Ships as a no-op (allowlist matches current state). Verifies that adding a new reference fails the build.

### PR M7.B — indicator_binding table + migration
**Branch:** `m7-indicator-binding`. Effort: 1.5 days.

Liquibase 026 → indicator_binding table; 027 → data migration; 028 → `sma_timeframe` becomes a view. Entity, repository, service, UI updated. SMA params include `slope` in JSON (not as a column).

Tests T7.1.1, T7.1.2, T7.2.1–T7.2.4 per MILESTONE_DETAILS.

## Done definition for M7

- [ ] Both PRs merged.
- [ ] Parity green.
- [ ] Adding an EMA binding via the UI produces signals end-to-end.
- [ ] `CHANGELOG.md` release block `[M7 — Indicator binding]`.
- [ ] `IMPLEMENTATION_PLAN.md`: M7 ☑.

---

# M8 — Disk-backed BacktestMarketDataCache *(medium detail)*

**One PR.** Branch `m8-disk-cache`. Effort: 2 days.

Implements: per-day JSON files, compact array format, atomic write (`*.tmp` + rename), version key with INFO log on mismatch, fallback to in-memory if dir unwritable.

Tests T8.1–T8.5.

## Done definition for M8

- [ ] PR merged.
- [ ] Second backtest run for same date <5s.
- [ ] Parity green.
- [ ] `CHANGELOG.md` release block `[M8 — Disk cache]`.
- [ ] `IMPLEMENTATION_PLAN.md`: M8 ☑.

---

# M9 — Backtest perf Phases 2+3 *(light detail)*

**One PR.** Branch `m9-perf-phases`. Effort: 2 days.

Skip-redundant-TF cache in strategies + benchmark regression test (machine-local baseline at `.bt-baselines/<hostname>.json`).

Tests T9.1–T9.4.

## Done definition for M9

- [ ] PR merged.
- [ ] 2-day backtest <15s OR within 30% of machine-local baseline.
- [ ] Parity green.
- [ ] `CHANGELOG.md` release block `[M9 — Perf phases]`.

---

# M10 — Pre-resolve strikes per day *(light detail)*

**One PR.** Branch `m10-prerolved-strikes`. Effort: 0.5 day.

Per-(date, configId) cache for strike compute; 2-day eviction.

## Done definition for M10

- [ ] PR merged.
- [ ] Parity green.
- [ ] `CHANGELOG.md` release block `[M10 — Strike pre-resolution]`.
- [ ] `IMPLEMENTATION_PLAN.md`: M10 ☑.

---

# M11–M14 *(deferred)*

See `MILESTONE_DETAILS.md` for what these milestones contain and when to activate them.

- **M11** activates after 90 days of M6 in production with no consumer reads.
- **M12** activates when a 90+ day backtest workflow is needed.
- **M13** activates when day-parallel backtest is needed.
- **M14** activates when 100-day routine sweeps materialise.

Each will get its own detailed runbook at activation time.

---

# What "done" looks like at the end of M10

- ~5 weeks of focused engineering complete.
- All architectural debt that compounds per-feature has been addressed.
- Backtest is reproducible, asserted-on-every-PR, and runs a 2-day historical scenario in <15s.
- Live trading has no overnight position leak.
- Adding a new indicator is a one-class change with no schema work.
- The UI lets ops manage configs, clone-yesterday, and soft-delete.
- The day-summary digest reports actual rupee P&L.

Three deferred milestones (M11, M12, M13/14) remain explicitly parked with clear activation triggers — no silent debt.

---

# Right now

We are at: **M0 — Test harness infrastructure**.

**Next action:** confirm the three pre-flight items at the top of M0, then I start PR M0.1.

If you'd also like to commit the existing uncommitted work (trade-config admin UI + market-hours + day-summary + the new docs) before kicking off M0, say so — I'd recommend doing that first so M0 branches from a clean main.
