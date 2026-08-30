# Strategy analysis — TODO & open questions

**This is the single backlog for everything strategy-related.** Every gap, open
question, suspected mis-signal, parameter worth revisiting, or analysis
follow-up that concerns a `Strategy` bean, its rules, or the signals it emits is
recorded here — **not** in [`GAPS.md`](GAPS.md), and not as a `// TODO` comment
in the tree.

> **Why separate from `GAPS.md`.** `GAPS.md` is infrastructure debt — schedulers,
> wiring, schema, delivery. The items here change **what trades get taken**, so
> they need a different bar before anything is acted on: each one wants a
> measured impact from a backtest run, not just a code fix, and each one is a
> live-behaviour change that must be confirmed with the user first. Mixing the
> two buries the trading questions in a list of plumbing chores.

For what the strategies currently *do*, see [`STRATEGIES.md`](STRATEGIES.md).
This page is only what is unresolved about them.

---

## Working rules for this file

1. **Every strategy gap lands here first.** If you notice it while doing
   something else, write the entry before you move on — a strategy question left
   in a commit message or a code comment is lost.
2. **Never state an impact you have not measured.** Write `Impact | Unquantified`
   and say what would measure it. A guessed trade-count delta is worse than an
   admitted unknown, because the next reader will act on it.
3. **Never change strategy behaviour to close an entry without asking.** These
   are live trading rules. Propose, get confirmation, then re-run the same
   backtest window before and after and record both numbers in the entry.
4. **Resolved entries stay**, moved to the bottom with the date and what the
   measurement showed. The rejected options matter as much as the chosen one.

Entry format matches `GAPS.md`: **what** / **where** / **why** / **impact** /
**fix sketch** / **effort**. Effort legend: **S** < 1 hour, single file · **M**
half-day, 2-4 files + doc · **L** multi-day, schema or cross-cutting.

Ids are `S<n>` so they never collide with `GAPS.md` numbering.

---

## Open

### S1. `Strategy2`'s SMA-20 slope filter is inert when the slope is unknown — **PARKED 2026-08-30**

