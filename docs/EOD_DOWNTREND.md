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
| `transaction_type`, `lot_quantity`, `max_loss`, `no_of_trades`, `no_of_parrellel_trades` for the generated config | `EodDowntrendDetectionService.strategyDefaults(strategyId)` — one switch branch per strategy |
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

## Table change: `trade_config.source`

Changeset
[`019_add_source_to_trade_config.xml`](../src/main/resources/db/changelog/019_add_source_to_trade_config.xml)
adds:

| Column   | Values                          | Default    |
|----------|---------------------------------|------------|
| `source` | `MANUAL` / `AUTO_DOWNTREND`     | `MANUAL`   |

Every existing row stays `MANUAL`. Auto-generated rows are stamped
`AUTO_DOWNTREND` so the detector can dedupe its own output across re-runs.

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
| Reset / regenerate AUTO rows for a date | `DELETE FROM trade_config WHERE source='AUTO_DOWNTREND' AND trading_date='YYYY-MM-DD'` then re-run the backtest covering the prior day. |

---

## Verification recipe

1. Insert a single `sma_downtrend_rule` row (sample above).
2. Run the backtest for two consecutive days:
   ```
   curl -X POST "http://localhost:8080/api/backtest/analysis?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD+1"
   ```
3. Inspect `trade_config WHERE source='AUTO_DOWNTREND'` for day 2 and the
   attached `sma_timeframe` rows — there should be at most one CE row + one
   PE row, with one child per `(sma, timeframe)` that passed.
4. Watch the log line
   `[EOD-downtrend] {day} — inserted N AUTO_DOWNTREND trade_config(s) for {nextDay}`
   per day, and the per-side
   `[EOD-downtrend] inserted AUTO_DOWNTREND trade_config id=... combos=[5min/SMA50, 15min/SMA200, ...]`.

---

## What this is **not**

- Not a strategy by itself — it just produces inputs for the existing strategy engine.
- Not live-mode wired today.
- Not aware of broker holidays.
- Not a backfill — only writes for the *next* calendar trading day after the one being processed.
