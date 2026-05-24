package com.moneymaker.scheduler;

import com.moneymaker.dto.AllTimeFramedto;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.indicator.IndicatorConfig;
import com.moneymaker.indicator.IndicatorService;
import com.moneymaker.market.service.MarketDataService;
import com.moneymaker.repository.ExpiryDatesRepository;
import com.moneymaker.repository.InstrumentDetailsRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.strategy.StrategyFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.*;

@Component
public class AnalysisScheduler {
    private static final Logger logger = LoggerFactory.getLogger(AnalysisScheduler.class);
    private final MarketDataService marketDataService;
    private final IndicatorService indicatorService;
    private final InstrumentDetailsRepository instrumentDetailsRepository;
    private final ExpiryDatesRepository expiryDatesRepository;
    private final StrategyFactory strategyFactory;

    public AnalysisScheduler(MarketDataService marketDataService,
                             IndicatorService indicatorService,
                             InstrumentDetailsRepository instrumentDetailsRepository,
                             ExpiryDatesRepository expiryDatesRepository,
                             StrategyFactory strategyFactory) {
        this.marketDataService = Objects.requireNonNull(marketDataService, "marketDataService must not be null");
        this.indicatorService = Objects.requireNonNull(indicatorService, "indicatorService must not be null");
        this.instrumentDetailsRepository = Objects.requireNonNull(instrumentDetailsRepository, "instrumentDetailsRepository must not be null");
        this.expiryDatesRepository = Objects.requireNonNull(expiryDatesRepository, "expiryDatesRepository must not be null");
        this.strategyFactory = Objects.requireNonNull(strategyFactory, "strategyFactory must not be null");
    }

