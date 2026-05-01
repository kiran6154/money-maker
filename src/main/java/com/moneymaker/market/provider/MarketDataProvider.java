package com.moneymaker.market.provider;

import com.moneymaker.entity.MarketData;
import java.time.LocalDateTime;
import java.util.List;

public interface MarketDataProvider {
    String getName();
    List<MarketData> fetchHistoricalData(String symbol, LocalDateTime from, LocalDateTime to, String interval);
}
