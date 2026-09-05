package com.moneymaker.scheduler;

import com.moneymaker.dto.AllTimeFramedto;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.indicator.IndicatorConfig;
import com.moneymaker.indicator.IndicatorService;
import com.moneymaker.market.exception.HistoricalDataMissingException;
import com.moneymaker.market.instrument.OffsetStrikeSelector;
import com.moneymaker.market.instrument.OptionInstrumentResolver;
import com.moneymaker.market.instrument.SyntheticUnderlyingContract;
import com.moneymaker.market.instrument.UnderlyingSymbols;
import com.moneymaker.journal.JournalRecorder;
import com.moneymaker.journal.ObservationContextFactory;
import com.moneymaker.market.service.MarketDataService;
import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.StrategyFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.*;

@Component
public class AnalysisScheduler {
    private static final Logger logger = LoggerFactory.getLogger(AnalysisScheduler.class);
    private final MarketDataService marketDataService;
    private final IndicatorService indicatorService;
    private final StrategyFactory strategyFactory;
    private final MarketHoursService marketHours;
    private final TradeOrderRepository tradeOrderRepository;

    /**
     * Supplies the underlying / option {@code symbol} strings and the expiry.
     * Broker tokens in normal operation; natural-key strings when the backtest
     * reads from the imported historical tables.
     */
    private final OptionInstrumentResolver instrumentResolver;

    /**
     * Journalling sits here, not in the strategies, because this is where every
     * leg any strategy might trade is resolved. Recording at the strategy would
     * only ever see the legs that strategy was handed, and could never answer
     * "what about the strikes we passed over".
     */
    private final JournalRecorder journal;
    private final ObservationContextFactory observations;

    /**
     * Run mode, from the same {@code app.mode} key the Telegram backtest gate
     * reads ({@code TelegramNotifier}). Constructor-injected rather than
     * field-injected so a unit test can build the bean in either mode.
     */
    private final String appMode;

    public AnalysisScheduler(MarketDataService marketDataService,
                             IndicatorService indicatorService,
                             StrategyFactory strategyFactory,
                             MarketHoursService marketHours,
                             TradeOrderRepository tradeOrderRepository,
                             OptionInstrumentResolver instrumentResolver,
                             JournalRecorder journal,
                             ObservationContextFactory observations,
                             @Value("${app.mode:live}") String appMode) {
        this.marketDataService = Objects.requireNonNull(marketDataService, "marketDataService must not be null");
        this.indicatorService = Objects.requireNonNull(indicatorService, "indicatorService must not be null");
        this.strategyFactory = Objects.requireNonNull(strategyFactory, "strategyFactory must not be null");
        this.marketHours = Objects.requireNonNull(marketHours, "marketHours must not be null");
        this.tradeOrderRepository = Objects.requireNonNull(tradeOrderRepository, "tradeOrderRepository must not be null");
        this.instrumentResolver = Objects.requireNonNull(instrumentResolver, "instrumentResolver must not be null");
        this.journal = Objects.requireNonNull(journal, "journal must not be null");
        this.observations = Objects.requireNonNull(observations, "observations must not be null");
        this.appMode = appMode == null ? "" : appMode.trim();
        logger.info("AnalysisScheduler initialized with instrument resolver: {}", instrumentResolver.getName());
    }

    /**
     * The wall-clock entry point: every 5 minutes during NSE trading hours.
     *
     * <p>Carries only wall-clock concerns — the backtest gate and the live
     * market-hours gate. The replayable work is
     * {@link #calculateIndicator(LocalDateTime)} + {@link #runStrategies(LocalDateTime)},
     * which {@code BacktestAnalysisService} calls directly with the simulated
     * timestamp; neither may grow a mode check (invariant 8).</p>
     *
     * <p>In {@code app.mode=backtest} the trigger still fires — the bean is
     * needed by the replay, so it cannot be {@code @ConditionalOnProperty}-ed
     * away — but does no work, and in particular never calls
     * {@code calculateIndicator(LocalDateTime.now())}, which would fetch and
     * cache <i>today's</i> candles into the same
     * {@code SharedData.strikeMarketDataByInstrumentAndInterval} map the replay
     * is reading. See {@code docs/GAPS.md} #4.</p>
     */
    @Scheduled(cron = "0 0/5 9-16 * * MON-FRI")
    public void analyzeMarketData() {
        if ("backtest".equalsIgnoreCase(appMode)) {
            logger.debug("AnalysisScheduler cron tick ignored - app.mode=backtest drives calculateIndicator() directly");
            return;
        }
        if ("live".equalsIgnoreCase(appMode) && !marketHours.isOpenNow()) {
            logger.debug("AnalysisScheduler skipped: outside market hours");
            return;
        }
        logger.info("Starting market analysis scheduler");
        try {
            calculateIndicator(LocalDateTime.now());
        } catch (Exception ex) {
            logger.error("Error in market analysis scheduler", ex);
        }
    }

