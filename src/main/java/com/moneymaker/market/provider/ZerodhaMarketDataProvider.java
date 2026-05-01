package com.moneymaker.market.provider;

import com.moneymaker.entity.MarketData;
import com.zerodhatech.kiteconnect.KiteConnect;
import com.zerodhatech.kiteconnect.kitehttp.exceptions.KiteException;
import com.zerodhatech.models.HistoricalData;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Objects;

@Component
@ConditionalOnProperty(name = "broker.active", havingValue = "ZERODHA", matchIfMissing = true)
public class ZerodhaMarketDataProvider implements MarketDataProvider {
    private static final Logger logger = LoggerFactory.getLogger(ZerodhaMarketDataProvider.class);
    private static final String NAME = "ZERODHA";
    private static final DateTimeFormatter KITE_TIMESTAMP_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ssZ");
    private final KiteConnect sharedKiteConnect;

    public ZerodhaMarketDataProvider(@Qualifier("sharedKiteConnect") KiteConnect sharedKiteConnect) {
        this.sharedKiteConnect = Objects.requireNonNull(sharedKiteConnect, "sharedKiteConnect must not be null");
        logger.info("ZerodhaMarketDataProvider initialized");
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
            Date fromDate = Date.from(from.atZone(ZoneId.systemDefault()).toInstant());
            Date toDate = Date.from(to.atZone(ZoneId.systemDefault()).toInstant());

            HistoricalData historicalData = sharedKiteConnect.getHistoricalData(
                    fromDate,
                    toDate,
                    symbol,
                    interval,
                    false,
                    true
            );
            return mapToMarketData(historicalData, symbol);
        } catch (KiteException ex) {
            logger.error("Failed to fetch historical data from Zerodha for symbol: {}", symbol, ex);
            throw new RuntimeException("Failed to fetch historical data from Zerodha: " + ex.message, ex);
        } catch (Exception ex) {
            logger.error("Failed to fetch historical data from Zerodha for symbol: {}", symbol, ex);
            throw new RuntimeException("Failed to fetch historical data from Zerodha: " + ex.getMessage(), ex);
        }
    }

    private List<MarketData> mapToMarketData(HistoricalData historicalData, String symbol) {
        List<MarketData> marketDataList = new ArrayList<>();
        List<HistoricalData> historicalDataList = historicalData != null ? historicalData.dataArrayList : null;
        if (historicalDataList == null || historicalDataList.isEmpty()) {
            return marketDataList;
        }
        for (HistoricalData data : historicalDataList) {
            MarketData marketData = new MarketData();
            marketData.setTimestamp(parseTimestamp(data.timeStamp));
            marketData.setOpen(BigDecimal.valueOf(data.open));
            marketData.setHigh(BigDecimal.valueOf(data.high));
            marketData.setLow(BigDecimal.valueOf(data.low));
            marketData.setClose(BigDecimal.valueOf(data.close));
            marketData.setInstrumenttoken(symbol);
            marketDataList.add(marketData);
        }
        return marketDataList;
    }

    private LocalDateTime parseTimestamp(String timestamp) {
        if (timestamp == null || timestamp.isBlank()) {
            return LocalDateTime.now();
        }
        try {
            return OffsetDateTime.parse(timestamp, KITE_TIMESTAMP_FORMATTER).toLocalDateTime();
        } catch (DateTimeParseException ignored) {
            try {
                return OffsetDateTime.parse(timestamp, DateTimeFormatter.ISO_OFFSET_DATE_TIME).toLocalDateTime();
            } catch (DateTimeParseException ex) {
                try {
                    return Instant.parse(timestamp).atZone(ZoneId.systemDefault()).toLocalDateTime();
                } catch (DateTimeParseException instantEx) {
                    logger.warn("Unable to parse Kite historical timestamp: {}", timestamp);
                    return LocalDateTime.now();
                }
            }
        }
    }
}
