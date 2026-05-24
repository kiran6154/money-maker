package com.moneymaker.strategy.rules;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeConfig;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * Reusable rule predicates and SMA helpers shared across strategies. Strategies
 * compose these via method references (e.g. {@code CommonRules::isEndOfDay})
 * inside their own rule builders.
 */
public final class CommonRules {
    private CommonRules() {}

    // ----- Predicates -------------------------------------------------

    /** True when the candle time is at or after 15:15 (typical market close time). */
    public static boolean isMarketCloseTime(RuleContext ctx) {
        if (ctx.candle == null || ctx.candle.getTimestamp() == null) return false;
        java.time.LocalTime time = ctx.candle.getTimestamp().toLocalTime();
        return time.compareTo(java.time.LocalTime.of(15, 15)) >= 0;
    }

    /**
     * True when the absolute distance between the primary SMA and the
     * next-higher SMA period (50→100, 100→200, 200→500) exceeds the
     * configured profit target. Returns false if either SMA is unavailable
     * or no target is set.
     */
    public static boolean isDistanceToNextHigherSmaAboveTarget(RuleContext ctx) {
        Integer higher = nextHigherSmaPeriod(ctx.primarySmaPeriod);
        if (higher == null) return false;
        double primary = smaValue(ctx.candle, ctx.primarySmaPeriod);
        double upper   = smaValue(ctx.candle, higher);
        if (primary <= 0 || upper <= 0) return false;

        Double target = profitTarget(ctx.config);
        if (target == null) return false;

        return Math.abs(upper - primary) > target;
    }

    // ----- Helpers ----------------------------------------------------

    public static Integer nextHigherSmaPeriod(Integer period) {
        if (period == null) return null;
        switch (period) {
            case 20:  return 50;
            case 50:  return 100;
            case 100: return 200;
            case 200: return 500;
            default:  return null;
        }
    }

    public static Double profitTarget(TradeConfigCombinedDTO config) {
        if (config == null) return null;
        TradeConfig tc = config.getTradeConfig();
        if (tc == null) return null;
        BigDecimal target = tc.getTarget();
        return target == null ? null : target.doubleValue();
    }

    /**
     * Reads the SMA field for the given period off a {@link MarketData} candle.
     * Returns 0 if the SMA isn't available (unsupported period or null value).
     */
    public static double smaValue(MarketData c, Integer period) {
        if (c == null || period == null) return 0;
        Double v;
        switch (period) {
            case 20:  v = c.getSmaValue20();  break;
            case 50:  v = c.getSmaValue50();  break;
            case 100: v = c.getSmaValue100(); break;
            case 200: v = c.getSmaValue200(); break;
            case 500: v = c.getSmaValue500(); break;
            default:  return 0;
        }
        return v == null ? 0 : v;
    }

    /** Returns the candle's open price as a double (0 if null). */
    public static double openValue(MarketData c) {
        return c == null || c.getOpen() == null ? 0 : c.getOpen().doubleValue();
    }

    /** Returns the candle's close price as a double (0 if null). */
    public static double closeValue(MarketData c) {
        return c == null || c.getClose() == null ? 0 : c.getClose().doubleValue();
    }
}