    public void calculateIndicator(LocalDateTime analysisDateTime) {
        Objects.requireNonNull(analysisDateTime, "analysisDateTime must not be null");
        logger.debug("Calculating indicators for date-time: {}", analysisDateTime);

        try {
            // Lookback derived from the largest (timeframe × SMA-period) the
            // analysis pipeline is configured to compute. Hardcoding 10 days
            // was failing for SMA500 on 5-min and above. See
            // computeLookbackCalendarDays() for the calculation.
            int lookbackDays = computeLookbackCalendarDays();
            LocalDateTime startOfDay = analysisDateTime.minusDays(lookbackDays);

            logger.debug("Fetching market data from {} to {} (lookback={} calendar days)",
                    startOfDay, analysisDateTime, lookbackDays);

            List<TradeConfigCombinedDTO> combinedDtoList = SharedData.combinedDto;
            if (combinedDtoList == null || combinedDtoList.isEmpty()) {
                logger.warn("No shared trade config data available for date: {}", analysisDateTime);
                return;
            }

            // Read once per tick, not once per (config × timeframe). Nothing
            // between here and the end of this method writes to trade_order —
            // orders are drained by OrderScheduler after calculateIndicator
            // returns — so every one of those repeated reads saw the same rows.
            List<TradeOrder> openOrders = tradeOrderRepository.findByStatus("OPEN");

            // Since changeset 031 combinedDtoList holds one entry per
            // (config × tagged strategy), so a config tagged with two strategies
            // appears twice. What this loop fetches — underlying candles and the
            // strike series around them — depends only on the config, so running
            // it once per tag would double every MarketDataService call for
            // identical data. That matters: those calls are rate-limited and
            // Resilience4j-wrapped, and the strike fetch is the most expensive
            // thing in the tick.
            //
            // Dispatch is unaffected: runStrategies() still walks every DTO, so
            // each tagged strategy scans the shared cache this loop populated.
            Set<Integer> fetchedConfigIds = new HashSet<>();

            for (TradeConfigCombinedDTO dto : combinedDtoList) {
                Integer configId = dto.getTradeConfig() != null ? dto.getTradeConfig().getId() : null;
                if (configId != null && !fetchedConfigIds.add(configId)) {
                    continue; // another tag on this config already fetched its data
                }

                // The resolver owns what a "symbol" is: a broker instrument token
                // normally, a historical natural key when replaying imported CSVs
                // (where no instrument_details row exists at all).
                String symbol = instrumentResolver.underlyingSymbol(dto);
                if (symbol == null) {
                    logger.warn("Skipping trade config — {} resolver could not resolve an underlying symbol: {}",
                            instrumentResolver.getName(), dto.getTradeConfig());
                    continue;
                }

                // Only the intervals this config's own sma_timeframe rows name.
                //
                // This used to iterate the global SharedData.allTimeFrameMap, which
                // is hardcoded to 5/10/15 — so every tick cached a 10-minute series
                // that no strategy ever scans (sma_timeframe holds only 5- and
                // 15-minute rows). That series was not merely wasted work: anything
                // resolving a quote by option token alone could pick it up, which is
                // how targets and stop-losses ended up priced off a 10-minute bar.
                // Deriving the set from the config keeps the cache to what something
                // actually reads, and drops roughly a third of the per-tick fetches.
                Set<Integer> timeframes = timePeriodsOf(dto);
                if (timeframes.isEmpty()) {
                    logger.warn("No timeframes configured for symbol: {}", symbol);
                    continue;
                }

                boolean indexLineEmitted = false;
                for (Integer timeframe : timeframes) {
                    String interval = toMarketDataInterval(timeframe);
                    if (interval == null) {
                        logger.warn("Skipping instrument token {} because timeframe has no time period", symbol);
                        continue;
                    }
                    // A timeframe with no registered SMA periods contributes nothing:
                    // fetchAndShareStrikeMarketData would cache candles with no SMA
                    // values on them and the strategy's gate would read 0. Skipping
                    // here preserves the old behaviour for an unregistered timeframe,
                    // which simply never got fetched when this loop walked the map.
                    List<Integer> registeredSmaPeriods = SharedData.allTimeFrameMap != null
                            ? SharedData.allTimeFrameMap.get(timeframe)
                            : null;
                    if (registeredSmaPeriods == null || registeredSmaPeriods.isEmpty()) {
                        logger.warn("Skipping timeframe {} for symbol {} — no SMA periods registered for it",
                                timeframe, symbol);
                        continue;
                    }
                    long start = System.nanoTime();
                    List<MarketData> marketDataList = marketDataService.fetchHistoricalData(
                            symbol,
                            startOfDay,
                            analysisDateTime,
                            interval  );
                    if (marketDataList == null || marketDataList.isEmpty()) {
                        logger.warn("No market data available for instrument token: {}, interval: {}, date-time: {}", symbol, interval, analysisDateTime);
                        continue;
                    }

                    String marketDataKey = toMarketDataKey(symbol, interval);
                    SharedData.marketDataByInstrumentAndInterval.put(marketDataKey, marketDataList);

                    // ---- changeset 042: the SPOT baseline book ---------------
                    // A config that trades the underlying itself has no option
                    // leg to fetch. Publishing the spot series into the STRIKE
                    // cache under a pseudo-contract key is what lets the whole
                    // downstream stack treat it like any other contract:
                    // Strategy5 finds it by the same prefix scan, and
                    // SharedData.latestCachedCandle - and therefore
                    // BacktestingPositionMonitorService and the force-close
                    // sweep - resolve its quotes with no knowledge of spot at
                    // all. See SyntheticUnderlyingContract for why this is a
                    // pseudo-contract and not a second exit engine.
                    //
                    // Guarded on the flag, so no pre-042 config reaches it.
                    if (dto.getTradeConfig() != null && dto.getTradeConfig().tradesUnderlyingLeg()) {
                        String spotKey = marketDataKey
                                + "|" + SyntheticUnderlyingContract.SIDE
                                + "|" + SyntheticUnderlyingContract.STRIKE
                                + "|" + SyntheticUnderlyingContract.TOKEN
                                + "|" + dto.getTradeConfig().getItmDepth()
                                + "|" + dto.getTradeConfig().getOtmDepth();
                        SharedData.putStrikeSeries(spotKey, marketDataList, analysisDateTime);
                        logger.debug("[strikes] tradeConfigId={} underlying-leg: published spot series as {}",
                                dto.getTradeConfig().getId(), spotKey);
                    }

                    List<List<Integer>> strikeList = withOpenPositionStrikes(
                            calculateStrikesForCandles(marketDataList, dto.getInstrument(), dto.getTradeConfig()),
                            dto.getTradeConfig(), openOrders);
                    SharedData.strikeList = strikeList;

                    // One [index] line per config per tick — emitted on the first
                    // timeframe iteration. Strikes are computed off the last candle's
                    // close so they're identical across timeframes; no value in
                    // repeating the line per timeframe.
                    if (!indexLineEmitted && logger.isDebugEnabled()) {
                        logIndexLine(dto, marketDataList, strikeList);
                        indexLineEmitted = true;
                    }

                    // An underlying-leg config has no option leg: the block above
                    // already published its only tradable series. Fetching a
                    // strike ladder for it would be pure waste - roughly 249
                    // days x 5 candidate strikes of queries that nothing reads -
                    // and resolveOptionType would refuse it anyway, since
                    // trading_side does not resolve to CE or PE for a spot book.
                    if (dto.getTradeConfig() != null && dto.getTradeConfig().tradesUnderlyingLeg()) {
                        continue;
                    }

                    fetchAndShareStrikeMarketData(strikeList, dto.getInstrument(), dto.getTradeConfig(), timeframe, analysisDateTime.toLocalDate(), interval, startOfDay, analysisDateTime, marketDataKey, dto.getStrategyId(), analysisDateTime);

                }
            }

            logger.debug("Indicator analysis completed for date-time: {}", analysisDateTime);

        } catch (HistoricalDataMissingException ex) {
            // Propagate unwrapped: BacktestAnalysisService matches on this exact
            // type to abort the run. Rewrapping it in a plain RuntimeException
            // would demote a missing data set to a per-tick warning and let the
            // run "succeed" having traded on nothing.
            throw ex;
        } catch (Exception ex) {
            logger.error("Error calculating indicators for date-time: {}", analysisDateTime, ex);
            throw new RuntimeException("Indicator calculation failed for date-time: " + analysisDateTime, ex);
        }
    }

