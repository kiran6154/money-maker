package com.moneymaker.market.provider;

import com.moneymaker.entity.MarketData;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

@Component
@ConditionalOnProperty(name = "market.data.provider", havingValue = "GROWW")
public class GrowwMarketDataProvider implements MarketDataProvider {
    private static final Logger logger = LoggerFactory.getLogger(GrowwMarketDataProvider.class);
    private static final String NAME = "GROWW";
    private final GrowwApiClient growwApiClient;

    public GrowwMarketDataProvider(GrowwApiClient growwApiClient) {
        this.growwApiClient = Objects.requireNonNull(growwApiClient, "growwApiClient must not be null");
        logger.info("GrowwMarketDataProvider initialized");
    }

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public List<MarketData> fetchHistoricalData(String symbol, LocalDateTime from, LocalDateTime to, String interval) {
        Objects.requireNonNull(symbol, "symbol must not be null");
        Objects.requireNonNull(from, "from must not be null");
        Objects.requireNonNull(to, "to must not be null");
        Objects.requireNonNull(interval, "interval must not be null");

        try {
            GrowwHistoricalDataResponse response = growwApiClient.getHistoricalData(symbol, from, to, interval);
            return mapToMarketData(response, symbol);
        } catch (Exception ex) {
            logger.error("Failed to fetch historical data from Groww for symbol: {}", symbol, ex);
            throw new RuntimeException("Failed to fetch historical data from Groww: " + ex.getMessage(), ex);
        }
    }

    private List<MarketData> mapToMarketData(GrowwHistoricalDataResponse response, String symbol) {
        List<MarketData> marketDataList = new ArrayList<>();
        if (response == null || response.getCandles() == null || response.getCandles().isEmpty()) {
            return marketDataList;
        }
        for (GrowwCandle candle : response.getCandles()) {
            MarketData marketData = new MarketData();
            marketData.setTimestamp(candle.getTimestamp());
            marketData.setOpen(BigDecimal.valueOf(candle.getOpen()));
            marketData.setHigh(BigDecimal.valueOf(candle.getHigh()));
            marketData.setLow(BigDecimal.valueOf(candle.getLow()));
            marketData.setClose(BigDecimal.valueOf(candle.getClose()));
            marketData.setInstrumenttoken(symbol);
            marketDataList.add(marketData);
        }
        return marketDataList;
    }

    public static class GrowwApiClient {
        public GrowwHistoricalDataResponse getHistoricalData(String symbol, LocalDateTime from, LocalDateTime to, String interval) {
            return new GrowwHistoricalDataResponse();
        }
    }

    public static class GrowwHistoricalDataResponse {
        private List<GrowwCandle> candles = new ArrayList<>();

        public List<GrowwCandle> getCandles() {
            return candles;
        }

        public void setCandles(List<GrowwCandle> candles) {
            this.candles = candles;
        }
    }

    public static class GrowwCandle {
        private LocalDateTime timestamp;
        private double open;
        private double high;
        private double low;
        private double close;
        private double volume;

        public LocalDateTime getTimestamp() {
            return timestamp;
        }

        public void setTimestamp(LocalDateTime timestamp) {
            this.timestamp = timestamp;
        }

        public double getOpen() {
            return open;
        }

        public void setOpen(double open) {
            this.open = open;
        }

        public double getHigh() {
            return high;
        }

        public void setHigh(double high) {
            this.high = high;
        }

        public double getLow() {
            return low;
        }

        public void setLow(double low) {
            this.low = low;
        }

        public double getClose() {
            return close;
        }

        public void setClose(double close) {
            this.close = close;
        }

        public double getVolume() {
            return volume;
        }

        public void setVolume(double volume) {
            this.volume = volume;
        }
    }
}
