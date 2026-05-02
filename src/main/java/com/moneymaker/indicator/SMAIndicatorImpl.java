package com.moneymaker.indicator;

import com.moneymaker.entity.MarketData;
import lombok.extern.slf4j.Slf4j;
import org.ta4j.core.BarSeries;
import org.ta4j.core.BaseBarSeries;
import org.ta4j.core.indicators.SMAIndicator;
import org.ta4j.core.indicators.helpers.ClosePriceIndicator;
import org.ta4j.core.indicators.helpers.LowPriceIndicator;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.List;
import java.util.Objects;
@Slf4j

public class SMAIndicatorImpl implements Indicator {
    private static final String NAME = "SMA";

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public Double calculate(List<MarketData> marketData, IndicatorConfig config) {
        Objects.requireNonNull(marketData, "marketData must not be null");
        Objects.requireNonNull(config, "config must not be null");

        if (marketData.isEmpty()) {
            throw new IllegalArgumentException("marketData must not be empty");
        }

        int period = config.getPeriod();
        if (period <= 0 || period > marketData.size()) {
         //   throw new IllegalArgumentException("period must be valid " + period +" and less than or equal to marketData size " + marketData.size());
        log.error("period must be valid " + period +" and less than or equal to marketData size " + marketData.size());
        return null;
        }
        BarSeries series = new BaseBarSeries();
        for (MarketData md : marketData) {
            ZonedDateTime zdt = md.getTimestamp().atZone(ZoneId.systemDefault());
            org.ta4j.core.Bar bar = new org.ta4j.core.BaseBar(java.time.Duration.ofMinutes(1), zdt, md.getOpen(), md.getHigh(), md.getLow(), md.getClose(), BigDecimal.ZERO);
            series.addBar(bar);
        }
        // 3. Indicator for close price
        LowPriceIndicator closePrice = new LowPriceIndicator(series);

        // 4. SMA (period = 3)
        SMAIndicator sma = new SMAIndicator(closePrice, config.getPeriod());
        int i = 0;
        for (MarketData md : marketData) {
            if (config.getPeriod() == 50) {
                md.setSmaValue50(sma.getValue(i).doubleValue());
            } else if (config.getPeriod() == 100) {
                md.setSmaValue100(sma.getValue(i).doubleValue());
            } else if (config.getPeriod() == 200) {
                md.setSmaValue200(sma.getValue(i).doubleValue());
            } else if (config.getPeriod() == 500) {
                md.setSmaValue500(sma.getValue(i).doubleValue());
            }
            i++;
        }
        return sma.getValue(i - 1).doubleValue();
    }
}

