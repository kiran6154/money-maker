package com.moneymaker.tradeconfig.generation;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaDowntrendRule;
import com.moneymaker.entity.SmaDowntrendRuleStrategy;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.StrategyDefaults;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.indicator.IndicatorConfig;
import com.moneymaker.indicator.IndicatorService;
import com.moneymaker.market.exception.HistoricalDataMissingException;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.market.service.MarketDataService;
import com.moneymaker.market.service.TradingCalendar;
import com.moneymaker.repository.SmaDowntrendRuleRepository;
import com.moneymaker.repository.SmaDowntrendRuleStrategyRepository;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.StrategyDefaultsRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.strategy.rules.SmaTrendCalculator;
import com.moneymaker.util.StrategyIds;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * End-of-day downtrend detector.
 *
 * <p>At the close of each backtest trading day, for every enabled
 * {@link SmaDowntrendRule} we walk the fixed grid
 * {@link #SMA_PERIODS} × {@link #TIMEFRAMES_MINUTES} against the ATM
 * strike on both CE and PE. Per (side, timeframe) the strike's series is
 * fetched once, every {@link #SMA_PERIODS} SMA computed on it, and
 * {@link SmaTrendCalculator} runs with {@code rule.maxDeviation} starting
 * at {@code rule.startTime}. Every SMA whose last-candle down-trend flag
 * is still on is recorded as a passing combo for that side.</p>
 *
 * <p>For each side with at least one passing combo we insert exactly one
 * {@link TradeConfig} (next trading day, {@code source='AUTO_DOWNTREND'},
 * fields from the strategy's {@link com.moneymaker.entity.StrategyDefaults} row) plus one
 * {@link SmaTimeframe} child per passing combo.</p>
 *
 * <p><b>Exit bracket.</b> The generated config carries both shapes. The
 * enforced one is premium-relative — {@code target_pct} / {@code sl_pct}
 * copied off the rule, which {@code OrderService} turns into points against
 * the premium each trade actually opens at. The absolute
 * {@code target} / {@code stop_loss} are the fallback for a config with no
 * percentage, and are what {@code CommonRules.profitTarget} reads as an
 * entry gate; they come from {@link #averageIntradayRange} of the leg the
 * config will trade, times the rule's multipliers, capped by
 * {@link #clampToBandFloor}.</p>
 *
 * <p><b>Idempotency is per {@code (target day, strategy)}.</b> A strategy that
 * already has an {@code AUTO_DOWNTREND} config for the next trading day is
 * skipped; one that does not still generates. So replaying an unchanged range is
 * a no-op, while tagging a rule with a further strategy and replaying does fill
 * in that strategy's configs for days already covered by another. Delete a day's
 * generated rows to force a full re-write.</p>
 *
 * <p>Backtest-only today. Service is a Spring bean and the public entry
 * {@link #runForDay(LocalDate)} takes nothing backtest-specific, so a
 * future 15:25 cron can call it unchanged for live mode.</p>
 *
 * <p><b>Data-source agnostic.</b> Every symbol comes from
 * {@link OptionInstrumentResolver}, the same indirection {@code AnalysisScheduler}
 * uses, so the detector works against broker instrument tokens and against the
 * imported-CSV natural keys alike. It previously read {@code expiry_dates} /
 * {@code instrument_details} directly and resolved nothing at all under
 * {@code backtest.data-source=HISTORICAL_ICICI}, where neither table has rows.</p>
 *
 * <p>See {@code docs/EOD_DOWNTREND.md}.</p>
 */
@Slf4j
@Service
public class EodDowntrendDetectionService {

    private static final String SOURCE_AUTO = "AUTO_DOWNTREND";
    private static final LocalTime MARKET_CLOSE = LocalTime.of(15, 20);
    private static final LocalTime MARKET_OPEN  = LocalTime.of(9, 15);

    /** Tradable minutes in one NSE session (09:15–15:30). Used only to size the
     *  SMA lookback window — see {@link #lookbackCalendarDays(int)}. */
    private static final int SESSION_MINUTES = 375;

    /** Fixed SMA grid the detector evaluates. Add a period here AND extend
     *  {@code SmaTrendCalculator} / {@code MarketData} to track its flag. */
    static final int[] SMA_PERIODS = {50, 100, 200, 500};

    /** Fixed candle timeframes the detector evaluates (minutes). */
    static final int[] TIMEFRAMES_MINUTES = {5, 15};

    /** Safety rails on the ATR-derived strike band — see {@link #strikeDepthFor}. */
    private static final int MIN_STRIKE_DEPTH = 2;
    private static final int MAX_STRIKE_DEPTH = 6;

    /** NSE F&O price step. Market structure, not a trading rule — it is only used
     *  to land the clamped target one representable tick below the band floor. */
    private static final BigDecimal TICK_SIZE = new BigDecimal("0.05");

    private final SmaDowntrendRuleRepository ruleRepository;
    private final TradeConfigRepository tradeConfigRepository;
    private final SmaTimeframeRepository smaTimeframeRepository;
    private final SmaDowntrendRuleStrategyRepository ruleStrategyRepository;
    private final StrategyDefaultsRepository strategyDefaultsRepository;
    private final OptionInstrumentResolver instrumentResolver;
    private final MarketDataService marketDataService;
    private final IndicatorService indicatorService;
    private final TradingCalendar tradingCalendar;

    public EodDowntrendDetectionService(SmaDowntrendRuleRepository ruleRepository,
                                        TradeConfigRepository tradeConfigRepository,
                                        SmaTimeframeRepository smaTimeframeRepository,
                                        SmaDowntrendRuleStrategyRepository ruleStrategyRepository,
                                        StrategyDefaultsRepository strategyDefaultsRepository,
                                        OptionInstrumentResolver instrumentResolver,
                                        MarketDataService marketDataService,
                                        IndicatorService indicatorService,
                                        TradingCalendar tradingCalendar) {
        this.ruleRepository = ruleRepository;
        this.tradeConfigRepository = tradeConfigRepository;
        this.smaTimeframeRepository = smaTimeframeRepository;
        this.ruleStrategyRepository = ruleStrategyRepository;
        this.strategyDefaultsRepository = strategyDefaultsRepository;
        this.instrumentResolver = instrumentResolver;
        this.marketDataService = marketDataService;
        this.indicatorService = indicatorService;
        this.tradingCalendar = tradingCalendar;
    }

    /**
     * Runs every enabled rule against {@code tradingDay}'s close, emitting
     * one next-day {@code trade_config} per side per rule when at least one
     * (sma, timeframe) combo passes. Unscoped — every tagged strategy generates.
     */
    public void runForDay(LocalDate tradingDay) {
        runForDay(tradingDay, null);
    }

    /**
     * Scoped variant: only strategies in {@code strategyScope} generate
     * ({@code null} or empty = all). The scope is a per-run selection on top of
     * the standing DB setup — a strategy still needs its
     * {@code sma_downtrend_rule_strategy} tag (or the rule's fallback
     * {@code strategy_id}) plus an enabled {@code strategy_defaults} row; the
     * scope can only narrow that set, never widen it. Idempotency is untouched:
     * a scoped run skips strategies that already generated for the target day
     * and leaves the others' existing configs alone.
     */
    public void runForDay(LocalDate tradingDay, Set<Integer> strategyScope) {
        if (tradingDay == null) return;

        List<SmaDowntrendRule> rules = ruleRepository.findByEnabledTrue();
        if (rules.isEmpty()) {
            log.debug("[EOD-downtrend] {} — no enabled rules, skipping", tradingDay);
            return;
        }

        // The next *session*, not merely the next weekday. Sourced from the data
        // when replaying imported candles, so a market holiday is never handed a
        // config and a special Saturday session is never skipped.
        LocalDate nextDay = tradingCalendar.nextTradingDay(tradingDay);
        if (nextDay == null) {
            log.info("[EOD-downtrend] {} — no trading day follows in the calendar, nothing to generate", tradingDay);
            return;
        }

        // Which strategies already have a generated config for the target day.
        //
        // The guard used to be per *day*: any AUTO_DOWNTREND row for nextDay skipped
        // the whole run. That made the strategy tags un-actionable in hindsight —
        // tag a rule with a second strategy after a day had already generated, and
        // that strategy could never appear for it, because strategy 1's config was
        // enough to suppress the entire day.
        //
        // Now the unit is (day, strategy): a strategy that already generated for
        // nextDay is skipped, one that has not still generates. Re-running an
        // unchanged setup remains a no-op, which is the property the backtest relies
        // on when the same range is replayed.
        Set<Integer> alreadyGenerated = new HashSet<>();
        for (TradeConfig existing : tradeConfigRepository.findByTradingDateAndSource(nextDay, SOURCE_AUTO)) {
            alreadyGenerated.addAll(StrategyIds.parse(existing.getStrategyIds()));
            if (existing.getStratergyId() != null) {
                // Pre-035 rows may carry only the primary column.
                alreadyGenerated.add(existing.getStratergyId());
            }
        }

        int inserted = 0;
        for (SmaDowntrendRule rule : rules) {
            try {
                inserted += processRule(rule, tradingDay, nextDay, alreadyGenerated, strategyScope);
            } catch (Exception ex) {
                log.error("[EOD-downtrend] {} — rule id={} failed", tradingDay, rule.getId(), ex);
            }
        }
        log.info("[EOD-downtrend] {} — inserted {} AUTO_DOWNTREND trade_config(s) for {}{}",
                tradingDay, inserted, nextDay,
                strategyScope == null || strategyScope.isEmpty() ? "" : " (strategy scope " + strategyScope + ")");
    }

    // ------------------------------------------------------------------
    // Per-rule pipeline
    // ------------------------------------------------------------------

    private int processRule(SmaDowntrendRule rule, LocalDate tradingDay, LocalDate nextDay,
                            Set<Integer> alreadyGenerated, Set<Integer> strategyScope) {
        Instrument instrument = rule.getInstrument();
        if (instrument == null || instrument.getInsName() == null) {
            log.warn("[EOD-downtrend] rule id={} has no instrument, skipping", rule.getId());
            return 0;
        }

        // One entry per generated config: its field block plus the strategies tagged
        // onto it. Usually a single entry covering every tagged strategy — see
        // resolveConfigGroups.
        List<ConfigGroup> groups = resolveConfigGroups(rule, alreadyGenerated, strategyScope);
        if (groups.isEmpty()) {
            // Quiet when a scope is active: a rule whose strategies are simply not
            // selected this run is expected, not a misconfiguration. The per-strategy
            // skip reasons are still logged inside resolveConfigGroups either way.
            if (strategyScope == null || strategyScope.isEmpty()) {
                log.warn("[EOD-downtrend] rule id={} — no usable strategy, skipping", rule.getId());
            }
            return 0;
        }

        if (!hasUsableBand(rule)) {
            return 0;
        }

        LocalDate expiry = instrumentResolver.resolveExpiry(instrument, tradingDay);
        if (expiry == null) {
            log.warn("[EOD-downtrend] rule id={} — no expiry resolved for {} on {}",
                    rule.getId(), instrument.getInsName(), tradingDay);
            return 0;
        }

        // The contract the generated config will trade, which is not always the one
        // we detect the trend on. resolveExpiry returns the first expiry on or after
        // the date asked for, so on an expiry day `expiry` is the series dying at
        // today's close while the config being written is for tomorrow. Measuring the
        // exit bracket on the dying series is how a target ended up sized by the
        // expiry-day premium collapse — a move the fresh contract cannot repeat.
        LocalDate tradeExpiry = instrumentResolver.resolveExpiry(instrument, nextDay);
        if (tradeExpiry == null) {
            tradeExpiry = expiry;
        }

        Integer atmStrike = computeAtmStrike(instrument, tradingDay);
        if (atmStrike == null) {
            log.warn("[EOD-downtrend] rule id={} — cannot determine ATM strike for {} on {}",
                    rule.getId(), instrument.getInsName(), tradingDay);
            return 0;
        }

        // Strike band width, from how far the underlying can plausibly travel in a
        // session. This is not cosmetic: AnalysisScheduler only fetches candles for
        // the strikes it derives from the live ATM, so a band narrower than the day's
        // movement orphans an open position the moment spot crosses a strike boundary
        // — its cached series stops refreshing and PositionService then evaluates
        // target/SL against a frozen quote.
        int strikeDepth = strikeDepthFor(
                computeAtr(instrumentResolver.underlyingSymbol(instrument), tradingDay, rule.getAtrPeriods()),
                instrument.getStrikePoints());

        int written = 0;
        for (String side : new String[]{"CE", "PE"}) {
            String optionToken = instrumentResolver.optionSymbol(instrument, expiry, atmStrike, side);
            if (optionToken == null) {
                log.warn("[EOD-downtrend] rule id={} {} — no option instrument for ATM strike={} expiry={}",
                        rule.getId(), side, atmStrike, expiry);
                continue;
            }

            // One absent leg must not cost the other its config. The historical
            // source throws when a series is wholly missing (an un-imported strike),
            // and letting that escape processRule would drop the whole rule — both
            // sides — on a data gap that only affects this one.
            try {
                List<int[]> passing = scanSide(optionToken, tradingDay, rule);
                if (passing.isEmpty()) {
                    log.debug("[EOD-downtrend] rule id={} {} ATM={} — nothing trending down",
                            rule.getId(), side, atmStrike);
                    continue;
                }

                // Bracket basis. Measured on the option leg, not the underlying, and
                // therefore per-side: target/stop_loss end up on trade_order and are
                // compared by PositionService against per-share option-premium P&L, so
                // an index-denominated number would be in the wrong unit entirely.
                //
                // Measured on the leg the config will TRADE (tradeExpiry), not the one
                // the trend was detected on, and as intraday range rather than true
                // range — see averageIntradayRange for why the difference matters.
                String bracketToken = instrumentResolver.optionSymbol(
                        instrument, tradeExpiry, atmStrike, side);

                BigDecimal basis = null;
                if (bracketToken != null && !bracketToken.equals(optionToken)) {
                    try {
                        basis = averageIntradayRange(
                                bracketToken, tradingDay, tradeExpiry, rule.getAtrPeriods());
                    } catch (HistoricalDataMissingException ex) {
                        basis = null;
                    }
                }

                // On an expiry day the contract the config will trade often has no
                // history yet — it may not even be listed. Falling back to the leg
                // we detected on keeps a config being written; the basis is then a
                // dying series, but still gap-free and still excluding the expiry
                // session itself, which is where the old ATR did its real damage.
                if (basis == null || basis.signum() <= 0) {
                    if (bracketToken != null && !bracketToken.equals(optionToken)) {
                        log.debug("[EOD-downtrend] rule id={} {} — no history for traded contract {} "
                                        + "as of {}, sizing the bracket off {} instead",
                                rule.getId(), side, bracketToken, tradingDay, optionToken);
                    }
                    basis = averageIntradayRange(optionToken, tradingDay, expiry, rule.getAtrPeriods());
                }

                if (basis == null || basis.signum() <= 0) {
                    log.warn("[EOD-downtrend] rule id={} {} — no range basis for token={} on {}, skipping side",
                            rule.getId(), side, optionToken, tradingDay);
                    continue;
                }

                // The scan above runs once per side no matter how many strategies are
                // tagged — it depends on the downtrend, not on who trades it. Only
                // the write below repeats, and only when two tagged strategies want
                // different trade_config conventions.
                for (ConfigGroup group : groups) {
                    insertAutoTradeConfig(rule, group, nextDay, side, basis, passing, instrument, strikeDepth);
                    written++;
                }
            } catch (HistoricalDataMissingException ex) {
                log.warn("[EOD-downtrend] rule id={} {} — no imported series for token={} on {}, skipping side: {}",
                        rule.getId(), side, optionToken, tradingDay, ex.getMessage());
            }
        }
        return written;
    }

    /**
     * Returns the list of {@code [sma, timeframe-minutes]} pairs whose last-candle
     * down-trend flag is on for the given strike on {@code tradingDay}.
     * <p>The strike series is fetched <i>once per timeframe</i> and all SMAs are
     * computed on it before {@link SmaTrendCalculator} runs.</p>
     *
     * <p><b>The fetch spans {@link #lookbackCalendarDays(int)} calendar days, not
     * just {@code tradingDay}.</b> SMAs must be continuous across sessions to match
     * what the trader sees on a chart — a 15-minute chart carries ~25 candles per
     * session, so a single day cannot even produce SMA(50), let alone SMA(500), and
     * {@code SMAIndicatorImpl} returns null whenever {@code period > series.size()}.
     * Fetching one day silently reduced the whole grid to its shortest period and
     * made every longer one permanently unreachable.
     * {@code AnalysisScheduler} already fetches with a lookback for exactly this
     * reason; this method now matches it.</p>
     *
     * <p>Widening the window does <i>not</i> leak prior sessions into the verdict:
     * the {@code startTime} trim below is a time-of-day filter, and
     * {@link SmaTrendCalculator} resets its deviation counters on every new day, so
     * the flags read off the final candle still describe {@code tradingDay} alone —
     * only the SMA values themselves now carry the correct history.</p>
     *
     * <p><b>A period the broker cannot cover is dropped, not approximated.</b> The
     * fetch window is only a request; what matters is how much history actually came
     * back for this leg. Each period is admitted only if a full {@code period}-wide
     * window has already closed by the first judged candle. A newly listed strike, a
     * thin leg, or a broker that trims history therefore contributes fewer combos —
     * or none — instead of a trend read off a partial average.</p>
     */
    private List<int[]> scanSide(String optionToken, LocalDate tradingDay, SmaDowntrendRule rule) {
        List<int[]> passing = new ArrayList<>();

        LocalDateTime to = LocalDateTime.of(tradingDay, MARKET_CLOSE);

        for (int tfMinutes : TIMEFRAMES_MINUTES) {
            String interval = tfMinutes + "minute";

            LocalDateTime from = LocalDateTime.of(tradingDay, MARKET_OPEN)
                    .minusDays(lookbackCalendarDays(tfMinutes));

            List<MarketData> series = marketDataService.fetchHistoricalData(optionToken, from, to, interval);
            if (series == null || series.isEmpty()) {
                continue;
            }

            // Populate sma_value{50,100,200,500} on every candle in the series.
            // sma_value20 is deliberately left null — SMA(20) is not in the grid, so
            // SmaTrendCalculator leaves its flags false and no 20-period combo can be
            // produced. The chart's own SMA20 comes from ChartIndicatorService and is
            // unaffected.
            for (int period : SMA_PERIODS) {
                try {
                    indicatorService.calculate("SMA", series, IndicatorConfig.of(period, "SMA"));
                } catch (Exception ex) {
                    log.debug("[EOD-downtrend] SMA({}) skipped on token={} tf={}: {}",
                            period, optionToken, interval, ex.getMessage());
                }
            }

            // First candle that actually gets judged: on tradingDay, at/after start_time.
            // Its index is also the count of candles preceding it, i.e. the warm-up the
            // broker actually supplied — which is what decides SMA sufficiency below.
            int evalStartIdx = -1;
            for (int i = 0; i < series.size(); i++) {
                MarketData c = series.get(i);
                if (c.getTimestamp() == null) continue;
                if (!c.getTimestamp().toLocalDate().equals(tradingDay)) continue;
                if (c.getTimestamp().toLocalTime().isBefore(rule.getStartTime())) continue;
                evalStartIdx = i;
                break;
            }
            if (evalStartIdx < 0) {
                log.debug("[EOD-downtrend] token={} tf={} — no candles on {} at/after {}",
                        optionToken, interval, tradingDay, rule.getStartTime());
                continue;
            }

            // Trim to candles at/after start_time — deviation counting starts there.
            List<MarketData> windowed = new ArrayList<>();
            for (MarketData c : series) {
                if (c.getTimestamp() == null) continue;
                if (!c.getTimestamp().toLocalTime().isBefore(rule.getStartTime())) {
                    windowed.add(c);
                }
            }
            if (windowed.isEmpty()) continue;

            SmaTrendCalculator.compute(windowed, rule.getMaxDeviation());
            MarketData last = windowed.get(windowed.size() - 1);

            for (int period : SMA_PERIODS) {
                // Sufficiency gate. ta4j's SMAIndicator averages however many bars it
                // has rather than returning null, so a period with too little history
                // still yields a number — a partial average that looks like a real SMA
                // and would be silently trend-tested. Require a full period-wide window
                // to already be closed at the first judged candle; if the broker did not
                // return that much history for this leg, the period contributes no combo.
                if (evalStartIdx < period - 1) {
                    log.debug("[EOD-downtrend] token={} tf={} SMA{} — insufficient history: "
                                    + "{} candles before {} {}, need {}; period dropped",
                            optionToken, interval, period, evalStartIdx, tradingDay,
                            rule.getStartTime(), period - 1);
                    continue;
                }
                if (smaDownFlag(last, period)) {
                    passing.add(new int[]{period, tfMinutes});
                }
            }
        }
        return passing;
    }

    /**
     * How far back to ask the broker so the longest period in {@link #SMA_PERIODS}
     * has a full window for every judged candle at {@code tfMinutes}.
     *
     * <p>Stated in candles first, because that is the real requirement:
     * {@code maxPeriod} candles of warm-up (SMA(500) at 15-minute needs 500) plus
     * one session's worth, so the SMA is already full-window at the day's first
     * candle and stays full-window to its last. That count is converted to calendar
     * days via {@link #SESSION_MINUTES}, the 7/5 factor for weekends, and {@code +5}
     * for holidays.</p>
     *
     * <p>This only sizes the <i>request</i>. It is deliberately generous and never
     * decides anything: whether a period is actually usable is settled in
     * {@code scanSide} by counting the candles the broker really returned. A short
     * fetch drops that period rather than trend-testing a partial average. This is
     * a data-sufficiency calculation, not a trading-behaviour knob.</p>
     */
    private int lookbackCalendarDays(int tfMinutes) {
        int maxPeriod = 0;
        for (int p : SMA_PERIODS) {
            maxPeriod = Math.max(maxPeriod, p);
        }
        int candlesPerSession = Math.max(1, SESSION_MINUTES / tfMinutes);
        int candlesNeeded = maxPeriod + candlesPerSession;

        double tradingDays = (double) candlesNeeded / candlesPerSession;
        return (int) Math.ceil(tradingDays * 7.0 / 5.0) + 5;
    }

    /**
     * Period → the entity's down-trend flag. Reached only for periods in
     * {@link #SMA_PERIODS}; {@code case 20} is kept because this is a generic
     * mapper over {@link MarketData}'s flags, and {@code default: false} makes an
     * unmapped period fail closed either way.
     */
    private boolean smaDownFlag(MarketData c, int period) {
        if (c == null) return false;
        switch (period) {
            case 20:  return c.isSma20DownTrending();
            case 50:  return c.isSma50DownTrending();
            case 100: return c.isSma100DownTrending();
            case 200: return c.isSma200DownTrending();
            case 500: return c.isSma500DownTrending();
            default:  return false;
        }
    }

    /**
     * Rejects a rule whose premium band cannot produce a tradeable config.
     *
     * <p>Both columns are {@code NOT NULL} as of changeset 026, so a null here
     * means the migration has not been applied — and writing the config anyway
     * would hand {@code AbstractSmaCrossStrategy} a null bound, which it reads as
     * <i>unbounded</i>. Skipping loudly is better than silently generating the
     * any-premium config the band exists to prevent.</p>
     *
     * <p>An inverted band (max below min) can never admit a signal, so it is
     * treated the same way rather than producing a config that looks live and
     * never trades.</p>
     */
    private boolean hasUsableBand(SmaDowntrendRule rule) {
        BigDecimal min = rule.getMinOptionPrice();
        BigDecimal max = rule.getMaxOptionPrice();

        if (min == null || max == null) {
            log.warn("[EOD-downtrend] rule id={} — no premium band (min={}, max={}), skipping. "
                            + "Apply changeset 026 or set min_option_price / max_option_price on the rule.",
                    rule.getId(), min, max);
            return false;
        }
        if (max.compareTo(min) < 0) {
            log.warn("[EOD-downtrend] rule id={} — premium band is inverted (min={} > max={}), skipping",
                    rule.getId(), min, max);
            return false;
        }

        // A target of 100% of entry premium needs the leg to go to zero intraday,
        // so anything at or above 1.0 is a config that can only ever stop out.
        // Rejected rather than clamped: unlike the absolute target, this one is
        // typed directly by whoever edits the rule, so silently rewriting it would
        // hide the mistake.
        BigDecimal targetPct = rule.getTargetPct();
        BigDecimal slPct = rule.getSlPct();
        if (targetPct != null && (targetPct.signum() <= 0 || targetPct.compareTo(BigDecimal.ONE) >= 0)) {
            log.warn("[EOD-downtrend] rule id={} — target_pct={} is outside (0, 1); a short leg cannot "
                    + "gain more than the premium it was sold at. Skipping.", rule.getId(), targetPct);
            return false;
        }
        if (slPct != null && slPct.signum() <= 0) {
            log.warn("[EOD-downtrend] rule id={} — sl_pct={} must be positive, skipping",
                    rule.getId(), slPct);
            return false;
        }
        return true;
    }

    // ------------------------------------------------------------------
    // Strike helper (ATM only)
    // ------------------------------------------------------------------

    /**
     * Rounds the underlying's last 5-minute close on {@code tradingDay} to the
     * nearest {@code instrument.strikePoints}. ATM only — no depth.
     */
    private Integer computeAtmStrike(Instrument instrument, LocalDate tradingDay) {
        if (instrument.getStrikePoints() == null || instrument.getStrikePoints().signum() <= 0) return null;

        String underlyingSymbol = instrumentResolver.underlyingSymbol(instrument);
        if (underlyingSymbol == null) return null;

        LocalDateTime from = LocalDateTime.of(tradingDay, MARKET_OPEN);
        LocalDateTime to   = LocalDateTime.of(tradingDay, MARKET_CLOSE);

        List<MarketData> underlying = marketDataService.fetchHistoricalData(
                underlyingSymbol, from, to, "5minute");
        if (underlying == null || underlying.isEmpty()) return null;

        BigDecimal close = underlying.get(underlying.size() - 1).getClose();
        if (close == null) return null;

        BigDecimal step = instrument.getStrikePoints();
        BigDecimal multiplier = close.divide(step, 0, RoundingMode.HALF_UP);
        return multiplier.multiply(step).intValueExact();
    }

    // ------------------------------------------------------------------
    // ATR — daily true range over the last N completed trading days
    // ------------------------------------------------------------------

    /**
     * ATR(N) over daily candles of {@code token}.
     *
     * <p><b>Pass the option leg's token, not the underlying's.</b> The result lands
     * on {@code trade_config.target} / {@code stop_loss}, which
     * {@code PositionService.thresholdBreach} compares against per-share option
     * <i>premium</i> P&amp;L. An ATR taken on the index is denominated in index
     * points and is not comparable: NIFTY ATR(14) sits near 180 while an ATM
     * premium is nearer 100, so the target exceeded the most a short leg can ever
     * earn (premium decaying to zero) and could never trigger.</p>
     */
    private BigDecimal computeAtr(String token, LocalDate tradingDay, Integer periods) {
        if (token == null || token.isBlank()) return null;
        int n = periods == null || periods <= 0 ? 14 : periods;

        LocalDateTime from = LocalDateTime.of(tradingDay.minusDays(Math.max(n * 2L + 10, 30)), LocalTime.MIDNIGHT);
        LocalDateTime to   = LocalDateTime.of(tradingDay, LocalTime.of(23, 59));

        List<MarketData> daily = marketDataService.fetchHistoricalData(token, from, to, "day");
        if (daily == null || daily.size() < 2) return null;

        int startIdx = Math.max(1, daily.size() - n);
        BigDecimal sum = BigDecimal.ZERO;
        int count = 0;
        for (int i = startIdx; i < daily.size(); i++) {
            BigDecimal tr = trueRange(daily.get(i), daily.get(i - 1));
            if (tr == null) continue;
            sum = sum.add(tr);
            count++;
        }
        if (count == 0) return null;
        return sum.divide(BigDecimal.valueOf(count), 4, RoundingMode.HALF_UP);
    }

    /**
     * Mean daily {@code high - low} of {@code token} over the last {@code periods}
     * sessions, skipping the contract's own expiry day. This is the basis for the
     * absolute {@code target} / {@code stop_loss} the detector writes.
     *
     * <p><b>Why not {@link #computeAtr}.</b> True range takes
     * {@code max(H-L, |H-prevClose|, |L-prevClose|)}, so it counts the overnight
     * gap. On an index that gap is a real move a trade can capture the next day.
     * On an option leg it is mostly re-pricing — the same strike is a different
     * distance from spot, one day closer to expiry — and an intraday trade opening
     * after the open can never capture it. Measured on the imported Jan-2024 NIFTY
     * 21700 PE, the gap term dominated the range term on 2 of 4 days, and on
     * expiry day contributed a true range of 156.90 against an intraday range of
     * 116.35. Averaging those gave a 119.89-point target on a leg the config would
     * enter between 80 and 250 — reachable only if the premium went to zero.</p>
     *
     * <p>The expiry-day bar is skipped rather than averaged in: a leg's last
     * session is a one-way premium collapse, not a range the next contract will
     * reproduce. Because the token passed here belongs to the contract the config
     * will trade — whose expiry is still ahead — this normally excludes nothing;
     * it is a guard for the case where the detector runs on that contract's own
     * expiry day.</p>
     *
     * <p>This is still only the <i>basis</i>. What the generated config enforces is
     * the premium-relative bracket ({@code target_pct} / {@code sl_pct}); the
     * absolute value derived here is the fallback and the number
     * {@code CommonRules.profitTarget} reads as an entry gate.</p>
     */
    private BigDecimal averageIntradayRange(String token, LocalDate tradingDay,
                                            LocalDate contractExpiry, Integer periods) {
        if (token == null || token.isBlank()) return null;
        int n = periods == null || periods <= 0 ? 14 : periods;

        LocalDateTime from = LocalDateTime.of(tradingDay.minusDays(Math.max(n * 2L + 10, 30)), LocalTime.MIDNIGHT);
        LocalDateTime to   = LocalDateTime.of(tradingDay, LocalTime.of(23, 59));

        List<MarketData> daily = marketDataService.fetchHistoricalData(token, from, to, "day");
        if (daily == null || daily.isEmpty()) return null;

        List<BigDecimal> ranges = new ArrayList<>();
        for (MarketData bar : daily) {
            if (bar == null || bar.getHigh() == null || bar.getLow() == null) continue;
            if (contractExpiry != null && bar.getTimestamp() != null
                    && contractExpiry.equals(bar.getTimestamp().toLocalDate())) {
                continue;
            }
            BigDecimal range = bar.getHigh().subtract(bar.getLow());
            if (range.signum() > 0) ranges.add(range);
        }
        if (ranges.isEmpty()) return null;

        BigDecimal sum = BigDecimal.ZERO;
        int startIdx = Math.max(0, ranges.size() - n);
        for (int i = startIdx; i < ranges.size(); i++) {
            sum = sum.add(ranges.get(i));
        }
        return sum.divide(BigDecimal.valueOf(ranges.size() - startIdx), 4, RoundingMode.HALF_UP);
    }

    /**
     * Strike-band half-width in strikes, derived from the underlying's ATR:
     * {@code ceil(ATR / strikePoints)}, clamped to
     * {@link #MIN_STRIKE_DEPTH}..{@link #MAX_STRIKE_DEPTH}.
     *
     * <p>Sizing this from ATR is what keeps an open position observable. The band
     * is recomputed from the live ATM on every tick, so if the underlying moves
     * further than the band is wide, the strike a position was opened on drops out
     * of the fetch set and its cached candles stop advancing — the monitor then
     * reads a frozen quote and target/SL can never trigger. A band as wide as a
     * typical day's travel keeps the entry strike covered.</p>
     *
     * <p>The clamp is a safety rail, not a trading rule: the floor keeps a band
     * around ATM on unusually quiet days, and the ceiling stops a volatility spike
     * from fanning out into dozens of broker fetches per tick.</p>
     */
    private int strikeDepthFor(BigDecimal underlyingAtr, BigDecimal strikePoints) {
        if (underlyingAtr == null || underlyingAtr.signum() <= 0
                || strikePoints == null || strikePoints.signum() <= 0) {
            return MIN_STRIKE_DEPTH;
        }
        int depth = underlyingAtr.divide(strikePoints, 0, RoundingMode.CEILING).intValue();
        return Math.max(MIN_STRIKE_DEPTH, Math.min(MAX_STRIKE_DEPTH, depth));
    }

    private BigDecimal trueRange(MarketData curr, MarketData prev) {
        if (curr == null || prev == null) return null;
        if (curr.getHigh() == null || curr.getLow() == null || prev.getClose() == null) return null;
        BigDecimal hl  = curr.getHigh().subtract(curr.getLow()).abs();
        BigDecimal hpc = curr.getHigh().subtract(prev.getClose()).abs();
        BigDecimal lpc = curr.getLow().subtract(prev.getClose()).abs();
        return hl.max(hpc).max(lpc);
    }

    // ------------------------------------------------------------------
    // Per-strategy defaults for trade_config conventions
    // ------------------------------------------------------------------

    /**
     * One generated {@code trade_config}: the field block it carries, and every
     * strategy that gets tagged onto it.
     *
     * <p>Several strategies share one config whenever their
     * {@link StrategyDefaults} blocks are identical, which is the usual case —
     * {@code Strategy2} is {@code Strategy1} plus a filter, so both trade the same
     * side under the same caps. When two tagged strategies genuinely want
     * different conventions they cannot share a row, because those fields live on
     * {@code trade_config} itself; {@link #resolveConfigGroups} then emits one
     * config per distinct block.</p>
     */
    record ConfigGroup(StrategyDefaults defaults, List<Integer> strategyIds) {}

    /**
     * The configs one rule should generate, resolved from its
     * {@code sma_downtrend_rule_strategy} tags.
     *
     * <p>Replaces a hardcoded {@code switch} that handled strategy 1 and returned
     * {@code null} for everything else — which silently dropped any rule tagged
     * with another strategy. The block now comes from {@code strategy_defaults}
     * (changeset 033), so adding a strategy to the auto-config pipeline is an
     * INSERT rather than a redeploy.</p>
     *
     * <p>A rule with no tag rows falls back to its own {@code strategy_id}, so a
     * database whose tags were never written behaves exactly as before changeset
     * 034.</p>
     *
     * <p>Every skip is logged and names the strategy. A missing or disabled
     * {@code strategy_defaults} row is a configuration mistake, and a detector
     * that quietly generated nothing is precisely the failure this replaces.</p>
     */
    // Package-private rather than private so the branch matrix (no tags / missing
    // defaults row / disabled / shared block / distinct blocks / run scope) is
    // unit-testable without standing up the whole detector against a database.
    List<ConfigGroup> resolveConfigGroups(SmaDowntrendRule rule, Set<Integer> alreadyGenerated,
                                          Set<Integer> strategyScope) {
        List<Integer> tagged = rule.getId() == null
                ? List.of()
                : ruleStrategyRepository.findByRuleIdAndEnabledTrueOrderByStrategyIdAsc(rule.getId())
                        .stream()
                        .map(SmaDowntrendRuleStrategy::getStrategyId)
                        .filter(Objects::nonNull)
                        .toList();

        if (tagged.isEmpty()) {
            if (rule.getStrategyId() == null) {
                log.warn("[EOD-downtrend] rule id={} has no strategy tags and no strategy_id, skipping",
                        rule.getId());
                return List.of();
            }
            tagged = List.of(rule.getStrategyId());
        }

        // Per-run selection (the strategyIds request param): applied after the
        // fallback above so an untagged rule whose strategy_id is out of scope is
        // excluded too. The scope only narrows; a strategy it names that the rule
        // is not tagged with still generates nothing.
        if (strategyScope != null && !strategyScope.isEmpty()) {
            List<Integer> inScope = tagged.stream().filter(strategyScope::contains).toList();
            if (inScope.isEmpty()) {
                log.debug("[EOD-downtrend] rule id={} — strategies {} all outside the requested scope {}, skipping rule",
                        rule.getId(), tagged, strategyScope);
                return List.of();
            }
            tagged = inScope;
        }

        // LinkedHashMap so the emitted order follows the ascending strategy order
        // the repository query pins — a re-run of the same backtest day must write
        // the same configs in the same sequence.
        Map<String, ConfigGroup> groups = new LinkedHashMap<>();
        for (Integer strategyId : tagged) {
            StrategyDefaults defaults = strategyDefaultsRepository.findById(strategyId).orElse(null);
            if (defaults == null) {
                log.warn("[EOD-downtrend] rule id={} — strategy {} has no strategy_defaults row, skipping it. "
                                + "Insert one (see changeset 033) to generate configs for this strategy.",
                        rule.getId(), strategyId);
                continue;
            }
            if (!Boolean.TRUE.equals(defaults.getAutoConfigEnabled())) {
                log.warn("[EOD-downtrend] rule id={} — strategy {} has auto_config_enabled=false, skipping it",
                        rule.getId(), strategyId);
                continue;
            }
            if (alreadyGenerated != null && alreadyGenerated.contains(strategyId)) {
                log.debug("[EOD-downtrend] rule id={} — strategy {} already has a config for the "
                        + "target day, skipping it", rule.getId(), strategyId);
                continue;
            }
            ConfigGroup existing = groups.get(defaults.configSignature());
            if (existing == null) {
                List<Integer> ids = new ArrayList<>();
                ids.add(strategyId);
                groups.put(defaults.configSignature(), new ConfigGroup(defaults, ids));
            } else {
                existing.strategyIds().add(strategyId);
            }
        }
        return new ArrayList<>(groups.values());
    }

    // ------------------------------------------------------------------
    // Insert the auto-generated trade_config + sma_timeframe rows
    // ------------------------------------------------------------------

    private void insertAutoTradeConfig(SmaDowntrendRule rule,
                                       ConfigGroup group,
                                       LocalDate nextDay,
                                       String side,
                                       BigDecimal basis,
                                       List<int[]> passing,
                                       Instrument instrument,
                                       int strikeDepth) {
        StrategyDefaults defaults = group.defaults();
        TradeConfig tc = new TradeConfig();
        tc.setTradingDate(nextDay);
        tc.setTradingSide(side);
        tc.setInstrument(rule.getInstrument());
        // Primary strategy = the lowest-numbered one sharing this config, matching
        // what TradeConfigAdminService keeps in the column for hand-made configs.
        // Dispatch is driven by strategy_ids below, not by this column — see
        // changesets 031/035.
        tc.setStratergyId(group.strategyIds().get(0));

        // What actually makes the config run. Without this the config would fall
        // back to its stratergy_id and be scanned by that one strategy only — which
        // is the whole point of tagging the rule with more than one.
        tc.setStrategyIds(StrategyIds.format(group.strategyIds()));
        tc.setSource(SOURCE_AUTO);

        // The bracket that actually decides exits: a fraction of whatever premium
        // the trade opens at, resolved by OrderService into target_at_entry /
        // stop_loss_at_entry. Straight off the rule — see changeset 027.
        tc.setTargetPct(rule.getTargetPct());
        tc.setSlPct(rule.getSlPct());
        // The asymmetric half of the bracket (changeset 036): cap the stop the
        // percentage above resolves to, and trail the profit. Copied verbatim like
        // the percentages — the rule table is where a generated config's bracket
        // is decided, and both columns are NOT NULL there so this cannot write a
        // config that silently reverts to an uncapped, non-trailing stop.
        tc.setMaxSlPoints(rule.getMaxSlPoints());
        tc.setTrailLadder(rule.getTrailLadder());

        // Absolute fallback, in premium points — the same unit PositionService
        // compares against. Used when a config carries no percentage, and read by
        // CommonRules.profitTarget as an SMA-separation gate at entry regardless.
        // Basis is the traded leg's mean intraday range; see averageIntradayRange.
        tc.setTarget(clampToBandFloor(
                basis.multiply(rule.getTargetMultiplier()).setScale(2, RoundingMode.HALF_UP),
                rule));
        tc.setStopLoss(basis.multiply(rule.getSlMultiplier()).setScale(2, RoundingMode.HALF_UP));

        // The per-strategy convention block, from strategy_defaults (changeset 033)
        // rather than the hardcoded switch this used to carry.
        tc.setTransactionType(defaults.getTransactionType());
        tc.setMaxLoss(defaults.getMaxLoss());
        tc.setNumberOfTradesPerDay(defaults.getNoOfTrades());
        tc.setNumberOfParallelTrades(defaults.getNoOfParallelTrades());

        // Order quantity goes to the broker verbatim, and NFO only accepts whole
        // lots — so it comes from the contract, not from a strategy constant.
        // strategy_defaults.lot_quantity is a last-resort fallback.
        Integer lotQty = instrument == null ? null : instrument.getLotQty();
        tc.setLotQuantity(lotQty != null && lotQty > 0 ? lotQty : defaults.getLotQuantity());

        // Symmetric band around ATM, sized by strikeDepthFor(...).
        //
        // NOTE: 0 does NOT mean "ATM" — AnalysisScheduler.calculateStrikesForCandles
        // builds a strike list only when itmDepth > 0 or otmDepth > 0, and never reads
        // atmDepth at all, so 0/0/0 yields an EMPTY strike list and the config can
        // never trade. The ITM loop starts at i=0, whose first element is the base
        // (ATM) strike, so itmDepth already includes ATM.
        tc.setItmDepth(strikeDepth);
        tc.setOtmDepth(strikeDepth);
        tc.setAtmDepth(0);

        // Premium band, straight off the rule. Leaving these null is not "no
        // opinion" — AbstractSmaCrossStrategy.outsidePriceBand skips a null bound entirely, so an
        // unset band is an *unbounded* config, free to sell a 6-point leg against
        // a 30-point target. Every generated config carries a band for the same
        // reason every hand-made one does; see changesets 024-026.
        tc.setMinOptionPrice(rule.getMinOptionPrice());
        tc.setMaxOptionPrice(rule.getMaxOptionPrice());

        TradeConfig saved = tradeConfigRepository.save(tc);

        for (int[] combo : passing) {
            SmaTimeframe tf = new SmaTimeframe();
            tf.setTradeConfig(saved);
            tf.setSma(combo[0]);
            tf.setTimePeriod(combo[1]);
            smaTimeframeRepository.save(tf);
        }

        log.info("[EOD-downtrend] inserted AUTO_DOWNTREND trade_config id={} for {} side={} strategies={} "
                        + "target={}%/{}pts sl={}%/{}pts maxSl={}pts trail={} basis={} band={}-{} combos={}",
                saved.getId(), nextDay, side, group.strategyIds(),
                tc.getTargetPct(), tc.getTarget(), tc.getSlPct(), tc.getStopLoss(),
                tc.getMaxSlPoints(), tc.getTrailLadder(), basis,
                tc.getMinOptionPrice(), tc.getMaxOptionPrice(), summarise(passing));
    }

    /**
     * Caps an absolute target at one tick below the premium band's floor.
     *
     * <p>A short leg's maximum possible gain is the premium it was sold at, so a
     * target at or above {@code min_option_price} cannot be reached by the cheapest
     * entry the config is allowed to take — the trade is guaranteed to end at the
     * stop or at force close. That is arithmetic about the payoff, not a view on
     * what a good target is, so it is enforced here rather than left to the
     * multiplier.</p>
     *
     * <p>Clamps rather than skipping the side: the down-trend that was detected is
     * still real, and a config with a reachable target is more useful than no
     * config. The warning names both numbers so a persistently clamped rule is
     * visible as a multiplier that wants lowering.</p>
     */
    private BigDecimal clampToBandFloor(BigDecimal target, SmaDowntrendRule rule) {
        BigDecimal floor = rule.getMinOptionPrice();
        if (target == null || floor == null || floor.signum() <= 0) return target;

        BigDecimal cap = floor.subtract(TICK_SIZE);
        if (cap.signum() <= 0 || target.compareTo(cap) <= 0) return target;

        log.warn("[EOD-downtrend] rule id={} — target {} is unreachable at the band floor {}; "
                        + "clamped to {}. Lower target_multiplier to size it deliberately.",
                rule.getId(), target, floor, cap);
        return cap;
    }

    private String summarise(List<int[]> passing) {
        StringBuilder sb = new StringBuilder("[");
        for (int i = 0; i < passing.size(); i++) {
            if (i > 0) sb.append(", ");
            sb.append(passing.get(i)[1]).append("min/SMA").append(passing.get(i)[0]);
        }
        return sb.append("]").toString();
    }

    /** Skips Sat/Sun. Holidays not modelled — picked up at the next backtest invocation. */
}
