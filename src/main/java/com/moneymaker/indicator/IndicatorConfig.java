package com.moneymaker.indicator;

public final class IndicatorConfig {
    private final int period;
    private final String name;

    private IndicatorConfig(int period, String name) {
        if (period <= 0) {
            throw new IllegalArgumentException("period must be > 0");
        }
        this.period = period;
        this.name = name;
    }

    public int getPeriod() {
        return period;
    }

    public String getName() {
        return name;
    }

    public static IndicatorConfig of(int period, String name) {
        return new IndicatorConfig(period, name);
    }

    public static IndicatorConfig of(int period) {
        return new IndicatorConfig(period, "");
    }
}

