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

    /**
     * True when the candle is at or after the close-signal time
     * <b>of the session being evaluated</b>. The time comes from
     * {@code ctx.closeSignalTime} (derived from {@code app.market.close} minus
     * {@code app.market.close-signal-offset-minutes}); a null falls back to the
     * legacy 15:15 constant so manually built contexts keep the old behaviour.
     *
     * <p>The date check is load-bearing, not defensive padding. Comparing only
     * the time-of-day made every previous session's closing bar an eligible
     * close signal, and the candle series a strategy reads spans the whole SMA
     * lookback — so on the first ticks of a day, before a coarse timeframe's
     * first bucket has settled, the newest bar available is yesterday's 15:15 or
     * 15:30. That fired an exit carrying yesterday's timestamp and price.
     *
     * <p>{@code ctx.asOf} may be null for callers that do not supply it; the
     * rule then degrades to the old time-only behaviour rather than silently
     * refusing to ever fire.
     */
    public static boolean isMarketCloseTime(RuleContext ctx) {
        if (ctx.candle == null || ctx.candle.getTimestamp() == null) return false;
        java.time.LocalDateTime ts = ctx.candle.getTimestamp();
        if (ctx.asOf != null && !ts.toLocalDate().equals(ctx.asOf.toLocalDate())) return false;
        java.time.LocalTime trigger = ctx.closeSignalTime != null
                ? ctx.closeSignalTime : java.time.LocalTime.of(15, 15);
        return ts.toLocalTime().compareTo(trigger) >= 0;
    }

    /**
     * True when the 20-period SMA is sloping <b>upward</b> at this candle —
     * i.e. {@code sma20(this) > sma20(previous candle)}.
     *
     * <p>This is the instantaneous slope, deliberately <i>not</i>
     * {@code candle.isSma20UpTrending()}. That flag is a whole-day verdict from
     * {@link SmaTrendCalculator}: with {@code maxDeviations = 0} it means the
     * SMA has risen on every candle since the open, and one flat bar at 09:20
     * switches it off for the rest of the session. "Is the 20 SMA rising right
     * now" is a much narrower question, and the one a per-tick entry filter
     * needs.</p>
     *
     * <h3>When it returns false</h3>
     * Both SMA values must be present, positive, and belong to the <b>same
     * trading day</b>; otherwise the slope is unknown and this returns false.
     * That is the permissive answer on purpose — callers use it to <i>block</i>
     * entries, and "we cannot tell" must not block. Three cases hit it:
     * <ul>
     *   <li>the SMA-20 warm-up window (fewer than 20 candles fetched);</li>
     *   <li>the first candle of a day, whose predecessor is the previous
     *       session's close — an overnight gap, not a slope. {@code SmaTrendCalculator}
     *       resets at the same boundary for the same reason;</li>
     *   <li>a period with no SMA-20 column stamped on the series at all.</li>
     * </ul>
     *
     * <p>{@code AnalysisScheduler} stamps every SMA period in
     * {@code SharedData.allTimeFrameMap} (20/50/100/200/500) onto every strike
     * series it caches, so SMA-20 is available regardless of which period the
     * config itself trades on.</p>
     */
    public static boolean isSma20SlopeUp(RuleContext ctx) {
        if (ctx == null || ctx.candle == null) return false;
        Double curr = ctx.candle.getSmaValue20();
        if (curr == null || curr <= 0) return false;

        MarketData prev = previousSameDayCandle(ctx);
        if (prev == null) return false;
        Double previous = prev.getSmaValue20();
        if (previous == null || previous <= 0) return false;

        return curr > previous;
    }

    /**
     * The candle immediately before {@code ctx.candle} in the same series, or
     * null when there is none or it falls on an earlier trading day.
     */
    private static MarketData previousSameDayCandle(RuleContext ctx) {
        if (ctx.allCandles == null || ctx.index <= 0 || ctx.index >= ctx.allCandles.size()) {
            return null;
        }
        MarketData prev = ctx.allCandles.get(ctx.index - 1);
        if (prev == null || prev.getTimestamp() == null || ctx.candle.getTimestamp() == null) {
            return null;
        }
        LocalDate prevDay = prev.getTimestamp().toLocalDate();
        LocalDate currDay = ctx.candle.getTimestamp().toLocalDate();
        return prevDay.equals(currDay) ? prev : null;
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
