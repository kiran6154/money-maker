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
@ConditionalOnProperty(name = "market.data.provider", havingValue = "CUSTOM")
public class CustomMarketDataProvider implements MarketDataProvider {
    private static final Logger logger = LoggerFactory.getLogger(CustomMarketDataProvider.class);
    private static final String NAME = "CUSTOM";
    private final CustomDataSource customDataSource;

    public CustomMarketDataProvider(CustomDataSource customDataSource) {
        this.customDataSource = Objects.requireNonNull(customDataSource, "customDataSource must not be null");
        logger.info("CustomMarketDataProvider initialized");
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
            List<CustomCandle> customCandles = customDataSource.fetchCandles(symbol, from, to, interval);
            return mapToMarketData(customCandles, symbol);
        } catch (Exception ex) {
            logger.error("Failed to fetch historical data from custom provider for symbol: {}", symbol, ex);
            throw new RuntimeException("Failed to fetch historical data from custom provider: " + ex.getMessage(), ex);
        }
    }

    private List<MarketData> mapToMarketData(List<CustomCandle> customCandles, String symbol) {
        List<MarketData> marketDataList = new ArrayList<>();
        if (customCandles == null || customCandles.isEmpty()) {
            return marketDataList;
        }
        for (CustomCandle custom : customCandles) {
            MarketData marketData = new MarketData();
            marketData.setTimestamp(custom.getTimestamp());
            marketData.setOpen(BigDecimal.valueOf(custom.getOpen()));
            marketData.setHigh(BigDecimal.valueOf(custom.getHigh()));
            marketData.setLow(BigDecimal.valueOf(custom.getLow()));
            marketData.setClose(BigDecimal.valueOf(custom.getClose()));
            marketData.setInstrumenttoken(symbol);
            marketDataList.add(marketData);
        }
        return marketDataList;
    }

    public interface CustomDataSource {
        List<CustomCandle> fetchCandles(String symbol, LocalDateTime from, LocalDateTime to, String interval);
    }

    public static class CustomCandle {
        private LocalDateTime timestamp;
        private double open;
        private double high;
        private double low;
        private double close;
        private double volume;

        public CustomCandle(LocalDateTime timestamp, double open, double high, double low, double close, double volume) {
            this.timestamp = timestamp;
            this.open = open;
            this.high = high;
            this.low = low;
            this.close = close;
            this.volume = volume;
        }

        public LocalDateTime getTimestamp() {
            return timestamp;
        }

        public double getOpen() {
            return open;
        }

        public double getHigh() {
            return high;
        }

        public double getLow() {
            return low;
        }

        public double getClose() {
            return close;
        }

        public double getVolume() {
            return volume;
        }
    }
}
