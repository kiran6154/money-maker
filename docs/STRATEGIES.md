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
| 3 | [`Strategy3`](../src/main/java/com/moneymaker/strategy/Strategy3.java) | Baseline **inverted**: BUY entry on the cross-**up** + up-trend, SELL exit at the close signal. Requires `transaction_type = BUY`. |
| 4 | [`Strategy4`](../src/main/java/com/moneymaker/strategy/Strategy4.java) | Baseline detection **unchanged, execution inverted**: the sell signal is placed as a BUY, the close-time exit as SELL. Requires `transaction_type = BUY`. |
| 5 | [`Strategy5`](../src/main/java/com/moneymaker/strategy/Strategy5.java) | **Pressure** — not an SMA strategy at all. Scores NIFTY 5-min **spot** on RSI / VWAP / Supertrend / opening range / ADX and trades the continuation on an exact-offset option leg. See [PRESSURE_STRATEGY.md](PRESSURE_STRATEGY.md). |
| 6 | [`Strategy6`](../src/main/java/com/moneymaker/strategy/Strategy6.java) | Strategy 2 **plus three entry gates**: the leg's 15-minute SMA-50 must be in a whole-day down-trend (unknown allows), no entry bar after 14:45, and a `STOP_LOSS` exit locks the book for the day. |
| 7 | [`Strategy7`](../src/main/java/com/moneymaker/strategy/Strategy7.java) | Strategy 6 **plus the first-hour regime gate**: after 10:15, no entry on a leg whose side the underlying's first hour moved against by more than 0.2 × ATR-14 (unknown allows; opening-bar entries untouched). |
| 8 | [`Strategy8`](../src/main/java/com/moneymaker/strategy/Strategy8.java) | **20SMA 15min candle** — not an SMA-cross. On the leg's own 15-minute candles: SMA-20 of closes sloping down **and** close below the previous close → SELL; no cross gate, no down-trend rule. Exits on a **chandelier trail** (peak − 2 × ATR-14, `trail_atr_multiple`), no target (`target_mode = NONE`), 14:45 cut-off, 15:15 close signal. |

**Strategies 1–4, 6, 7 and 8** extend
[`AbstractSmaCrossStrategy`](../src/main/java/com/moneymaker/strategy/AbstractSmaCrossStrategy.java),
which holds *everything* except the id and the rule sets: cache-key ownership
matching, the premium sort, the SMA-cross gate, the entry price band, the
signal emission. Strategies 1 and 2 override none of it, so those two are
identical apart from the one rule described below; strategy 3 additionally
flips the engine's *detection* direction, and strategy 4 keeps the baseline
detection and inverts only the *emitted* action (see their sections).

> **Strategy 5 is a different lineage and everything below this line is about
> 1–4.** It subclasses the same base only to share its small helpers and keep one
> registration shape, but it **fully replaces `execute`** — none of the shared
> engine described in the next section runs for it. Its decision input is the
> underlying, not the option premium; it emits entries only, with no exit signal;
> and it resolves one exact strike rather than ranking a set. Do not reason about
> it from this page — read
> [PRESSURE_STRATEGY.md](PRESSURE_STRATEGY.md) instead.

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

   That is the **sell-entry** path, used by strategies 1 and 2. A strategy whose
   `entryAction()` is BUY (strategy 3) runs the mirror,
   `RuleEngine.decideBuyEntry(...)`: `open < SMA && close > SMA` → BUY
   candidate gated by the buy rules, with the sell rules running ungated as the
   exit leg.

   Detection and emission are separate seams: whatever path detected the
   action, `mapAction(...)` (identity by default) maps it to what is actually
   emitted. Strategy 4 overrides only that — baseline detection, inverted
   emission. Strategies whose *emitted* entry is BUY are also guarded at the
   top of `execute`: a config whose `transaction_type` contradicts it is
   skipped with a once-per-(strategy, config, day) WARN.
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

## Strategy 3 — the inverted baseline (buy side)

`Strategy3` is Strategy 1 with every signal direction flipped, applied to the
leg being scanned:

| | Strategy 1 (sell entry) | Strategy 3 (buy entry) |
|---|---|---|
| Entry gate | `open > SMA && close < SMA` (cross-down) | `open < SMA && close > SMA` (cross-up) |
| Entry rule (required) | `isSmaNNDownTrending` | `isSmaNNUpTrending` |
| Entry action | SELL | BUY |
| Exit (anyOf, ungated) | `isMarketCloseTime` → BUY | `isMarketCloseTime` → SELL |

