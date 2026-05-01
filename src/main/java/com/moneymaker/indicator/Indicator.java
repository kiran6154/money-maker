package com.moneymaker.indicator;

import com.moneymaker.entity.MarketData;
import java.util.List;

public interface Indicator {
    String getName();
    List<Double> calculate(List<MarketData> marketData, IndicatorConfig config);
}

