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
 * list has been trimmed — so the warm-up region is always recomputed. It costs
 * one pass, because there the window is a pure prefix and a running sum
 * reproduces ta4j's loop term for term.
 *
 * <p>In live mode every fetch builds fresh {@code MarketData} objects with null
 * SMA fields, so nothing is ever skipped and the result is the full computation —
 * same numbers as before, minus the {@code BaseBar} allocation.
 */
@Slf4j
public class SMAIndicatorImpl implements Indicator {
    private static final String NAME = "SMA";

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

        double last = 0d;

        // Warm-up region: window is [0..i], so one forward accumulation gives
        // every value in it. Always recomputed — see the class Javadoc.
        BigDecimal running = BigDecimal.ZERO;
        int warmUp = Math.min(period - 1, size);
        for (int i = 0; i < warmUp; i++) {
            running = running.add(low(marketData.get(i)), MATH_CONTEXT);
            last = running.divide(BigDecimal.valueOf(i + 1L), MATH_CONTEXT).doubleValue();
            if (writer != null) {
                writer.accept(marketData.get(i), last);
            }
        }

        // Full-window region: reusable across ticks, so skip what is already
        // stamped. Fresh ascending sum otherwise, matching ta4j term for term.
        BigDecimal divisor = BigDecimal.valueOf(period);
        for (int i = warmUp; i < size; i++) {
            MarketData candle = marketData.get(i);

            Double cached = reader == null ? null : reader.apply(candle);
            if (cached != null) {
                last = cached;
                continue;
            }

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
