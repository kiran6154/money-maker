package com.moneymaker.strategy.rules;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.shared.data.SharedData;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;

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
     * Whether the <b>same leg's</b> series on a coarser interval carries the
     * whole-day down-trend flag for {@code period} — the higher-timeframe
     * confirmation {@code Strategy6} requires before a sell entry.
     *
     * <p>Tri-state on purpose. {@code TRUE} / {@code FALSE} is the flag
     * {@link SmaTrendCalculator} (with {@code maxDeviations = 0}) stamps on the
     * newest <i>settled</i> bar of that interval: the SMA has fallen on every
     * bar of the session so far. {@code null} means the question cannot be
     * answered at this tick, and a filter must let the entry through rather
     * than block on ignorance — the same "unknown ⇒ allow" convention
     * {@link #isSma20SlopeUp} follows. The unknown cases:</p>
     * <ul>
     *   <li>the context carries no cache key (hand-built list, older caller);</li>
     *   <li>no series for that leg at that interval is in
     *       {@code SharedData.strikeMarketDataByInstrumentAndInterval} — the
     *       strategy did not declare it in {@code confirmationTimeframes()}, or
     *       the fetch came back empty;</li>
     *   <li>the series was not written by this tick (the S8 stale-key rule:
     *       the strike left the coarser interval's ATM window);</li>
     *   <li>the newest settled bar belongs to an earlier session — for a
     *       15-minute series that is every tick before 09:30, so the first
     *       three ticks of the day (which carry the opening-bar entries) are
     *       judged on the 5-minute evidence alone;</li>
     *   <li>the SMA for {@code period} is not stamped on that bar (series
     *       shorter than the period).</li>
     * </ul>
     *
     * <p>The series is looked up by rewriting the interval segment of the
     * context's own key, so it is the same contract, the same config depths
     * and the same tick that the traded series came from. The trend flags are
     * (re)stamped here with {@code maxDeviations = 0}; the calculation is
     * idempotent, so a series the engine already flagged is unchanged.</p>
     */
    public static Boolean higherTimeframeSmaDownTrending(RuleContext ctx, int intervalMinutes, int period) {
        if (ctx == null || ctx.strikeKey == null) return null;
        String[] parts = ctx.strikeKey.split("\\|");
        if (parts.length < 7) return null;
        parts[1] = intervalMinutes + "minute";
        String key = String.join("|", parts);

        Map<String, List<MarketData>> cache = SharedData.strikeMarketDataByInstrumentAndInterval;
        if (cache == null) return null;
        List<MarketData> series = cache.get(key);
        if (series == null || series.isEmpty()) return null;

        if (ctx.asOf != null) {
            Map<String, LocalDateTime> ticks = SharedData.strikeMarketDataTick;
            LocalDateTime stamp = ticks != null ? ticks.get(key) : null;
            if (stamp != null && !ctx.asOf.equals(stamp)) return null;
        }

        MarketData last = series.get(series.size() - 1);
        if (last == null || last.getTimestamp() == null) return null;
        if (ctx.asOf != null && !last.getTimestamp().toLocalDate().equals(ctx.asOf.toLocalDate())) return null;
        if (smaValue(last, period) <= 0) return null;

        SmaTrendCalculator.compute(series, 0);
        return isSmaDownTrending(last, period);
    }

    /**
     * True while the candle starts at or before the entry cut-off — the
     * close-signal time minus {@code minutesBeforeCloseSignal}. With the
     * standard 15:30 close and the 15-minute close-signal offset, 30 minutes
     * puts the last admissible entry bar at 14:45. Derived from
     * {@code ctx.closeSignalTime} (falling back to the legacy 15:15) so it
     * moves with {@code app.market.*} rather than being a second clock.
     *
     * <p>A candle without a timestamp fails: the cut-off is a required rule and
     * a bar whose time is unknown cannot be shown to be early enough.</p>
     */
    public static boolean isAtOrBeforeEntryCutoff(RuleContext ctx, int minutesBeforeCloseSignal) {
        if (ctx == null || ctx.candle == null || ctx.candle.getTimestamp() == null) return false;
        LocalTime closeSignal = ctx.closeSignalTime != null ? ctx.closeSignalTime : LocalTime.of(15, 15);
        LocalTime cutoff = closeSignal.minusMinutes(minutesBeforeCloseSignal);
        return !ctx.candle.getTimestamp().toLocalTime().isAfter(cutoff);
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

    /**
     * Reads the whole-day up-trend flag for the given period off a
     * {@link MarketData} candle — the mirror of the {@code isSmaNNDownTrending}
     * getters the baseline sell rules read directly. Stamped by
     * {@link SmaTrendCalculator}; false for an unsupported period.
     */
    public static boolean isSmaUpTrending(MarketData c, Integer period) {
        if (c == null || period == null) return false;
        switch (period) {
            case 20:  return c.isSma20UpTrending();
            case 50:  return c.isSma50UpTrending();
            case 100: return c.isSma100UpTrending();
            case 200: return c.isSma200UpTrending();
            case 500: return c.isSma500UpTrending();
            default:  return false;
        }
    }

    /**
     * Reads the whole-day down-trend flag for the given period — the flag the
     * baseline sell rules read via the typed {@code isSmaNNDownTrending}
     * getters, resolved by period. Stamped by {@link SmaTrendCalculator};
     * false for an unsupported period.
     */
    public static boolean isSmaDownTrending(MarketData c, Integer period) {
        if (c == null || period == null) return false;
        switch (period) {
            case 20:  return c.isSma20DownTrending();
            case 50:  return c.isSma50DownTrending();
            case 100: return c.isSma100DownTrending();
            case 200: return c.isSma200DownTrending();
            case 500: return c.isSma500DownTrending();
            default:  return false;
        }
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
