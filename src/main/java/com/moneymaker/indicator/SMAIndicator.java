package com.moneymaker.indicator;

import com.moneymaker.entity.MarketData;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

public class SMAIndicator implements Indicator {
    private static final String NAME = "SMA";

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public List<Double> calculate(List<MarketData> marketData, IndicatorConfig config) {
        Objects.requireNonNull(marketData, "marketData must not be null");
        Objects.requireNonNull(config, "config must not be null");

        if (marketData.isEmpty()) {
            throw new IllegalArgumentException("marketData must not be empty");
        }

        int period = config.getPeriod();
        if (period <= 0 || period > marketData.size()) {
            throw new IllegalArgumentException("period must be valid");
        }

        return new ArrayList<>();
    }
}

