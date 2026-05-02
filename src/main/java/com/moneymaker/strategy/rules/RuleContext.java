package com.moneymaker.strategy.rules;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;

import java.util.List;

/**
 * Bundle of inputs every {@link TradeRule} may need. Public final fields keep
 * lambdas terse: {@code ctx -> ctx.candle.isSma50DownTrending()}.
 */
public final class RuleContext {
    public final MarketData candle;
    public final int index;
    public final List<MarketData> allCandles;
    public final Integer primarySmaPeriod;
    public final TradeConfigCombinedDTO config;

    public RuleContext(MarketData candle, int index, List<MarketData> allCandles,
                       Integer primarySmaPeriod, TradeConfigCombinedDTO config) {
        this.candle = candle;
        this.index = index;
        this.allCandles = allCandles;
        this.primarySmaPeriod = primarySmaPeriod;
        this.config = config;
    }
}
