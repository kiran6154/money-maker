# Detailed milestone plan — engineer's plan with per-milestone architect review

> Every milestone below is reviewed by the architect **at the milestone level**,
> not in a summary block at the end. Each section runs:
>
> 1. **Engineer's plan** — goal, scope, files, effort.
> 2. **Open questions** — decisions still owed.
> 3. **Test cases** — explicit named tests with fixtures and assertions.
> 4. **Architect's review** — per-item challenges; sign-off or pushback.
> 5. **Engineer's response** — answer each architect concern.
> 6. **Final approval state** — APPROVED / APPROVED WITH CHANGES / BLOCKED ON DECISION.
>
> The prior round of debate failed because both voices agreed "we need tests"
> in the abstract. This round forces test coverage into every milestone
> *before* approval. No milestone proceeds without explicit test cases reviewed.
>
> **Cross-cutting rule:** every milestone past M2 must include
> `BacktestParityTest green` in its acceptance. Output changes require
> updated golden fixtures in the same PR with a justification in the commit
> message.

---

# M0 — Test harness infrastructure

## Engineer's plan
A working `BacktestParityTest` that boots Spring, seeds fixtures, runs a backtest, captures `trade_order`, and **diffs** against stored expected output. The test runs in M0 as **a diagnostic** — it does not assert yet. The initial flakiness is itself the proof that M1 (reproducibility fix) is needed.

### Goal
Test infrastructure exists and runs. Outputs are captured to a snapshot. No assertions yet — by design.

### In scope
- Maven test deps: Testcontainers MySQL, Spring Boot test slice.
- Fixture loader (`.sql` runner) and JSON snapshotter (sorted, deterministic).
- 6 fixtures (5 dates + 1 scenario-stress day — see test cases below).
- A capture-mode CLI that lets the engineer pull historical `market_data` from Kite into fixture SQL one-time.

### Out of scope
- The assertions (M2).
- New scenarios beyond the six listed (added as needed in later milestones).

### Files
- `pom.xml` — add `org.testcontainers:mysql:1.19.7`, ensure `spring-boot-starter-test` is on test scope.
- **New** `src/test/java/com/moneymaker/backtesting/BacktestParityTest.java`.
- **New** `src/test/java/com/moneymaker/backtesting/support/FixtureLoader.java`.
- **New** `src/test/java/com/moneymaker/backtesting/support/TradeOrderSnapshot.java` — serialises rows to JSON, sorted by `(entry_time, id)`, fields in fixed order.
- **New** `src/test/java/com/moneymaker/backtesting/support/MarketDataCaptureCli.java` — one-shot main; pulls a date's market_data via Kite and writes `.sql`.
- **New** `src/test/resources/fixtures/data/configs.sql`.
- **New** `src/test/resources/fixtures/data/market_data_<date>.sql` — six files.
- **Empty** `src/test/resources/fixtures/expected/` — populated in M2.

## Open questions
1. **Testcontainers MySQL vs H2.** H2 is faster (~60s saved per CI run) but its `BETWEEN` + index behaviour differs from MySQL — `OrderService` relies on these. Engineer recommends Testcontainers.
2. **Where do we host the captured `market_data` fixtures — git or LFS?** Six dates × 5 instruments × 75 candles ≈ a few hundred KB. Engineer recommends git.
3. **CI strategy.** No CI today. Engineer recommends shipping the test as local-only for now; CI is a separate ticket.

## Test cases

| # | Test name | Fixture date | What it covers | Expected `trade_order` shape |
|---|---|---|---|---|
| T0.1 | `parity_clean_target_exit` | 2026-04-01 | Single config; entry signal fires at 10:15; target hit at 11:30; clean exit | 1 row, `exit_reason=TARGET` |
| T0.2 | `parity_stop_loss_exit` | 2026-04-02 | Same config; entry at 10:00; SL hit at 13:45 | 1 row, `exit_reason=STOP_LOSS` |
| T0.3 | `parity_force_close_at_close` | 2026-04-03 | Entry at 14:50; no exit signal; force-close at 15:20 | 1 row, `exit_reason=FORCE_CLOSE` |
| T0.4 | `parity_signal_suppressed_by_trades_cap` | 2026-04-04 | Config has `numberOfTradesPerDay=1`; first trade closes; second signal fires; second entry suppressed | 1 row, second signal absent from ledger |
| T0.5 | `parity_signal_suppressed_by_max_loss` | 2026-04-05 | Config `maxLoss=500`; first trade loses 600; second entry suppressed | 1 row, no further entries |
| T0.6 | `parity_opposite_signal_closes_open` | 2026-04-08 | SELL signal opens trade; later BUY signal closes it (not opens new) | 1 row, `exit_reason=SIGNAL` |

In M0 these all run and log "diff vs empty expected" — they don't fail. M2 turns assertions on.

## Architect's review

**1. Six scenarios — is that the right coverage matrix, not just count?**
Six is fine if they cover the *behavioural surfaces*. I checked: target exit, SL exit, force-close, two suppression paths, opposite-signal close. **Coverage:** entry decision (1 + 5), exit decision (1, 2, 3, 6), cap enforcement (4, 5). Missing: **parallel-trades cap** (`numberOfParallelTrades`). Two simultaneous OPEN trades with a third signal arriving — that's a code path the suppression tests don't hit. **Add T0.7.**

**2. Why six separate dates instead of replaying one date six times with different configs?**
Engineer used dates as the dimension. Each date carries the actual market candles for that day. Adding scenarios as *new configs on existing dates* is cheaper than capturing new dates — and exercises the same code paths. **Suggestion:** add T0.7 as a third config on date 2026-04-01 (which already has target-exit data), not a new date. Saves a capture round-trip.

**3. The capture CLI — is it idempotent? Reproducible?**
The fixture SQL is committed to git. The CLI is one-shot to produce it; running it twice on the same date produces the same SQL. Good. But: if the engineer pulls fixtures from a *production* Kite session, those candles depend on which broker account is logged in. **Requirement:** the CLI must record the symbol token + interval + window in the fixture's header comment so a re-pull from a different account is verifiable.

**4. JSON snapshot determinism — what about `BigDecimal` scale?**
`TradeOrder.profit` is `DECIMAL(12,4)`. JSON serialisers can drop trailing zeroes. `12.5000` becomes `12.5` and a comparison with `12.50` fails. **Requirement:** snapshot uses string-form `BigDecimal.toPlainString()` for all decimal fields; no float coercion.

**5. Test isolation — does each test get a clean DB?**
Testcontainers starts one container per test class by default. With six tests and Liquibase migrations, that's six full schema rebuilds. **Suggestion:** one container per test class (shared) + a per-test `BacktestResetService.resetAll()` between tests. Cuts wall time from ~3 min to <30s.

**6. The "diagnostic mode that doesn't assert" — how do we know the test infrastructure itself works?**
If the test never fails in M0, how do we trust it once M2 turns assertions on? **Requirement:** add a deliberately-failing canary test that asserts `1 != 1` and verify it fails in CI/locally. Delete the canary once M2 lands.

## Engineer's response

1. **T0.7 added** — parallel-trades cap scenario, attached as a third config on 2026-04-01.
2. **Date-vs-config dimension** — agree; T0.7 reuses an existing capture, no new market_data fetch needed.
3. **CLI provenance header** — agree; the `MarketDataCaptureCli` writes a `-- captured-by user@host at ISO-timestamp; symbol=… interval=… from=… to=…` comment block at the top of every `.sql` file.
4. **`toPlainString()` for decimals** — agree; included in `TradeOrderSnapshot`.
5. **Shared container + per-test reset** — agree; uses `@Testcontainers(disabledWithoutDocker = true)` + `@BeforeEach { resetService.resetAll(); fixtureLoader.load(...); }`.
6. **Canary test** — agree; `BacktestParityTest.canary_must_fail()` added in M0, removed in M2's final commit.

## Final approval — M0
**APPROVED WITH CHANGES.** Engineer's revised plan accepted. New effort: **3 days** (was 2). New file count: 7 (was 6).

---