    /**
     * The distinct {@code time_period} values this config's timeframes name, in
     * declaration order. Empty when the config carries no usable timeframe —
     * the caller treats that as "nothing to fetch for this config".
     */
    private Set<Integer> timePeriodsOf(TradeConfigCombinedDTO dto) {
        Set<Integer> periods = new LinkedHashSet<>();
        if (dto == null || dto.getTimeframes() == null) {
            return periods;
        }
        for (SmaTimeframe tf : dto.getTimeframes()) {
            if (tf != null && tf.getTimePeriod() != null && tf.getTimePeriod() > 0) {
                periods.add(tf.getTimePeriod());
            }
        }
        return periods;
    }

    private String toMarketDataInterval(Integer timeframe) {

        return timeframe + "minute";
    }

    /**
     * NSE trading minutes per day (09:15 → 15:30 = 6h15m = 375 min).
     */
    private static final int NSE_MINUTES_PER_DAY = 375;

    /**
     * Buffer added on top of the strict requirement to absorb holidays,
     * occasional short trading days, and data gaps Zerodha sometimes returns.
     */
    private static final int LOOKBACK_BUFFER_DAYS = 7;

    /**
     * Returns the number of calendar days of historical data we must fetch so
     * that the largest {@code (timeframe × sma-period)} configured in
     * {@link SharedData#allTimeFrameMap} can be computed on every candle of
     * the analysis day.
     *
     * <p>Example with the default map (5/10/15-min, SMA periods up to 500):
     * largest pair is 10-min × 500 = 5000 trading minutes ≈ 14 trading days ≈
     * 20 calendar days + buffer = ~27 days. With a 15-min × 500 entry it
     * would jump to ~35 days. Computed each call so adding a timeframe in
     * {@link com.moneymaker.dto.AllTimeFramedto} automatically widens the
     * lookback without code edits.
     */
    public int computeLookbackCalendarDays() {
        Map<Integer, List<Integer>> map = SharedData.allTimeFrameMap;
        int maxRequiredMinutes = 0;
        if (map != null) {
            for (Map.Entry<Integer, List<Integer>> e : map.entrySet()) {
                Integer tf = e.getKey();
                List<Integer> smas = e.getValue();
                if (tf == null || smas == null || smas.isEmpty()) continue;
                int maxSma = smas.stream().mapToInt(Integer::intValue).max().orElse(0);
                maxRequiredMinutes = Math.max(maxRequiredMinutes, tf * maxSma);
            }
        }
        if (maxRequiredMinutes == 0) {
            // No timeframes configured yet — fall back to a small safe window.
            return 10;
        }
        int tradingDays  = (int) Math.ceil(maxRequiredMinutes / (double) NSE_MINUTES_PER_DAY);
        int calendarDays = (int) Math.ceil(tradingDays * 7.0 / 5.0);
        return calendarDays + LOOKBACK_BUFFER_DAYS;
    }