| | |
|---|---|
| Where | [`CommonRules.isSma20SlopeUp`](../src/main/java/com/moneymaker/strategy/rules/CommonRules.java), consumed as the `sma20SlopeNotUp` required rule in [`Strategy2.sellRulesFor`](../src/main/java/com/moneymaker/strategy/Strategy2.java) |
| Why | The predicate needs two same-day SMA-20 values to compute a slope. When it cannot get them it returns `false` — "not sloping up" — and the SELL entry proceeds unfiltered, i.e. `Strategy2` degrades to `Strategy1` for that candle. **In practice one case dominates:** the day's first *settled* bar, whose predecessor in the series belongs to the previous session — an overnight gap, not a slope (`previousSameDayCandle` returns null; `SmaTrendCalculator` resets at the same boundary for the same reason). That recurs every session, on every leg, on every timeframe, and it lands on exactly the bar where a gap-up open would otherwise be filtered. Note the stale-bar guard added 2026-08-30 ([S3](#s3-stale-bar-guard-asof--resolved-2026-08-30)) does **not** remove this: it skips bars from an *earlier* session, so the first bar it lets through is precisely the one with no same-day predecessor. The other two cases are near-theoretical and should not drive the fix: SMA-20 warm-up only bites if the *whole* fetched series is under 20 candles (`SMAIndicatorImpl` returns null and stamps nothing only when `period > size`; inside the series it writes a partial-window value from the first candle), and the lookback window spans weeks — and a missing SMA-20 column requires a timeframe that does not register period 20 in `allTimeFrameMap`, which none currently do. Either way it is silent: the `[tick]` log shows `sma20SlopeNotUp` passing, indistinguishable from a genuinely flat or falling SMA. |
| Impact | **Unquantified.** The measurement is narrower than it first looked: count `Strategy2` SELL entries whose candle is the first settled bar of its session, per timeframe. Upper bound is one bar per leg per timeframe per day — so on a 5-minute series with ~75 bars it is ~1.3% of evaluated bars, but those bars are not average bars: they carry the overnight gap, which is when a rising SMA-20 is most likely to be exactly what the filter was meant to catch. Compare realised P&L on that subset against the rest before concluding it is negligible. |
| Decision (Rule 0) | **2026-08-30 — no change for now. Current behaviour stands: unknown slope allows the entry.** The direction to try *when* it is revisited is **treat the overnight gap as the slope** — i.e. let the predicate use the previous session's last SMA-20 as the comparison point instead of returning "unknown", so the day's first settled bar gets a real up/down answer rather than an exemption. Signed off as a deliberate park, not an oversight: the behaviour is documented in [STRATEGIES.md](STRATEGIES.md#strategy-2--the-sma-20-slope-filter) and in the `isSma20SlopeUp` Javadoc, so nothing is silently wrong in the meantime. |
| Caveat to carry into that attempt | Treating the gap as the slope answers a *different* question than the rule was written to ask, and the asymmetry matters: on a **gap-down** open the overnight move reads as "sloping down", so the filter would **permit** a sell it currently exempts — the opposite of tightening. Whoever picks this up should measure gap-up and gap-down opens separately; a single blended trade count will hide it. |
| If revisited, first | Make the two cases distinguishable before changing anything: have the rule report "slope unknown" separately from "slope down/flat" in its `TradeRule.named(...)` label, so a replay can be counted. Fetching more history is *not* a lever here — `previousSameDayCandle` rejects a cross-day predecessor by construction, not for want of data. The rejected alternatives were: fail closed (suppress until a same-day slope exists), and formally document the first-bar exemption as intended. |
| Effort | **S** — the change itself is a single predicate in `CommonRules`. The cost is the before/after measurement and the sign-off, not the code. |
| Priority | **Deferred** — parked by the user 2026-08-30, worth trying later. Not blocking; revisit alongside the next `Strategy2` backtest, when a before/after window is being run anyway. |

> Nothing here is a defect. The code matches its documentation — the Javadoc on
> `isSma20SlopeUp` and the STRATEGIES.md section both state the "unknown ⇒ allow"
> rule explicitly. This entry stays open only because a *better* default may
> exist, and it is parked until someone measures whether it does.

---

### S4. The 036 exit bracket — SL ceiling + trailing ladder — is shipped but unmeasured

| | |
|---|---|
| Where | [`OrderService.capStopLoss` / `trailLadderAtEntry`](../src/main/java/com/moneymaker/order/service/OrderService.java), [`PositionService.applyTrail` / `thresholdBreach`](../src/main/java/com/moneymaker/position/service/PositionService.java), [`TrailLadder`](../src/main/java/com/moneymaker/util/TrailLadder.java), changeset `036_add_trailing_stop_loss.xml`. Config: `trade_config.max_sl_points`, `trade_config.trail_ladder`. |
| Why | Requested by the user 2026-08-30: *"target can be more, sl should be less. keep max sl as 60 points … whichever is lower for sl. profit needs to be tailed, say after 25 points profit move sl to 2 points. then after 50 move sl to 25 points so on."* Built as specified. It changes **where open trades exit**, on both sides: the ceiling tightens the stop at the top of the premium band, and the ladder converts realised excursion into a floor. Every rung and the ceiling are config columns — nothing about the ladder is hardcoded — and existing rows were seeded with `60` / `25:2,50:25,75:50,100:75` by 036, so **this is live for every existing config, not opt-in**. |
| Correction (2026-08-30) | **The feature was inert when it first landed and for some hours after.** `max_sl_points` and `trail_ladder` were on the entity and in the DB but absent from `TradeConfigRepository.fetchCombinedByTradingDate`'s SELECT list and from `TradeConfigScheduler.mapToTradeConfig`, so every DTO in `SharedData.combinedDto` carried null for both: `capStopLoss` was a no-op and no trade ever trailed, in live and backtest alike, with nothing logged. Found by a peer session, verified, and fixed in the same query + mapper. **Any backtest run before that fix measures the absence of the feature, not the feature** — discard those numbers; a zero `TRAIL_SL` count from such a run is an artifact. Now guarded by `TradeConfigCombinedQueryContractTest`, which fails if the SELECT list drifts from the mapper ordinals again. |
| Impact | **Unquantified — no valid backtest has been run before or after.** Two effects that do not necessarily point the same way and must be measured separately: **(a)** the ceiling only binds above a ~200-point entry with `sl_pct = 0.30`, and cutting a 75-point stop to 60 converts some trades that would have recovered into realised losses; **(b)** the ladder can only exit a trade *green*, but it exits trades that would otherwise have reached the target, so it trades win-rate for average-win. What would measure it: re-run the same window (the Jan-2024 NIFTY option series that changeset 027 was measured on) with 035 and with 036, and compare exit-reason mix, win rate, mean P&L per trade and total P&L. `exit_reason = TRAIL_SL` is a distinct value precisely so the ladder's contribution is separable in that comparison; `peak_profit` on `TRAIL_SL` rows shows what each trade gave back. |
| Known dead zone | The first rung must be reachable before the target or the ladder never arms. With `target_pct = 0.20` an 80-point leg targets 16, below the 25-point first rung, so the ladder is **inert below a ~125-point entry** — i.e. on a meaningful slice of the standing 80-250 band. Whether the rungs should be premium-relative (like `target_pct`) rather than absolute points is the obvious follow-up, and is exactly what the measurement above would settle. Not changed speculatively: the user specified points. |
| Fix sketch | Nothing to fix yet — this entry exists to record that a live-behaviour change shipped without a measurement, per working rule 2. Run the before/after window, record both numbers here, then decide on the dead zone. |
| Effort | **M** — no code; the cost is the paired backtest run and reading the exit-reason mix. |
| Priority | **High** — it is already affecting every config's exits. |

---

### S6. `target_pct` / `sl_pct` never reach the running pipeline — the percentage bracket has never actually run

| | |
|---|---|
| Where | [`TradeConfigRepository.fetchCombinedByTradingDate`](../src/main/java/com/moneymaker/repository/TradeConfigRepository.java) SELECT list and [`TradeConfigScheduler.mapToTradeConfig`](../src/main/java/com/moneymaker/scheduler/TradeConfigScheduler.java). Consumed (or rather, not) by `OrderService.bracketAtEntry`. |
| Why | Same class of defect as the 036 one recorded in [S4](#s4-the-036-exit-bracket--sl-ceiling--trailing-ladder--is-shipped-but-unmeasured), found while fixing it, but **older and wider**. Changeset 027 added `target_pct` / `sl_pct` to `trade_config` and `OrderService.bracketAtEntry` prefers them over the absolute columns — but neither column is selected by the native combined query or set by the positional mapper. So `getTargetPct()` / `getSlPct()` are null on every DTO the pipeline ever sees, `bracketAtEntry` always takes its absolute-column fallback, and **every trade since 027 has exited on `trade_config.target` / `stop_loss` points, not on the percentage**. The percentage is persisted, is visible in the admin UI, is copied onto generated configs by `EodDowntrendDetectionService`, and is documented as the bracket that decides exits — it just never arrives. |
| Impact | **Unquantified, and deliberately not fixed.** Wiring two columns into a SELECT list is a one-line change, but its effect is a live behaviour change on every config: exits would switch from absolute points to a fraction of entry premium, which is precisely the change 027 measured as moving TARGET hit-rate from 45.4% to 53.9% on the Jan-2024 series. That is a Rule 0 change — it needs the user's sign-off and a before/after run on the same window, not a silent fix folded into someone else's ticket. **Left unwired pending that decision**, and called out in the query's Javadoc and in `TradeConfigCombinedQueryContractTest` so it cannot be mistaken for an oversight. |
| Note on 027's own numbers | The measured table in changeset 027 came from an offline sweep over the imported option series, not from the live pipeline — so it is not invalidated by this. What is invalidated is any assumption that the running system has been trading that bracket. |
| Fix sketch | Append `tc.target_pct, tc.sl_pct` to the end of the trade_config block (indices 22-23), add the two `setTargetPct` / `setSlPct` lines to `mapToTradeConfig`, bump `mapToInstrument` to 24 and `mapToInstrumentDetails` to 29, and extend `EXPECTED_COLUMNS` in the contract test. Then re-run the S4 window and report both brackets. |
| Effort | **S** for the code; **M** including the paired measurement and sign-off. |
| Priority | **High** — it silently contradicts what `ORDERS_AND_POSITIONS.md`, `EOD_DOWNTREND.md` and the admin UI all say is happening. |


### S5. Session-window constants are hardcoded while `app.market.*` already exists

| | |
|---|---|
| Where | [`CommonRules.isMarketCloseTime`](../src/main/java/com/moneymaker/strategy/rules/CommonRules.java) — `LocalTime.of(15, 15)`; [`BacktestAnalysisService`](../src/main/java/com/moneymaker/backtesting/BacktestAnalysisService.java) — `marketStart = 09:20`, `marketEnd = 15:20` |
| Why | Both decide **what trades get taken**, which is why this is here and not in `GAPS.md`. 15:15 is the exit trigger for every `buyRulesForNN`. 09:20 / 15:20 decide which ticks a replayed day contains at all — and the 15:20 cutoff is the reason a 15-minute bucket stamped 15:15 never settles in backtest, so 15-minute trades leave via end-of-day force-close rather than the close signal. Meanwhile `app.market.open` / `app.market.close` (09:15 / 15:30) and [`MarketHoursService`](../src/main/java/com/moneymaker/market/service/MarketHoursService.java) already exist and are the declared source of truth, so the codebase currently holds two different answers to "when does the session end". |
| Impact | **Unquantified, and no known incorrect behaviour** — the constants are internally consistent and were left alone deliberately during the 2026-08-30 stale-bar work. The cost is that changing the window in config silently does *not* move the exit rule or the replay bounds, and the 15:20-vs-15:30 asymmetry is invisible unless you read all three files. To size it: count how many exits land on the 15:15 signal versus force-close, per timeframe. |
| Fix sketch | Read the close time from `MarketHoursService` in `isMarketCloseTime` — `ctx.asOf` already carries the session, so the date is available — and derive the backtest day bounds from the same service, with the squareoff offset as an explicit `app.market.*` key rather than a literal. |
| Caution | **Changes when trades fire**, so it needs a before/after ledger diff on a fixed window and explicit user sign-off, and should not ride along with an unrelated change. Note the diff is only meaningful against a post-[S3](#s3-stale-bar-guard-asof--resolved-2026-08-30) baseline. |
| Effort | **S** to move the values; **M** including the ledger diff. |
| Priority | _TBD_ |

---

### S7. Signal flip-flop consumes the daily trade cap with near-immediate round trips

| | |
|---|---|
| Where | Signals emitted by [`AbstractSmaCrossStrategy`](../src/main/java/com/moneymaker/strategy/AbstractSmaCrossStrategy.java), drained by [`OrderService`](../src/main/java/com/moneymaker/order/service/OrderService.java); cap: `trade_config.numberOfTradesPerDay` |
| Why | Observed in the 2024-01-02…04 verification run (18 trades, 2026-08-30 session): every exit was `SIGNAL` — zero TARGET, zero STOP_LOSS — and several were near-immediate round trips on the same leg (orders 242/243 re-entered 21500 CE at 177.10/177.90 ten minutes apart; 257/258/259 did the same on 21500 CE). With `numberOfTradesPerDay = 5` the daily cap is consumed by SMA-cross flip-flop rather than by trades reaching a bracket. Not a defect — the band, side, and dedupe checks all passed in that run — but it may not be the intended use of the cap. |
| Impact | **Unquantified.** Measure on a fixed window: count same-leg re-entries within one candle interval of the previous exit, and compare their net P&L (charges included) against the remaining trades. The S4/S6 measurement runs on the Jan-2024 window can produce this count from the same ledger at no extra cost. |
| Fix sketch | Nothing until measured and signed off. Every candidate lever (re-entry cooldown on the same leg, minimum holding time, hysteresis on the SMA cross) changes entry timing, so per working rule 3 and the no-hardcoding rule it would need new `TradeConfig` fields, a user decision, and its own before/after pair — never a constant in code. |
| Effort | **M** — the measurement is the work; a config-driven cooldown after it is **S–M**. |
| Priority | _TBD — flagged to the user 2026-08-30, no decision yet._ |

---

## Resolved

### S2. `Strategy1` scanned every config's legs, not its own — **RESOLVED 2026-08-25**

*Moved here from `GAPS.md` #19 on 2026-08-30 when this file was split out.*

| | |
|---|---|
| Where | `keyMatches`, now on [`AbstractSmaCrossStrategy`](../src/main/java/com/moneymaker/strategy/AbstractSmaCrossStrategy.java) (it lived on `Strategy1` until the base class was extracted on 2026-08-30), reading [`SharedData.strikeMarketDataByInstrumentAndInterval`](../src/main/java/com/moneymaker/shared/data/SharedData.java) written by [`AnalysisScheduler.toStrikeMarketDataKey`](../src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java) |
| Why | The writer keys each entry `instrumentToken\|interval\|optionType\|strike\|optionToken\|itmDepth\|otmDepth` and contributes only the legs of the config that fetched them. The reader matched an `instrumentToken\|interval\|` **prefix** only — `optionType` and both depths were never compared. `trading_side` reached the strategy solely as the sort direction (`strikeComparator(isCe)`), never as a filter, so every config scanned the union of all configs' legs. |
| Impact | On any day with the normal CE + PE config pair, each signal fired once under each config id and the ledger recorded **every trade twice**, with half the rows carrying an option type contradicting their own config's `trading_side` (e.g. a PE trade booked under a CE config). Realised P&L over such a run is doubled. The `existsByTradeConfigIdAndOptionTokenAndEntryDirectionAndEntryTime` dedupe guard could not catch it — it keys on `tradeConfigId`, so the pairs are legitimately distinct rows. Where several legs fired on one tick the two configs landed on *different* strikes instead of identical ones, because they sort in opposite directions and `no_of_parrellel_trades` cut the scan short at opposite ends — which is why the duplication was not uniform and read as "sometimes the wrong strike". |
| Resolution | `keyMatches` now splits the key and compares `optionType` against the config's resolved `trading_side` plus both depth segments against the config's own. `isCallSide` became `resolveOptionType`, mirroring `AnalysisScheduler.resolveOptionType` including its null-on-unresolved behaviour — the writer skips the fetch for an unresolved side, so defaulting to CE would have made such a config scan someone else's legs. |
| Related | Sibling of [`GAPS.md` #18](GAPS.md#18-shareddataoptiontokenmap-was-keyed-by-strike-alone--resolved-2026-08-22) — same root shape (a shared cache whose key was less specific than its contents), different map. Also worth re-reading alongside the `(tradeConfigId, strategyId)` ledger identity introduced by changeset 031: two strategies now legitimately share a config and each hold their own position on the same leg, which is the *intended* version of what this bug did accidentally. |
| Effort | **S** |

### S3. Stale-bar guard (`asOf`) — **RESOLVED 2026-08-30**

| | |
|---|---|
| Where | [`Strategy.execute(TradeConfigCombinedDTO, LocalDateTime asOf)`](../src/main/java/com/moneymaker/strategy/Strategy.java) → [`StrategyFactory.execute`](../src/main/java/com/moneymaker/strategy/StrategyFactory.java) → [`AbstractSmaCrossStrategy.execute`](../src/main/java/com/moneymaker/strategy/AbstractSmaCrossStrategy.java); tick supplied by [`AnalysisScheduler.runStrategies(asOf)`](../src/main/java/com/moneymaker/scheduler/AnalysisScheduler.java) from [`BacktestAnalysisService`](../src/main/java/com/moneymaker/backtesting/BacktestAnalysisService.java) |
| Why | Per the interface Javadoc: a strategy must not act on a bar belonging to an earlier session than `asOf`. The candle series spans the whole SMA lookback and ends at the newest bar **settled** by `asOf`, so for a coarse timeframe that bar is still the previous session's close until the day's first bucket completes — on a 15-minute series, until 09:30. |
| Impact | **Quantified, not hypothetical.** In the 2024 replay (88 ledger rows) it produced **13 exits stamped before their own entry** — `exit_price` matching the previous session's last 15-minute bar close exactly — and **2 entries** stamped on the previous session's 15:15 bar, which then read as overnight holds in an intraday system and were closed the next day by the position monitor. Every affected entry fell on the day's first two ticks (09:15 / 09:20), and every affected config carried a 15-minute timeframe. `Strategy2`'s SMA-20 slope rule was comparing two of yesterday's bars in the same window — see [S1](#s1-strategy2s-sma-20-slope-filter-is-inert-when-the-slope-is-unknown--parked-2026-08-30). |
| Decision (Rule 0) | **Skip the leg for this tick.** The alternative — walking back to the newest in-session bar — was rejected: on the day's first ticks there is no in-session bar for a coarse timeframe to walk back to, so it would either find nothing or silently substitute a finer timeframe's bar and misreport which timeframe fired. "This timeframe has no settled bar yet today" is the honest answer. Signed off with the two consequences stated explicitly: a 15-minute timeframe emits no signal before 09:30, and 15-minute trades continue to exit via end-of-day force-close rather than the 15:15 close signal (unchanged — bucket 15:15 settles at 15:30, after the backtest day loop's 15:20 cutoff). |
| Resolution | `AbstractSmaCrossStrategy` skips any leg whose newest settled bar pre-dates `asOf`'s date, logging the reason on the `[tick]` line. Only the decision is suppressed — the bars behind it still feed the SMA. [`CommonRules.isMarketCloseTime`](../src/main/java/com/moneymaker/strategy/rules/CommonRules.java) additionally asserts the candle belongs to `asOf`'s session (via a new nullable `asOf` on [`RuleContext`](../src/main/java/com/moneymaker/strategy/rules/RuleContext.java), old constructor retained); that is redundant behind the guard but the predicate was wrong standalone. Documented in [STRATEGIES.md](STRATEGIES.md#the-shared-engine). |
| Related | Landed alongside a second, independent defect in the same replay: monitor-driven exits were priced off whichever cached interval hashed first, including a 10-minute series **no config asks for**. Fixed by `SharedData.latestCachedCandle` (finest cached interval) plus scoping the `AnalysisScheduler` fetch to the config's own timeframes. Both fixes change the ledger by design — see the re-baseline note in [BACKTEST_PERFORMANCE.md](BACKTEST_PERFORMANCE.md#parity-verification-checklist). |
| Effort | **S** |

---

## Not tracked here

- **`stratergy_id` column-name typo** — schema naming, not strategy behaviour.
  Stays at [`GAPS.md` #10](GAPS.md#10-tradeconfigstratergyid--column-name-typo).
- **Indicator correctness** (SMA source = candle low, EMA/RSI stubs) — those are
  `indicator/` concerns. `GAPS.md` #15 covers the stubs; the deliberate
  low-vs-close choice is documented in `SMAIndicatorImpl`'s Javadoc.
- **How a config reaches a strategy** (the `trade_config.strategy_ids` fan-out from
  changeset 031) — that is routing, described in
  [STRATEGIES.md](STRATEGIES.md). An entry belongs here only when it changes
  which *signals* a strategy emits.
