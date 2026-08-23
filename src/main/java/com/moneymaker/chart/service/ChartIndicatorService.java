package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.ChartCandleResponse;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;

/**
 * Computes every overlay the dashboard draws, for one already-aggregated candle
 * series: paired SMAs over low and high, and SuperTrend(7, 3).
 *
 * <p>Single home for both chart data sources — {@code ChartDashboardService} and
 * {@code HistoricalIciciChartDashboardService} previously carried a private copy
 * of the same rolling-SMA class each.
 *
 * <h3>Call it after aggregating, not before</h3>
 * Indicators must be computed on the series actually being drawn. SuperTrend is
 * path-dependent — its band ratchets and its direction flips off the previous
 * candle's state — so there is no way to down-sample it after the fact the way
 * {@code ChartTimeframeAggregator} used to carry SMA through a bucket. Running
 * this on 5-minute candles and then bucketing to 15m would also mean a "SMA20"
 * that is really a 100-minute average, not a 300-minute one.
 *
 * <p>Feed the full lookback window in and filter to the visible day afterwards,
 * so the leading candles have warmed the indicators up.
 */
@Service
public class ChartIndicatorService {

    /** Periods the dashboard offers. Both a low and a high line are produced for each. */
    private static final int[] SMA_PERIODS = {20, 50, 100, 200, 500};

    /** SuperTrend ATR lookback. */
    private static final int SUPERTREND_PERIOD = 7;

    /** SuperTrend band multiplier. */
    private static final BigDecimal SUPERTREND_MULTIPLIER = BigDecimal.valueOf(3);

    private static final int SCALE = 4;
    private static final BigDecimal TWO = BigDecimal.valueOf(2);

    /**
     * Fills every overlay field on {@code candles} in place, in ascending time
     * order. Candles are mutated rather than copied — they are request-scoped
     * DTOs built a few lines earlier by the calling service, never entities.
     */
    public void applyIndicators(List<ChartCandleResponse> candles) {
        if (candles == null || candles.isEmpty()) {
            return;
        }
        applySma(candles);
        applySupertrend(candles);
    }

    // ------------------------------------------------------------------ SMA

    private void applySma(List<ChartCandleResponse> candles) {
        for (int period : SMA_PERIODS) {
            RollingMean low = new RollingMean(period);
            RollingMean high = new RollingMean(period);

            for (ChartCandleResponse candle : candles) {
                setSma(candle, period, low.add(candle.getLow()), high.add(candle.getHigh()));
            }
        }
    }

    private void setSma(ChartCandleResponse candle, int period, BigDecimal low, BigDecimal high) {
        switch (period) {
            case 20 -> {
                candle.setSma20Low(low);
                candle.setSma20High(high);
            }
            case 50 -> {
                candle.setSma50Low(low);
                candle.setSma50High(high);
            }
            case 100 -> {
                candle.setSma100Low(low);
                candle.setSma100High(high);
            }
            case 200 -> {
                candle.setSma200Low(low);
                candle.setSma200High(high);
            }
            case 500 -> {
                candle.setSma500Low(low);
                candle.setSma500High(high);
            }
            default -> throw new IllegalStateException("Unsupported SMA period: " + period);
        }
    }

    // ----------------------------------------------------------- SuperTrend

