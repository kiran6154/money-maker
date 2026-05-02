package com.moneymaker.indicator;

import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.function.Supplier;

public final class IndicatorFactory {
    private static final Map<String, Supplier<Indicator>> registry = new HashMap<>();

    static {
        registry.put("SMA", SMAIndicatorImpl::new);
        registry.put("EMA", EMAIndicatorImpl::new);
        registry.put("RSI", RSIIndicatorImpl::new);
    }

    private IndicatorFactory() {
    }

    public static Indicator create(String name) {
        Objects.requireNonNull(name, "indicator name must not be null");
        Supplier<Indicator> supplier = registry.get(name.toUpperCase());
        if (supplier == null) {
            throw new IllegalArgumentException("Unknown indicator: " + name);
        }
        return supplier.get();
    }

    public static void register(String name, Supplier<Indicator> supplier) {
        Objects.requireNonNull(name, "name must not be null");
        Objects.requireNonNull(supplier, "supplier must not be null");
        registry.put(name.toUpperCase(), supplier);
    }
}

