package com.moneymaker.indicator;

import com.moneymaker.entity.MarketData;
import com.moneymaker.strategy.rules.CommonRules;
import com.moneymaker.strategy.rules.RuleContext;
import com.moneymaker.strategy.rules.SmaTrendCalculator;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.math.MathContext;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Parity harness for the lazy warm-up ("lazy SMA tail") in {@link SMAIndicatorImpl}.
 *
 * <p>The ground truth is a full ta4j-equivalent recompute of every index —
 * ascending {@code BigDecimal} summation under {@code MathContext(32, HALF_UP)},
 * divisor {@code min(period, index + 1)} — the arithmetic Phase 3 verified
 * bit-identical against ta4j. The lazy warm-up deliberately stops stamping
 * indices on trading days before the last candle's, so equality is asserted on
 * the <b>readable surface</b>: the returned value, every stamp at
 * {@code index >= period - 1}, every stamp on the last candle's trading day,
 * the {@link SmaTrendCalculator} flags on the last candle, and the
 * {@link CommonRules#isSma20SlopeUp} slope read. Exact {@code Double} equality
 * throughout — no tolerances.</p>
 */
class SMAIndicatorImplLazyWarmupTest {

    private static final MathContext MC = new MathContext(32, RoundingMode.HALF_UP);
    private static final LocalDate FIRST_DAY = LocalDate.of(2024, 1, 1);

    // ------------------------------------------------------------------
    // Fixtures
    // ------------------------------------------------------------------

    /** Deterministic multi-day 5-minute series: {@code days × barsPerDay} candles. */
    private static List<MarketData> series(int days, int barsPerDay) {
        List<MarketData> out = new ArrayList<>(days * barsPerDay);
        int k = 0;
        for (int d = 0; d < days; d++) {
            for (int b = 0; b < barsPerDay; b++, k++) {
                MarketData c = new MarketData();
                c.setTimestamp(LocalDateTime.of(FIRST_DAY.plusDays(d), LocalTime.of(9, 15))
                        .plusMinutes(5L * b));
                c.setLow(BigDecimal.valueOf(100 + 20 * Math.sin(k * 0.37) + (k % 13) * 0.75));
                out.add(c);
            }
        }
        return out;
    }

    /** Fresh objects with the same timestamps/lows — the reference arm's copy. */
    private static List<MarketData> cloneOf(List<MarketData> src) {
        List<MarketData> out = new ArrayList<>(src.size());
        for (MarketData c : src) {
            MarketData copy = new MarketData();
            copy.setTimestamp(c.getTimestamp());
            copy.setLow(c.getLow());
            out.add(copy);
        }
        return out;
    }

    /** Full recompute of every index — the pre-change/ta4j-equivalent arithmetic. */
    private static double[] reference(List<MarketData> candles, int period) {
        double[] out = new double[candles.size()];
        for (int i = 0; i < candles.size(); i++) {
            BigDecimal sum = BigDecimal.ZERO;
            for (int j = Math.max(0, i - period + 1); j <= i; j++) {
                sum = sum.add(candles.get(j).getLow(), MC);
            }
            out[i] = sum.divide(BigDecimal.valueOf(Math.min(period, i + 1)), MC).doubleValue();
        }
        return out;
    }

    /** Stamps reference values onto the clone so flag/slope readers see them. */
    private static void stampAll(List<MarketData> candles, int period, double[] values) {
        for (int i = 0; i < candles.size(); i++) {
            stamp(candles.get(i), period, values[i]);
        }
    }

    private static void stamp(MarketData c, int period, Double v) {
        switch (period) {
            case 20 -> c.setSmaValue20(v);
            case 50 -> c.setSmaValue50(v);
            case 100 -> c.setSmaValue100(v);
            case 200 -> c.setSmaValue200(v);
            case 500 -> c.setSmaValue500(v);
            default -> throw new IllegalArgumentException("no stamp column for " + period);
        }
    }

    private static Double stampOf(MarketData c, int period) {
        return switch (period) {
            case 20 -> c.getSmaValue20();
            case 50 -> c.getSmaValue50();
            case 100 -> c.getSmaValue100();
            case 200 -> c.getSmaValue200();
            case 500 -> c.getSmaValue500();
            default -> null;
        };
    }

    private static boolean downFlag(MarketData c, int period) {
        return switch (period) {
            case 20 -> c.isSma20DownTrending();
            case 50 -> c.isSma50DownTrending();
            case 100 -> c.isSma100DownTrending();
            case 200 -> c.isSma200DownTrending();
            case 500 -> c.isSma500DownTrending();
            default -> false;
        };
    }

    private static Double calculate(List<MarketData> candles, int period) {
        return new SMAIndicatorImpl().calculate(candles, IndicatorConfig.of(period, "SMA"));
    }

    private static int firstIndexOfLastDay(List<MarketData> candles) {
        LocalDate lastDay = candles.get(candles.size() - 1).getTimestamp().toLocalDate();
        for (int i = 0; i < candles.size(); i++) {
            if (candles.get(i).getTimestamp().toLocalDate().equals(lastDay)) {
                return i;
            }
        }
        throw new IllegalStateException("unreachable");
    }

    /**
     * The readable-surface assertion shared by every scenario: return value,
     * full-window stamps, last-day stamps, last-candle trend flags, slope read.
     */
    private static void assertReadableSurfaceMatches(List<MarketData> lazy, List<MarketData> ref,
                                                     int period, Double returned, double[] expected) {
        int size = lazy.size();
        assertThat(returned).isEqualTo(expected[size - 1]);

        for (int i = period - 1; i < size; i++) {
            assertThat(stampOf(lazy.get(i), period))
                    .as("full-window stamp at index %d, period %d", i, period)
                    .isEqualTo(expected[i]);
        }
        for (int i = firstIndexOfLastDay(lazy); i < size; i++) {
            assertThat(stampOf(lazy.get(i), period))
                    .as("last-day stamp at index %d, period %d", i, period)
                    .isEqualTo(expected[i]);
        }

        stampAll(ref, period, expected);
        SmaTrendCalculator.compute(lazy, 0);
        SmaTrendCalculator.compute(ref, 0);
        MarketData lazyLast = lazy.get(size - 1);
        MarketData refLast = ref.get(size - 1);
        assertThat(downFlag(lazyLast, period))
                .as("last-candle down flag, period %d", period)
                .isEqualTo(downFlag(refLast, period));
        assertThat(CommonRules.isSmaUpTrending(lazyLast, period))
                .as("last-candle up flag, period %d", period)
                .isEqualTo(CommonRules.isSmaUpTrending(refLast, period));

        if (period == 20) {
            boolean lazySlope = CommonRules.isSma20SlopeUp(
                    new RuleContext(lazyLast, size - 1, lazy, period, null));
            boolean refSlope = CommonRules.isSma20SlopeUp(
                    new RuleContext(refLast, size - 1, ref, period, null));
            assertThat(lazySlope).as("sma20 slope").isEqualTo(refSlope);
        }
    }

    // ------------------------------------------------------------------
    // Scenarios
    // ------------------------------------------------------------------

    @Test
    void warmupBeforeDecisionDayIsSkippedAndReadableSurfaceIsIdentical() {
        for (int period : new int[]{20, 50, 100, 200}) {
            List<MarketData> lazy = series(6, 75);
            List<MarketData> ref = cloneOf(lazy);
            double[] expected = reference(ref, period);

            Double returned = calculate(lazy, period);

            // The mechanism: warm-up indices before the decision day carry no stamp.
            int lastDayStart = firstIndexOfLastDay(lazy);
            for (int i = 0; i < Math.min(period - 1, lastDayStart); i++) {
                assertThat(stampOf(lazy.get(i), period))
                        .as("pre-decision-day warm-up stamp at index %d, period %d", i, period)
                        .isNull();
            }
            assertReadableSurfaceMatches(lazy, ref, period, returned, expected);
        }
    }

    @Test
    void warmupIntersectingDecisionDayIsStillComputed() {
        // 2 × 75 candles, period 100: warm-up [0, 99) reaches into the second
        // (decision) day, which starts at index 75 — the short-option-series shape.
        List<MarketData> lazy = series(2, 75);
        List<MarketData> ref = cloneOf(lazy);
        double[] expected = reference(ref, 100);

        Double returned = calculate(lazy, 100);

        for (int i = 0; i < 75; i++) {
            assertThat(stampOf(lazy.get(i), 100)).as("index %d", i).isNull();
        }
        for (int i = 75; i < 99; i++) {
            assertThat(stampOf(lazy.get(i), 100))
                    .as("decision-day warm-up stamp at index %d", i)
                    .isEqualTo(expected[i]);
        }
        assertReadableSurfaceMatches(lazy, ref, 100, returned, expected);
    }

    @Test
    void tickSimulationWithMovingLeftEdgeMatchesFullRecompute() {
        // The backtest shape: the slice shares objects across ticks (stamps
        // persist), the window is constant-width, and both edges advance one
        // candle per tick — crossing two day boundaries along the way.
        List<MarketData> master = series(6, 75);
        int window = 200;

        for (int t = 260; t < master.size(); t++) {
            List<MarketData> slice = new ArrayList<>(master.subList(t - window + 1, t + 1));
            for (int period : new int[]{20, 100}) {
                List<MarketData> ref = cloneOf(slice);
                double[] expected = reference(ref, period);
                Double returned = calculate(slice, period);
                assertReadableSurfaceMatches(slice, ref, period, returned, expected);
            }
        }
    }

    @Test
    void staleStampOnOldWarmupCandleIsNeitherTrustedNorOverwritten() {
        List<MarketData> lazy = series(6, 75);
        List<MarketData> ref = cloneOf(lazy);
        double[] expected = reference(ref, 100);

        lazy.get(10).setSmaValue100(999.0);   // day 1, deep in the warm-up region
        Double returned = calculate(lazy, 100);

        assertThat(lazy.get(10).getSmaValue100()).isEqualTo(999.0);
        assertReadableSurfaceMatches(lazy, ref, 100, returned, expected);
    }

    @Test
    void sizeExactlyPeriodComputesDecisionDayWarmupAndBoundary() {
        // 2 × 50 candles, period 100 == size: the full-window loop runs exactly
        // once (the boundary), and the decision day sits inside the warm-up.
        List<MarketData> lazy = series(2, 50);
        List<MarketData> ref = cloneOf(lazy);
        double[] expected = reference(ref, 100);

        Double returned = calculate(lazy, 100);

        for (int i = 0; i < 50; i++) {
            assertThat(stampOf(lazy.get(i), 100)).as("index %d", i).isNull();
        }
        for (int i = 50; i < 100; i++) {
            assertThat(stampOf(lazy.get(i), 100))
                    .as("decision-day stamp at index %d", i)
                    .isEqualTo(expected[i]);
        }
        assertThat(returned).isEqualTo(expected[99]);
    }

    @Test
    void nullTimestampFallsBackToComputingTheWholeWarmup() {
        List<MarketData> lazy = series(6, 75);
        double[] expected = reference(lazy, 100);
        lazy.get(lazy.size() - 1).setTimestamp(null);

        Double returned = calculate(lazy, 100);

        assertThat(returned).isEqualTo(expected[lazy.size() - 1]);
        for (int i = 0; i < 99; i++) {
            assertThat(stampOf(lazy.get(i), 100))
                    .as("fallback warm-up stamp at index %d", i)
                    .isEqualTo(expected[i]);
        }
    }

    @Test
    void periodWithoutStampColumnStillReturnsTheExactValue() {
        List<MarketData> lazy = series(6, 75);
        double[] expected = reference(lazy, 33);

        Double returned = calculate(lazy, 33);

        assertThat(returned).isEqualTo(expected[lazy.size() - 1]);
        for (MarketData c : lazy) {
            assertThat(c.getSmaValue20()).isNull();
            assertThat(c.getSmaValue50()).isNull();
            assertThat(c.getSmaValue100()).isNull();
            assertThat(c.getSmaValue200()).isNull();
            assertThat(c.getSmaValue500()).isNull();
        }
    }
}