    private String toMarketDataKey(String instrumentToken, String interval) {
        return instrumentToken + "|" + interval;
    }

    /**
     * Adds the strikes of any still-OPEN position to the derived strike set.
     *
     * <p>The derived strikes follow the <i>live</i> ATM, which moves during the day.
     * A position opened at one strike therefore drops out of the fetch set as soon as
     * spot crosses a boundary far enough — and once it does, nothing refreshes its
     * entry in {@code strikeMarketDataByInstrumentAndInterval}. The backtest monitor
     * resolves quotes by scanning that map, so it keeps returning the last candle
     * cached before the strike went out of range: the position freezes at a stale
     * price and its target / stop-loss can never trigger, no matter how far the
     * option actually moves.</p>
     *
     * <p>Observed: an ATM-only config opened 24400CE at 09:15, spot fell through
     * 24400 at ~09:30, and the position was then evaluated 73 more times against the
     * 09:30 quote — exiting on a signal at 15:15 with a realised P&amp;L larger than
     * the peak the monitor ever recorded.</p>
     *
     * <p>Only strikes matching this config's option type are added, so a CE config
     * never starts pulling PE series. Widening the configured band reduces how often
     * this happens; keeping open strikes pinned is what actually prevents it.</p>
     */
    private List<List<Integer>> withOpenPositionStrikes(List<List<Integer>> strikeList, TradeConfig tradeConfig,
                                                        List<TradeOrder> openOrders) {
        String optionType = resolveOptionType(tradeConfig);
        if (optionType == null) {
            return strikeList;
        }

        List<Integer> openStrikes = new ArrayList<>();
        for (TradeOrder order : openOrders) {
            if (order.getOptionStrike() == null) continue;
            if (!optionType.equalsIgnoreCase(order.getOptionType())) continue;
            openStrikes.add(order.getOptionStrike());
        }
        if (openStrikes.isEmpty()) {
            return strikeList;
        }

        // uniqueStrikes(...) de-dupes downstream, so overlap with the derived band
        // costs nothing.
        List<List<Integer>> merged = new ArrayList<>(strikeList);
        merged.add(openStrikes);
        logger.debug("[strikes] pinned {} open-position strike(s) {} for {}",
                openStrikes.size(), openStrikes, optionType);
        return merged;
    }

