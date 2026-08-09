package com.moneymaker.chart.dto;

import com.fasterxml.jackson.annotation.JsonCreator;
import com.fasterxml.jackson.annotation.JsonValue;

public enum ChartTimeframe {
    FIVE_MINUTES("5m"),
    TEN_MINUTES("10m"),
    FIFTEEN_MINUTES("15m");

    private final String value;

    ChartTimeframe(String value) {
        this.value = value;
    }

    @JsonValue
    public String getValue() {
        return value;
    }

    @JsonCreator
    public static ChartTimeframe fromValue(String value) {
        for (ChartTimeframe timeframe : values()) {
            if (timeframe.value.equalsIgnoreCase(value)) {
                return timeframe;
            }
        }
        throw new IllegalArgumentException("Unsupported timeframe: " + value);
    }
}