# M1 — Reproducibility fix

## Engineer's plan
Identical inputs → identical `trade_order` rows. M0's harness goes from flaky to green after this lands.

### Goal
1. Deterministic iteration over `SharedData` maps.
2. Pipeline schedulers run in explicit order, not by alphabetical accident.
3. `POST /api/backtest/reset` purges DB + in-memory state for a date range.

### In scope
- Sort key sets before iterating at every `SharedData` map access (5 sites: `AnalysisScheduler`, `Strategy1`, `Strategy2`, `BacktestAnalysisService`, `OrderService` if needed).
- New `scheduler/TradingPipelineScheduler.java` — single `@Scheduled`, `tryLock`-guarded, calls analysis → orders → positions in order.
- Remove `@Scheduled` from the three existing schedulers; their methods stay as service entry points.
- New `backtesting/BacktestResetService` + `BacktestResetController` for `POST /api/backtest/reset?fromDate=&toDate=`.
- `application.properties` — `backtest.auto-reset=true`.
- `BacktestController.runAnalysis` auto-invokes reset when enabled.

### Out of scope
- `CacheRegistry` SPI (M7).
- 08:00 live-cache reset (M5.5).

### Files
- `AnalysisScheduler.java` — remove `@Scheduled`; sort keys at iteration sites.
- `OrderScheduler.java`, `PositionScheduler.java` — remove `@Scheduled`.
- `Strategy1.java`, `Strategy2.java` — sort keys.
- **New** `scheduler/TradingPipelineScheduler.java`.
- **New** `backtesting/BacktestResetService.java`.
- **New** `backtesting/BacktestResetController.java`.
- `BacktestController.java` — wire auto-reset.
- `application.properties`.

## Open questions
1. **What's the iteration-deterministic ordering?** Natural ordering of `String` keys is fine for `instrument|interval`-style keys. For `Integer` strike keys, natural numeric. Engineer recommends `Comparator.naturalOrder()` everywhere.
2. **What does `tryLock` do when it fails?** Log WARN, skip. Engineer's preference.
3. **`backtest.auto-reset=true` default — is this too aggressive?** It silently deletes `trade_order` rows in the date range before every backtest run. If an operator runs a backtest to *inspect* prior output, they'd lose it. Engineer's call: default `true` for safety in CI/dev; document the override prominently.
4. **Reset endpoint auth.** None today. Engineer flags as a Gap; out of scope for M1.

## Test cases

| # | Test name | What it covers |
|---|---|---|
| T1.1 | `tradingPipeline_runs_in_order` | Mocks analysis/order/position services; asserts call order analysis → orders → positions |
| T1.2 | `tradingPipeline_skips_when_locked` | First tick `Thread.sleep`s; second tick fires concurrently; asserts second tick logs WARN and returns immediately, no service calls |
| T1.3 | `backtestReset_clears_trade_order_in_range` | Seeds 3 trade_order rows on dates A, B, C; reset for [B, C]; row A remains, B+C deleted |
| T1.4 | `backtestReset_clears_alert_state_in_range` | Same pattern, on alert_state table |
| T1.5 | `backtestReset_clears_in_memory_caches` | Populates C9/C11/C12 with sentinel values; reset; asserts caches empty |
| T1.6 | `mapKeys_iterated_in_sorted_order` | New unit test in `AnalysisScheduler` / `Strategy1`: capture iteration sequence over an unordered input map; assert sorted |
| T1.7 | **M0's six parity tests must run and produce consistent output across two consecutive runs** | The reproducibility validation itself |

## Architect's review

**1. The `tryLock` skip — is the missed tick going to cause an issue?**
Skipping a tick means a 5-min window has no analysis/order/position work. If the prior tick was slow because of broker latency, the next tick fires after the broker is healthy — so the 5-min gap is the broker's fault, not ours. **Accept**, but add a counter so an alert can fire if skips exceed some threshold in a day.

**2. `Comparator.naturalOrder()` on String keys — what if a key is null?**
`Comparator.naturalOrder()` throws NPE on null elements. The `SharedData` maps shouldn't have null keys, but defensive coding matters in production. **Requirement:** use `Comparator.nullsLast(Comparator.naturalOrder())`.

**3. `backtest.auto-reset=true` by default — engineer says "for safety in CI/dev."**
For dev, sure. For *production live backtest endpoint that an operator hits to investigate*, the default destroys their investigation data. **Pushback:** default should be `false` in production; tests override to `true`. Engineer's framing of "CI/dev safety" is misaligned because there's no CI yet — this is dev-only safety today.

**4. Test T1.7 — "six parity tests must produce consistent output across two consecutive runs."**
This is the load-bearing test. How exactly does the test framework express "run twice, compare"? **Requirement:** a new test `parity_run_twice_identical` that uses `BacktestAnalysisService.run(date, date)` twice within the same test method, snapshots both, asserts byte-equal. If this passes, M1 is real.

**5. Removing `@Scheduled` from three schedulers — what stops a future engineer from adding it back?**
A code comment is not enforcement. **Suggestion:** ArchUnit test that scans `com.moneymaker.scheduler.*Scheduler` classes (except `TradingPipelineScheduler`, `LoginScheduler`, `TradeConfigScheduler`, `DaySummaryScheduler`) and asserts no method carries `@Scheduled`. Catches the regression at build time.

**6. Reset endpoint — what if `toDate` is in the future?**
Currently no constraint. Operator typo could wipe future-dated data (currently impossible to have, but pre-emptive). **Suggestion:** validation — `toDate` must be ≤ today; 400 otherwise.

## Engineer's response

1. **Skip counter** — agree; add `pipelineSkippedTickCounter` (AtomicLong); log INFO every 10 skips with the cumulative count; alert if >50 in a trading day (covered by M4.1).
2. **`nullsLast`** — agree; trivial change.
3. **`auto-reset` default `false`** — agree on the principle. Compromise: default `true` in `application-test.properties` (test profile) and `false` in main `application.properties`. Test profile auto-loads under `@SpringBootTest`.
4. **`parity_run_twice_identical`** — agree; this becomes T1.7's concrete form. **Failed once = M1 isn't done.**
5. **ArchUnit guard** — agree; lives next to the M7.1 SharedData lint.
6. **toDate validation** — agree; ≤ today, returns 400 with body `{"error": "toDate cannot be in the future"}`.

## Final approval — M1
**APPROVED WITH CHANGES.** Six follow-ups from architect's review all accepted. Effort unchanged at **1 day** (auth deferred; ArchUnit guard piggybacks on M7's planned ArchUnit suite, so no marginal cost here).

---

# M2 — Lock down golden outputs

## Engineer's plan
Run the M1-stabilised backtest for the seven fixture scenarios. Capture `trade_order` snapshots. Commit as expected output. Flip M0's harness from "log diffs" to "assert equal."

### Goal
After this lands, every PR runs `mvn verify` and catches behaviour regressions.

### In scope
- Run M0's seven tests against the stabilised system.
- Capture `target/test-output/trade_order_<scenario>.json` for each.
- Commit as `src/test/resources/fixtures/expected/`.
- Remove the M0 canary test.
- Replace logging in `BacktestParityTest` with `assertEquals` per test.

### Out of scope
- New scenarios.

### Files
- 7 new JSON files under `expected/`.
- `BacktestParityTest.java` — replace `log.warn(diff)` with `assertEquals(expected, actual)`.
- Delete `canary_must_fail` test.

## Open questions
1. **What's the format of the expected JSON?** Engineer recommends `JSON Array of objects, fields in alphabetical order, BigDecimal as plain string, datetimes as ISO-8601`. Stable across machines.
2. **How to update an expected fixture when behaviour intentionally changes?** Manual: delete the file, re-run test (which logs the new actual), inspect, commit if reviewer approves. Engineer recommends a `-Dupdate-fixtures=true` test flag that auto-writes; reviewer still scrutinises the diff in the PR.

## Test cases

This milestone **is** the test setup. No new test cases; T0.1–T0.7 from M0 are now asserted instead of logged.

## Architect's review