    private List<List<Integer>> calculateStrikesForCandles(List<MarketData> marketDataList, Instrument instrument, TradeConfig tradeConfig) {
        if (marketDataList == null || marketDataList.isEmpty() || instrument == null || tradeConfig == null) {
            return List.of();
        }
        if (instrument.getStrikePoints() == null || instrument.getStrikePoints().signum() <= 0) {
            logger.warn("Cannot calculate strikes because strike points are missing for instrument: {}", instrument.getInsName());
            return List.of();
        }

        int strikeStep = instrument.getStrikePoints().intValue();
        boolean isCall = tradeConfig.getTradingSide() != null
                && tradeConfig.getTradingSide().toUpperCase().contains("C");
        List<List<Integer>> allStrikes = new ArrayList<>();
        MarketData candle = marketDataList.get(marketDataList.size()-1);

        // ---- changeset 042: exact-offset mode -------------------------------
        // A config that names strike_offset_points wants ONE contract at a
        // signed points distance from ATM, not the depth-count strike SET the
        // block below expands. Returns the ordered candidate list from
        // OffsetStrikeSelector; fetchAndShareStrikeMarketData stops at the first
        // candidate that actually has candles, so the dense-ladder case costs
        // exactly one fetch.
        //
        // Guarded on the column being set, so a config that predates 042 - which
        // is every config strategies 1-4 run - never reaches this branch and the
        // expansion below is bit-identical to what it has always done.
        if (tradeConfig.getStrikeOffsetPoints() != null) {
            int step = tradeConfig.getStrikeStepPoints() != null && tradeConfig.getStrikeStepPoints() > 0
                    ? tradeConfig.getStrikeStepPoints()
                    : strikeStep;
            int atm = OffsetStrikeSelector.atm(candle.getClose().doubleValue(), step);
            List<Integer> candidates = OffsetStrikeSelector.candidates(
                    atm, isCall ? "CE" : "PE", tradeConfig.getStrikeOffsetPoints(), step);
            logger.debug("[strikes] tradeConfigId={} offset-mode: spot={} step={} ATM={} offset={} -> candidates {}",
                    tradeConfig.getId(), candle.getClose(), step, atm,
                    tradeConfig.getStrikeOffsetPoints(), candidates);
            allStrikes.add(candidates);
            return allStrikes;
        }

             double closePrice = candle.getClose().doubleValue();
            int baseStrike = (int) (Math.floor(closePrice / strikeStep) * strikeStep);

            if (tradeConfig.getItmDepth() != null && tradeConfig.getItmDepth() > 0) {
                List<Integer> itmStrikes = new ArrayList<>();
                for (int i = 0; i < tradeConfig.getItmDepth(); i++) {
                    itmStrikes.add(isCall ? baseStrike - i * strikeStep : baseStrike + i * strikeStep);
                }
                allStrikes.add(itmStrikes);
            }

            if (tradeConfig.getOtmDepth() != null && tradeConfig.getOtmDepth() > 0) {
                List<Integer> otmStrikes = new ArrayList<>();
                for (int i = 1; i <= tradeConfig.getOtmDepth(); i++) {
                    otmStrikes.add(isCall ? baseStrike + i * strikeStep : baseStrike - i * strikeStep);
                }
                allStrikes.add(otmStrikes);
            }


        return allStrikes;
    }

