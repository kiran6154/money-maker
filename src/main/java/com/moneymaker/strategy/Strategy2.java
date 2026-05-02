package com.moneymaker.strategy;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

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
        System.out.println("Executing Strategy2 for tradeConfigId="
                + (config != null && config.getTradeConfig() != null
                        ? config.getTradeConfig().getId()
                        : "null"));
    }
}

