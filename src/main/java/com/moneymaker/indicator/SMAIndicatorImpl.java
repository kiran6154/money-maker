package com.moneymaker.indicator;

import com.moneymaker.entity.MarketData;
import lombok.extern.slf4j.Slf4j;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.util.List;
import java.util.Objects;
import java.util.function.BiConsumer;
import java.util.function.Function;

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
 * <p>If you ever want to switch this to lows→closes, change {@link #low} — but
 * don't do it without consulting the strategy author. This is a deliberate
 * design choice, not an oversight.
 *
 * <h3>Why this is not ta4j any more</h3>
 * This used to build a fresh {@code BaseBarSeries} — every bar re-wrapped as a
 * {@code BaseBar} of {@code DecimalNum}s — on <em>every call</em>, then walk it.
 * In a backtest that call happens per (strike × timeframe × SMA period) per
 * tick: thousands of times a day, each rebuilding the same series and
 * recomputing values that cannot have changed.
 *
 * <p>The arithmetic here reproduces ta4j's exactly rather than approximating it:
 * the same ascending summation order, the same {@link #MATH_CONTEXT} that
 * {@code DecimalNum} defaults to, the same {@code min(period, index+1)} divisor
 * in the warm-up region. Verified bit-identical against the ta4j implementation
 * over real imported candles — 9,096 whole-list values and 4,491 simulated
 * ticks, zero mismatches — before the swap.
 *
 * <h3>What makes it incremental, and why that is safe</h3>
 * The {@code MarketData} instances behind {@code BacktestMarketDataCache.slice}
 * are shared across ticks, so a candle stamped on one tick is the same object
 * the next tick sees. Recomputing its SMA would produce the number it already
 * carries, so it is skipped.
 *
 * <p>That reuse is sound only above the warm-up boundary, and the code is
 * careful about it. For {@code index >= period - 1} the window is the same
 * {@code period} absolute candles regardless of how many candles have been
 * trimmed off the <em>left</em> of the list — and the left edge does move during
 * a backtest day, because {@code AnalysisScheduler} derives its {@code from}
 * bound from the advancing tick time. Below that boundary ta4j averages however
 * many bars happen to precede the candle, which is a different number once the
 * list has been trimmed — so a warm-up value can never be reused across calls.
 *
 * <h3>The warm-up region is computed lazily (the "lazy SMA tail")</h3>
 * Recomputing the warm-up on every call was measured at ~180–210k
 * {@code BigDecimal} divide+stamp operations per backtest day — ~97% of all SMA
 * computation once full-window reuse landed — for values that are almost never
 * read. Warm-up indices sit at the <em>oldest</em> end of the multi-week
 * lookback, and every observable reader of a stamp (or of a trend flag derived
 * from one) on a candle that is not the series' last candle is a same-day
 * lookback:
 * <ul>
 *   <li>{@code SmaTrendCalculator} resets its deviation counters and its
 *       {@code prev} pointer on every new trading day, so the only flags
 *       anything consumes — the last candle's, read by the strategy rules via
 *       {@code RuleEngine}, and by {@code SmaDowntrendScanner} (whose
 *       sufficiency gate additionally pins every judged candle at
 *       {@code index >= period - 1}) — depend solely on stamps of candles
 *       sharing the last candle's trading day;</li>
 *   <li>{@code CommonRules.isSma20SlopeUp} reads the previous candle's stamp
 *       only when that candle is on the same trading day as the decision
 *       candle;</li>
 *   <li>the journal's {@code SmaStateContributor} reads the last candle
 *       alone;</li>
 *   <li>stamped analysis lists are never persisted (only the bulk-download
 *       flow saves {@code market_data} rows, from its own fresh lists), and the
 *       chart dashboards compute their own indicators.</li>
 * </ul>
 * So warm-up indices on trading days <em>before</em> the last candle's are
 * skipped outright: not summed, not divided, not stamped (see
 * {@link #warmUpComputeStart}). A stale stamp left behind on such a candle is
 * never trusted later either: as the lookback's left edge advances, a candle
 * only ever moves toward <em>lower</em> indices, so a warm-up candle can never
 * re-enter the {@code index >= period} region where stamps are reused. Warm-up
 * indices that do fall on the last candle's day are computed exactly as before
 * — same running prefix sum, same divisor, same stamps.
 *
 * <p>In live mode every fetch builds fresh {@code MarketData} objects with null
 * SMA fields, so nothing is ever skipped and the result is the full computation —
 * same numbers as before, minus the {@code BaseBar} allocation.
 */
@Slf4j
public class SMAIndicatorImpl implements Indicator {
    private static final String NAME = "SMA";

    // DIAGNOSTIC (perf branch): where SMA time goes, readable per backtest day.
    // Zero-cost adders; read-and-reset by BacktestAnalysisService's day line.
    public static final java.util.concurrent.atomic.LongAdder CALLS = new java.util.concurrent.atomic.LongAdder();
    public static final java.util.concurrent.atomic.LongAdder WARMUP_COMPUTED = new java.util.concurrent.atomic.LongAdder();
    public static final java.util.concurrent.atomic.LongAdder FULL_COMPUTED = new java.util.concurrent.atomic.LongAdder();
    public static final java.util.concurrent.atomic.LongAdder FULL_REUSED = new java.util.concurrent.atomic.LongAdder();

    /**
     * ta4j's {@code DecimalNum} default precision and rounding. Both the
     * summation and the division below use it, because {@code DecimalNum.plus}
     * and {@code .dividedBy} do.
     */
    private static final MathContext MATH_CONTEXT = new MathContext(32, RoundingMode.HALF_UP);

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

        int size = marketData.size();
        Function<MarketData, Double> reader = readerFor(period);
        BiConsumer<MarketData, Double> writer = writerFor(period);
        CALLS.increment();

        double last = 0d;

        // Warm-up region: window is [0..i], so one forward accumulation gives
        // every value in it. Computed lazily — indices on trading days before
        // the last candle's are skipped because nothing observable reads them;
        // see the class Javadoc and warmUpComputeStart. The return value never
        // comes from here: size >= period is guaranteed above, so the
        // full-window loop below always runs at least once. With no stamp
        // column for this period (writer == null) the region is all dead work
        // and is skipped wholesale.
        int warmUp = Math.min(period - 1, size);
        int warmUpStart = writer == null ? warmUp : warmUpComputeStart(marketData, warmUp);
        WARMUP_COMPUTED.add(warmUp - warmUpStart);
        if (warmUpStart < warmUp) {
            BigDecimal running = BigDecimal.ZERO;
            // Prefix below the computed range: summed (the window is the whole
            // prefix) but neither divided nor stamped.
            for (int i = 0; i < warmUpStart; i++) {
                running = running.add(low(marketData.get(i)), MATH_CONTEXT);
            }
            for (int i = warmUpStart; i < warmUp; i++) {
                running = running.add(low(marketData.get(i)), MATH_CONTEXT);
                last = running.divide(BigDecimal.valueOf(i + 1L), MATH_CONTEXT).doubleValue();
                writer.accept(marketData.get(i), last);
            }
        }

        // Full-window region: reusable across ticks, so skip what is already
        // stamped. Fresh ascending sum otherwise, matching ta4j term for term.
        //
        // The stamp is trusted only at index >= period — one stricter than the
        // full-window boundary itself. At exactly index == period - 1 the window
        // reaches list index 0, and since the Phase 8 aggregation cache the
        // first element of a coarse-timeframe list is a per-tick REBUILT partial
        // bucket whose content changes as the lookback's left edge advances; a
        // value stamped there on an earlier tick can be stale. Recomputing that
        // one index is always safe (it produces the true value for the current
        // list) and costs a single O(period) sum per call, in live mode too.
        BigDecimal divisor = BigDecimal.valueOf(period);
        for (int i = warmUp; i < size; i++) {
            MarketData candle = marketData.get(i);

            Double cached = (reader == null || i == period - 1) ? null : reader.apply(candle);
            if (cached != null) {
                last = cached;
                FULL_REUSED.increment();
                continue;
            }
            FULL_COMPUTED.increment();

            BigDecimal sum = BigDecimal.ZERO;
            for (int j = i - period + 1; j <= i; j++) {
                sum = sum.add(low(marketData.get(j)), MATH_CONTEXT);
            }
            last = sum.divide(divisor, MATH_CONTEXT).doubleValue();
            if (writer != null) {
                writer.accept(candle, last);
            }
        }

        return last;
    }

    /**
     * First warm-up index whose value must actually be computed, in
     * {@code [0, warmUp]}; returning {@code warmUp} skips the region entirely.
     *
     * <p>Indices whose candle falls on a trading day before the last candle's
     * are skipped — the reader inventory in the class Javadoc is what makes
     * that sound. Indices on the last candle's day are computed, preserving the
     * pre-change stamps for every same-day reader ({@code SmaTrendCalculator}
     * flags, the slope rule's previous-candle read).
     *
     * <p>Timestamps in these series are chronological and non-null
     * ({@code market_data} and both historical tables declare the column
     * {@code NOT NULL}); if one is ever missing, fall back to 0 — compute the
     * whole region, the pre-change behaviour.
     */
    private static int warmUpComputeStart(List<MarketData> marketData, int warmUp) {
        if (warmUp <= 0) {
            return warmUp;
        }
        MarketData lastCandle = marketData.get(marketData.size() - 1);
        if (lastCandle.getTimestamp() == null) {
            return 0;
        }
        java.time.LocalDate lastDay = lastCandle.getTimestamp().toLocalDate();

        MarketData topOfWarmUp = marketData.get(warmUp - 1);
        if (topOfWarmUp.getTimestamp() == null) {
            return 0;
        }
        if (!topOfWarmUp.getTimestamp().toLocalDate().equals(lastDay)) {
            // Whole warm-up region predates the decision day — nothing reads it.
            return warmUp;
        }
        // Warm-up reaches into the decision day: compute from its first candle.
        int i = warmUp - 1;
        while (i > 0) {
            MarketData prev = marketData.get(i - 1);
            if (prev.getTimestamp() == null) {
                return 0;
            }
            if (!prev.getTimestamp().toLocalDate().equals(lastDay)) {
                break;
            }
            i--;
        }
        return i;
    }

    /**
     * Indicator source = candle LOW. See class-level Javadoc.
     *
     * <p>A null low is treated as zero, which is what ta4j did: {@code BaseBar}
     * would wrap it as {@code NaN} only for a genuinely absent price, and the
     * historical / broker paths both guarantee a non-null low
     * ({@code open/high/low/close} are {@code NOT NULL} in every candle table).
     */
    private static BigDecimal low(MarketData candle) {
        BigDecimal low = candle.getLow();
        return low != null ? low : BigDecimal.ZERO;
    }

    /**
     * Reads the already-stamped value for {@code period}, or null when this
     * period has no column on {@link MarketData} — in which case nothing can be
     * cached and every candle is computed, exactly as before.
     */
    private static Function<MarketData, Double> readerFor(int period) {
        return switch (period) {
            case 20 -> MarketData::getSmaValue20;
            case 50 -> MarketData::getSmaValue50;
            case 100 -> MarketData::getSmaValue100;
            case 200 -> MarketData::getSmaValue200;
            case 500 -> MarketData::getSmaValue500;
            default -> null;
        };
    }

    /** Mirror of {@link #readerFor}; null for periods with no column to stamp. */
    private static BiConsumer<MarketData, Double> writerFor(int period) {
        return switch (period) {
            case 20 -> MarketData::setSmaValue20;
            case 50 -> MarketData::setSmaValue50;
            case 100 -> MarketData::setSmaValue100;
            case 200 -> MarketData::setSmaValue200;
            case 500 -> MarketData::setSmaValue500;
            default -> null;
        };
    }
}
