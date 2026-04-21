package com.moneymaker.util;

public class ConverterUtility {

    public static Integer toInteger(Object value) {
        if (value == null) return null;
        if (value instanceof Integer) return (Integer) value;
        if (value instanceof Number) return ((Number) value).intValue();
        if (value instanceof String) return Integer.parseInt((String) value);
        throw new IllegalArgumentException("Cannot convert value to Integer: " + value);
    }
    public static String toString(Object value) {
        return value != null ? value.toString() : null;
    }
    // Helper to safely convert to BigDecimal
    public static java.math.BigDecimal toBigDecimal(Object value) {
        if (value == null) return null;
        if (value instanceof java.math.BigDecimal) return (java.math.BigDecimal) value;
        if (value instanceof Number) return new java.math.BigDecimal(value.toString());
        if (value instanceof String) return new java.math.BigDecimal((String) value);
        throw new IllegalArgumentException("Cannot convert value to BigDecimal: " + value);
    }
}
