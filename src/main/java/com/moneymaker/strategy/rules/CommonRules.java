package com.moneymaker.strategy.rules;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.shared.data.SharedData;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
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
     * The underlying's first-hour move on the signal's session, signed in the
     * leg's favour and expressed in ATR-14 units — the 10:15 checkpoint of the
     * regime study, reshaped for a one-sided premium short ({@code Strategy7}).
     *
     * <p>{@code move = close(last underlying bar before checkpoint) − open(first
     * bar of the session)}; for a CE config the favourable direction is down so
     * the sign is flipped; for a PE config up is favourable. ATR-14 is the mean
     * true range of the 14 completed sessions before the signal's day, rolled
     * up from the same intraday series (the detector sizes strike depth from
     * the same quantity, computed from daily bars — the two agree to within the
     * 15:30 print).</p>
     *
     * <p>Tri-state like {@link #higherTimeframeSmaDownTrending}: {@code null}
     * means "cannot be judged at this tick" and a filter must allow. Unknown
     * when: the signal bar starts before the checkpoint (the first hour has not
     * finished — every opening-bar entry is judged on its own evidence); the
     * context carries no cache key, config or trading side; no underlying
     * series is cached for the leg's interval; the session's first bar is
     * missing or the first bar of the day starts after 09:30 (a data gap, not
     * an open); fewer than {@value #ATR_MIN_SESSIONS} completed prior sessions
     * are available; or the true range is zero.</p>
     *
     * <p>The underlying series is found by taking the first two segments of the
     * leg's cache key ({@code token|interval}), which is exactly the key
     * {@code AnalysisScheduler} writes the underlying under — same interval as
     * the signal, so a 15-minute signal reads 15-minute buckets (the 10:00
     * bucket closes at 10:15, the same print as the 10:10 five-minute bar).</p>
     */
    public static Double firstHourMoveInFavourAtr(RuleContext ctx, LocalTime checkpoint) {
        if (ctx == null || ctx.strikeKey == null || ctx.candle == null || ctx.candle.getTimestamp() == null) return null;
        if (ctx.candle.getTimestamp().toLocalTime().isBefore(checkpoint)) return null;
        if (ctx.config == null || ctx.config.getTradeConfig() == null) return null;
        String side = ctx.config.getTradeConfig().getTradingSide();
        int sign;
        if ("CE".equalsIgnoreCase(side)) sign = -1;
        else if ("PE".equalsIgnoreCase(side)) sign = 1;
        else return null;

        String[] parts = ctx.strikeKey.split("\\|");
        if (parts.length < 2) return null;
        Map<String, List<MarketData>> cache = SharedData.marketDataByInstrumentAndInterval;
        if (cache == null) return null;
        List<MarketData> series = cache.get(parts[0] + "|" + parts[1]);
        if (series == null || series.isEmpty()) return null;

        LocalDate day = ctx.asOf != null ? ctx.asOf.toLocalDate() : ctx.candle.getTimestamp().toLocalDate();
        MarketData first = null, lastBeforeCheckpoint = null;
        for (MarketData c : series) {
            if (c == null || c.getTimestamp() == null || !c.getTimestamp().toLocalDate().equals(day)) continue;
            if (first == null) first = c;
            if (c.getTimestamp().toLocalTime().isBefore(checkpoint)) lastBeforeCheckpoint = c;
        }
        if (first == null || lastBeforeCheckpoint == null) return null;
        if (first.getTimestamp().toLocalTime().isAfter(LocalTime.of(9, 30))) return null;   // gap, not an open
        double open = openValue(first), close = closeValue(lastBeforeCheckpoint);
        if (open <= 0 || close <= 0) return null;

        Double atr = sessionAtr(series, day, ATR_PERIOD);
        if (atr == null || atr <= 0) return null;
        return sign * (close - open) / atr;
    }

    /** ATR period and the minimum number of completed prior sessions the ATR needs. */
    public static final int ATR_PERIOD = 14;
    public static final int ATR_MIN_SESSIONS = 5;

    /**
     * Mean true range of the last {@code n} completed sessions strictly before
     * {@code day}, rolled up from an intraday series: session high/low from the
     * bars, true range against the previous session's close (the first session
     * has no previous close and is used only as that reference). Null when fewer
     * than {@value #ATR_MIN_SESSIONS} sessions precede {@code day}.
     */
    static Double sessionAtr(List<MarketData> series, LocalDate day, int n) {
        java.util.TreeMap<LocalDate, double[]> sessions = new java.util.TreeMap<>();   // date -> {high, low, close}
        for (MarketData c : series) {
            if (c == null || c.getTimestamp() == null) continue;
            LocalDate dte = c.getTimestamp().toLocalDate();
            if (!dte.isBefore(day)) continue;
            double h = c.getHigh() == null ? 0 : c.getHigh().doubleValue();
            double l = c.getLow() == null ? 0 : c.getLow().doubleValue();
            double cl = closeValue(c);
            if (h <= 0 || l <= 0 || cl <= 0) continue;
            double[] s = sessions.get(dte);
            if (s == null) sessions.put(dte, new double[]{h, l, cl});
            else { s[0] = Math.max(s[0], h); s[1] = Math.min(s[1], l); s[2] = cl; }
        }
        if (sessions.size() < ATR_MIN_SESSIONS) return null;
        List<double[]> ordered = new ArrayList<>(sessions.values());
        List<Double> trs = new ArrayList<>();
        for (int i = 1; i < ordered.size(); i++) {
            double[] s = ordered.get(i); double prevClose = ordered.get(i - 1)[2];
            trs.add(Math.max(s[0] - s[1], Math.max(Math.abs(s[0] - prevClose), Math.abs(s[1] - prevClose))));
        }
        if (trs.isEmpty()) return null;
        List<Double> tail = trs.subList(Math.max(0, trs.size() - n), trs.size());
        double sum = 0; for (double t : tail) sum += t;
        return sum / tail.size();
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