    private void fetchAndShareStrikeMarketData(List<List<Integer>> strikeList,
                                               Instrument instrument,
                                               TradeConfig tradeConfig,
                                               Integer timeframe,
                                               LocalDate analysisDate,
                                               String interval,
                                               LocalDateTime startOfDay,
                                               LocalDateTime endOfDay,
                                               String parentMarketDataKey,
                                               Integer strategyId,
                                               LocalDateTime observedAt) {
        if (strikeList == null || strikeList.isEmpty()) {
            return;
        }

        String optionType = resolveOptionType(tradeConfig);
        if (optionType == null) {
            logger.warn("Cannot fetch strike market data because trading side is missing or unsupported: {}",
                    tradeConfig != null ? tradeConfig.getTradingSide() : null);
            return;
        }

        LocalDate expiryDate = instrumentResolver.resolveExpiry(instrument, analysisDate);
        if (expiryDate == null) {
            logger.warn("No expiry date found for instrument: {}, analysis date: {}", instrument.getInsName(), analysisDate);
            return;
        }

        // ---- changeset 042: exact-offset mode walks candidates in order -----
        // In offset mode strikeList.get(0) is OffsetStrikeSelector's ordered
        // candidate list - the exact strike first, then +/-1 and +/-2 steps -
        // and only the FIRST one that actually has candles is wanted. Any
        // further lists are the open-position strikes withOpenPositionStrikes
        // pinned, and those must all be fetched regardless: a position whose
        // strike drifted out of the ATM window still needs a live quote or it
        // freezes at a stale price and its stop can never trigger.
        //
        // Depth-count configs - everything strategies 1-4 run - take the else
        // branch, which is the original single loop over uniqueStrikes.
        boolean offsetMode = tradeConfig != null && tradeConfig.getStrikeOffsetPoints() != null;
        if (offsetMode) {
            List<Integer> candidates = strikeList.get(0);
            boolean got = false;
            for (Integer strike : candidates) {
                if (fetchOneStrike(strike, instrument, tradeConfig, timeframe, interval,
                        startOfDay, endOfDay, parentMarketDataKey, strategyId, observedAt,
                        optionType, expiryDate)) {
                    got = true;
                    break;
                }
            }
            if (!got) {
                logger.warn("[strikes] tradeConfigId={} offset-mode: none of the candidate strikes {} "
                                + "had candles for {} {} - no leg tradable this tick",
                        tradeConfig.getId(), candidates, optionType, expiryDate);
            }
            java.util.Set<Integer> pinned = new java.util.LinkedHashSet<>();
            for (int li = 1; li < strikeList.size(); li++) {
                if (strikeList.get(li) != null) pinned.addAll(strikeList.get(li));
            }
            for (Integer strike : pinned) {
                fetchOneStrike(strike, instrument, tradeConfig, timeframe, interval,
                        startOfDay, endOfDay, parentMarketDataKey, strategyId, observedAt,
                        optionType, expiryDate);
            }
            return;
        }

        for (Integer strike : uniqueStrikes(strikeList)) {
            fetchOneStrike(strike, instrument, tradeConfig, timeframe, interval,
                    startOfDay, endOfDay, parentMarketDataKey, strategyId, observedAt,
                    optionType, expiryDate);
        }
    }

