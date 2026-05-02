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
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

@Component
public class AnalysisScheduler {
    private static final Logger logger = LoggerFactory.getLogger(AnalysisScheduler.class);
    private final MarketDataService marketDataService;
    private final IndicatorService indicatorService;
    private final InstrumentDetailsRepository instrumentDetailsRepository;
    private final ExpiryDatesRepository expiryDatesRepository;

    public AnalysisScheduler(MarketDataService marketDataService,
                             IndicatorService indicatorService,
                             InstrumentDetailsRepository instrumentDetailsRepository,
                             ExpiryDatesRepository expiryDatesRepository) {
        this.marketDataService = Objects.requireNonNull(marketDataService, "marketDataService must not be null");
        this.indicatorService = Objects.requireNonNull(indicatorService, "indicatorService must not be null");
        this.instrumentDetailsRepository = Objects.requireNonNull(instrumentDetailsRepository, "instrumentDetailsRepository must not be null");
        this.expiryDatesRepository = Objects.requireNonNull(expiryDatesRepository, "expiryDatesRepository must not be null");
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
        logger.info("Calculating indicators for date-time: {}", analysisDateTime);

        try {
            // Calculate startOfDay: 500 candles of 15 minutes = 7500 minutes lookback
            LocalDateTime startOfDay = analysisDateTime.minusMinutes(1000 * 10);

            logger.debug("Fetching market data from {} to {}", startOfDay, analysisDateTime);

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
                for (Integer timeframe : timeframes.keySet()) {
                    String interval = toMarketDataInterval(timeframe);
                    if (interval == null) {
                        logger.warn("Skipping instrument token {} because timeframe has no time period", symbol);
                        continue;
                    }

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
                    shareStrikesByStrikeKey(strikeList, dto.getInstrument(), dto.getTradeConfig(), analysisDateTime.toLocalDate(), interval);

                    fetchAndShareStrikeMarketData(strikeList, dto.getInstrument(), dto.getTradeConfig(), timeframe, analysisDateTime.toLocalDate(), interval, startOfDay, analysisDateTime, marketDataKey);

                }
            }

            logger.info("Indicator analysis completed for date-time: {}", analysisDateTime);

        } catch (Exception ex) {
            logger.error("Error calculating indicators for date-time: {}", analysisDateTime, ex);
            throw new RuntimeException("Indicator calculation failed for date-time: " + analysisDateTime, ex);
        }
    }

    private String toMarketDataInterval(Integer timeframe) {

        return timeframe + "minute";
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
            InstrumentDetails optionInstrument = resolveOptionInstrument(strike, optionType, instrument, expiryDate);
            if (optionInstrument == null || optionInstrument.getInstrumentToken() == null) {
                logger.warn("No option instrument found for strike: {}, type: {}", strike, optionType);
                continue;
            }

            String optionToken = optionInstrument.getInstrumentToken().toString();
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
            String strikeMarketDataKey = toStrikeMarketDataKey(parentMarketDataKey, strike, optionType, optionToken, tradeConfig, interval);
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

        String tradingSymbol = buildOptionTradingSymbol(instrument, expiryDate, strike, optionType);
        // Convert LocalDate to String format (YYYY-MM-DD) and Integer to BigDecimal for repository query
        String expiryString = expiryDate.toString();
        BigDecimal strikeBigDecimal = new BigDecimal(strike);

        return instrumentDetailsRepository.findByCriteria(
                instrument.getInsName(),
                expiryString,
                strikeBigDecimal,
                optionType
        ).orElseGet(() -> {
            logger.warn("No instrument details found for trading symbol: {}", tradingSymbol);
            return null;
        });
    }

    private String buildOptionTradingSymbol(Instrument instrument, LocalDate expiryDate, Integer strike, String optionType) {
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
    }

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

    private String toStrikeMarketDataKey(String parentMarketDataKey, Integer strike, String optionType, String optionToken, TradeConfig tradeConfig, String interval) {
        return parentMarketDataKey + "|" + optionType + "|" + strike + "|" + optionToken+ "|" + tradeConfig.getItmDepth()+ "|" + tradeConfig.getOtmDepth()+ "|" + interval;
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
}