The engine plumbing is `entryAction()` (overridden to BUY), which routes the
decision through `RuleEngine.decideBuyEntry(...)` instead of
`RuleEngine.decide(...)`. Scanning, premium sort, price band, cache-key
matching, and the stale-bar / stale-key guards are all inherited unchanged.

**How this expresses "PE sell becomes CE buy".** A strategy only scans and
trades its own config's `trading_side` — the ledger requires the traded option
type to match the config (see the `keyMatches` history in
`AbstractSmaCrossStrategy`). So the inversion pairs at **config level**: tag
the CE-side config with strategy 3 (and `transaction_type = BUY`), and at the
market moment the sibling PE config fires Strategy 1's cross-down SELL (index
rising, PE premium falling), the CE leg is the mirror image — its premium
crossing *up* through its own SMA with the SMA up-trending — and strategy 3
fires BUY on it. Symmetrically, a PE config tagged with strategy 3 buys puts
when a CE leg would be firing sells. The equivalence is structural, **not
tick-exact** — each leg is judged on its own candle series, so the paired
signals land on the same market move but not necessarily the same bar. That
open question is
[S19](STRATEGY_ANALYSIS_TODO.md#s19-strategy3s-mirror-equivalence-to-strategy-1-is-structural-not-tick-exact--and-unmeasured).

**Config prerequisites.** `transaction_type = BUY` is required, not just
conventional: on a SELL config the strategy's BUY entries would be discarded by
`OrderService` (direction mismatch) while its close-time SELL *exit* signal
would be mistaken for a fresh short entry. The guard at the top of
`AbstractSmaCrossStrategy.execute` (shared with strategy 4) therefore refuses
to scan a non-BUY config, with a once-per-(strategy, config, day) WARN. This is
a mis-configuration guard, not a trading rule.

**Enablement tracks the baseline; rule content does not.** A period with no
baseline sell rules (20, or anything without a `case`) stays fail-closed in
strategy 3 too — `buyRulesFor` derives enablement from
`super.sellRulesFor(period)` being non-empty. But the mirroring of the rule
*content* is by hand: a predicate added to the baseline sell rules later does
not acquire an inverse here automatically.

**Auto-config generation.** Like every strategy, 3 generates `AUTO_DOWNTREND`
configs only once its `strategy_defaults` row and `sma_downtrend_rule_strategy`
tags exist ([EOD_DOWNTREND.md](EOD_DOWNTREND.md#table-strategy_defaults)). Its
row wants `transaction_type='BUY'` and `opposite_side=TRUE` (changeset 040): the
detector detects a *downtrend* per leg, and the mirror trade belongs on the
*other* leg — a PE ending the day downtrending yields strategy 3 a CE BUY
config, the same day strategy 1 gets its PE SELL config.

---

## Strategy 4 — Strategy 1's detection, inverted at execution

`Strategy4` takes Strategy 1's sell signal **as-is** and places the opposite
order on it. Nothing about detection changes — same legs, same cross-down gate,
same `isSmaNNDownTrending` requirement, tick for tick — only what gets emitted:

| | Detected (Strategy 1's engine) | Emitted by Strategy 4 |
|---|---|---|
| Cross-down + down-trend | SELL | **BUY** |
| Close-signal time (ungated) | BUY | **SELL** (closes the long) |

The plumbing is `mapAction(...)`: the strategy overrides nothing else — not
`entryAction()`, not a single rule builder — so a config tagged `1,4` detects
on identical ticks under both strategies and books mirror-image entries.
Brackets need no special casing: target, stop-loss, the SL ceiling and the
trailing ladder all key off `entry_direction` in `OrderService` /
`PositionService`, so the config's same numbers apply on the long side (SL
fires when the premium falls, target when it rises).

**Contrast with strategy 3.** Strategy 3 *mirrors the detection* onto the
traded leg (cross-up + up-trend) — same market view as the baseline's sell,
expressed long on the opposite-side config. Strategy 4 *keeps the detection*
and fades it: it buys the very option whose premium just crossed down in a
day-long downtrend — long against the detected momentum, with theta also
against the position. That is the specified design (2026-09-04), and its
economics are deliberately left to measurement — see
[S20](STRATEGY_ANALYSIS_TODO.md#s20-strategy4-buys-the-falling-option--the-fade-is-specified-but-unmeasured).

**Config prerequisites.** `transaction_type = BUY`, enforced by the same
`AbstractSmaCrossStrategy.execute` guard as strategy 3 — on a SELL config the
mapped entries would be discarded while the mapped close-time SELL would open a
fresh short at 15:15.

---

## Strategy 6 — Strategy 2 with higher-timeframe confirmation, an entry cut-off and a stop-loss lock

`Strategy6` extends `Strategy2` (so `sma20SlopeNotUp` is inherited) and
appends two required sell rules; a third gate is a ledger question and is
declared on the bean but enforced by `OrderService`:

| Gate | Where it lives | What it does |
|---|---|---|
| `htf15Sma50DownOrUnknown` | [`CommonRules.higherTimeframeSmaDownTrending`](../src/main/java/com/moneymaker/strategy/rules/CommonRules.java) | Blocks the entry when the **same leg's 15-minute series** carries `isSma50DownTrending = false` on its newest settled bar (`SmaTrendCalculator`, `maxDeviations = 0` — the SMA-50 must have fallen on every 15-minute bar of the session). Applies to every primary period and to 5- and 15-minute signals alike. |
| `entryAtOrBefore1445` | [`CommonRules.isAtOrBeforeEntryCutoff`](../src/main/java/com/moneymaker/strategy/rules/CommonRules.java) | The signal bar must start at or before `closeSignalTime − 30 min` — 14:45 on the standard session. Follows `app.market.*` rather than carrying a second clock. |
| stop-loss lock | `Strategy.stopLossLocksBookForDay()` → [`OrderService.handleSignal`](../src/main/java/com/moneymaker/order/service/OrderService.java) gate 6 | Once this `(config, strategy)` has exited `STOP_LOSS` today, nothing further opens on that config for the session. `TRAIL_SL` does not lock. Read from `trade_order`, so a restart cannot forget it. |

The rule order in the `[tick]` log is baseline down-trend, `sma20SlopeNotUp`,
`htf15Sma50DownOrUnknown`, `entryAtOrBefore1445` — a blocked entry names the
first rule that failed.

**Unknown allows.** The confirmation rule is tri-state and lets the entry
through whenever the question cannot be answered: no 15-minute series cached
for the leg, the series not refreshed by this tick (the S8 stale-key rule), its
newest settled bar belonging to an earlier session — which is every tick before
09:30, so the day's first three 5-minute bars are judged on their own — or
SMA-50 not yet stamped on that bar. This is the same convention as
`isSma20SlopeUp`, and it is deliberate: the 09:15 entries were the replay's best
slice, and gating them on evidence that does not exist yet cost 200 points
(see S21). The full case list is on the method's Javadoc.

**Where the 15-minute series comes from.** The bean declares
`confirmationTimeframes() = {15}`, and `AnalysisScheduler` unions that into the
fetch set for every config the strategy is tagged on — gathered across *all*
tags before the once-per-config fetch, so a config tagged `1,6` gets the series
on strategy 1's turn too (see
[SCHEDULERS.md → AnalysisScheduler](SCHEDULERS.md#analysisscheduler)). The
series is keyed exactly like a traded interval, and the rule finds it by
swapping the interval segment of its own cache key (`RuleContext.strikeKey`).
The config's own `sma_timeframe` rows need not name 15 minutes.

**Why these three, and why the slope filter stays.** Replaying strategies 1
and 2 over the dbviewer NIFTY series (Dec-2023 → Dec-2025, 1,581 / 963
trades) the three gates were the ones that survived a rank-on-2024 /
read-2025 check; the slope filter on its own was noise (the trades it blocks
average the same as the ones it lets through) but on top of the other three it
raised the profit factor from 1.17 to 1.28 and was the only variant positive in
every half-year. Numbers, the variant grid and the caveats (in-sample selection,
unverified charge rates, lot 75 throughout) are in
[S21](STRATEGY_ANALYSIS_TODO.md#s21-strategy6s-three-gates-are-replay-selected--the-constants-are-strategy-identity-not-config).

**Config prerequisites.** `transaction_type = SELL`, like strategies 1 and 2.
Tag an existing config `"1,2,6"` (or `"2,6"`) to run it alongside the others —
each strategy keeps its own caps, budget and position. For `AUTO_DOWNTREND`
generation, changeset 046 seeds its `strategy_defaults` row as a copy of
strategy 1's block (so the two share one generated config, `"1,…,6"`); what
remains is the operator's decision to tag it on the rule, one row per rule:

```sql
INSERT INTO sma_downtrend_rule_strategy (rule_id, strategy_id, enabled)
SELECT rs.rule_id, 6, TRUE
  FROM sma_downtrend_rule_strategy rs
 WHERE rs.strategy_id = 1 AND rs.enabled = TRUE;
```

**Leave the knobs where strategy 1 has them.** Every config-level change that
helps strategy 1 on its own (`no_of_trades = 2`, 5-minute rules only, SMA-200
dropped, `min_option_price = 100`) makes strategy 6 *worse* — 2,021 → 1,882 /
1,071 / 1,889 / 1,567 points in the replay — because the three gates already
remove the trades those knobs remove, and the knobs then cut good ones. The
same holds for the bracket (`target_pct` 0.25 / `sl_pct` 0.25: 1,856;
`max_sl_points` 45: 1,584) and the close signal (15:00: 2,069, a wash).
The detector's `max_deviation` barely matters (0 / 2 / 5 → PF 1.29 / 1.30 /
1.28). Numbers in S21.

The three numbers on the bean (`15` minutes, SMA `50`, `30` minutes before the
close signal) are strategy identity — what makes a config tagged 6 differ from
one tagged 2 — and deliberately not `TradeConfig` columns yet; that question is
recorded in S21 rather than guessed at (CLAUDE.md #9).

## Strategy 7 — Strategy 6 with the first-hour regime gate

`Strategy7` extends `Strategy6` and appends one required sell rule,
`firstHourNotAgainstOrUnknown`
([`CommonRules.firstHourMoveInFavourAtr`](../src/main/java/com/moneymaker/strategy/rules/CommonRules.java)):
for a signal bar starting at or after **10:15**, the underlying's first-hour
move (session open → last bar before the checkpoint), signed in the leg's
favour (down for a CE config, up for a PE config) and divided by ATR-14 of the
preceding sessions, must be **≥ −0.20**. A CE is not sold into a morning that
rose more than a fifth of a day's range; a PE is not sold into one that fell
that much. Entries before 10:15 — the opening-bar trades — are not judged.

The rule comes from the intraday regime study's 10:15 checkpoint, reshaped for a
one-sided short. Tagging every replay trade by how its day ended shows why it
is the right shape: sideways days pay (Strategy 6: 367 trades, +1,866 pts, PF
1.45), favourable trends pay more (110, +2,036, PF 3.93) and **all** the losses
are trend-against days (84, −1,881, PF 0.23). Nothing known at the open flags
those days — the gap rule (|open − prev close| ≤ 0.5 ATR) and the expected-move
level were both tried and rejected — but the first hour's direction is the best
partial tell for the afternoon: the after-10:15 entries this gate removes were
trend-against days 35% of the time against a 14% base rate. Replay: **525
trades, +2,125 pts, PF 1.31**, positive in all four half-years (Strategy 6:
561, +2,021, 1.28); flat across thresholds −0.1…−0.3 and with the 09:15 ATM
straddle as the normaliser instead of ATR (S22).

**Data it reads.** The underlying series `AnalysisScheduler` already caches
under `token|interval` (the first two segments of the leg's own cache key), at
the signal's interval — a 15-minute signal reads 15-minute buckets, whose 10:00
bucket closes on the same print as the 10:10 five-minute bar. ATR-14 is rolled
up from that series' completed prior sessions (the detector sizes strike depth
from the same quantity off daily bars; they agree to within the 15:30 print).
**Unknown allows**, as for the 15-minute confirmation: before the checkpoint, no
side on the config, no underlying series, the session's first bar missing (day
starts after 09:30), fewer than 5 prior sessions, zero range.

**Config prerequisites.** Same as Strategy 6: `transaction_type = SELL`;
changeset 047 seeds its `strategy_defaults` row as a copy of strategy 1's;
tagging it on a rule is the operator's decision (the same one-row-per-rule
`INSERT` as Strategy 6 with `7`). Tag `"1,6,7"` to run all three on one
generated config — each keeps its own caps, budget, lock and position — and
diff the 6 and 7 ledgers to see exactly which trades the gate removed.
The checkpoint (10:15) and threshold (0.20 ATR) are strategy identity, not
`TradeConfig` columns (S21 open question (a) applies).

## Strategy 8 — the "20SMA 15min candle" rule, no cross gate, chandelier exit

Defined 2026-09-06 from the user's rule and the dbeaver-export replay (S29 in
[STRATEGY_ANALYSIS_TODO.md](STRATEGY_ANALYSIS_TODO.md) has the numbers).
[`Strategy8`](../src/main/java/com/moneymaker/strategy/Strategy8.java) reuses
the shared engine's scan, premium sort, stale-bar guard, price band and signal
emission, but **not its trigger**: it overrides the new
`AbstractSmaCrossStrategy.decide(...)` hook to route its rules through
`RuleEngine.decideWithoutCrossGate`, so the SMA-cross gate and the per-period
down-trend rules never run for it.

**Entry (SELL), all required, in this order:**

| Rule | What it checks |
|---|---|
| `is15MinuteSeries` | The cache key's interval segment is `15minute`. The rule reads the *traded* series, so the config needs a 15-minute `sma_timeframe` row; `execute` narrows the config to its first such row (one evaluation per leg per tick) and logs once a day when there is none. The row's SMA period does not matter. |
| `sma20SlopeDown` | Plain 20-bar mean of closes on the newest settled bar is below the same mean one bar earlier. Consecutive bars of the series, across the session boundary, exactly as a chart draws it; needs 21 bars (the 35-day 15-minute lookback gives hundreds). |
| `closeBelowPrevClose` | The bar closes below the previous bar's close. |
| `entryAtOrBefore1445` | Bar starts at or before close-signal − 30 min ([`CommonRules.isAtOrBeforeEntryCutoff`](../src/main/java/com/moneymaker/strategy/rules/CommonRules.java)), as Strategy 6. |

**Exit:** the standard close-signal BUY (`isMarketCloseTime`) plus the ledger
exits: the chandelier floor (below) and the config's `sl_pct` / `max_sl_points`
as the hard cap on the first stop. No profit target — changeset 048 seeds
`strategy_defaults.target_mode = NONE`, the new `BracketMode` value that makes
`bracketAtEntry` return null. `stopLossLocksBookForDay()` is false: the replay
re-entered after stops.

**The chandelier trail** ([ORDERS_AND_POSITIONS.md](ORDERS_AND_POSITIONS.md#trailing-stop-loss-changeset-036)):
the signal carries ATR-14 of the 15-minute series (`TradeSignal.atr`, set by
`Strategy8.signalAtr`); `OrderService` freezes `trail_atr_multiple × ATR` onto
`trade_order.trail_atr_distance_at_entry` and drops the ladder for that trade;
`PositionService` then floors the stop at `peak_profit − distance` on every
tick, so the stop starts at entry + 2 × ATR (or the `sl_pct` cap if tighter)
and only ratchets down. Fills at the floor, `exit_reason = TRAIL_SL`.

**Replay it was built from** (Python replica on the dbeaver export, Jan-2024 →
Dec-2025, ATM leg only, 1 pt/round-trip cost): intraday, chandelier 2 × ATR:
1,780 trades, +2.0/trade, +3,532 pts, PF 1.16; the same entries carried to the
weekly expiry: 1,060 trades, +6.0/trade, +6,366 pts, PF 1.43, max drawdown −423.
The always-in baseline with the same exit (no signal) made +5,518 pts held to
expiry: the rule is a quality filter on theta, not the source of the profit.
**This bean is the intraday form**; holding to expiry needs the carry-over
work listed in S29.

**Config prerequisites:** `transaction_type = SELL`, a 15-minute
`sma_timeframe` row, the `strategy_defaults` row from changeset 048, and — for
`AUTO_DOWNTREND` generation — a `sma_downtrend_rule_strategy` tag the changeset
deliberately does not add. Note the detector only writes a 15-minute row when
it found a down-trend on that width, so the ATM leg the replay traded on every
bar is not always what a tagged config offers; a hand-made config with a
15-minute row and depth 0 is the faithful setup.

---

## Adding a strategy

1. Extend `AbstractSmaCrossStrategy`, annotate `@Component`, return a fresh id
   from `getId()`. `StrategyFactory` discovers it via `List<Strategy>` injection
   and the admin dropdown picks it up automatically.
2. To **narrow** the baseline, wrap `super.sellRulesFor(...)` /
   `super.buyRulesFor(...)` rather than rebuilding the rule lists — that way a
   later change to the baseline rules reaches your strategy too. To flip the
   *detection* direction, override `entryAction()` (see `Strategy3`); to keep
   detection and flip only the *emitted* action, override `mapAction(...)`
   (see `Strategy4`). Either way the emitted-entry `transaction_type` guard in
   `AbstractSmaCrossStrategy.execute` covers you automatically. A rule that
   needs the leg on another interval declares it in `confirmationTimeframes()`
   and reads it through `RuleContext.strikeKey` (see `Strategy6`); a rule that
   needs the ledger is declared on the bean and enforced in `OrderService`
   (`stopLossLocksBookForDay()`), never queried from inside a `TradeRule`.
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