    /**
     * Fetches, caches and journals ONE strike's series.
     *
     * <p>Extracted verbatim from the body of the loop that used to live in
     * {@link #fetchAndShareStrikeMarketData}, so the depth-count path does
     * exactly what it did before. It became a method only because the
     * exact-offset path (changeset 042) needs to stop after the first candidate
     * that yields data, which a single flat loop cannot express.</p>
     *
     * @return true when a non-empty series was cached for this strike
     */
    private boolean fetchOneStrike(Integer strike,
                                   Instrument instrument,
                                   TradeConfig tradeConfig,
                                   Integer timeframe,
                                   String interval,
                                   LocalDateTime startOfDay,
                                   LocalDateTime endOfDay,
                                   String parentMarketDataKey,
                                   Integer strategyId,
                                   LocalDateTime observedAt,
                                   String optionType,
                                   LocalDate expiryDate) {
        {
            // Cache per contract, not per strike — a CE and a PE config on the
            // same day walk identical strikes.
            String optionTokenCacheKey = SharedData.optionTokenKey(expiryDate, strike, optionType);
            String optionToken = SharedData.optionTokenMap.get(optionTokenCacheKey);
            if(optionToken==null) {
                optionToken = instrumentResolver.optionSymbol(instrument, expiryDate, strike, optionType);
                if (optionToken == null) {
                    logger.warn("No option instrument found for strike: {}, type: {}, expiry: {}",
                            strike, optionType, expiryDate);
                    return false;
                }
                SharedData.optionTokenMap.put(optionTokenCacheKey, optionToken);

            }


            List<MarketData> strikeMarketDataList = marketDataService.fetchHistoricalData(
                    optionToken,
                    startOfDay,
                    endOfDay,
                    interval
            );



            if (strikeMarketDataList == null || strikeMarketDataList.isEmpty()) {
                logger.warn("No strike market data available for option token: {}, strike: {}, interval: {}",
                        optionToken, strike, interval);
                return false;
            }


            List<Integer> smaPeriodList = SharedData.allTimeFrameMap.get(timeframe);
            for (Integer period : smaPeriodList) {
                Map<String, Double> strikeIndicators = calculateIndicators(strikeMarketDataList, period);
            }
            String strikeMarketDataKey = toStrikeMarketDataKey(parentMarketDataKey, strike, optionType, optionToken, tradeConfig);
            SharedData.strikeMarketDataList = strikeMarketDataList;
            // Publishes the series, the S8 freshness stamp (which lets strategies
            // refuse a strike that stopped being refreshed when it left the ATM
            // window) and the contract-id index, in one place. Never put into
            // the cache directly - see SharedData.strikeSeriesByToken.
            SharedData.putStrikeSeries(strikeMarketDataKey, strikeMarketDataList, observedAt);

            // CANDIDATE: every leg evaluated this tick, whether or not it is
            // traded. `selected` is left false here because nothing has decided
            // yet - the strategies run after this - so it is the ENTRY row that
            // marks what was taken. This is what makes "how would the strikes we
            // passed over have done" a query rather than another backtest.
            //
            // Written AFTER the SMA stamping above, so the journalled features
            // are the ones the strategy is about to read, not a recomputation.
            if (journal.isEnabled()) {
                journal.record(observations.forCandidate(
                        observedAt,
                        strategyId,
                        tradeConfig != null ? tradeConfig.getId() : null,
                        instrument != null ? instrument.getInsName() : null,
                        optionToken,
                        optionType,
                        strike,
                        timeframe,
                        strikeMarketDataList,
                        isSellSide(tradeConfig)), false);
            }
            return true;
        }
    }

    private void shareStrikesByStrikeKey(List<List<Integer>> strikeList,
                                         Instrument instrument,
                                         TradeConfig tradeConfig,
                                         LocalDate analysisDate,
                                         String interval) {
        if (strikeList == null || strikeList.isEmpty()) {
            return;
        }

        String optionType = resolveOptionType(tradeConfig);
        LocalDate expiryDate = instrumentResolver.resolveExpiry(instrument, analysisDate);
        if (optionType == null || expiryDate == null) {
            return;
        }

        for (Integer strike : uniqueStrikes(strikeList)) {
            SharedData.strikesByInstrumentAndInterval.put(
                    toStrikeKey(instrument, expiryDate, strike, optionType, interval),
                    List.of(List.of(strike))
            );
        }
    }

    private Set<Integer> uniqueStrikes(List<List<Integer>> strikeList) {
        Set<Integer> strikes = new LinkedHashSet<>();
        for (List<Integer> strikeGroup : strikeList) {
            if (strikeGroup != null) {
                strikes.addAll(strikeGroup);
            }
        }
        return strikes;
    }

    private String resolveOptionType(TradeConfig tradeConfig) {
        if (tradeConfig == null || tradeConfig.getTradingSide() == null) {
            return null;
        }
        String tradingSide = tradeConfig.getTradingSide().toUpperCase();
        if (tradingSide.contains("CE") || tradingSide.contains("C")) {
            return "CE";
        }
        if (tradingSide.contains("PE") || tradingSide.contains("P")) {
            return "PE";
        }
        return null;
    }

    private String toStrikeKey(Instrument instrument, LocalDate expiryDate, Integer strike, String optionType, String interval) {
        return UnderlyingSymbols.canonicalName(instrument) + "|" + expiryDate + "|" + optionType + "|" + strike + "|" + interval;
    }