**1. The `-Dupdate-fixtures=true` flag is a footgun.**
A developer running the test suite with that flag enabled accidentally overwrites the golden file. **Requirement:** flag also requires `-Dconfirm-fixture-update=$today_date` to avoid drive-by overwrites. Two-key safety.

**2. Field ordering — alphabetical inside each row, but what about row ordering across the array?**
Engineer's snapshot sorts by `(entry_time, id)`. ID is database-assigned, so two CI runs on different containers could produce different IDs even for identical logic. **Requirement:** sort by `(entry_time, instrument_token, option_strike, option_type, entry_direction)` — fully deterministic from business data, not from DB-assigned IDs. Then strip `id` from the snapshot entirely (it's a meaningless DB artefact for parity).

**3. What's the assertion granularity — full-row equality or field-by-field?**
Engineer plans full-row JSON equality. If a single field diff fails, the engineer must hunt through the whole row. **Suggestion:** use AssertJ's `assertThat(actual).usingRecursiveComparison().isEqualTo(expected)` — produces precise field-level diff messages.

**4. Coverage of newly-introduced columns in later milestones.**
M4.1 adds `lot_quantity_at_entry`. The expected JSON files from M2 don't have it. When M4.1 lands, every expected JSON must be regenerated. **Suggestion:** the snapshot serialiser ignores columns absent from the expected JSON (lenient mode); the test fails if the *actual* is missing a column the *expected* has, but tolerates new columns added in actual. This way M4.1 doesn't require re-snapshotting all seven fixtures.

**Pushback on suggestion 4 from engineer (anticipated):** lenient mode hides bugs. If we add a column, we *want* the expected file to declare it.

**Architect's counter-counter:** in practice, snapshot regeneration becomes a chore; people get sloppy. Lenient mode + a separate test `expected_includes_all_known_columns_test` enforces coverage at the schema level without forcing fixture rewrites for every minor column addition.

## Engineer's response

1. **Two-key fixture update flag** — agree. Annoying for the developer, intentional.
2. **Row sort by business keys, drop `id` from snapshot** — agree. This is the right fix; the engineer's initial sort was wrong.
3. **AssertJ recursive comparison** — agree. Minor pom change.
4. **Lenient mode** — disagree initially, but on reflection accept the architect's counter. Lenient comparison + schema-level test for column coverage. Two layers, each with a clear job.

## Final approval — M2
**APPROVED WITH CHANGES.** All four architect items integrated. Effort unchanged at **0.5 day**.

---

# M3 — Force-close real broker exit

## Engineer's plan
A live trade still OPEN at 15:30 places a broker exit order. Today it only flips the DB row to CLOSED while the broker position stays open — overnight gamma risk + auto-squareoff charges. **Only money-risk item in the queue.**

### Goal
Live force-close at 15:20 (configurable) places opposite-side market order; failure raises `[ALERT]`; backtest behaviour unchanged.

### In scope
- New `OrderPlacementService.placeExit(TradeOrder)` interface method.
- Implementations in each broker package + the backtest no-op stub.
- `OrderService.forceCloseOpenPositions` — calls `placeExit` *before* flipping the row to CLOSED.
- Failure path: row stays OPEN with `fill_status=EXIT_FAILED`; new `NotificationService.alertOrderExitFailed`.
- `DaySummaryScheduler` reports `exit-failed: N`.

### Out of scope
- Partial fills (separate problem).
- Limit-then-market variants (engineer recommends market-at-15:25; see open question).
- Multi-broker force-close: each broker's `OrderPlacementService` implements independently.

### Files
- `order/service/OrderPlacementService.java` — add `placeExit` to interface.
- `broker/zerodha/ZerodhaOrderPlacement.java` — implement.
- `broker/groww/GrowwOrderPlacement.java` — implement.
- `broker/angelone/AngelOneOrderPlacement.java` — implement.
- `backtesting/BacktestingOrderPlacement.java` — implement as `return FILL_BACKTEST` (no-op, matches current behaviour).
- `order/service/OrderService.java` — modify `forceCloseOpenPositions`.
- `telegram/NotificationService.java` — `alertOrderExitFailed`.
- `scheduler/DaySummaryScheduler.java` — include `exit-failed` count.

## Open questions — **BLOCKING M3 START**
1. **Order type at force-close.** Three variants:
   - **(a) Market at 15:25** — 5-min buffer, accept slippage. Engineer + architect recommend.
   - **(b) Limit at 15:25, fallback market at 15:29** — "right thing," doubles code.
   - **(c) Keep DB-only, alert loudly** — cheapest, doesn't actually fix the risk.

   **Engineer recommends (a). Architect agrees. Needs user sign-off.**

2. **Time-of-day for force-close** — currently `marketHours.marketCloseToday()` returns 15:30. Engineer's recommendation (a) wants 15:25. New property `app.market.force-close-time=15:25`?
3. **What if the position is already partially closed?** Engineer says: the row is CLOSED, no force-close attempted. Today's logic already handles this.

## Test cases

| # | Test name | What it covers |
|---|---|---|
| T3.1 | `forceClose_places_opposite_market_order` | Open SELL trade; trigger force-close; verify `placement.placeExit` called with `direction=BUY`, market order type, correct option token |
| T3.2 | `forceClose_failure_keeps_row_open` | Open trade; mock placement throws; verify row remains `OPEN`, `fill_status=EXIT_FAILED`, alert fired |
| T3.3 | `forceClose_skips_already_closed` | Row with `status=CLOSED` in batch; verify no placement call for it |
| T3.4 | `backtest_forceClose_unchanged` | Run M0 fixture T0.3 (force-close scenario) — parity test green; no behaviour change |
| T3.5 | `daySummary_reports_exit_failed_count` | Mock 2 OPEN trades; mock placement throws on 1; verify summary text contains `exit-failed: 1` |
| T3.6 | `forceClose_uses_configured_time` | Property `app.market.force-close-time=15:25`; verify `OrderService.forceCloseOpenPositions` called with `closeAt=15:25` |

## Architect's review

**1. Backtest no-op stub — engineer says `return FILL_BACKTEST`.**
What does the existing backtest behaviour expect? Today `OrderService.forceCloseOpenPositions` does **everything** locally (sets exit price, profit, status, exit_reason) without calling placement. If we now add a `placeExit` call before flipping the row, backtest's `placeExit` no-op must still return successfully so the rest of the flow runs. **Verify:** the backtest stub returns a valid `FillSnapshot`-like object so the calling code doesn't NPE. Engineer to confirm signature.

**2. `placeExit` interface signature.**
Engineer wrote `placeExit(TradeOrder)`. What does it *return*? Likely `FillSnapshot` mirroring `place()`. Engineer must spec the return type. If null/empty means "failed", contract is brittle. **Requirement:** return `Optional<FillSnapshot>`; empty = exit failed; present with `fillStatus` = result. Caller handles each case explicitly.

