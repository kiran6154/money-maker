package com.moneymaker.market.service;

import com.moneymaker.entity.MarketData;
import com.moneymaker.market.provider.MarketDataProvider;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

@Service
public class MarketDataService {
    private static final Logger logger = LoggerFactory.getLogger(MarketDataService.class);
    private final MarketDataProvider marketDataProvider;

    public MarketDataService(MarketDataProvider marketDataProvider) {
        this.marketDataProvider = Objects.requireNonNull(marketDataProvider, "marketDataProvider must not be null");
        logger.info("MarketDataService initialized with provider: {}", marketDataProvider.getName());
    }

    public List<MarketData> fetchHistoricalData(String symbol, LocalDateTime from, LocalDateTime to, String interval) {
        Objects.requireNonNull(symbol, "symbol must not be null");
        Objects.requireNonNull(from, "from must not be null");
        Objects.requireNonNull(to, "to must not be null");
        Objects.requireNonNull(interval, "interval must not be null");

        try {
            return marketDataProvider.fetchHistoricalData(symbol, from, to, interval);
        } catch (Exception ex) {
            logger.error("Error fetching historical data for symbol: {} using provider: {}", symbol, marketDataProvider.getName(), ex);
            throw new RuntimeException("Failed to fetch market data: " + ex.getMessage(), ex);
        }
    }

    public List<Double> extractClosePrices(List<MarketData> marketDataList) {
        List<Double> closePrices = new ArrayList<>();
        if (marketDataList == null || marketDataList.isEmpty()) {
            return closePrices;
        }
        for (MarketData data : marketDataList) {
            if (data.getClose() != null) {
                closePrices.add(data.getClose().doubleValue());
            }
        }
        return closePrices;
    }

    public String getActiveProvider() {
        return marketDataProvider.getName();
    }
}