    /** True when this config trades short premium; drives WITH/AGAINST tagging. */
    private static boolean isSellSide(TradeConfig tradeConfig) {
        String txn = tradeConfig == null ? null : tradeConfig.getTransactionType();
        return txn == null || txn.isBlank() || "SELL".equalsIgnoreCase(txn.trim());
    }

    private String toStrikeMarketDataKey(String parentMarketDataKey, Integer strike, String optionType, String optionToken, TradeConfig tradeConfig) {
        return parentMarketDataKey + "|" + optionType + "|" + strike + "|" + optionToken+ "|" + tradeConfig.getItmDepth()+ "|" + tradeConfig.getOtmDepth();
    }

    private Map<String, Double> calculateIndicators(List<MarketData> marketDataList, int smaPeriod) {
        Map<String, Double> indicators = new HashMap<>();
        indicators.put("SMA", indicatorService.calculate("SMA", marketDataList, IndicatorConfig.of(smaPeriod, "SMA")));
        return indicators;
    }

    private int resolveSmaPeriod(AllTimeFramedto timeframe) {
        if (timeframe == null || timeframe.getSma() == null || timeframe.getSma() <= 0) {
            return 14;
        }
        return timeframe.getSma();
    }

    /**
     * Emits the per-tick {@code [index]} narrative line: underlying name,
     * spot (last candle close), ATM, and the configured ITM / OTM strike sets.
     * Only the call site decides when to emit — this method just formats.
     */
    private void logIndexLine(TradeConfigCombinedDTO dto, List<MarketData> marketDataList,
                              List<List<Integer>> strikeList) {
        if (marketDataList == null || marketDataList.isEmpty()) return;
        MarketData last = marketDataList.get(marketDataList.size() - 1);
        if (last == null || last.getClose() == null) return;

        String name = dto.getInstrument() != null ? dto.getInstrument().getInsName() : "?";
        double close = last.getClose().doubleValue();
        int strikeStep = (dto.getInstrument() != null && dto.getInstrument().getStrikePoints() != null)
                ? dto.getInstrument().getStrikePoints().intValue()
                : 0;
        int atm = strikeStep > 0
                ? (int) (Math.floor(close / strikeStep) * strikeStep)
                : -1;

        List<Integer> itm = (strikeList != null && !strikeList.isEmpty()) ? strikeList.get(0) : List.of();
        List<Integer> otm = (strikeList != null && strikeList.size() > 1) ? strikeList.get(1) : List.of();
        logger.debug("[index] {} spot={} ATM={} ITM={} OTM={} tradeConfigId={}",
                name, close, atm, itm, otm,
                dto.getTradeConfig() != null ? dto.getTradeConfig().getId() : null);
    }

    /**
     * Dispatches every active config to its strategy for the moment {@code asOf}
     * — the backtest tick, or wall-clock in live.
     *
     * <p>The parameter is not cosmetic. The candle series a strategy reads spans
     * the whole SMA lookback, so the newest <i>settled</i> bar of a coarse
     * timeframe stays the previous session's close until that timeframe's first
     * bucket of the day completes: on a 15-minute series that is true until
     * 09:30. Without knowing what "now" is, a strategy cannot tell that bar from
     * a current one, and any signal it emits carries the previous session's
     * timestamp and price. See the stale-bar guard in
     * {@code AbstractSmaCrossStrategy.execute}.</p>
     */
    public void runStrategies(LocalDateTime asOf) {
        List<TradeConfigCombinedDTO> combinedDtoList = SharedData.combinedDto;
        if (combinedDtoList == null || combinedDtoList.isEmpty()) {
            logger.warn("No shared trade config data available; skipping strategy dispatch");
            return;
        }
        for (TradeConfigCombinedDTO dto : combinedDtoList) {
            if (dto == null || dto.getTradeConfig() == null) {
                continue;
            }
            try {
                strategyFactory.execute(dto, asOf);
            } catch (Exception ex) {
                // Both ids: one config can appear here several times, once per
                // strategy tagged on it, and the config id alone would not say
                // which of those runs failed.
                logger.error("Strategy execution failed for tradeConfigId={} strategyId={}",
                        dto.getTradeConfig().getId(), dto.getStrategyId(), ex);
            }
        }
    }
}
