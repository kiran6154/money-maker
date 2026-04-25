package com.moneymaker.login.model;

/**
 * Supported brokers. Add a new value here and provide a matching
 * {@link com.moneymaker.login.service.BrokerLoginService} implementation
 * to integrate a new broker.
 */
public enum Broker {
    ZERODHA,
    GROWW,
    ANGEL_ONE;

    public static Broker fromString(String value) {
        if (value == null) {
            throw new IllegalArgumentException("Broker name must not be null");
        }
        return Broker.valueOf(value.trim().toUpperCase().replace('-', '_'));
    }
}

