# End-of-Day Downtrend Detection

Auto-generates next-day `trade_config` rows when the ATM option series ends
the day in a sustained downtrend.

> **Scope today:** Backtest only. The detector is a Spring bean and its
> public entry (`EodDowntrendDetectionService.runForDay(LocalDate)`) takes
> nothing backtest-specific — a 15:25 cron can call it for live mode later
> without code changes.

---

## What it does

For each trading day in a backtest run, after force-close at 15:20:

1. Loads every enabled row from `sma_downtrend_rule`.
2. For each rule, for both CE and PE:
   - Picks the ATM strike on the underlying (round last 5-min close to the
     nearest `instrument.strike_points`). No moneyness/depth knob — ATM only.
   - For each timeframe in `{5, 15}` minutes:
     - Pulls the option-leg's intraday series once via
       [`MarketDataService`](../src/main/java/com/moneymaker/market/service/MarketDataService.java).
     - Computes `SMA(20)`, `SMA(50)`, `SMA(100)`, `SMA(200)`, `SMA(500)` on
       the series (populates the `smaValueXX` fields on every candle).
     - Trims to candles `>= rule.start_time`.
     - Runs
       [`SmaTrendCalculator`](../src/main/java/com/moneymaker/strategy/rules/SmaTrendCalculator.java#L25)
       with `rule.max_deviation`.
     - Records every SMA period whose last-candle `smaXxDownTrending` flag is `true`.
3. For each side with at least one passing `(sma, timeframe)` combo:
   - Inserts **one** `trade_config` row stamped `source='AUTO_DOWNTREND'`
     for the next trading day (skip Sat/Sun).
   - Inserts **one** `sma_timeframe` child row per passing combo.

Once any `AUTO_DOWNTREND` row exists for the next day, the whole write is
skipped on re-runs (idempotency — delete those rows by hand to force a re-write).

The generated config flows through the normal day-start path —
`TradeConfigScheduler.getConfigsForDate` picks it up on the next backtest day
the same way it picks up any human-inserted config.

---

## What lives in the rules table vs. what lives in code

The rules table is the **detection** config: which underlying to monitor,
when to start counting, how strict, and how to derive target/SL.

Everything else — the SMA grid the detector walks, the moneyness it
monitors, and the strategy-specific `trade_config` conventions — is **in
code** so that the table doesn't duplicate fields that already exist on
`trade_config`.

| Concern | Where it lives |
|---|---|
| Which SMAs are checked | `EodDowntrendDetectionService.SMA_PERIODS` (`{20, 50, 100, 200, 500}`) |
| Which timeframes are checked | `EodDowntrendDetectionService.TIMEFRAMES_MINUTES` (`{5, 15}`) |
| Which strike type | hardcoded ATM in `computeAtmStrike` |
| `transaction_type`, `max_loss`, `no_of_trades`, `no_of_parrellel_trades` for the generated config | `EodDowntrendDetectionService.strategyDefaults(strategyId)` — one switch branch per strategy |
| `lot_quantity` | `instrument.lot_qty` — the contract's lot size, not a strategy constant (`strategyDefaults` is only a fallback) |
| Detection threshold (`max_deviation`, `start_time`) | `sma_downtrend_rule` |
| Target/SL derivation (`atr_periods`, `target_multiplier`, `sl_multiplier`) | `sma_downtrend_rule` |
| Which strategy + underlying a rule applies to | `sma_downtrend_rule` |

This split satisfies CLAUDE.md #9: detection thresholds and target/SL knobs
are config-driven; the strategy conventions are *strategy identity*, not
trading-behaviour knobs, and live on the strategy.

---

## Table: `sma_downtrend_rule`

| Column                    | Notes |
|---------------------------|-------|
| `id`                      | PK    |
| `strategy_id`             | Strategy whose trade_config gets generated. The detector also uses this to pick the `strategyDefaults(...)` block. |
| `instrument_id`           | Underlying (FK to `instrument`). Drives both ATM strike selection and ATR. |
| `max_deviation`           | Max number of candles where `curr_sma >= prev_sma` before the day is no longer "downtrending". 0 = strictly monotonic. |
| `start_time`              | The deviation counter only includes candles `>= start_time`. Default `09:20:00`. |
| `atr_periods`             | N for ATR(N) of the underlying. Default 14. |
| `target_multiplier`       | `target = ATR(N) × target_multiplier` for the generated config. |
| `sl_multiplier`           | `stop_loss = ATR(N) × sl_multiplier`. |
| `enabled`                 | Toggle the rule on/off without deleting. |

### Sample row

```sql
INSERT INTO sma_downtrend_rule
  (strategy_id, instrument_id, max_deviation, start_time, atr_periods,
   target_multiplier, sl_multiplier, enabled)
VALUES
  (1, 1, 5, '09:20:00', 14, 1.0, 1.0, TRUE);
```

That single row says: *"for Strategy 1 on instrument id=1, walk the full
{20,50,100,200,500} × {5min,15min} grid against ATM CE and PE; allow up
to 5 deviations from 09:20 onwards; derive target/SL from ATR(14)."*

---

## Schema changes

Three changesets back this feature. **`sma_downtrend_rule` is created fat and
then slimmed — read 018 and 020 together to get the table's current shape.**

| Changeset | Effect |
|---|---|
| [`018_create_sma_downtrend_rule_table.xml`](../src/main/resources/db/changelog/018_create_sma_downtrend_rule_table.xml) | Creates `sma_downtrend_rule` in its original **fat** shape, including `sma`, `time_period`, `moneyness`, `depth` and five `trade_config`-duplicate columns. |
| [`019_add_source_to_trade_config.xml`](../src/main/resources/db/changelog/019_add_source_to_trade_config.xml) | Adds `trade_config.source` — `MANUAL` / `AUTO_DOWNTREND`, default `MANUAL`. |
| [`020_drop_unused_sma_downtrend_rule_columns.xml`](../src/main/resources/db/changelog/020_drop_unused_sma_downtrend_rule_columns.xml) | Drops all nine of those columns, leaving the detection-only shape documented above. |

Every existing `trade_config` row stays `MANUAL`. Auto-generated rows are
stamped `AUTO_DOWNTREND` so the detector can dedupe its own output across
re-runs.

> **If the sample INSERT below fails with `Field 'sma' doesn't have a default
> value`, changeset 020 has not been applied to your database.** Check
> `spring.liquibase.enabled` — with it set to `false`, `sma_downtrend_rule`
> keeps the fat 018 shape and the detection-only INSERT cannot satisfy the
> leftover `NOT NULL` columns.

---

## Wiring

| File | Role |
|---|---|
| [`SmaDowntrendRule`](../src/main/java/com/moneymaker/entity/SmaDowntrendRule.java) | JPA entity for the rules table. |
| [`SmaDowntrendRuleRepository`](../src/main/java/com/moneymaker/repository/SmaDowntrendRuleRepository.java) | Spring Data — exposes `findByEnabledTrue()`. |
| [`EodDowntrendDetectionService`](../src/main/java/com/moneymaker/backtesting/EodDowntrendDetectionService.java) | Orchestrator. Public entry: `runForDay(LocalDate)`. Constants `SMA_PERIODS`, `TIMEFRAMES_MINUTES`. Per-strategy defaults: `strategyDefaults(int)`. |
| [`BacktestAnalysisService`](../src/main/java/com/moneymaker/backtesting/BacktestAnalysisService.java) | Calls `runForDay(currentDate)` after force-close, inside the per-day try-block. |
| [`TradeConfigRepository`](../src/main/java/com/moneymaker/repository/TradeConfigRepository.java) | New `findByTradingDateAndSource` powers the idempotency probe. |

---

## How to extend (the deltas you'll most likely add)

| Need                                | Where to change |
|-------------------------------------|-----------------|
| New strategy with different fixed fields (e.g. `transaction_type=BUY`) | Add a `case <id>:` branch to `strategyDefaults(...)`, then insert a `sma_downtrend_rule` row with `strategy_id=<id>`. |
| New SMA period beyond 20/50/100/200/500 | Add the period to `SMA_PERIODS`, extend [`MarketData`](../src/main/java/com/moneymaker/entity/MarketData.java) with the new `smaValueXX` field, update [`SmaTrendCalculator`](../src/main/java/com/moneymaker/strategy/rules/SmaTrendCalculator.java#L25) and the `smaDownFlag(...)` switch in `EodDowntrendDetectionService`. |
| Additional timeframe (e.g. `30min`) | Add to `TIMEFRAMES_MINUTES`. That's it. |
| Different strike type (ITM/OTM at depth N) | Replace `computeAtmStrike` with a `computeStrike(rule, side)` and add the depth columns back to the rule. |
| Target/SL formula other than `ATR × mult` (fixed, daily-range, percentage of close) | Branch inside `insertAutoTradeConfig` on a new column like `target_mode`, or replace the multiplier columns with a single `target_formula` column. |
| Up-trend variant (for BUY strategies) | Add a `direction` column (`DOWN`/`UP`), branch in `scanSide` to read `smaXxUpTrending` instead. |
| Promote to live mode | Add a new `@Scheduled(cron="0 25 15 * * MON-FRI")` method on a new scheduler that calls `eodDowntrendDetectionService.runForDay(LocalDate.now())`. No service changes required. |
| Holiday-aware "next trading day" | Swap `nextTradingDay(...)` to consult a holiday table. Method is private; only caller is `runForDay`. |
| Telegram alert when a rule fires | Inject `NotificationService` into the service; call `notifier.sendIfChanged(...)` from `insertAutoTradeConfig`. |
| Reset / regenerate AUTO rows for a date | Use the **Bulk delete** panel on `/trade-configs`, or the API below. Hand-written SQL is no longer needed and misses the `sma_timeframe` children. |

---

## Verification recipe

### Prerequisites

These are easy to miss and each one silently produces "nothing happened":

1. **`spring.liquibase.enabled=true`** — otherwise 020 never applies and step 1
   below fails outright (see the warning above).
2. **`app.mode=backtest`** — [`BacktestController`](../src/main/java/com/moneymaker/backtesting/BacktestController.java)
   is `@ConditionalOnProperty(app.mode=backtest)`, so in live mode
   `/api/backtest/analysis` returns **404**, not an error you can read.
3. **Day 1 must already have a `trade_config` row.** The detector runs inside
   the per-day loop of `BacktestAnalysisService`, *after* the
   "no active configs → skip day" guard. A day with no config is skipped
   before the detector is reached, so **the feature cannot bootstrap a config
   chain from nothing** — it only ever extends an existing one. Symptom:
   `totalDays: 0` in the response and no `[EOD-downtrend]` lines at all.
4. **An `expiry_dates` row on/after day 1** — `resolveExpiry` returns the first
   expiry `>= tradingDay`; with none, the rule is skipped with
   `no expiry resolved`.

### Steps

1. Insert a single `sma_downtrend_rule` row (sample above).
2. Run the backtest across two consecutive days, where **day 1 already has a
   `trade_config`**:
   ```
   curl -X POST "http://localhost:8080/api/backtest/analysis?fromDate=2026-05-26&toDate=2026-05-27"
   ```
3. Inspect `trade_config WHERE source='AUTO_DOWNTREND'` for day 2 and the
   attached `sma_timeframe` rows — there should be at most one CE row + one
   PE row, with one child per `(sma, timeframe)` that passed.
4. Watch the log line
   `[EOD-downtrend] {day} — inserted N AUTO_DOWNTREND trade_config(s) for {nextDay}`
   per day, and the per-side
   `[EOD-downtrend] inserted AUTO_DOWNTREND trade_config id=... combos=[5min/SMA50, 15min/SMA200, ...]`.

---

## Practical limits (verified against live data)

Four things that are not obvious from the code and each of which silently
produces `inserted 0`:

**1. The SMA is computed on the candle LOW, not the close.**
[`SMAIndicatorImpl`](../src/main/java/com/moneymaker/indicator/SMAIndicatorImpl.java)
feeds `LowPriceIndicator` into ta4j's `SMAIndicator`. Any hand-check of a
trend decision must use lows or it will disagree with the detector.

**2. The SMA window spans multiple sessions, and a period the broker cannot
cover is dropped.**
`scanSide` fetches `lookbackCalendarDays(tf)` of history, not just the
trading day — 16 days at 5min, 35 at 15min, sized in *candles*: the longest
period in `SMA_PERIODS` plus one session, so the SMA is full-window at the
day's first judged candle and stays full-window to its last.

The request is only a request. What decides usability is how much history
actually came back **for that leg**: a period is admitted only if a full
`period`-wide window has already closed by the first judged candle
(`evalStartIdx >= period - 1`). This matters because ta4j's `SMAIndicator`
averages however many bars it has instead of returning null, so a period
with too little history still produces a number — a partial average that
looks like a real SMA and would otherwise be trend-tested silently.

Observed on a strike listed 2026-07-15, evaluated 2026-07-22:

```
tf=15minute SMA50  — 43 candles, need  49; period dropped
tf=15minute SMA500 — 43 candles, need 499; period dropped
tf=5minute  SMA200 — 126 candles, need 199; period dropped
-> inserted combos=[5min/SMA50, 5min/SMA100, 15min/SMA20]
```

Legs are judged independently — two strikes on the same day had 43 and 83
candles of 15-minute history. Expect newly listed strikes to yield fewer
combos, and a brand-new strike to yield none. That is the intended
behaviour: no config beats a config built on a partial average.

This is not cosmetic. A single session carries ~73 candles at 5min and ~25
at 15min, and `SMAIndicatorImpl` returns `null` when
`period > series.size()`. Fetching one day therefore silently collapsed the
grid to SMA(20) — plus SMA(50) at 5min — and made SMA(100)/(200)/(500)
permanently unreachable at every timeframe. Worse, the surviving SMA(20)
was computed from that day's candles alone, so it did not match the SMA(20)
on a broker chart, which is continuous across sessions.

Widening the window does not smear prior sessions into the verdict: the
`start_time` trim is a time-of-day filter and `SmaTrendCalculator` resets
its deviation counters per day, so the flags still describe the trading day
— only the SMA values now carry the right history.

Measured on ATM NIFTY 24400 CE/PE for 2026-08-13 at `max_deviation=5`:

| Window | Result |
|---|---|
| Single day (old) | 0 configs — every combo rejected |
| With lookback (current) | 2 configs; CE 6 combos, PE 5 combos, incl. SMA(500) at both timeframes |

`AnalysisScheduler.computeLookbackCalendarDays()` already existed for this
exact reason ("was failing for SMA500 on 5-min and above"); the detector was
the one path that never got it.

**3. Kite does not serve intraday history for expired option contracts.**
The API returns `status: success` with an **empty** candle array — no error.
Verified: an expired weekly returned 0 candles for *every* date in its own
life, while NIFTY spot returned 73 candles for the same dates. `scanSide`
treats an empty series as `continue`, so an expired-contract backtest always
yields `inserted 0` with no failure logged. **Backtest the current expiry**,
or the run proves nothing. Note this is a broker limit, not a data gap —
`market_data` may well hold the candles locally, but `MarketDataService`
always fetches from the broker and never reads that table.

**4. `max_deviation` counts every candle from `start_time`.** The counter is
not a slope test — it tallies each `curr >= prev` step across the whole
session, so a genuinely falling leg still accumulates deviations. With the
lookback in place, `max_deviation=5` behaves sensibly on real data
(2026-08-13 produced 6 passing combos on CE and 5 on PE).

If you are tuning it, measure rather than guess — and note the interaction
with limit 2: on a day-only window the same threshold rejected everything,
which looks identical to "market wasn't trending". Confirm the window is
right before touching the threshold.

---

## Two traps in the generated `trade_config`

Both were live defects; both are fixed. They are recorded because the failure
mode in each case is silent — the row looks perfectly reasonable in the table.

**Depth `0` means "no strikes", not "ATM".**
[`AnalysisScheduler.calculateStrikesForCandles`](../src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java#L220)
builds a strike list only when `itm_depth > 0` or `otm_depth > 0`, and never
reads `atm_depth` at all. A config with `0/0/0` therefore selects **zero
strikes**: `fetchAndShareStrikeMarketData` returns early, nothing reaches
`SharedData`, and the strategy has nothing to evaluate. The config sits in the
table looking valid and never trades.

ATM-only is `itm_depth=1` — the ITM loop starts at `i=0` and its first element
is the base (ATM) strike. `atm_depth` is effectively a dead column.

**`target` / `stop_loss` are option-premium points, so the ATR must be the
option's.**
`PositionService.thresholdBreach` compares them against `perShareProfit`, which
is entry-minus-current on the **option leg**. Deriving them from an ATR on the
underlying mixes units: NIFTY ATR(14) is ~180 index points while an ATM premium
is ~100, so `target` exceeded the most a short leg can ever earn — premium
decaying to zero — and could never fire. Every trade then exits on `STOP_LOSS`
or `FORCE_CLOSE`, quietly skewing any backtest built on those configs.

`computeAtr` therefore takes the option token and is evaluated per side; CE and
PE legitimately get different target/SL.

---

## Deleting generated configs

Auto-generated configs are disposable — regenerate them whenever a detector
change lands. The **Bulk delete** panel on `/trade-configs` (collapsed by
default, above the table) is the supported way; it removes the
`sma_timeframe` children too, which hand-written SQL usually forgets.

Two selectors, because they answer different questions:

| Selector | Answers | Use when |
|---|---|---|
| **Trading date** | "drop what trades on the 12th" | A specific day's configs are wrong |
| **Generation run** | "undo what the detector just wrote" | A whole backtest run was wrong |

A run spans several trading dates, so only `updated_date` can identify one —
that is what changeset
[`023_add_updated_date_to_trade_config.xml`](../src/main/resources/db/changelog/023_add_updated_date_to_trade_config.xml)
exists for. Runs are recovered by clustering `updated_date` values less than
two minutes apart, since one detector pass writes its rows seconds apart.

### API

```bash
# per-day counts (paints the calendar)
curl "http://localhost:8080/api/trade-configs/auto/calendar?from=2026-08-01&to=2026-08-31"

# generation runs, newest first
curl "http://localhost:8080/api/trade-configs/auto/runs"

# preview — dryRun defaults to true, so this never deletes
curl -X POST http://localhost:8080/api/trade-configs/auto/delete \
     -H 'Content-Type: application/json' \
     -d '{"mode":"TRADING_DATE","dates":["2026-08-12","2026-08-13"]}'

# commit
curl -X POST http://localhost:8080/api/trade-configs/auto/delete \
     -H 'Content-Type: application/json' \
     -d '{"mode":"TRADING_DATE","dates":["2026-08-12"],"dryRun":false}'
```

Three guarantees worth knowing:

- **`source='AUTO_DOWNTREND'` is pinned server-side.** MANUAL configs cannot be
  reached through this endpoint no matter what the request body says.
- **`dryRun` defaults to `true`.** The UI always previews first and shows the
  server's count, so the number you confirm is the number the server matched.
- **Configs referenced by `trade_order` rows are skipped**, matching the audit
  protection on the single-config delete. They are reported as
  `skippedWithTrades` rather than failing the batch.

---

## What this is **not**

- Not a strategy by itself — it just produces inputs for the existing strategy engine.
- Not live-mode wired today.
- Not aware of broker holidays.
- Not a backfill — only writes for the *next* calendar trading day after the one being processed.
- **Not a bootstrap.** It runs inside the per-day loop, after the
  "no active configs → skip day" guard, so it only fires on days that already
  have a `trade_config`. It extends a chain; it cannot start one. Seed day 1
  by hand.
