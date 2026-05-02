package com.moneymaker.indicator;

import com.moneymaker.entity.MarketData;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Objects;

@Service
public final class IndicatorService {

    public Double calculate(String indicatorName, List<MarketData> marketData, IndicatorConfig config) {
        Objects.requireNonNull(indicatorName, "indicatorName must not be null");
        Objects.requireNonNull(marketData, "marketData must not be null");
        Objects.requireNonNull(config, "config must not be null");

        if (marketData.isEmpty()) {            throw new IllegalArgumentException("marketData must not be empty");
        }

        Indicator indicator = IndicatorFactory.create(indicatorName);
        return indicator.calculate(marketData, config);
    }

    public static Double calculate(String indicatorName, List<MarketData> marketData, int period) {
        IndicatorConfig config = IndicatorConfig.of(period);
        return new IndicatorService().calculate(indicatorName, marketData, config);
    }
}

