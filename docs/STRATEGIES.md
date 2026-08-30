# Strategies

Which `Strategy` bean a config runs, what each one does, and how they differ.

> **Open questions about any of this go in
> [STRATEGY_ANALYSIS_TODO.md](STRATEGY_ANALYSIS_TODO.md), not in `GAPS.md`** — see
> Rule 0 in `CLAUDE.md`. This page describes what the strategies *do*; that one
> tracks what is unresolved about them.

## How a config reaches a strategy

A config can be run by **several** strategies. Two columns on `trade_config` are
involved:

- `stratergy_id` — the config's **primary** strategy (the typo is in the schema —
  see [GAPS.md](GAPS.md#10-tradeconfigstratergyid--column-name-typo)). Still what
  the orders ledger and the Telegram digest display, and kept in step by
  `TradeConfigAdminService`. It **no longer decides dispatch on its own**.
- `strategy_ids` — ascending, comma-separated ids (`"1"`, `"1,2"`), added by
  changeset 035, which **replaced the `trade_config_strategy` child table**
  introduced by 031. Blank or null means "no tags" and falls back to
  `stratergy_id`, so a pre-existing config behaves exactly as before.

> **Parse or format that column only via
> [`StrategyIds`](../src/main/java/com/moneymaker/util/StrategyIds.java).** A CSV
> column is only as sound as the discipline that nothing else calls `split(",")`
> on it and invents its own whitespace, ordering and duplicate rules. `parse` is
> deliberately lenient (`" 2 , 1 ,"` → `[1, 2]`) because the column gets edited by
> hand in SQL, and it skips a malformed fragment rather than throwing — one typo
> must not stop the day's configs loading. The ascending order is not cosmetic: it
> fixes strategy dispatch order, so a replayed backtest day behaves identically.

`TradeConfigScheduler` **fans each config out into one `TradeConfigCombinedDTO`
per tagged strategy** — same `tradeConfig`, different `strategyId`. That is the
only place the fan-out happens, which is what lets `StrategyFactory` keep
dispatching exactly one strategy per DTO;
[`TradeConfigCombinedDTO.getStrategyId()`](../src/main/java/com/moneymaker/dto/TradeConfigCombinedDTO.java)
falls back to `stratergy_id` when nothing was tagged.

**`SharedData.combinedDto`'s length is the number of `(config, strategy)` pairs,
not configs** — anything reporting `combinedDto.size()` as a config count is
counting pairs. Siblings share one `TradeConfig` instance and one timeframe list;
a caller needing to mutate a config per strategy must copy first.

**`(tradeConfig.id, strategyId)` is the pipeline's ledger identity.** It is what
`OrderService` counts trades, parallel positions and realised loss against. Two
strategies sharing a config each get their own caps and their own position on the
same leg — they do not compete for one budget. Worth holding onto when reading a
backtest: the same config appearing twice in the ledger is expected, and is *not*
the duplication bug that was
[S2](STRATEGY_ANALYSIS_TODO.md#s2-strategy1-scanned-every-configs-legs-not-its-own--resolved-2026-08-25).

The admin dropdown is populated from `StrategyFactory.availableStrategyIds()`,
so a new strategy bean appears in the UI with no further wiring.

---

## Inventory

| `stratergy_id` | Bean | In one line |
|---|---|---|
| 1 | [`Strategy1`](../src/main/java/com/moneymaker/strategy/Strategy1.java) | Baseline SMA-cross. No extra filter. |
| 2 | [`Strategy2`](../src/main/java/com/moneymaker/strategy/Strategy2.java) | Baseline **plus**: no SELL entry while the 20-period SMA is sloping upward. |

Both extend
[`AbstractSmaCrossStrategy`](../src/main/java/com/moneymaker/strategy/AbstractSmaCrossStrategy.java),
which holds *everything* except the id and the rule sets: cache-key ownership
matching, the premium sort, the SMA-cross gate, the entry price band, the
signal emission. Neither subclass overrides any of it, so the two strategies
are identical apart from the one rule described below.

---

## The shared engine

Per config, per configured timeframe, per matching option leg (highest premium
first):

1. `SmaTrendCalculator.compute(candles, maxDeviations=0)` stamps the
   `smaNNUpTrending` / `smaNNDownTrending` flags.
1. **The decision bar must belong to the session being evaluated.** The candle
   list spans the whole SMA lookback and ends at the newest bar that has
   *finished forming* by `asOf`, so for a coarse timeframe the last bar is still
   the previous session's close until the day's first bucket completes — on a
   15-minute series the 09:15 bucket only settles at 09:30. A leg whose last bar
   pre-dates `asOf`'s date is skipped, with the reason on the `[tick]` log.

   > This is why **a 15-minute timeframe emits no signal before 09:30**, and it
   > is deliberate: "this timeframe has no settled bar yet today" is the honest
   > answer. Without the guard the strategy acted on yesterday's closing bar and
   > stamped the signal with yesterday's timestamp and price — producing exits
   > recorded *before* their own entry, and entries that looked like overnight
   > holds in an intraday system. The same hazard exists live, where a broker
   > asked for a 15-minute series over a multi-day window at 09:20 also returns
   > yesterday's last bar as the newest.
2. `RuleEngine.decide(...)` applies the cross gate on the config's **primary**
   SMA period (`sma_timeframe.sma`):
   - `open > SMA && close < SMA` → SELL candidate, then the sell rules must pass.
   - The raw buy cross is deliberately disabled; the buy rules still run, and
     today the only one is the 15:15 market-close exit.
3. An entry signal outside `min_option_price` / `max_option_price` is dropped —
   see [ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md#option-premium-band-min_option_price--max_option_price).
   Exit-direction signals are never filtered.

Rules are `TradeRules(required AND…, anyOf OR…)`. A **fully empty** pair means
"nobody wrote rules for this SMA period" and `RuleEngine` fails it closed — a
commented-out `case` disables that period rather than widening it. Any subclass
narrowing the baseline must preserve that; see the note at the bottom of this
page.

Baseline rules, identical in both strategies:

| Primary SMA | Sell (required) | Buy (anyOf) |
|---|---|---|
| 20 | *(case commented out — no signals)* | *(case commented out)* |
| 50 / 100 / 200 / 500 | `isSmaNNDownTrending` | `isMarketCloseTime` (≥ the close-signal time **of the session being evaluated** — `app.market.close` − `app.market.close-signal-offset-minutes`, 15:15 by default) |

---

## Strategy 2 — the SMA-20 slope filter

`Strategy2` overrides only `sellRulesFor(period)`, appending one required rule
to whatever the baseline produced:

```java
required.add(TradeRule.named("sma20SlopeNotUp",
        ctx -> !CommonRules.isSma20SlopeUp(ctx)));
```

A blocked entry is visible in the `[tick]` log as
`sellGate=true, sell rules FAIL [required[1:sma20SlopeNotUp]=FAIL]`.

**Slope, not the trend flag.**
[`CommonRules.isSma20SlopeUp`](../src/main/java/com/moneymaker/strategy/rules/CommonRules.java)
compares this candle's `smaValue20` against the previous candle's — the
instantaneous slope. It deliberately does **not** read
`candle.isSma20UpTrending()`: that flag is a whole-day verdict from
`SmaTrendCalculator` (with `maxDeviations = 0` it means the SMA has risen on
*every* candle since the open, so one flat bar at 09:20 switches it off for the
rest of the session). "Is the 20 SMA rising right now" is the narrower question
a per-tick entry filter needs.

**Unknown slope does not block.** The predicate returns `false` — i.e. allows
the entry — when the SMA-20 is still warming up (< 20 candles), when the SMA-20
column is absent, or on the first candle of a trading day, whose predecessor is
the previous session's close and therefore an overnight gap rather than a slope.
`SmaTrendCalculator` resets at the same day boundary for the same reason. The
filter exists to *suppress* entries, so "cannot tell" must not suppress.

> In practice the day-boundary case is the only one that fires regularly — the
> other two need a series shorter than 20 candles, or a timeframe that does not
> register period 20. Note the stale-bar guard above does not remove it: the
> first bar that guard admits is precisely the one with no same-day predecessor.
> **"Unknown ⇒ allow" is the confirmed behaviour for now**, parked 2026-08-30
> rather than left undecided. The direction to try later is to treat the
> overnight gap as the slope, giving the day's first bar a real answer instead
> of an exemption — with the asymmetry that would introduce recorded in
> [S1](STRATEGY_ANALYSIS_TODO.md#s1-strategy2s-sma-20-slope-filter-is-inert-when-the-slope-is-unknown--parked-2026-08-30).

**Scope of the filter:**

| | |
|---|---|
| Applies to | SELL signals only |
| Applies for | Every primary SMA period — 50 / 100 / 200 / 500, and any period enabled later |
| Does **not** apply to | BUY signals — on a SELL config that is the *exit* leg (the 15:15 close), and gating it would strand open positions until stop-loss or the end-of-day force-close |
| Measured on | The option leg's own candle series (same series the cross gate uses), not the underlying index |

**Where the SMA-20 comes from.** `AnalysisScheduler` stamps every period in
`SharedData.allTimeFrameMap` (20, 50, 100, 200, 500) onto each strike series it
caches — not only the period the config trades on — so SMA-20 is available to a
config whose own primary SMA is 200. See
[SCHEDULERS.md → AnalysisScheduler](SCHEDULERS.md#analysisscheduler).

---

## Adding a strategy

1. Extend `AbstractSmaCrossStrategy`, annotate `@Component`, return a fresh id
   from `getId()`. `StrategyFactory` discovers it via `List<Strategy>` injection
   and the admin dropdown picks it up automatically.
2. To **narrow** the baseline, wrap `super.sellRulesFor(...)` /
   `super.buyRulesFor(...)` rather than rebuilding the rule lists — that way a
   later change to the baseline rules reaches your strategy too.
3. **Pass a fully-empty `TradeRules` straight through.** Appending a required
   rule to an empty pair turns `RuleEngine`'s deliberate fail-closed ("no rules
   defined for this period") into "trade this period whenever my one rule
   passes". `Strategy2.sellRulesFor` shows the guard.
4. Add a row to the inventory table above, and file anything you are unsure
   about — a rule you could not measure, a case you deliberately allowed — in
   [STRATEGY_ANALYSIS_TODO.md](STRATEGY_ANALYSIS_TODO.md) (Rule 0). Shipping a
   strategy with a known open question is fine; leaving it unrecorded is not.
5. Rules that express *this strategy's identity* belong in code, like the ones
   here. Anything tunable — caps, thresholds, lifecycle counts — belongs in
   `TradeConfig` instead; see
   ["Hardcoded vs config-driven"](ORDERS_AND_POSITIONS.md#hardcoded-vs-config-driven).
