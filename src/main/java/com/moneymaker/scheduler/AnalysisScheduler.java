package com.moneymaker.scheduler;

import com.moneymaker.entity.MarketData;
import com.moneymaker.indicator.IndicatorConfig;
import com.moneymaker.indicator.IndicatorService;
import com.moneymaker.market.service.MarketDataService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Objects;

@Component
public class AnalysisScheduler {
    private static final Logger logger = LoggerFactory.getLogger(AnalysisScheduler.class);
    private final MarketDataService marketDataService;
    private final IndicatorService indicatorService;

    public AnalysisScheduler(MarketDataService marketDataService, IndicatorService indicatorService) {
        this.marketDataService = Objects.requireNonNull(marketDataService, "marketDataService must not be null");
        this.indicatorService = Objects.requireNonNull(indicatorService, "indicatorService must not be null");
    }

    @Scheduled(cron = "0 0/5 9-16 * * MON-FRI")
    public void analyzeMarketData() {
        logger.info("Starting market analysis scheduler");
        try {
            calculateIndicator(LocalDate.now());
        } catch (Exception ex) {
            logger.error("Error in market analysis scheduler", ex);
        }
    }

    public void calculateIndicator(LocalDate analysisDate) {
        Objects.requireNonNull(analysisDate, "analysisDate must not be null");
        logger.info("Calculating indicators for date: {}", analysisDate);

        try {
            LocalDateTime startOfDay = analysisDate.atStartOfDay();
            LocalDateTime endOfDay = analysisDate.atTime(LocalTime.MAX);

            logger.debug("Fetching market data from {} to {}", startOfDay, endOfDay);

            List<MarketData> marketDataList = marketDataService.fetchHistoricalData(
                    "DEFAULT_SYMBOL",
                    startOfDay,
                    endOfDay,
                    "5minute"
            );

            if (marketDataList == null || marketDataList.isEmpty()) {
                logger.warn("No market data available for date: {}", analysisDate);
                return;
            }

            List<Double> closePrices = marketDataService.extractClosePrices(marketDataList);

            IndicatorConfig smaConfig = IndicatorConfig.of(14, "SMA");
            List<Double> smaValues = indicatorService.calculate("SMA", marketDataList, smaConfig);
            logger.info("SMA calculation completed with {} values", smaValues.size());

            IndicatorConfig emaConfig = IndicatorConfig.of(14, "EMA");
            List<Double> emaValues = indicatorService.calculate("EMA", marketDataList, emaConfig);
            logger.info("EMA calculation completed with {} values", emaValues.size());

            IndicatorConfig rsiConfig = IndicatorConfig.of(14, "RSI");
            List<Double> rsiValues = indicatorService.calculate("RSI", marketDataList, rsiConfig);
            logger.info("RSI calculation completed with {} values", rsiValues.size());

            logger.info("Indicator analysis completed for date: {}", analysisDate);

        } catch (Exception ex) {
            logger.error("Error calculating indicators for date: {}", analysisDate, ex);
            throw new RuntimeException("Indicator calculation failed for date: " + analysisDate, ex);
        }
    }
}