**3. The 5-min buffer (15:25 vs 15:30) — does this break the existing `PositionScheduler`?**
Currently `PositionScheduler` fires through 15:30 (it's gated by `marketHours.isOpenNow()` which includes 15:30 boundary inclusive). If force-close runs at 15:25, the next two PositionScheduler ticks (15:25, 15:30) see CLOSED rows and skip them. Behaviour-wise fine. But: any tick between 15:20 and 15:25 still monitors OPEN positions normally. **Confirm with engineer:** is this the intent? **Engineer:** yes, intentional — we monitor as long as possible, exit just before close to avoid 15:30 cliff.

**4. What about the 15:31 `DaySummaryScheduler` — does its own force-close run again?**
After M3, force-close happens at 15:25 (live) or 15:20 (backtest, current code). `DaySummaryScheduler` at 15:31 also calls `forceCloseOpenPositions(today, 15:30)`. After M3 lands, this should be a no-op (everything's already CLOSED) — but if a row failed to exit at 15:25 (`fill_status=EXIT_FAILED, status=OPEN`), the 15:31 call would try **again**. Is that desired? **Pushback from architect:** probably yes (give it a second shot), but the engineer must explicitly design this and document it. Don't ship the implicit retry.

**5. `EXIT_FAILED` fill_status — new enum value?**
Current values: `PENDING, COMPLETE, REJECTED, CANCELLED, BACKTEST`. Adding `EXIT_FAILED` is fine, but the M0 fixtures need to handle this column not having that value. **Action:** snapshot serialiser already handles unknown enum strings; no fixture impact.

**6. Money risk — what's the rollback plan if M3 causes a *worse* problem than the silent overnight exposure?**
Engineer's rollback section says "revert." That's correct, but: if a broker order succeeds and then the rest of `forceCloseOpenPositions` throws (e.g. DB write fails), the broker position is closed but the row stays OPEN — *inverted* exposure. **Requirement:** transaction discipline. The order is: (1) call `placeExit`, (2) if success, update row to CLOSED with the broker fill; (3) if failure, update row to `EXIT_FAILED`. Wrap in try/catch; *never* leave the DB row OPEN if the broker order succeeded.

## Engineer's response

1. **Backtest stub return** — agree; signature aligned with point 2. Returns `Optional.of(new FillSnapshot(BACKTEST, ...))` with synthetic exit price (last cached candle close) so caller logic is identical.
2. **`Optional<FillSnapshot>` return** — agree; clean contract.
3. **5-min buffer intent** — confirmed; document in code comment.
4. **Retry at 15:31** — agree; explicit design. After 15:25 force-close, the 15:31 DaySummaryScheduler force-close acts only on rows where `status=OPEN` (i.e. exit failed at 15:25). Second attempt; if still fails, alert raised with `RETRY_FAILED` flag. Document.
5. **`EXIT_FAILED` enum** — accept; document in `ORDERS_AND_POSITIONS.md` columns table when M3 ships.
6. **Transaction discipline** — agree; this was implicit in my plan but worth making explicit. Pseudocode:
   ```
   FillSnapshot fill;
   try { fill = placement.placeExit(order); }
   catch (Exception e) { markExitFailed(order, e); alert; return; }
   try {
       order.setExitPrice(fill.price); order.setStatus(CLOSED); ... ; repo.save();
   } catch (Exception e) {
       // Broker order succeeded but DB write failed — this is rare but
       // financially safer than leaving OPEN. Mark a recovery row and alert
       // CRITICAL so ops manually reconciles.
       alertCritical(order, "broker exited but DB write failed", e);
   }
   ```

## Final approval — M3
**BLOCKED ON DECISION.** Six architect items addressed. Awaiting user sign-off on **force-close order-type variant** (engineer + architect recommend (a) market at 15:25) and the **new `app.market.force-close-time=15:25` property**. Effort: **2 days** unchanged.

---

# M4 — Live trading polish

Five sub-items. Each shipped as its own commit; bundled milestone for tracking.

## M4.1 — Rupee P&L on day-summary

### Engineer's plan
Snapshot `lot_quantity` onto `trade_order` at entry. Day-summary multiplies per-share P&L by lot count for rupee figure.

### Files
- Liquibase `021_add_lot_quantity_at_entry.xml` — column `INT NOT NULL DEFAULT 0`.
- `TradeOrder.java` — `lotQuantityAtEntry`.
- `OrderService.openOrder` — snapshot from `tradeConfig.lotQuantity`.
- `DaySummaryScheduler.buildSummary` — `rupeePnl = pnl × lotQuantityAtEntry`.

### Test cases
| # | Test | Coverage |
|---|---|---|
| T4.1.1 | `openOrder_snapshots_lot_quantity` | New row's `lot_quantity_at_entry` equals config's `lotQuantity` at open time |
| T4.1.2 | `daySummary_includes_rupee_pnl` | Mock 2 trades, 50-lot each, profit ₹10/share; summary contains `P/L (rupees): 1000.00` |

### Open questions
1. **What if `tradeConfig.lotQuantity` is null at open?** Default `0` makes rupee P&L `0`. Engineer recommends: validate non-null at config save; backstop with `coalesce(lotQuantity, 1)` at order open with a WARN log.

### Architect's review

**1. Schema default `INT NOT NULL DEFAULT 0` — historical rows.**
All existing `trade_order` rows get `lot_quantity_at_entry = 0`. Day-summary on a historical date would report `₹0`. Misleading. **Requirement:** backfill in the same Liquibase changeset — `UPDATE trade_order SET lot_quantity_at_entry = (SELECT lot_quantity FROM trade_config WHERE id = trade_order.trade_config_id) WHERE lot_quantity_at_entry = 0;`. Acceptable to skip for backtest-only test data.

**2. Coalesce backstop on null — disagree with engineer's suggestion.**
A null `lotQuantity` is a misconfigured config. Silently using 1 hides the bug. **Requirement:** if null at order open, the order is NOT opened; signal logged as `SKIP: lotQuantity unset`; alert raised. Loud failure beats silent default.

### Engineer's response
1. **Backfill in migration** — agree.
2. **Loud failure on null** — agree on principle. Override engineer's initial coalesce-with-WARN suggestion.

### Final approval — M4.1
**APPROVED WITH CHANGES.** Effort: **4 hours**.

---

## M4.2 — Clone yesterday's configs

### Engineer's plan
`POST /api/trade-configs/clone?fromDate=&toDate=` clones every active config from `fromDate` to `toDate`, including SMA timeframes. UI gets a "Clone yesterday" button.

### Files
- `TradeConfigAdminService.cloneFromDate(LocalDate from, LocalDate to)`.
- Controller endpoint.
- UI button + handler in `trade-configs.html`.

### Test cases
| # | Test | Coverage |
|---|---|---|
| T4.2.1 | `clone_copies_all_fields_and_timeframes` | Source has 2 configs with 3 timeframes each; clone target has 2 configs with 3 timeframes each, all fields match except id and tradingDate |
| T4.2.2 | `clone_is_idempotent` | Same `from→to` cloned twice; second call adds another batch (intentional — engineer's design) OR no-ops (architect's preference, see review) |

### Open questions
1. **Idempotency.** Engineer designed it to add a new batch each call. Architect will likely push for skip-if-exists.

### Architect's review

**1. T4.2.2 — idempotency behaviour.**
Engineer says "second call adds another batch." Result: cloning twice yields *duplicate configs* on the target date. UI doesn't distinguish them. Operator gets confused, deletes one, can't tell which. **Pushback:** skip clones where a config with identical `(instrumentId, strategyId, tradingSide, transactionType, tradingDate)` already exists. The dedupe key is loose enough to allow intentional duplicates (just edit one field) but blocks the accident.

**2. Cloning inactive configs?**
M4.3 adds `is_active`. If a config is `is_active=false` on the source date, do we clone it? Engineer didn't address. **Requirement:** clone only active configs; document.

### Engineer's response
1. **Dedupe on the loose key** — agree.
2. **Active-only clone** — agree; depends on M4.3 landing first or coordinating order.

### Final approval — M4.2
**APPROVED WITH CHANGES.** Effort: **4 hours**. Sequencing: M4.3 must precede M4.2 (or land together).

---

## M4.3 — Soft-delete via `is_active`

### Engineer's plan
New column `is_active BOOLEAN NOT NULL DEFAULT TRUE` on `trade_config`. Repository methods filter by it. UI gets a per-row toggle.

### Files
- Liquibase `022_add_is_active_to_trade_config.xml`.
- `TradeConfig.java` — `isActive` field.
- `TradeConfigRepository` — `findByTradingDateAndIsActiveTrue`.
- `TradeConfigAdminService` — toggle method.
- UI — toggle button per row.

### Test cases
| # | Test | Coverage |
|---|---|---|
| T4.3.1 | `inactive_config_not_included_in_pipeline` | Config has `is_active=false`; live tick runs; no signals generated for this config |
| T4.3.2 | `toggling_off_doesnt_close_open_trades` | Config has OPEN trade; toggle to inactive; trade stays OPEN until SL/target/force-close |
| T4.3.3 | `toggling_back_on_resumes_signals_next_tick` | After toggle on, next analysis tick generates signals normally |

### Open questions
None substantial.

### Architect's review

**1. T4.3.2 is critical.**
Soft-delete must NOT close open positions. The pipeline reads configs from `SharedData.combinedDto` which is refreshed on UI write (existing behaviour from prior PR). If `combinedDto` is rebuilt without inactive configs, would `PositionScheduler.processPositions` still walk the OPEN row? Yes — PositionScheduler iterates `findByStatus(OPEN)` from `trade_order`, not from configs. **Verified safe.** But the test must explicitly cover this.

**2. UI confirmation on toggle off?**
Engineer didn't specify. **Requirement:** confirm dialog "Toggle off? Trades already opened will continue to be monitored." — explicit user education.

### Engineer's response
1. T4.3.2 already in test list.
2. **Confirm dialog** — agree.

### Final approval — M4.3
**APPROVED WITH CHANGES.** Effort: **4 hours**.

---

## M4.4 — Open-trade warning banner

### Engineer's plan
When editing a config with OPEN trades on today's date, UI shows a yellow banner: "This config has N open trade(s). Changes to entry rules take effect immediately; existing exits use snapshot values from order entry."

### Files
- `TradeConfigAdminController` — view DTO carries `hasOpenTrades` flag.
- `trade-configs.html` — banner template.

### Test cases
| # | Test | Coverage |
|---|---|---|
| T4.4.1 | `view_dto_includes_hasOpenTrades` | Config with 1 OPEN trade returns `hasOpenTrades=true` in JSON |
| T4.4.2 | `view_dto_no_open_trades_returns_false` | Config with only CLOSED trades returns `false` |

### Open questions
None.

### Architect's review

**1. Banner shows only on today's open trades, or any historical OPEN?**
A row could be OPEN from yesterday (force-close failed). Engineer's wording says "today's date" — but a forgotten OPEN from yesterday is exactly the case that *most* needs the warning. **Requirement:** banner shows for any `status=OPEN` row regardless of date, with separate counts for today vs. carryover.

### Engineer's response
1. **Date-agnostic count** — agree. Banner text: "N open trade(s) (M from today, N-M carryover)."

### Final approval — M4.4
**APPROVED WITH CHANGES.** Effort: **2 hours**.

---

## M4.5 — `strategyId` rename (3-step migration)

### Engineer's plan (revised after architect's pushback from prior review)
Three deploys, each independently reversible:
1. **Add** `strategy_id` column, dual-write from JPA. Reads prefer new col, fall back to old.
2. **Backfill** `strategy_id` from `stratergy_id`; verify counts equal.
3. **Drop** `stratergy_id`; entity uses only `strategy_id`.

### Files (per step)
- Step 1: Liquibase `023_add_strategy_id_column.xml`; `TradeConfig.java` has both fields, dual-write.
- Step 2: Liquibase `024_backfill_strategy_id.xml`.
- Step 3: Liquibase `025_drop_stratergy_id.xml`; `TradeConfig.java` removes old field.

### Test cases
| # | Test | Coverage |
|---|---|---|
| T4.5.1 | `dual_write_both_columns_after_step1` | New config saved; both columns populated identically |
| T4.5.2 | `backfill_populates_all_rows` | Run step 2 against table with historical rows; all `strategy_id` populated |
| T4.5.3 | `parity_green_after_each_step` | M0's seven fixtures pass after step 1, after step 2, after step 3 |

### Open questions
1. **Hold-time between deploys.** Engineer says "deploy each step, observe for a day, then next." Architect needs to validate hold time.

### Architect's review

**1. Hold time — 1 day per step is fine for single-process deploy.**
Three calendar days minimum for the rename to complete. Engineer assumed this is fast; it's not. Worth flagging in `IMPLEMENTATION_PLAN.md` that M4.5 takes 3 calendar days even though active engineering work is ~half a day total.

**2. What if step 2 (backfill) fails mid-way?**
SQL transaction; rolls back. But: partial commit in Liquibase changeset = inconsistent state. **Requirement:** the backfill changeset is wrapped in a single transaction with `<rollback>` defined.

**3. Step 1's dual-write — what if an external tool writes directly to the DB and only sets the old column?**
None today (only JPA writes). Document the assumption; if external writers appear, this migration plan breaks.

### Engineer's response
1. **3 calendar days** — agree; flag in plan.
2. **Transaction + rollback** — agree.
3. **Document assumption** — agree.

### Final approval — M4.5
**APPROVED WITH CHANGES.** Effort: **0.5 day active work, 3 calendar days total**.

---

## M4 combined approval
**APPROVED.** Total effort: 1.25 days active + 3-day rename hold = ~4 calendar days.

---

# M5 — Operational hardening

Five small ops items. Each shippable independently. Reviewed in aggregate by the architect because none are architecturally significant.

## M5.1 — Two-key day-summary guard *(GAPS #5)*
- **Engineer:** Two `DailyEventGuard` keys: `day-summary-forceclose`, `day-summary-telegram`. Each marked independently.
- **Test:** T5.1.1 — fail Telegram send; verify next-cron-tick re-attempts only telegram, not force-close.
- **Architect:** Approved. **APPROVED.**

## M5.2 — Manual day-summary re-trigger *(GAPS #6)*
- **Engineer:** `POST /api/admin/day-summary?date=&force=true`. Bypasses guard when force=true.
- **Test:** T5.2.1 — re-trigger after guard set; verify summary fires again.
- **Architect:** Same auth concern as M1's reset endpoint — track separately. **APPROVED.**

## M5.3 — Heartbeat windowing *(GAPS #3)*
- **Engineer:** `MarketHoursService.isWithinHeartbeatWindow()` (07:50–15:40 default); `LoginScheduler.heartbeat` early-returns outside it.
- **Test:** T5.3.1 — mock clock outside window; verify no broker calls. T5.3.2 — inside window; verify normal behaviour.
- **Architect:** What about pre-close at 15:30–15:40? Heartbeat checks token health; if token dies at 15:35 we want to know before tomorrow's 08:00 login. **Accept the 15:40 boundary**, document why. **APPROVED.**

## M5.4 — Delete `dailyTaskAt912AM` stub *(GAPS #11)*
- **Engineer:** Delete method, that's it.
- **Test:** No test (deletion).
- **Architect:** Confirm no callers via grep. **APPROVED.**

## M5.5 — Daily 08:00 live-cache reset *(SEQ #6)*
- **Engineer:** New `LiveCacheJanitor` bean, `@Scheduled(cron = "0 0 8 * * MON-FRI")`, clears `SharedData.optionTokenMap`, `strikesByInstrumentAndInterval`, `NotificationService.dedupeState/throttleState`. Live-only (`app.mode` check).
- **Test:** T5.5.1 — populate maps; trigger cleaner; assert empty.
- **Architect:** **Why 08:00 and not at app start AND 08:00?** App restarts after 08:00 miss the reset. **Requirement:** add `@EventListener(ApplicationReadyEvent.class)` that also runs the cleaner. Mirrors `TradeConfigScheduler.seedConfigsOnStartup` pattern. **APPROVED WITH CHANGE.**

## M5 combined approval
**APPROVED.** Total effort: **1 day**.

---

# M6 — `IndicatorComputeService` introduction

## Engineer's plan
Single compute path for all indicators. Strategies route through it. **SMA columns still written** for parity during a 1-quarter soak. Drop scheduled for M11.

### Goal
1. Remove every indicator-compute call from outside `IndicatorComputeService`.
2. Implement rolling-sum SMA (mathematically identical to current ta4j path).
3. Per-tick cache keyed by `(candle-list-fingerprint, indicator, params)`.

### Files
- **New** `indicator/IndicatorComputeService.java`.
- **New** `indicator/IndicatorRegistry.java` (Spring `Map<String, Indicator>` injection).
- **New** `indicator/IndicatorCacheKey.java`.
- `indicator/SMAIndicatorImpl.java` — rolling-sum rewrite; still writes columns.
- `indicator/IndicatorService.java` — deprecated, retained for legacy callers, logs WARN on call.
- `Strategy1.java`, `Strategy2.java` — route reads through new service.

## Open questions
1. **Cache key composition.** Engineer's first attempt: `(firstTimestamp, lastTimestamp, size, indicatorName, paramsHash)`. Architect's prior pushback was correct (see review item 1).
2. **Cache scope: per-tick or per-day or per-run?** Engineer: per-tick. Same candle list re-queried across timeframes in the same tick.
3. **What happens to `IndicatorService.calculate(...)` static method?** Engineer: deprecated but functional; logs WARN; removed in M11.

## Test cases

| # | Test | Coverage |
|---|---|---|
| T6.1 | `rollingSum_SMA_equals_from_scratch_SMA` | For periods 5, 20, 50, 100, 200: random candle list of size 500; rolling-sum result equals from-scratch result (BigDecimal scale-equal) |
| T6.2 | `cache_hit_avoids_recompute` | Mock `Indicator.calculate`; same key called twice; verify second call returns from cache without invoking calculate again |
| T6.3 | `cache_miss_on_changed_candle_content` | Two candle lists with identical timestamps but different OHLC; verify cache treats them as separate keys |
| T6.4 | `cache_key_stable_across_runs` | Construct identical inputs in two separate JVM runs; cache keys equal |
| T6.5 | `parity_test_green` | M0's seven fixtures still pass byte-identically |
| T6.6 | `deprecated_indicatorService_logs_warn` | Call `IndicatorService.calculate(...)`; log captured contains WARN |

## Architect's review

**1. T6.3 — content fingerprint in the cache key.**
Engineer's original key was `(firstTimestamp, lastTimestamp, size, indicatorName, paramsHash)`. The architect's prior pushback: if broker emits corrected candles for a past timestamp, the key matches but cached value is stale. Engineer agreed to add **first candle's close** to the fingerprint. Confirmed in T6.3.

**Architect re-pushback:** "first candle's close" is *one* point. What if the broker correction is on the second candle? Still a cache hit, still stale. **Requirement:** fingerprint should be a hash over all close values. `Arrays.hashCode(closes)` over 1500 candles is ~microseconds; we're not optimising compute time. **Engineer:** acceptable.

**2. T6.1 — `BigDecimal` scale-equal across implementations.**
Rolling-sum SMA and ta4j SMA can produce equal *values* with different *scales*. `12.50` vs `12.500`. `BigDecimal.equals` distinguishes; `BigDecimal.compareTo` does not. Engineer's test uses `equals`. **Pushback:** strategy code uses `BigDecimal` comparisons; if scale differs, downstream comparisons might shift. **Requirement:** rolling-sum impl explicitly sets scale to 4 (same as `MarketData.close.scale`); test asserts `equals` (not `compareTo`).

**3. Per-tick cache scope — when is "tick" defined?**
Engineer's plan says "per-tick." A tick is the `AnalysisScheduler.analyzeMarketData()` invocation. In backtest, it's `runForDateTime(t)`. **Concrete need:** the cache lives as a field on a per-call instance, not a singleton. Or it's a `ThreadLocal`. Or it's cleared at the start of each tick. **Requirement:** engineer picks one mechanism explicitly. Recommend: cache is a method-local `Map` passed down through method args, not stored on the service. Avoids the "did we clear it?" question entirely.

**Engineer pushback:** passing the cache through args couples the API to caching as an implementation detail. Cleaner: cache is a field on `IndicatorComputeService`; clear method called at tick entry by `AnalysisScheduler`.

**Architect counter:** that brings us back to "did we remember to clear it?" — the exact bug class we're fighting in M0/M1. **Resolution:** introduce a `try (var tick = computeService.startTick()) { ... }` AutoCloseable. The tick's cache is scoped to the try block. Compiler enforces close.

**4. Deprecation WARN log — frequency?**
T6.6 verifies one call logs WARN. What if it's called 1500 times per tick? Log spam. **Requirement:** `@Deprecated` annotation + first-call-per-JVM WARN, subsequent calls TRACE. Standard pattern.

**5. Rollback story.**
Engineer's section: "revert; strategies re-call `IndicatorService` directly." But strategies' code has changed shape. Revert is per-PR; clean if M6 is one PR. **Requirement:** M6 ships as **one PR**, not split into "introduce service" + "migrate strategies" because partial migration means both paths active = double work.

### Engineer's response
1. **Hash-over-all-closes** — agree; trivial cost.
2. **Scale-4** — agree; explicit `setScale(4, RoundingMode.HALF_UP)`.
3. **AutoCloseable tick scope** — agree; cleaner than my "field on service" proposal.
4. **Once-per-JVM WARN** — agree; standard pattern, `AtomicBoolean` gate.
5. **Single PR** — agree.

## Final approval — M6
**APPROVED WITH CHANGES.** Five items addressed. Effort revised: **4 days** unchanged (AutoCloseable tick is trivial; hash-over-closes is trivial; the bulk is migration + verification).

---

# M7 — `SharedData` lint + `indicator_binding`

## Engineer's plan

### M7.1 — ArchUnit lint
Test: classes in `com.moneymaker.*` outside an allowlist must not reference `SharedData`. Build fails on new references.

### M7.2 — `indicator_binding` replaces `sma_timeframe`
Schema: `indicator_binding(id, tc_id, indicator_name, params_json, slope)`. Data migration: each `sma_timeframe` row → `indicator_name='SMA'`, `params_json='{"period":N,"timePeriod":M}'`. `sma_timeframe` retained as a SQL view over `indicator_binding` for one release cycle (architect's prior pushback).

### Files
- **New test** `src/test/java/com/moneymaker/architecture/SharedDataAccessTest.java`.
- Liquibase `026_create_indicator_binding.xml`.
- Liquibase `027_migrate_sma_timeframe_to_binding.xml`.
- Liquibase `028_replace_sma_timeframe_with_view.xml`.
- **New entity** `IndicatorBinding.java`.
- **New repo** `IndicatorBindingRepository.java`.
- `TradeConfigAdminService` migrated.
- UI updated.

## Open questions
1. **`params_json` format — what's the schema?** Engineer recommends a JSON object with indicator-specific shape. E.g. SMA `{"period": 20, "timePeriod": 5}`, MACD `{"fast": 12, "slow": 26, "signal": 9}`. Each `Indicator` impl validates its own params.
2. **The allowlist for ArchUnit lint — who maintains it?** Engineer recommends: the allowlist is the current set of files that read `SharedData`; new files cannot be added; existing files get cleared by M13 (`RunSession` refactor).

## Test cases

| # | Test | Coverage |
|---|---|---|
| T7.1.1 | `archunit_blocks_new_SharedData_reference` | Add a new test-fixture class in `com.moneymaker.test_fixtures` referencing `SharedData`; build fails |
| T7.1.2 | `archunit_allows_existing_references` | Current callers (AnalysisScheduler, Strategy1, etc.) remain allowed |
| T7.2.1 | `migration_preserves_all_sma_rows` | Pre-migration row count of `sma_timeframe` equals post-migration count of `indicator_binding` with `name='SMA'` |
| T7.2.2 | `view_returns_same_rows_as_table` | Query `SELECT * FROM sma_timeframe` after migration; rows equal pre-migration `sma_timeframe` query |
| T7.2.3 | `parity_test_green` | M0's seven fixtures green after migration |
| T7.2.4 | `new_EMA_binding_works_end_to_end` | Add EMA binding via API; analysis tick computes EMA via `IndicatorComputeService`; signal generated |

## Architect's review

**1. T7.1.1 — what does ArchUnit actually check?**
Engineer's test adds a deliberately-bad file in tests. But ArchUnit runs on `src/main/java` only by default. **Clarification:** ArchUnit can scan any classpath; the test class must explicitly include `test_fixtures` or whatever package. Engineer must pin the package configuration.

Actually — wait. The lint should prevent **production code** from adding `SharedData` references, not test code. **Refinement:** the test scans `com.moneymaker..` (production); fails if any class **outside the allowlist** has an import of `SharedData`. T7.1.1's "deliberately bad" file must therefore be in production code, which means the test temporarily adds and removes it. Easier: instead of a deliberately-failing file test, the assertion is "the current set of `SharedData` references equals the allowlist." Anything new fails the test. Engineer can verify with a TDD-style temporary edit.

**Conclusion:** T7.1.1 reframed as "allowlist matches current state."

**2. `params_json` schema validation — who's responsible?**
Engineer says "each `Indicator` impl validates its own params." Where exactly? On read? On write? **Requirement:** `Indicator.parseParams(String json)` throws on invalid; `TradeConfigAdminService.save` calls it for every binding before persistence. UI errors surface clearly.

**3. View over the migrated table — performance?**
`sma_timeframe` becomes `SELECT id, time_period, sma, tc_id, slope FROM indicator_binding WHERE indicator_name='SMA' …` with JSON path queries for time_period and sma. **Performance:** JSON parsing per row in MySQL is slow. If anything queries the view in a hot path, performance regression. **Verify:** which production code reads `sma_timeframe`? Today only `SmaTimeframeRepository.findByTradeConfigId`, called by `TradeConfigScheduler.fetchTradeConfigsByDate` and the trade-config admin. Both are called once per day or per UI action, not hot. **Accept the view.**

**4. M7's two PRs — separate or together?**
Engineer doesn't say. **Suggestion:** ArchUnit lint (M7.1) ships first as a no-op (passes immediately). Then M7.2's migration can violate it if needed (allowlist updated in same PR). Splitting reduces risk; ArchUnit alone has no migration risk.

**5. `IndicatorBinding.slope` — what is this field?**
Engineer carried it over from `sma_timeframe.slope`. But "slope" is an SMA-specific concept (rising vs falling). For EMA/RSI it's irrelevant. **Pushback:** move `slope` into `params_json` as part of the SMA-specific params. Don't carry a fossil column on the new schema.

### Engineer's response
1. **Allowlist-matches-current-state** — agree; cleaner test design.
2. **`parseParams` on `TradeConfigAdminService.save`** — agree.
3. **View performance accepted** — agree; document the assumption.
4. **Split M7.1 and M7.2 PRs** — agree.
5. **`slope` into `params_json`** — agree. SMA params: `{"timePeriod": M, "smaPeriod": N, "slope": X}`.

## Final approval — M7
**APPROVED WITH CHANGES.** Five items addressed. Effort unchanged at **2 days**.

---

# M8 — Disk-backed `BacktestMarketDataCache`

## Engineer's plan
Per-day JSON file caches market_data fetched by backtest. Same date twice = zero broker calls on the second run.

### Files
- `BacktestMarketDataCache.java` — `beginDay` checks disk first; populates from broker on miss; writes to disk.
- New properties: `app.backtest.cache-dir=./.bt-cache`, `app.backtest.cache-version=1`.
- `.gitignore` — exclude `.bt-cache/`.

## Open questions
1. **Cache version mismatch — re-fetch?** Engineer recommends silently delete + re-fetch.
2. **What if `cache-dir` is unwritable?** Disable disk cache, log WARN, fall back to in-memory.

## Test cases

| # | Test | Coverage |
|---|---|---|
| T8.1 | `disk_cache_miss_writes_file` | `beginDay` for fresh date; mock broker call; verify file `bt-cache/2026-04-01/NIFTY_5min.json` exists after |
| T8.2 | `disk_cache_hit_skips_broker` | First call seeds file; second call mocks broker to throw; second `beginDay` succeeds (used file) |
| T8.3 | `version_mismatch_refetches` | Seed file with `version: 0`; current version is `1`; `beginDay` deletes + re-fetches |
| T8.4 | `unwritable_dir_falls_back` | `cache-dir` set to a read-only path; backtest still works in-memory |
| T8.5 | `parity_test_green` | M0's seven fixtures pass with and without disk cache |

## Architect's review

**1. T8.3 — version mismatch.**
Engineer's behaviour: "silently delete + re-fetch." Operator can't tell whether they expected a hit or miss. **Requirement:** log INFO on version-mismatch deletion; include old version + new version. Audit trail.

**2. File format — JSON, but field naming?**
Engineer didn't specify. Two reasonable choices: (a) match `MarketData` field names; (b) compact format (e.g. arrays of `[ts, o, h, l, c]`). Compact saves disk + I/O at the cost of human-readability. **Suggestion:** compact arrays; the cache is machine-only data.

**3. Concurrent writes.**
Single-JVM use only (engineer's scope). If two backtest runs in the same JVM hit the same date in parallel (M13 day-parallel), both try to write the file. **Requirement:** atomic write — write to `*.tmp`, rename. Standard Unix-safe pattern.

**4. `.gitignore` — what if a CI agent pre-populates the cache?**
Engineer's intent: cache lives only on the dev box. CI agents need their own cache. Worth documenting that the cache directory is *intentionally local* and not shared.

**5. Cache file rotation / size limit?**
Engineer doesn't address. A backtest of 200 dates = 200 directories = ~50 MB. Not a problem. But: cache accumulates indefinitely. **Suggestion:** document that `rm -rf .bt-cache` is a normal operator action; no rotation needed.

### Engineer's response
1. **INFO log on version mismatch** — agree.
2. **Compact array format** — agree. Saves ~70% disk.
3. **Atomic write via tmp + rename** — agree; concurrent safety even within single JVM.
4. **CI agents own their cache** — agree; document.
5. **No rotation** — agree.

## Final approval — M8
**APPROVED WITH CHANGES.** Five items addressed. Effort unchanged at **2 days**.

---

# M9 — Perf Phases 2+3

## Engineer's plan
- **9.1** — Strategy1/Strategy2 skip-redundant-timeframe-run cache.
- **9.2** — Rolling-sum SMA (already done in M6; M9 just verifies the speedup).

### Files
- `Strategy1.java`, `Strategy2.java` — `Map<(tcId, interval, strike), LocalDateTime>` skip cache; cleared on day-start via `strategy.resetDayState()`.

## Open questions
1. **Live equivalence.** In live mode, the 5-min cron always sees a *new* candle for the smallest timeframe; the skip cache helps 15-min strategy. Engineer claims this is safe. Architect must verify.

## Test cases

| # | Test | Coverage |
|---|---|---|
| T9.1 | `skip_cache_avoids_redundant_run` | Mock strategy execute; same candle timestamp called twice; verify second call returns without re-evaluating rules |
| T9.2 | `day_start_resets_skip_cache` | Populate cache; call `resetDayState`; verify subsequent call re-evaluates |
| T9.3 | `parity_test_green` | M0's seven fixtures pass identically |
| T9.4 | `benchmark_regression_check` | 2-day backtest; record duration; assert within 30% of stored baseline; baseline auto-updates with `-Dupdate-benchmark=true` |

## Architect's review

**1. T9.4 — benchmark relative to baseline.**
Engineer's plan: assert within 30%. Where does the baseline live? File in `src/test/resources/benchmarks/`. **Requirement:** baseline file includes the hardware identifier (cpu model, RAM) so a baseline captured on a faster machine doesn't false-fail on a slower one. Or: the baseline IS the test machine's first run; subsequent runs compare against the machine's own baseline. **Engineer pick:** machine-local baseline; first-run captures, subsequent runs compare. Solves the "where do we store baselines for multiple machines" problem.

**2. Live mode skip cache — what if config changes mid-day?**
Engineer assumed candle timestamp is the only invariant. But: if the user toggles a config mid-day (M4.3), the skip cache holds stale state. **Requirement:** invalidate the per-config entries in the skip cache when `TradeConfigAdminService` writes affect today's configs. Hook into the existing `invalidateConfigsCache()` call.

**3. T9.2 — what calls `resetDayState`?**
Engineer says `BacktestAnalysisService.beginDay`. In live, no equivalent — the JVM doesn't have a "day start" event today. **Requirement:** `LiveCacheJanitor` from M5.5 also calls `strategy.resetDayState()` at 08:00 + on ApplicationReadyEvent. Bundles cleanly.

### Engineer's response
1. **Machine-local benchmark baseline** — agree; baseline lives at `.bt-baselines/<hostname>.json`, gitignored.
2. **Config-change invalidation** — agree; hook into `TradeConfigAdminService`.
3. **`resetDayState` via `LiveCacheJanitor`** — agree.

## Final approval — M9
**APPROVED WITH CHANGES.** Three items addressed. Effort unchanged at **2 days**.

---

# M10 — Pre-resolve strikes per day — **ABANDONED 2026-08-31**

> **This milestone was approved on a false premise and is closed without code.**
> The engineer's answer below — *"uses the *first* candle of the day to anchor
> ATM ... **Confirmed stable**"* — is not what the code does.
> `AnalysisScheduler.calculateStrikesForCandles` anchors on
> `marketDataList.get(marketDataList.size() - 1)`, the **latest** candle, so the
> ATM base tracks spot through the session and the strike set shifts with it.
> The architect asked exactly the right question and got a wrong answer; nobody
> opened the file. Closed as `GAPS.md` #16 option (c): strike compute is
> intentionally per-tick. Kept here unedited below as a record of how the premise
> got through review.


## Engineer's plan
`AnalysisScheduler.calculateStrikesForCandles` runs per-tick today. Within a day the active strike set is stable. Cache by `(date, tradeConfigId)` for the day's duration.

### Files
- `AnalysisScheduler.java` — extract strike compute into `Map<LocalDate, Map<Integer, List<List<Integer>>>>`; cleared in `BacktestAnalysisService.beginDay`.

## Test cases

| # | Test | Coverage |
|---|---|---|
| T10.1 | `strikes_computed_once_per_day` | Mock `calculateStrikesForCandles`; 72 ticks of a backtest day; verify called exactly once per config |
| T10.2 | `parity_test_green` | M0's seven fixtures pass |
| T10.3 | `live_strike_cache_invalidated_on_day_start` | Populate cache for date X; advance day to X+1; verify cache empty for X+1 |

## Architect's review

**1. Within-day stability — is the strike set REALLY stable within a day?**
The strike set is computed from spot. Spot can swing ±2% intraday on NIFTY. If the spot moves 200 points, the ITM/ATM/OTM strike set shifts. **Pushback:** engineer's premise may be wrong. Verify before optimising.

**Engineer:** Let me check. `calculateStrikesForCandles` uses the *first* candle of the day to anchor ATM, then ±n*strikePoints for ITM/OTM. So once computed, it doesn't shift even if spot moves. **Confirmed stable.** Documenting in code.

**2. Cache invalidation across midnight?**
Engineer says "cleared in BacktestAnalysisService.beginDay." Live has no equivalent — but the cache is keyed by date, so a new day naturally gets a fresh entry. The old day's entry leaks. **Requirement:** evict entries older than 2 days, on every cache access. Trivial.

### Engineer's response
1. **Verified stable** — agree; add code comment + link to this conversation.
2. **2-day eviction** — agree.

## Final approval — M10
**APPROVED WITH CHANGES.** Effort unchanged at **0.5 day**.

---

# M11 — Drop SMA columns *(deferred, quarter-soak)*

## Engineer's plan
After 3 months of M6 running in production with no consumer reading `sma_value*` columns, drop them. Same migration drops the `sma_timeframe` view from M7.

### Files
- Liquibase `029_drop_sma_value_columns.xml`.
- Liquibase `030_drop_sma_timeframe_view.xml`.
- `MarketData.java` — remove fields.
- `SMAIndicatorImpl` — remove the write side.

## Pre-conditions
- 90 days of M6 in production.
- SQL grep + IDE-wide grep show zero `getSmaValue*()` reads outside `IndicatorComputeService`.
- Parity test green throughout the soak period.

## Test cases

| # | Test | Coverage |
|---|---|---|
| T11.1 | `parity_test_green_after_drop` | M0 fixtures pass |
| T11.2 | `sma_timeframe_view_gone` | `SELECT * FROM sma_timeframe` returns "table doesn't exist" |

## Architect's review

**1. The 90-day soak — who verifies?**
Engineer says "SQL grep + IDE-wide grep." That's a one-time check. What about a tool added in month 2 that introduces a new read? **Requirement:** add an ArchUnit test in M6 that fails the build if any class outside `IndicatorComputeService` references `MarketData.getSmaValue*()`. Solves the "did someone add a new caller" question.

**2. Rollback after drop?**
Dropping a column loses the data. If the soak missed a caller and we discover post-drop, rollback is incomplete. **Acceptable risk** given the soak + ArchUnit + repeated parity tests. Document.

### Engineer's response
1. **ArchUnit guard added in M6** — agree; M6's task list updated.
2. **Acceptable risk** — agree; documented in this milestone.

## Final approval — M11
**APPROVED.** Effort: **0.5 day**, deferred until pre-conditions met.

---

# M12 — Full live-writes-candles *(deferred to demand)*

## Engineer's plan
- Liquibase `031_add_interval_to_market_data.xml` + UNIQUE constraint.
- Async write from `AnalysisScheduler` via `MarketDataPersistenceService`.
- `MarketDataLocalProvider` registered in `app.mode=backtest`.
- Nightly `MarketDataGapDetector` (16:00).

## Trigger to start
"Someone asks for a 90+ day backtest" OR "team commits to multi-month parameter sweeps." Not before.

## Test cases
*Deferred. Full test plan written when milestone is activated.*

## Architect's review
*Not yet conducted — milestone is deferred. Review happens at activation time.*

## Final approval — M12
**DEFERRED.** Effort: **1 week**, deferred to demand.

---

# M13 — `RunSession` refactor *(deferred to demand)*

## Engineer's plan
~20-30 file changes. Defined in ARCHITECTURE_REVIEW.md §6.

## Trigger to start
Day-parallel backtest becomes a real ask, OR M7's lint allowlist becomes too painful to maintain.

## Test cases
*Deferred.*

## Architect's review
*Deferred.*

## Final approval — M13
**DEFERRED.** Effort: **1-2 weeks**, deferred.

---

# M14 — Day-parallel + vectorise *(deferred)*

## Final approval — M14
**DEFERRED.** Only when 100-day sweeps become routine.

---

# Final summary table

| # | Milestone | Effort | Status | Blocking decisions |
|---|---|---|---|---|
| M0 | Test harness | 3 days | APPROVED WITH CHANGES | — |
| M1 | Reproducibility | 1 day | APPROVED WITH CHANGES | — |
| M2 | Lock golden outputs | 0.5 day | APPROVED WITH CHANGES | — |
| M3 | Force-close real exit | 2 days | **BLOCKED ON DECISION** | Order-type variant; `app.market.force-close-time` |
| M4 | Live polish (5 sub) | 4 calendar days | APPROVED WITH CHANGES | — |
| M5 | Ops hardening (5 sub) | 1 day | APPROVED WITH CHANGES | — |
| M6 | IndicatorComputeService | 4 days | APPROVED WITH CHANGES | — |
| M7 | Lint + indicator_binding | 2 days | APPROVED WITH CHANGES | — |
| M8 | Disk-backed cache | 2 days | APPROVED WITH CHANGES | — |
| M9 | Perf Phases 2+3 | 2 days | APPROVED WITH CHANGES | — |
| M10 | Pre-resolve strikes | 0.5 day | ~~APPROVED WITH CHANGES~~ **ABANDONED 2026-08-31** — premise false, see GAPS #16 | — |
| M11 | Drop SMA columns | 0.5 day | APPROVED, deferred 1Q | — |
| M12 | Live candle writes | 1 week | DEFERRED to demand | — |
| M13 | RunSession refactor | 1-2 weeks | DEFERRED to demand | — |
| M14 | Day-parallel + vectorise | open | DEFERRED | — |

**Total approved work (M0–M10): ~23 calendar days = ~5 weeks.**

**Decisions still required before M3 starts:**
1. Force-close order-type variant: (a) market at 15:25, (b) limit-then-market, (c) DB-only with alert.
2. `app.market.force-close-time` property value (engineer recommends 15:25).

Both engineer and architect recommend variant (a) + 15:25. Awaiting user sign-off.
