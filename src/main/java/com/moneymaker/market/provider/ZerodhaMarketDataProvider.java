package com.moneymaker.market.provider;

import com.moneymaker.entity.MarketData;
import com.zerodhatech.kiteconnect.KiteConnect;
import com.zerodhatech.models.HistoricalData;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

@Component
@ConditionalOnProperty(name = "market.data.provider", havingValue = "ZERODHA")
public class ZerodhaMarketDataProvider implements MarketDataProvider {
    private static final Logger logger = LoggerFactory.getLogger(ZerodhaMarketDataProvider.class);
    private static final String NAME = "ZERODHA";
    private final KiteConnect kiteConnect;

    public ZerodhaMarketDataProvider(KiteConnect kiteConnect) {
        this.kiteConnect = Objects.requireNonNull(kiteConnect, "kiteConnect must not be null");
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
            long instrumentToken = resolveInstrumentToken(symbol);
            long fromEpoch = from.atZone(ZoneId.systemDefault()).toInstant().getEpochSecond();
            long toEpoch = to.atZone(ZoneId.systemDefault()).toInstant().getEpochSecond();

/*            List<HistoricalData> historicalDataList = kiteConnect.getHistoricalData(
                    fromEpoch,
                    toEpoch,
                    instrumentToken,
                    interval,
                    false,
                    true
            );*/
            List<HistoricalData> historicalDataList = new ArrayList<>();
            return mapToMarketData(historicalDataList, symbol);
        } catch (Exception ex) {
            logger.error("Failed to fetch historical data from Zerodha for symbol: {}", symbol, ex);
            throw new RuntimeException("Failed to fetch historical data from Zerodha: " + ex.getMessage(), ex);
        }
    }

    private long resolveInstrumentToken(String symbol) {
        return 0L;
    }

    private List<MarketData> mapToMarketData(List<HistoricalData> historicalDataList, String symbol) {
        List<MarketData> marketDataList = new ArrayList<>();
        if (historicalDataList == null || historicalDataList.isEmpty()) {
            return marketDataList;
        }
        for (HistoricalData data : historicalDataList) {
            MarketData marketData = new MarketData();
           // marketData.setTimestamp(data.timeStamp != null ? data.timeStamp.toLocalDateTime() : LocalDateTime.now());
            marketData.setOpen(BigDecimal.valueOf(data.open));
            marketData.setHigh(BigDecimal.valueOf(data.high));
            marketData.setLow(BigDecimal.valueOf(data.low));
            marketData.setClose(BigDecimal.valueOf(data.close));
            marketData.setInstrumenttoken(symbol);
            marketDataList.add(marketData);
        }
        return marketDataList;
    }
}