    /**
     * Standard SuperTrend:
     * <pre>
     *   mid   = (high + low) / 2
     *   upper = mid + multiplier * ATR      lower = mid - multiplier * ATR
     * </pre>
     * Each band then ratchets — the upper band may only move down while price
     * stays below the previous upper band, and vice versa — and the trend flips
     * when close closes beyond the opposing band. ATR uses Wilder's smoothing,
     * seeded with a simple mean of the first {@code period} true ranges, which is
     * what charting platforms use for SuperTrend.
     */
    private void applySupertrend(List<ChartCandleResponse> candles) {
        int size = candles.size();
        BigDecimal[] trueRange = new BigDecimal[size];

        for (int i = 0; i < size; i++) {
            ChartCandleResponse candle = candles.get(i);
            if (!hasOhlc(candle)) {
                continue;
            }
            BigDecimal range = candle.getHigh().subtract(candle.getLow());
            if (i > 0 && candles.get(i - 1).getClose() != null) {
                BigDecimal prevClose = candles.get(i - 1).getClose();
                range = range
                        .max(candle.getHigh().subtract(prevClose).abs())
                        .max(candle.getLow().subtract(prevClose).abs());
            }
            trueRange[i] = range;
        }

        BigDecimal atr = null;
        BigDecimal finalUpper = null;
        BigDecimal finalLower = null;
        boolean uptrend = true;
        int warmup = 0;
        BigDecimal seedSum = BigDecimal.ZERO;

        for (int i = 0; i < size; i++) {
            ChartCandleResponse candle = candles.get(i);
            if (!hasOhlc(candle) || trueRange[i] == null) {
                continue;
            }

            if (atr == null) {
                // Seed: simple mean of the first SUPERTREND_PERIOD true ranges.
                seedSum = seedSum.add(trueRange[i]);
                if (++warmup < SUPERTREND_PERIOD) {
                    continue;
                }
                atr = seedSum.divide(BigDecimal.valueOf(SUPERTREND_PERIOD), SCALE, RoundingMode.HALF_UP);
            } else {
                // Wilder: atr = (atr * (n - 1) + tr) / n
                atr = atr.multiply(BigDecimal.valueOf(SUPERTREND_PERIOD - 1L))
                        .add(trueRange[i])
                        .divide(BigDecimal.valueOf(SUPERTREND_PERIOD), SCALE, RoundingMode.HALF_UP);
            }

            BigDecimal mid = candle.getHigh().add(candle.getLow())
                    .divide(TWO, SCALE, RoundingMode.HALF_UP);
            BigDecimal offset = SUPERTREND_MULTIPLIER.multiply(atr);
            BigDecimal basicUpper = mid.add(offset);
            BigDecimal basicLower = mid.subtract(offset);

            BigDecimal prevClose = i > 0 ? candles.get(i - 1).getClose() : null;

            // Ratchet: keep the tighter band unless price has broken the old one.
            if (finalUpper == null || prevClose == null || prevClose.compareTo(finalUpper) > 0) {
                finalUpper = basicUpper;
            } else {
                finalUpper = basicUpper.min(finalUpper);
            }

            if (finalLower == null || prevClose == null || prevClose.compareTo(finalLower) < 0) {
                finalLower = basicLower;
            } else {
                finalLower = basicLower.max(finalLower);
            }

            BigDecimal close = candle.getClose();
            if (close.compareTo(finalUpper) > 0) {
                uptrend = true;
            } else if (close.compareTo(finalLower) < 0) {
                uptrend = false;
            }

            candle.setSupertrend(uptrend ? finalLower : finalUpper);
            candle.setSupertrendUp(uptrend);
        }
    }

    private boolean hasOhlc(ChartCandleResponse candle) {
        return candle != null
                && candle.getHigh() != null
                && candle.getLow() != null
                && candle.getClose() != null;
    }

    // --------------------------------------------------------------- helper

    /** Fixed-window arithmetic mean; {@code null} until the window is full. */
    private static final class RollingMean {
        private final int period;
        private final Deque<BigDecimal> window = new ArrayDeque<>();
        private BigDecimal sum = BigDecimal.ZERO;

        private RollingMean(int period) {
            this.period = period;
        }

        private BigDecimal add(BigDecimal value) {
            if (value == null) {
                return window.size() >= period ? mean() : null;
            }

            window.addLast(value);
            sum = sum.add(value);
            if (window.size() > period) {
                sum = sum.subtract(window.removeFirst());
            }
            return window.size() < period ? null : mean();
        }

        private BigDecimal mean() {
            return sum.divide(BigDecimal.valueOf(period), SCALE, RoundingMode.HALF_UP);
        }
    }
}
