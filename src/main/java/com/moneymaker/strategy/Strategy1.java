package com.moneymaker.strategy;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.moneymaker.shared.data.SharedData;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Map;

@Slf4j
@Component
public class Strategy1 implements Strategy {

    public static final int ID = 1;

    @Override
    public int getId() {
        return ID;
    }

    @Override
    public void execute(TradeConfigCombinedDTO config) {
        Integer tradeConfigId = (config != null && config.getTradeConfig() != null)
                ? config.getTradeConfig().getId()
                : null;
        System.out.println("Executing Strategy1 for tradeConfigId=" + tradeConfigId);

        Map<String, List<MarketData>> strikeMarketData = SharedData.strikeMarketDataByInstrumentAndInterval;
        if (strikeMarketData == null || strikeMarketData.isEmpty()) {
            System.out.println("  Strategy1: No strike market data available");
            return;
        }

        strikeMarketData.forEach((key, marketDataList) -> {
            System.out.println("  Strategy1: Processing strike key=" + key
                    + ", dataPoints=" + (marketDataList != null ? marketDataList.size() : 0));

            // Create variables for analysis (dummy values for Nifty options 150-200 range)
            double open = 178.0;  // Dummy open price
            double high = 182.0;  // Dummy high price  
            double low = 174.0;   // Dummy low price
            double close = 175.5; // Dummy close price
            double smaValue = 176.0; // Dummy SMA value
            boolean tradeStart = false;

            // Logic: if open > sma AND close < sma, mark tradeStart as true
            if (open > smaValue && close < smaValue) {
                tradeStart = true;
            }

            System.out.println("    Open: " + open + ", High: " + high + ", Low: " + low + 
                             ", Close: " + close + ", SMA: " + smaValue + ", TradeStart: " + tradeStart);
        });
    }
}
