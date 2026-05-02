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
public class Strategy2 implements Strategy {

    public static final int ID = 2;

    @Override
    public int getId() {
        return ID;
    }

    @Override
    public void execute(TradeConfigCombinedDTO config) {
        Integer tradeConfigId = (config != null && config.getTradeConfig() != null)
                ? config.getTradeConfig().getId()
                : null;

        Map<String, List<MarketData>> strikeMarketData = SharedData.strikeMarketDataByInstrumentAndInterval;
        if (strikeMarketData == null || strikeMarketData.isEmpty()) {

            return;
        }

        strikeMarketData.forEach((key, marketDataList) -> {

        });
    }
}