    @Scheduled(cron = "0 0/5 9-16 * * MON-FRI")
    public void analyzeMarketData() {
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

            for (TradeConfigCombinedDTO dto : combinedDtoList) {
                if (dto.getInstrumentDetails() == null || dto.getInstrumentDetails().getInstrumentToken() == null) {
                    logger.warn("Skipping trade config without instrument token: {}", dto.getTradeConfig());
                    continue;
                }

                Map<Integer, List<Integer>>  timeframes = SharedData.allTimeFrameMap;
                if (timeframes == null || timeframes.isEmpty()) {
                    logger.warn("No timeframes configured for instrument token: {}", dto.getInstrumentDetails().getInstrumentToken());
                    continue;
                }

                String symbol = dto.getInstrumentDetails().getInstrumentToken().toString();
                boolean indexLineEmitted = false;
                for (Integer timeframe : timeframes.keySet()) {
                    String interval = toMarketDataInterval(timeframe);
                    if (interval == null) {
                        logger.warn("Skipping instrument token {} because timeframe has no time period", symbol);
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

                    List<List<Integer>> strikeList = calculateStrikesForCandles(marketDataList, dto.getInstrument(), dto.getTradeConfig());
                    SharedData.strikeList = strikeList;

                    // One [index] line per config per tick — emitted on the first
                    // timeframe iteration. Strikes are computed off the last candle's
                    // close so they're identical across timeframes; no value in
                    // repeating the line per timeframe.
                    if (!indexLineEmitted && logger.isDebugEnabled()) {
                        logIndexLine(dto, marketDataList, strikeList);
                        indexLineEmitted = true;
                    }

                    fetchAndShareStrikeMarketData(strikeList, dto.getInstrument(), dto.getTradeConfig(), timeframe, analysisDateTime.toLocalDate(), interval, startOfDay, analysisDateTime, marketDataKey);

                }
            }

            logger.debug("Indicator analysis completed for date-time: {}", analysisDateTime);

        } catch (Exception ex) {
            logger.error("Error calculating indicators for date-time: {}", analysisDateTime, ex);
            throw new RuntimeException("Indicator calculation failed for date-time: " + analysisDateTime, ex);
        }
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
    private int computeLookbackCalendarDays() {
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
                                               String parentMarketDataKey) {
        if (strikeList == null || strikeList.isEmpty()) {
            return;
        }

        String optionType = resolveOptionType(tradeConfig);
        if (optionType == null) {
            logger.warn("Cannot fetch strike market data because trading side is missing or unsupported: {}",
                    tradeConfig != null ? tradeConfig.getTradingSide() : null);
            return;
        }

        LocalDate expiryDate = resolveExpiryDate(instrument, analysisDate);
        if (expiryDate == null) {
            logger.warn("No expiry date found for instrument: {}, analysis date: {}", instrument.getInsName(), analysisDate);
            return;
        }

        for (Integer strike : uniqueStrikes(strikeList)) {
            String optionToken =SharedData.optionTokenMap.get(strike);
            if(optionToken==null) {
                InstrumentDetails optionInstrument = resolveOptionInstrument(strike, optionType, instrument, expiryDate);
                if (optionInstrument == null || optionInstrument.getInstrumentToken() == null) {
                    logger.warn("No option instrument found for strike: {}, type: {}", strike, optionType);
                    continue;
                }
                optionToken=optionInstrument.getInstrumentToken().toString();
                SharedData.optionTokenMap.put(strike,optionToken);

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
                continue;
            }


            List<Integer> smaPeriodList = SharedData.allTimeFrameMap.get(timeframe);
            for (Integer period : smaPeriodList) {
                Map<String, Double> strikeIndicators = calculateIndicators(strikeMarketDataList, period);
            }
            String strikeMarketDataKey = toStrikeMarketDataKey(parentMarketDataKey, strike, optionType, optionToken, tradeConfig);
            SharedData.strikeMarketDataList = strikeMarketDataList;
            SharedData.strikeMarketDataByInstrumentAndInterval.put(
                    strikeMarketDataKey,
                    strikeMarketDataList);
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
        LocalDate expiryDate = resolveExpiryDate(instrument, analysisDate);
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

    private LocalDate resolveExpiryDate(Instrument instrument, LocalDate analysisDate) {
        if (instrument == null || analysisDate == null) {
            return null;
        }
        return expiryDatesRepository
                .findFirstByInstrumentAndExpiryDateGreaterThanEqualOrderByExpiryDateAsc(instrument, analysisDate)
                .map(com.moneymaker.entity.ExpiryDates::getExpiryDate)
                .orElse(null);
    }

    private InstrumentDetails resolveOptionInstrument(Integer strike, String optionType, Instrument instrument, LocalDate expiryDate) {
        if (strike == null || optionType == null || instrument == null || expiryDate == null) {
            return null;
        }

       // String tradingSymbol = buildOptionTradingSymbol(instrument, expiryDate, strike, optionType);
        // Convert LocalDate to String format (YYYY-MM-DD) and Integer to BigDecimal for repository query
        String expiryString = expiryDate.toString();
        BigDecimal strikeBigDecimal = new BigDecimal(strike);
        List<InstrumentDetails> matches = instrumentDetailsRepository.findByCriteria(
                instrument.getInsName(),
                expiryString,
                strikeBigDecimal,
                optionType
        );

        if (matches.isEmpty()) {
            logger.warn("No InstrumentDetails for {}, expiry={}, strike={}, type={}",
                    instrument.getInsName(), expiryString, strikeBigDecimal, optionType);
            return null;
        }
        if (matches.size() > 1) {
            // Same expiry / strike / type on two listings (e.g. NSE + BSE) — pick
            // the lowest-id row deterministically and warn so the data can be cleaned.
            logger.warn("Multiple InstrumentDetails ({}) for {}, expiry={}, strike={}, type={} — picking id={}",
                    matches.size(), instrument.getInsName(), expiryString, strikeBigDecimal,
                    optionType, matches.get(0).getInstrumentToken());
        }
        return matches.get(0);
    }

/*    private String buildOptionTradingSymbol(Instrument instrument, LocalDate expiryDate, Integer strike, String optionType) {
        int day = expiryDate.getDayOfMonth();
        int monthValue = expiryDate.getMonthValue();
        int year = expiryDate.getYear();
        String cepe = optionType.equalsIgnoreCase("C") ? "CE" : optionType;
        String symbolPrefix = toOptionSymbolPrefix(instrument);

        LocalDate firstOfMonth = expiryDate.withDayOfMonth(1);
        LocalDate lastOfMonth = expiryDate.withDayOfMonth(expiryDate.lengthOfMonth());
        List<com.moneymaker.entity.ExpiryDates> expiriesInMonth = expiryDatesRepository
                .findByInstrumentAndExpiryDateBetween(instrument, firstOfMonth, lastOfMonth);
        boolean isLastExpiry = expiriesInMonth.stream()
                .map(com.moneymaker.entity.ExpiryDates::getExpiryDate)
                .max(LocalDate::compareTo)
                .orElse(expiryDate)
                .equals(expiryDate);

        String yy = String.valueOf(year).substring(2);
        if (isLastExpiry) {
            String monthAbbr = expiryDate.getMonth().toString().substring(0, 3).toUpperCase();
            return String.format("%s%s%s%s%s", symbolPrefix, yy, monthAbbr, strike, cepe);
        }

        String mm = (monthValue < 10 ? "0" : "") + monthValue;
        String dd = (day < 10 ? "0" : "") + day;
        return String.format("%s%s%s%s%s%s", symbolPrefix, yy, mm, dd, strike, cepe);
    }*/

    private String toOptionSymbolPrefix(Instrument instrument) {
        if (instrument.getInsName() == null || instrument.getInsName().isBlank()) {
            return "";
        }
        String name = instrument.getInsName().toUpperCase();
        if (name.contains("BANKNIFTY")) {
            return "BANKNIFTY";
        }
        if (name.contains("FINNIFTY")) {
            return "FINNIFTY";
        }
        if (name.contains("NIFTY")) {
            return "NIFTY";
        }
        return name.replaceAll("[^A-Z]", "");
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
        return toOptionSymbolPrefix(instrument) + "|" + expiryDate + "|" + optionType + "|" + strike + "|" + interval;
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

    public void runStrategies() {
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
                strategyFactory.execute(dto);
            } catch (Exception ex) {
                logger.error("Strategy execution failed for tradeConfigId={}",
                        dto.getTradeConfig().getId(), ex);
            }
        }
    }
}
