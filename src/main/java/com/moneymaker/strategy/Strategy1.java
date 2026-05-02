package com.moneymaker.strategy;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

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
        System.out.println("Executing Strategy1 for tradeConfigId="
                + (config != null && config.getTradeConfig() != null
                        ? config.getTradeConfig().getId()
                        : "null"));
    }
}

