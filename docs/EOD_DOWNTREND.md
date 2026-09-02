# End-of-Day Downtrend Detection

Auto-generates next-day `trade_config` rows when the ATM option series ends
the day in a sustained downtrend.

> **Home (since 2026-08-31):** `com.moneymaker.tradeconfig.generation` — config
> generation is trade-config-domain work, not backtesting (user decision:
> producing configs and replaying them are different tasks). The entry points
> are `POST /api/trade-configs/generate?fromDate=&toDate=[&strategyIds=]` and
> `TradeConfigGenerationService.generateForWindow`; **the backtest replay no
> longer calls the detector at all.** The detector takes nothing
> backtest-specific — a 15:25 cron can call it for live mode later without
> code changes. The optional `strategyIds` scopes one run to selected
> strategies — see [Per-run strategy selection](#per-run-strategy-selection).
>
> **Both data sources.** It runs under `backtest.data-source=BROKER` and
> `HISTORICAL_ICICI` alike: every symbol comes from `OptionInstrumentResolver`,
> so the detector never needs to know whether it is holding a broker instrument
> token or an imported-CSV natural key. Under `HISTORICAL_ICICI` the depth of
> the ATR and the SMA grid is bounded by how many days have been imported —
> see [`BACKTESTING.md`](BACKTESTING.md#limits-when-historical_icici-is-active).

---

## What it does

For each trading day in a backtest run, after force-close at 15:20:

1. Loads every enabled row from `sma_downtrend_rule`.
2. For each rule, for both CE and PE — the scan below is the rule's
   [`EodTrendScanner`](../src/main/java/com/moneymaker/tradeconfig/generation/EodTrendScanner.java),
   selected by `indicator_type` (changeset 039; `SMA_DOWNTREND`, the default and
   only shipped scanner, is
   [`SmaDowntrendScanner`](../src/main/java/com/moneymaker/tradeconfig/generation/SmaDowntrendScanner.java)):
   - Picks the ATM strike on the underlying (round last 5-min close to the
     nearest `instrument.strike_points`). No moneyness/depth knob — ATM only.
   - For each timeframe in the rule's `timeframes_minutes` (default `5,15`):
     - Pulls the option-leg's intraday series once via
       [`MarketDataService`](../src/main/java/com/moneymaker/market/service/MarketDataService.java).
     - Computes each SMA in the rule's `sma_periods` (default `50,100,200,500`)
       on the series, populating the matching `smaValueXX` fields on every
       candle. An unselected period's `smaValue` stays null, so its flags stay
       false and it can produce no combo — skipping a period *is* never
       computing it.
     - Trims to candles `>= rule.start_time`.
     - Runs
       [`SmaTrendCalculator`](../src/main/java/com/moneymaker/strategy/rules/SmaTrendCalculator.java#L25)
       with `rule.max_deviation`.
     - Records every selected SMA period whose last-candle `smaXxDownTrending`
       flag is `true`.
3. For each side with at least one passing `(sma, timeframe)` combo:
   - Inserts **one** `trade_config` row stamped `source='AUTO_DOWNTREND'`
     for the next trading day (skip Sat/Sun), carrying the rule's
     `min_option_price` / `max_option_price` as its premium band.
   - Inserts **one** `sma_timeframe` child row per passing combo.
   - Stamps `trade_config.strategy_ids` with every strategy sharing that config.

### Idempotency is per `(target day, strategy)`

A strategy that already has an `AUTO_DOWNTREND` config for the next trading day
is skipped; one that does not still generates. So:

- **Replaying an unchanged range is a no-op** — the property the backtest relies
  on when the same dates are run twice.
- **Tagging a rule with a further strategy and replaying fills that strategy in**
  for days another strategy had already covered.

The second point is why the guard moved. It used to be per *day*: any
`AUTO_DOWNTREND` row for the target date suppressed the whole run, which made
the strategy tags un-actionable in hindsight — tag a second strategy after a day
had generated and it could never appear for it, because the first strategy's
config was enough to skip the day.

Because existing rows are never rewritten, tagging strategies at *different*
times yields one config per strategy (`"1"` and `"2"`), while tagging both before
the first generation yields a single config (`"1,2"`). Both dispatch identically;
only the row count differs. Delete a day's generated rows to force a full
re-write.

The generated config flows through the normal day-start path —
`TradeConfigScheduler.getConfigsForDate` picks it up on the next backtest day
the same way it picks up any human-inserted config.

---

## What lives in the rules table vs. what lives in code

The rules table is the **detection** config: which underlying to monitor, which
indicator with which grid, when to start counting, how strict, and how to
derive target/SL.

Only the strike moneyness stays **in code**. Everything that decides *what gets
traded* is in a table — including, since changeset 039, the SMA grid itself.

| Concern | Where it lives |
|---|---|
| Which SMAs are checked | `sma_downtrend_rule.sma_periods` (CSV, default `50,100,200,500`; changeset 039). Capped to `{20,50,100,200,500}` — the periods `MarketData` has trend flags for; others are dropped with a WARN. |
| Which timeframes are checked | `sma_downtrend_rule.timeframes_minutes` (CSV minutes, default `5,15`; changeset 039) |
| Which indicator judges the leg | `sma_downtrend_rule.indicator_type` (default `SMA_DOWNTREND`; changeset 039). Each value maps to an `EodTrendScanner` bean — see [Skipping SMAs / adding an indicator](#skipping-smas--adding-a-different-indicator-rule). |
| Which strike type | hardcoded ATM in `computeAtmStrike` |
| `transaction_type`, `max_loss`, `no_of_trades`, `no_of_parrellel_trades` for the generated config | [`strategy_defaults`](#table-strategy_defaults) — one row per strategy (changeset 033) |
| Whether a strategy may generate at all | `strategy_defaults.auto_config_enabled` |
| `lot_quantity` | `instrument.lot_qty` — the contract's lot size, not a strategy constant (`strategy_defaults.lot_quantity` is only a fallback) |
| Detection threshold (`max_deviation`, `start_time`) | `sma_downtrend_rule` |
| Target/SL derivation (`atr_periods`, `target_multiplier`, `sl_multiplier`, `target_pct`, `sl_pct`) | `sma_downtrend_rule` |
| Premium band (`min_option_price`, `max_option_price`) | `sma_downtrend_rule` — copied verbatim onto the generated config |
| Which underlying a rule applies to | `sma_downtrend_rule` |
| **Which strategies a rule generates for** | [`sma_downtrend_rule_strategy`](#table-sma_downtrend_rule_strategy) — one row per strategy (changeset 034) |

This split satisfies CLAUDE.md #9. It did not always: until changeset 033 the
`transaction_type` / `max_loss` / trade-count block came from a hardcoded switch,

```java
case 1:  return new StrategyDefaults("SELL", 1, 200, 1, 1);
default: return null;
```

which was both a trading-behaviour constant in a service *and* the reason
tagging a rule with any other strategy silently generated nothing — the `default`
branch made `processRule` skip the rule outright.

---

## Skipping SMAs / adding a different indicator rule

Both provisions landed with changeset 039 (user request 2026-08-31).

### Skip periods or timeframes — the Detection rules panel, or an UPDATE

The **🧭 Detection rules** panel on `/trade-configs` (collapsed, below the
Generate panel) lists every `sma_downtrend_rule` with its grid editable inline:
SMA periods, timeframes, indicator, and the enabled toggle, saved per row via
`PUT /api/downtrend-rules/{id}/grid`. Saves are validated harder than the
scanner's run-time leniency — an unsupported period or unknown indicator is
**rejected** with the allowed values named, and hand-typed spacing is stored
canonically. The rest of the row (thresholds, bracket, band) is shown read-only
for context; editing those stays SQL, and the panel says so in its tooltips.

The equivalent SQL:

```sql
-- rule 1: drop the long SMAs and the 15-minute timeframe
UPDATE sma_downtrend_rule SET sma_periods = '50,100', timeframes_minutes = '5' WHERE id = 1;
```

Parsing (via [`IntCsv`](../src/main/java/com/moneymaker/util/IntCsv.java), the
columns' one owner) is lenient about spacing and duplicates, ascending, and
skips malformed fragments. Rules worth knowing:

- **Blank falls back to the default grid**, not to "scan nothing" — to silence a
  rule use `enabled=false`. Pre-039 rows are backfilled with the defaults, so an
  existing database behaves identically.
- **Only `{20, 50, 100, 200, 500}` are computable.** Those are the periods
  `MarketData` carries `smaXxDownTrending` flags for and `SmaTrendCalculator`
  tracks; anything else is dropped with a WARN naming it. A *new* period is
  still a code change (flag fields + calculator + `smaDownFlag`), exactly as
  before.
- **SMA-20 is selectable for detection** — but the strategies' own SMA-20 rule
  case is commented out (see [STRATEGIES.md](STRATEGIES.md#the-shared-engine)),
  so a config generated from a 20-period combo sits untraded until that case is
  deliberately re-enabled. Detection and trading are separate decisions.
- A rule that skips SMA(500) also fetches a proportionally shorter lookback —
  the window is sized from the longest *selected* period.

### Add a different indicator rule — one class, one UPDATE

The scan is behind the
[`EodTrendScanner`](../src/main/java/com/moneymaker/tradeconfig/generation/EodTrendScanner.java)
seam: the detector owns everything indicator-agnostic (rule iteration, ATM
selection, bracket basis, idempotency, the config/timeframe writes) and asks the
scanner one question — *does this leg qualify at today's close, and on which
(sma, timeframe) combos?* Scanners are discovered by Spring `List` injection and
matched on `indicator_type`, the same pattern as the broker factories.

To add one (say an RSI-threshold rule):

1. Implement `EodTrendScanner` as a `@Component` returning a new
   `indicatorType()` (e.g. `RSI_OVERBOUGHT`).
2. Put its thresholds in **new columns on `sma_downtrend_rule`** via their own
   changeset — detection knobs live in the table (CLAUDE.md #9), and the row
   already carries the shared ones (`start_time`, band, bracket).
3. `UPDATE sma_downtrend_rule SET indicator_type = 'RSI_OVERBOUGHT' WHERE id = …`.

No detector change. An `indicator_type` with no registered scanner skips the
rule with a WARN naming the registered types. Mind the **combo contract** on the
interface: the pairs a scanner returns become the generated config's
`sma_timeframe` children, which are the primary SMA periods the *strategies*
scan the next day — a non-SMA scanner still decides which combos its detection
vouches for. Which indicators to actually add, and with what thresholds, is an
open trading decision — see
[S17 in STRATEGY_ANALYSIS_TODO.md](STRATEGY_ANALYSIS_TODO.md#s17-the-indicator_type-seam-ships-with-one-scanner--which-indicators-earn-a-second-is-unmeasured).

---

## Tagging a rule with several strategies

A rule tagged with strategies 1 and 2 runs its scan **once** and writes **one**
`trade_config` whose `strategy_ids` column names both — not one config per
strategy. That matters twice over: the scan (the
`{50,100,200,500} × {5min,15min}` grid against ATM on both CE and PE) is the
expensive half of the detector, and duplicate configs are exactly the drift that
[changeset 031](STRATEGIES.md#how-a-config-reaches-a-strategy) exists to remove.

```sql
-- generate for strategy 2 as well, from tomorrow's run onward
INSERT INTO sma_downtrend_rule_strategy (rule_id, strategy_id, enabled)
VALUES (1, 2, TRUE);
```

No UI, no redeploy. The strategy needs a `strategy_defaults` row first, or the
detector skips it with a warning naming it.

**When one config cannot serve both.** `transaction_type`, `max_loss`,
`no_of_trades` and `no_of_parrellel_trades` live on `trade_config` itself, so two
strategies can only share a row when their `strategy_defaults` blocks are
identical — the usual case, since `Strategy2` is `Strategy1` plus a filter. When
the blocks differ, `resolveConfigGroups` emits one config per distinct block, each
tagged with the strategies that share it. The `[EOD-downtrend] inserted ...
strategies=[...]` log line names them.

### Per-run strategy selection

The tags above are the *standing* setup. On top of it, one generation run can be
scoped to selected strategies:

```powershell
# generate only strategy 2's configs for this window
curl.exe -X POST "http://localhost:8080/api/trade-configs/generate?fromDate=2024-01-01&toDate=2024-01-31&strategyIds=2"
```

The **Generate AUTO configs** panel on `/trade-configs` exposes the same thing as
strategy checkboxes (none ticked = every tagged strategy). Three properties worth
knowing:

- **The scope narrows, never widens.** A scoped strategy still needs its rule tag
  (or the rule's fallback `strategy_id`) and an enabled `strategy_defaults` row;
  naming a strategy the rules aren't tagged with generates nothing for it.
- **Idempotency is untouched.** The `(target day, strategy)` guard applies inside
  the scope, so a scoped run skips days that strategy already covered and leaves
  every other strategy's existing configs alone. Running `strategyIds=1` and then
  `strategyIds=2` over the same window fills each strategy in independently —
  note the two passes yield one config *per strategy* (`"1"`, `"2"`) even where a
  single unscoped pass would have written one shared config (`"1,2"`), exactly
  like tagging strategies at different times. Both dispatch identically.
- **The scan still runs once per rule** — the scope filters who the config is
  written for, not what gets measured.

---

## Table: `sma_downtrend_rule`

| Column                    | Notes |
|---------------------------|-------|
| `id`                      | PK    |
| `strategy_id`             | The rule's **primary** strategy. Since changeset 034 the strategies actually generated for come from `sma_downtrend_rule_strategy`; this column is what that table was backfilled from, and the fallback for a rule with no tag rows. |
| `instrument_id`           | Underlying (FK to `instrument`). Drives both ATM strike selection and ATR. |
| `max_deviation`           | Max number of candles where `curr_sma >= prev_sma` before the day is no longer "downtrending". 0 = strictly monotonic. |
| `start_time`              | The deviation counter only includes candles `>= start_time`. Default `09:20:00`. |
| `atr_periods`             | N sessions of lookback for the bracket basis. Default 14. |
| `target_multiplier`       | `target = basis × target_multiplier` for the generated config, where `basis` is the traded leg's mean intraday range. Default `0.30` since changeset 027 (was `1.0`). |
| `sl_multiplier`           | `stop_loss = basis × sl_multiplier`. Default `0.45` since changeset 027. |
| `target_pct`              | Target as a fraction of entry premium — `0.2000` = 20%. Copied onto `trade_config.target_pct`, which **overrides** the absolute `target`. `NOT NULL`, default `0.20`. |
| `sl_pct`                  | Stop loss as a fraction of entry premium. `NOT NULL`, default `0.30`. |
| `max_sl_points`           | Ceiling in premium points on the stop the config resolves to — the lower of `sl_pct × entry` and this wins. Copied onto `trade_config.max_sl_points`. `NOT NULL`, default `60` (changeset 036). |
| `trail_ladder`            | Trailing stop rungs as ascending `trigger:lock` pairs in points — `25:2,50:25,75:50,100:75`. Copied onto `trade_config.trail_ladder`. `NOT NULL`, default as shown (changeset 036). |
| `min_option_price`        | Copied verbatim onto `trade_config.min_option_price`. `NOT NULL`, default `80`. |
| `max_option_price`        | Copied verbatim onto `trade_config.max_option_price`. `NOT NULL`, default `250`. |
| `enabled`                 | Toggle the rule on/off without deleting. |
| `sma_periods`             | Which SMA periods this rule checks, CSV. `NOT NULL`, default `50,100,200,500` (changeset 039). Only `{20,50,100,200,500}` are computable; others dropped with a WARN. Blank = default grid. Parsed only by `IntCsv`. |
| `timeframes_minutes`      | Which candle timeframes it checks, CSV minutes. `NOT NULL`, default `5,15` (changeset 039). Feeds the fetch interval as `<n>minute`. |
| `indicator_type`          | Which `EodTrendScanner` runs the scan. `NOT NULL`, default `SMA_DOWNTREND` (changeset 039) — see [Skipping SMAs / adding an indicator](#skipping-smas--adding-a-different-indicator-rule). |

The band columns are `NOT NULL` on purpose. `AbstractSmaCrossStrategy.outsidePriceBand` skips a
null bound entirely, so a config with no band is an **unbounded** config — free
to sell a 6-point leg against a 30-point target, which is the exact case
changeset 024 was written to prevent. A rule whose band is null or inverted is
skipped with a warn rather than generating that config; see `hasUsableBand`.

### Sample row

```sql
INSERT INTO sma_downtrend_rule
  (strategy_id, instrument_id, max_deviation, start_time, atr_periods,
   target_multiplier, sl_multiplier, target_pct, sl_pct,
   max_sl_points, trail_ladder,
   min_option_price, max_option_price, enabled)
VALUES
  (1, 1, 5, '09:20:00', 14, 0.30, 0.45, 0.20, 0.30,
   60, '25:2,50:25,75:50,100:75', 80, 250, TRUE);
```

That single row says: *"for Strategy 1 on instrument id=1, walk the full
{50,100,200,500} × {5min,15min} grid against ATM CE and PE; allow up
to 5 deviations from 09:20 onwards; exit at 20% profit or 30% loss on the
premium each trade opens at; and only enter legs priced between 80 and 250."*

---

## Schema changes

Six changesets back this feature. **`sma_downtrend_rule` is created fat, then
slimmed, then given a premium band — read 018, 020 and 026 together to get the
table's current shape.**

| Changeset | Effect |
|---|---|
| [`018_create_sma_downtrend_rule_table.xml`](../src/main/resources/db/changelog/018_create_sma_downtrend_rule_table.xml) | Creates `sma_downtrend_rule` in its original **fat** shape, including `sma`, `time_period`, `moneyness`, `depth` and five `trade_config`-duplicate columns. |
| [`019_add_source_to_trade_config.xml`](../src/main/resources/db/changelog/019_add_source_to_trade_config.xml) | Adds `trade_config.source` — `MANUAL` / `AUTO_DOWNTREND`, default `MANUAL`. |
| [`020_drop_unused_sma_downtrend_rule_columns.xml`](../src/main/resources/db/changelog/020_drop_unused_sma_downtrend_rule_columns.xml) | Drops all nine of those columns, leaving the detection-only shape documented above. |
| [`027_add_pct_bracket.xml`](../src/main/resources/db/changelog/027_add_pct_bracket.xml) | Adds `target_pct` / `sl_pct` to both `trade_config` (nullable — opt-in) and `sma_downtrend_rule` (`NOT NULL`, `0.20` / `0.30`), and retunes `target_multiplier` / `sl_multiplier` from `1.0` to `0.30` / `0.45` on rows still holding the original default. |
| [`036_add_trailing_stop_loss.xml`](../src/main/resources/db/changelog/036_add_trailing_stop_loss.xml) | Adds `max_sl_points` / `trail_ladder` to `sma_downtrend_rule` (`NOT NULL`, `60` / `25:2,50:25,75:50,100:75`) and to `trade_config` (seeded with the same values on existing rows). |
| [`026_add_option_price_range_to_sma_downtrend_rule.xml`](../src/main/resources/db/changelog/026_add_option_price_range_to_sma_downtrend_rule.xml) | Adds `min_option_price` / `max_option_price`, `NOT NULL` defaulting to 80 / 250, so generated configs stop being written with an unbounded band. Existing rows are backfilled with the defaults. |

| [`033_create_strategy_defaults.xml`](../src/main/resources/db/changelog/033_create_strategy_defaults.xml) | Creates `strategy_defaults` and seeds strategy 1 from the hardcoded switch it replaces. See below. |
| [`034_create_sma_downtrend_rule_strategy.xml`](../src/main/resources/db/changelog/034_create_sma_downtrend_rule_strategy.xml) | Creates `sma_downtrend_rule_strategy`, backfilled one tag per rule from `sma_downtrend_rule.strategy_id`. |
| [`039_add_downtrend_rule_indicator_grid.xml`](../src/main/resources/db/changelog/039_add_downtrend_rule_indicator_grid.xml) | Adds `sma_periods` / `timeframes_minutes` / `indicator_type` — the detection grid becomes per-rule data and the scan goes behind the `EodTrendScanner` seam. Defaults reproduce the old hardcoded grid; existing rows are backfilled with them. |

Every existing `trade_config` row stays `MANUAL`. Auto-generated rows are
stamped `AUTO_DOWNTREND` so the detector can dedupe its own output across
re-runs.

### Table: `strategy_defaults`

One row per strategy, holding the `trade_config` field block the detector stamps
on every config it generates for that strategy.

| Column | Notes |
|---|---|
| `strategy_id` | PK. Matches `Strategy.getId()`. |
| `transaction_type` | `BUY` / `SELL` — the side an entry signal must carry. |
| `lot_quantity` | Fallback only; `instrument.lot_qty` wins when set, because NFO takes whole lots and the contract defines one. |
| `max_loss` | → `trade_config.max_loss`. |
| `no_of_trades` | → `trade_config.no_of_trades`. |
| `no_of_parallel_trades` | → `trade_config.no_of_parrellel_trades` (the typo is in that schema, not here). |
| `auto_config_enabled` | Parks a strategy without deleting its block. |

**Only strategy 1 is seeded**, with the exact values from the switch that was
deleted, so behaviour on an existing database is unchanged. Strategy 2 gets no
row on purpose: its `max_loss` / trade counts are trading decisions nobody has
made, and CLAUDE.md #9 forbids guessing them. Until the row exists the detector
logs — and generates nothing for it:

```
WARN [EOD-downtrend] rule id=1 — strategy 2 has no strategy_defaults row, skipping it.
     Insert one (see changeset 033) to generate configs for this strategy.
```

```sql
INSERT INTO strategy_defaults
  (strategy_id, transaction_type, lot_quantity, max_loss,
   no_of_trades, no_of_parallel_trades, auto_config_enabled)
VALUES (2, 'SELL', 1, <max_loss>, <trades>, <parallel>, TRUE);
```

### Table: `sma_downtrend_rule_strategy`

Which strategies a rule generates for. One row per strategy; see
[Tagging a rule with several strategies](#tagging-a-rule-with-several-strategies).

| Column | Notes |
|---|---|
| `id` | PK |
| `rule_id` | FK to `sma_downtrend_rule`. |
| `strategy_id` | Needs a matching `strategy_defaults` row to generate anything. |
| `enabled` | Park a tag without losing the row. |

Unique on `(rule_id, strategy_id)` — tagging the same strategy twice would emit
its config twice for one detected downtrend.

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
| [`EodDowntrendDetectionService`](../src/main/java/com/moneymaker/tradeconfig/generation/EodDowntrendDetectionService.java) | Orchestrator. Public entry: `runForDay(LocalDate[, strategyScope])`. Owns everything indicator-agnostic; resolves which configs to emit in `resolveConfigGroups(rule, …)` and dispatches the scan by `indicator_type`. |
| [`EodTrendScanner`](../src/main/java/com/moneymaker/tradeconfig/generation/EodTrendScanner.java) / [`SmaDowntrendScanner`](../src/main/java/com/moneymaker/tradeconfig/generation/SmaDowntrendScanner.java) | The indicator seam (changeset 039) and its one shipped implementation — the per-rule SMA grid walk, formerly `scanSide` inside the detector. |
| [`IntCsv`](../src/main/java/com/moneymaker/util/IntCsv.java) | The only place `sma_periods` / `timeframes_minutes` are parsed or formatted. |
| [`DowntrendRuleAdminController`](../src/main/java/com/moneymaker/tradeconfig/controller/DowntrendRuleAdminController.java) / [`DowntrendRuleAdminService`](../src/main/java/com/moneymaker/tradeconfig/service/DowntrendRuleAdminService.java) | The Detection rules panel's backend — `GET /api/downtrend-rules`, `GET /api/downtrend-rules/indicator-types`, `PUT /api/downtrend-rules/{id}/grid`. Grid + enabled only; save-time validation rejects what the scanner would WARN-drop. |
| [`StrategyDefaults`](../src/main/java/com/moneymaker/entity/StrategyDefaults.java) / [`StrategyDefaultsRepository`](../src/main/java/com/moneymaker/repository/StrategyDefaultsRepository.java) | The per-strategy `trade_config` field block. `configSignature()` is what decides whether two strategies can share one generated config. |
| [`SmaDowntrendRuleStrategy`](../src/main/java/com/moneymaker/entity/SmaDowntrendRuleStrategy.java) / [`SmaDowntrendRuleStrategyRepository`](../src/main/java/com/moneymaker/repository/SmaDowntrendRuleStrategyRepository.java) | Which strategies a rule generates for. |
| [`StrategyIds`](../src/main/java/com/moneymaker/util/StrategyIds.java) | The detector writes `trade_config.strategy_ids` through this — without it the config would be scanned by its `stratergy_id` alone. The only place that column is parsed or formatted. |
| [`OptionInstrumentResolver`](../src/main/java/com/moneymaker/market/instrument/OptionInstrumentResolver.java) | Supplies every symbol the detector fetches on — underlying, expiry, option leg. Same indirection `AnalysisScheduler` uses, which is what makes the detector work on both data sources. |
| [`BacktestAnalysisService`](../src/main/java/com/moneymaker/backtesting/BacktestAnalysisService.java) | **Since 2026-08-31 the replay no longer calls the detector by default** (user request — generation and measurement are separate operations). Generation runs via `POST /api/backtest/generate-configs?fromDate=&toDate=` (`generateConfigsOnly`, no replay, no ledger writes), or inside a replay only with the explicit `generateConfigs=true` request param. See [BACKTESTING.md](BACKTESTING.md#running-a-backtest--two-separate-operations-since-2026-08-31). |
| [`TradeConfigRepository`](../src/main/java/com/moneymaker/repository/TradeConfigRepository.java) | `findByTradingDateAndSource` powers the idempotency probe — its rows are read for their `strategy_ids` to build the already-generated set. |

---

## How to extend (the deltas you'll most likely add)

| Need                                | Where to change |
|-------------------------------------|-----------------|
| New strategy with different fixed fields (e.g. `transaction_type=BUY`) | Two INSERTs, no code: a `strategy_defaults` row for the strategy, and a `sma_downtrend_rule_strategy` row tagging it onto the rule. |
| An existing rule should also generate for another strategy | One INSERT into `sma_downtrend_rule_strategy`. If the two strategies' `strategy_defaults` blocks match they share one generated config; if not, each gets its own. |
| Stop generating for a strategy without losing the setup | `UPDATE strategy_defaults SET auto_config_enabled=FALSE` (all rules), or `UPDATE sma_downtrend_rule_strategy SET enabled=FALSE` (one rule). |
| Skip an SMA period or timeframe for one rule | `UPDATE sma_downtrend_rule SET sma_periods='50,100'` / `timeframes_minutes='5'` — see [Skipping SMAs / adding an indicator](#skipping-smas--adding-a-different-indicator-rule). No code. |
| Additional timeframe (e.g. `30min`) | Add it to the rule's `timeframes_minutes`. No code — but the value must be an interval the active data source serves. |
| New SMA period beyond 20/50/100/200/500 | Still code: extend [`MarketData`](../src/main/java/com/moneymaker/entity/MarketData.java) with the new `smaValueXX` field + flags, update [`SmaTrendCalculator`](../src/main/java/com/moneymaker/strategy/rules/SmaTrendCalculator.java#L25), and add the period to `SmaDowntrendScanner.SUPPORTED_PERIODS` + its `smaDownFlag(...)` switch. Then select it in `sma_periods`. |
| A different indicator entirely (RSI, EMA, …) | Implement [`EodTrendScanner`](../src/main/java/com/moneymaker/tradeconfig/generation/EodTrendScanner.java) as a bean; thresholds go in new `sma_downtrend_rule` columns; point rows at it via `indicator_type`. See [the section above](#skipping-smas--adding-a-different-indicator-rule). |
| Different strike type (ITM/OTM at depth N) | Replace `computeAtmStrike` with a `computeStrike(rule, side)` and add the depth columns back to the rule. |
| Target/SL formula other than the two shipped shapes (percentage of entry premium, or `mean intraday range × mult`) | Branch inside `insertAutoTradeConfig` on a new column like `target_mode`. A shape that is not a fixed points distance also needs `OrderService.bracketAtEntry` to know how to resolve it. |
| Up-trend variant (for BUY strategies) | Add a `direction` column (`DOWN`/`UP`), branch in `scanSide` to read `smaXxUpTrending` instead. |
| Promote to live mode | Add a new `@Scheduled(cron="0 25 15 * * MON-FRI")` method on a new scheduler that calls `eodDowntrendDetectionService.runForDay(LocalDate.now())`. No service changes required. |
| Holiday-aware "next trading day" | Swap `nextTradingDay(...)` to consult a holiday table. Method is private; only caller is `runForDay`. |
| Telegram alert when a rule fires | Inject `NotificationService` into the service; call `notifier.sendIfChanged(...)` from `insertAutoTradeConfig`. |
| Reset / regenerate AUTO rows for a date | Use the **Bulk delete** panel on `/trade-configs`, or the API below. Hand-written SQL is no longer needed and misses the `sma_timeframe` children. |
| Retune SL / target on configs already generated | The **Bulk edit** panel on `/trade-configs` (`POST /api/trade-configs/auto/bulk-update`) — one field-set across all matching configs, optionally per strategy / date window. Editing the *rule* only changes future generation. See [ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md#bulk-editing-many-configs). |
| Generate for one strategy only this run | `strategyIds` on the generate endpoint / the panel's strategy checkboxes — see [Per-run strategy selection](#per-run-strategy-selection). |

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
4. **An expiry on/after day 1** — the resolver returns the first expiry
   `>= tradingDay`; with none, the rule is skipped with `no expiry resolved`.
   Which table that comes from depends on `backtest.data-source`: `expiry_dates`
   under `BROKER`, `historical_option_candles` under `HISTORICAL_ICICI`.

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
tf=15minute SMA100 — 43 candles, need  99; period dropped
tf=15minute SMA200 — 43 candles, need 199; period dropped
tf=15minute SMA500 — 43 candles, need 499; period dropped
tf=5minute  SMA200 — 126 candles, need 199; period dropped
tf=5minute  SMA500 — 126 candles, need 499; period dropped
-> inserted combos=[5min/SMA50, 5min/SMA100]
```

Note the 15-minute timeframe contributes nothing here. With SMA(20) removed
from the grid, 50 is the shortest period, and a leg with 43 candles cannot
cover it — so a newly listed strike now yields 5-minute combos only until it
has ~49 candles of 15-minute history (about two sessions).

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
on a broker chart, which is continuous across sessions. (SMA(20) was in
`SMA_PERIODS` when this was diagnosed; it has since been removed. The
sufficiency argument is unchanged — it now bites at SMA(50) instead.)

Widening the window does not smear prior sessions into the verdict: the
`start_time` trim is a time-of-day filter and `SmaTrendCalculator` resets
its deviation counters per day, so the flags still describe the trading day
— only the SMA values now carry the right history.

Measured on ATM NIFTY 24400 CE/PE for 2026-08-13 at `max_deviation=5`,
while SMA(20) was still in the grid — expect fewer combos per config now:

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

**`target` / `stop_loss` are option-premium points, so the basis must be the
option's.**
`PositionService.thresholdBreach` compares them against `perShareProfit`, which
is entry-minus-current on the **option leg**. Deriving them from an ATR on the
underlying mixes units: NIFTY ATR(14) is ~180 index points while an ATM premium
is ~100, so `target` exceeded the most a short leg can ever earn — premium
decaying to zero — and could never fire. Every trade then exits on `STOP_LOSS`
or `FORCE_CLOSE`, quietly skewing any backtest built on those configs.

The bracket basis is therefore measured per side on an option token; CE and PE
legitimately get different target/SL.

### Why an option leg's ATR is not a usable basis

Switching the ATR to the option leg fixed the *unit* but not the *magnitude*.
Three properties of an option series make true range the wrong measure:

1. **True range counts the overnight gap.** On an index that gap is a real move
   the next session can extend. On an option leg it is mostly re-pricing — the
   same strike sits a different distance from spot, one day closer to expiry —
   and an intraday trade that opens after the open can never capture it.
2. **`resolveExpiry` returns the first expiry on or after the date asked for**,
   so on an expiry day the detector measured the series dying at that close,
   whose final true range is a one-way premium collapse, while writing a config
   for the next day that trades a different contract entirely.
3. **An option leg's ATR is about the size of its own premium.** A short leg's
   maximum gain *is* the premium, so a target at 1× ATR needs the premium to
   reach zero intraday.

Measured on the imported Jan-2024 NIFTY series, `ATR(14)` of the ATM 21700 PE on
2024-01-04 was **119.89** — of which the 2024-01-03 term came from the gap
(119.45 vs an intraday range of 113.25) and the 2024-01-04 term was the expiry
collapse (156.90, close 197.95 → low 41.05). That 119.89 became both the target
and the stop-loss of the config generated for 2024-01-05.

Replaying every 5-min candle 09:20–14:30 as a hypothetical short entry inside the
80–250 band, ATM ±3 strikes, front expiry, first touch on 5-min high/low:

| bracket | TARGET | STOP_LOSS | ran to force close |
|---|---|---|---|
| 120/120 pts (1× ATR) | **3.6%** | 10.1% | **86.3%** |
| 30/30 pts | 45.4% | 44.5% | 10.1% |
| 20% / 30% of entry premium | 53.9% | 33.7% | 12.4% |

At 1× ATR the bracket stops being an exit rule: the trade runs to force close
86% of the time.

### What the detector writes now

`averageIntradayRange` replaces `computeAtr` for the bracket. It averages daily
`high − low` — no gap term — over the leg **the generated config will trade**
(`resolveExpiry(nextDay)`), skipping that contract's own expiry session. On an
expiry day the next contract usually has no history yet, so it falls back to the
detected leg, still gap-free and still excluding the expiry session.

`computeAtr` stays, used only by `strikeDepthFor` on the underlying, where true
range is the right measure and the number is never compared to a premium.

The generated config then carries **both** bracket shapes:

| | Source | Used for |
|---|---|---|
| `target_pct` / `sl_pct` | copied off the rule | The bracket that decides exits. `OrderService` resolves `entryPrice × pct` into `trade_order.target_at_entry` / `stop_loss_at_entry` at open. |
| `target` / `stop_loss` | `basis × multiplier`, capped by `clampToBandFloor` | Fallback when a config has no percentage, and the SMA-separation gate `CommonRules.profitTarget` reads at entry. |
| `max_sl_points` / `trail_ladder` | copied off the rule | The asymmetric half of the bracket (changeset 036): the ceiling tightens whatever stop the row above resolves to, and the ladder ratchets a floor up as the trade runs. Both are `NOT NULL` on the rule because Hibernate writes every column explicitly — `trade_config`'s own DB default never reaches a generated row, so a null here would quietly hand the whole AUTO fleet an uncapped, non-trailing stop. |

A percentage is used because the premium band is a 3× spread: one absolute points
target is a 12% move at 250 and a 38% move at 80, so one end of the band always
gets a bracket that does not match the trade.

`clampToBandFloor` caps the absolute target one tick below `min_option_price`. A
short leg cannot gain more than the premium it sold, so a target at or above the
band floor is unreachable by the cheapest entry the config permits. It clamps
rather than skipping the side — the detected downtrend is still real — and warns,
so a rule that clamps every day is visibly a multiplier that wants lowering.

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

# commit, taking traded configs and their trade_order rows with it
curl -X POST http://localhost:8080/api/trade-configs/auto/delete \
     -H 'Content-Type: application/json' \
     -d '{"mode":"TRADING_DATE","dates":["2026-08-12"],"dryRun":false,"force":true}'
```

Three guarantees worth knowing:

- **`source` defaults to `AUTO_DOWNTREND`.** A request that omits it can only
  reach regenerable detector output; MANUAL configs need an explicit opt-in —
  see below. `mode=UPDATED_RANGE` stays pinned to AUTO either way.
- **`dryRun` defaults to `true`.** The UI always previews first and shows the
  server's count, so the number you confirm is the number the server matched.
- **Configs referenced by `trade_order` rows are skipped by default**, matching
  the audit protection on the single-config delete. They are reported as
  `skippedWithTrades` rather than failing the batch. `force` overrides this —
  see below.

### `force`: deleting configs that have trades

`"Deleted 0 of 5 matched config(s); 5 kept because trades reference them."` is
the expected result when the configs you are clearing have already produced
trades — typically after a backtest ran against them. Re-running the delete
will not change it: the skip is about `trade_order`, not about the configs.

`force: true` deletes those configs **and the `trade_order` rows that reference
them**. There is no FK between the two tables — only the lookup index from
[`008_create_trade_order_table.xml`](../src/main/resources/db/changelog/008_create_trade_order_table.xml)
— so leaving the trades behind would strand them on a `trade_config_id` that no
longer resolves. Hence a cascade rather than an orphan. The trade rows go first,
so an interrupted delete cannot lose the ids needed to find them again.

| | `force: false` (default) | `force: true` |
|---|---|---|
| Configs without trades | deleted | deleted |
| Configs with trades | skipped, counted in `skippedWithTrades` | deleted |
| Their `trade_order` rows | untouched | **deleted, permanently** |

The response reports `configsWithTrades` and `tradeOrders` either way, so a
default preview already tells you what an opt-in would cost. In the UI it is a
separate **"Also delete configs that have trades"** checkbox beside the delete
button, cleared after every run and after *Clear* so it cannot carry over into
the next delete. This is the only path in the app that removes `trade_order`
history — the single-config delete still refuses outright with a 409.

### `source`: aiming the panel at MANUAL configs

The panel exists for detector output, and that stays the default. But the same
calendar / preview / cascade machinery is what you want for clearing out
hand-written configs too, so `source` selects which rows the selector may reach:

```bash
curl -X POST http://localhost:8080/api/trade-configs/auto/delete \
     -H 'Content-Type: application/json' \
     -d '{"mode":"TRADING_DATE","dates":["2024-01-02"],"source":"MANUAL","dryRun":false,"force":true}'
```

Only `AUTO_DOWNTREND` and `MANUAL` are accepted — it is an enum, not a string
pasted into a query. Omit it and you get `AUTO_DOWNTREND`, so nothing reaches
hand-written configs by accident.

**`mode=UPDATED_RANGE` ignores it and stays on `AUTO_DOWNTREND`.** A generation
run is recovered by clustering `updated_date`, which the detector stamps on every
row it writes and hand-written configs mostly leave `NULL` — so the concept does
not transfer, and the combination would delete a surprising set.

In the UI the source is a dropdown beside the mode radios. Picking MANUAL
repaints the calendar (the counts are per-source), clears the current selection —
the ticked days referred to the other source's rows — and raises a standing red
banner on the panel plus a line in the confirm dialog. The selector is hidden in
*Generation run* mode, matching the server-side pin.

Note the two opt-ins are independent and compose: `source: MANUAL` chooses
*which* configs, `force` decides whether ones with trades are included.

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

---

## Detection is no longer gated on having traded (2026-08-29)

`BacktestAnalysisService` used to `continue` past any day with no active config,
which skipped `runForDay` along with everything else. Because `AUTO_DOWNTREND`
configs are only ever written by the *previous* day's detection, one day that
generated nothing ended the chain permanently - **a 31-day range stopped after 5
days**, and every later day was skipped for want of a config that could no longer
be created.

Detection now runs on every trading day, whether or not anything traded. The
question it answers - should we trade *tomorrow* - does not depend on whether we
happened to trade today.

### Why a day generates nothing, and why that is usually temporary

The detector measures the ATM option leg, and in the imported data an option
series exists only within its own expiry cycle. On the **first day of a cycle**
the newly-nearest contract has only that morning's candles, so almost nothing in
the SMA grid is computable:

| At close of | Candles on the contract | Grid combos computable (of 8) |
|---|---|---|
| Day 1 of cycle | ~75 | **1** |
| Day 2 | ~152 | 3 |
| Day 3 | ~228 | 4 |
| Day 4 | ~304 | 5 |

So the day after each expiry rollover often generates no config. With detection
decoupled that costs one day of trading, not the rest of the run - the next day's
detection has ~152 candles and re-arms the chain.

This is a limitation of the **export**, not of the market: a weekly contract
trades for weeks before its cycle starts, but the CSVs window each expiry to
`cycle_start .. expiry`. Re-exporting with a wider window removes it. See
[`BACKTESTING.md` -> Importing a full ICICI export](BACKTESTING.md#importing-a-full-icici-export).

### Next trading day is data-driven

`nextTradingDay` no longer means "next weekday" - it comes from `TradingCalendar`,
so a market holiday is never handed a config and a special Saturday session is
never skipped.
