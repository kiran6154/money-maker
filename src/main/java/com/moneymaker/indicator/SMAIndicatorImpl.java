package com.moneymaker.indicator;

import com.moneymaker.entity.MarketData;
import lombok.extern.slf4j.Slf4j;
import org.ta4j.core.BarSeries;
import org.ta4j.core.BaseBarSeries;
import org.ta4j.core.indicators.SMAIndicator;
import org.ta4j.core.indicators.helpers.LowPriceIndicator;

import java.math.BigDecimal;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.List;
import java.util.Objects;

/**
 * SMA indicator computed over candle <b>lows</b> (intentionally — not closes).
 *
 * <p>The strategy gate (see {@code RuleEngine.decide}) compares the current
 * candle's open and close against {@code SMA(low)}. Because
 * {@code SMA(low) ≤ SMA(close)}, this gives a more permissive "rejection at
 * SMA" pattern: the candle's open more easily clears the SMA and the close
 * more easily sits below it, surfacing intraday rejection candles that a
 * close-based SMA would miss.
 *
 * <p>If you ever want to switch this to closes, swap {@link LowPriceIndicator}
 * for {@code ClosePriceIndicator}. Don't do it without consulting the
 * strategy author — this is a deliberate design choice, not an oversight.
 */
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
            log.debug("SMA period={} cannot be computed: requires marketData size >= period, got size={}",
                    period, marketData.size());
            return null;
        }
        BarSeries series = new BaseBarSeries();
        for (MarketData md : marketData) {
            ZonedDateTime zdt = md.getTimestamp().atZone(ZoneId.systemDefault());
            org.ta4j.core.Bar bar = new org.ta4j.core.BaseBar(java.time.Duration.ofMinutes(1), zdt,
                    md.getOpen(), md.getHigh(), md.getLow(), md.getClose(), BigDecimal.ZERO);
            series.addBar(bar);
        }

        // Indicator source = candle LOW. See class-level Javadoc.
        LowPriceIndicator lowPrice = new LowPriceIndicator(series);
        SMAIndicator sma = new SMAIndicator(lowPrice, config.getPeriod());

        int i = 0;
        for (MarketData md : marketData) {
            if (config.getPeriod() == 20) {
                md.setSmaValue20(sma.getValue(i).doubleValue());
            } else if (config.getPeriod() == 50) {
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
