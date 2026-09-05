package com.moneymaker.indicator.series;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * Pins {@link WilderRsi} against Wilder's own published worked example.
 *
 * <p>This matters more than a typical indicator test. The Pressure score reads
 * RSI at hard thresholds — {@code < 40} and {@code > 60} — so an implementation
 * that is merely "RSI-shaped" but a few points off flips score terms on real
 * bars, and the error is invisible in aggregate. The existing
 * {@code RSIIndicatorImpl} returns a hardcoded {@code 0.0}, which is exactly the
 * failure this file exists to make impossible for the new one.
 */
class WilderRsiTest {

    /**
     * The closing series from Wilder's "New Concepts in Technical Trading
     * Systems", reproduced in essentially every RSI reference since.
     */
    private static final double[] WILDER_CLOSES = {
            44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42,
            45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28, 46.00,
            46.03, 46.41, 46.22, 45.64, 46.21, 46.25, 45.71, 46.45
    };

    @Test
    @DisplayName("matches Wilder's published RSI(14) at the seed and the first smoothed bar")
    void matchesWilderReference() {
        double[] rsi = WilderRsi.compute(WILDER_CLOSES, 14);

        // Seed: mean of the first 14 changes.
        //   gains  = 3.34 / 14 = 0.238571
        //   losses = 1.40 / 14 = 0.100000
        //   RS = 2.385714 -> RSI = 70.46
        assertThat(rsi[14]).isCloseTo(70.46, within(0.02));

        // First smoothed bar: close falls 46.28 -> 46.00.
        //   avgGain = (0.238571*13 + 0)    / 14 = 0.221531
        //   avgLoss = (0.100000*13 + 0.28) / 14 = 0.112857
        //   RS = 1.9629 -> RSI = 66.25
        assertThat(rsi[15]).isCloseTo(66.25, within(0.02));
    }

    @Test
    @DisplayName("bars before the seed are NA, never 0 — a 0 would read as permanently oversold")
    void warmupIsNaNotZero() {
        double[] rsi = WilderRsi.compute(WILDER_CLOSES, 14);

        for (int i = 0; i < 14; i++) {
            assertThat(Bars.isNa(rsi[i]))
                    .as("index %d must be NA during warmup", i)
                    .isTrue();
        }
        assertThat(Bars.isNa(rsi[14])).isFalse();
    }

    @Test
    @DisplayName("Wilder smoothing, not a simple moving average — the two must not agree")
    void isWilderNotSma() {
        // A step change followed by a flat run separates the two: Wilder's
        // exponential recurrence keeps memory of the step long after a
        // 14-bar SMA has rolled it out of the window. If someone ever swaps in
        // the SMA variant, these values converge and this test fails.
        double[] closes = new double[40];
        closes[0] = 100;
        for (int i = 1; i < 40; i++) {
            closes[i] = i <= 15 ? closes[i - 1] + 1 : closes[i - 1];
        }
        double[] rsi = WilderRsi.compute(closes, 14);

        // 20+ flat bars after the rally. A simple 14-bar average would have
        // dropped every gain out of its window by now and printed exactly 50;
        // Wilder still remembers them.
        assertThat(rsi[39]).isGreaterThan(60d);
    }

    @Test
    @DisplayName("an unbroken run of up-bars is 100, not NaN from a divide by zero")
    void allGainsIsHundred() {
        double[] closes = new double[20];
        for (int i = 0; i < 20; i++) closes[i] = 100 + i;

        double[] rsi = WilderRsi.compute(closes, 14);

        // avgLoss is exactly 0 here. Left to the division this is Infinity and
        // then NaN, which PressureScore reads as "not computable" and silently
        // drops the term — turning a maximally overbought bar into no signal.
        assertThat(Bars.isNa(rsi[19])).isFalse();
        assertThat(rsi[19]).isEqualTo(100d);
    }

    @Test
    @DisplayName("a series shorter than the period yields all-NA rather than throwing")
    void tooShortIsAllNa() {
        double[] rsi = WilderRsi.compute(new double[]{1, 2, 3}, 14);
        assertThat(rsi).hasSize(3);
        for (double v : rsi) assertThat(Bars.isNa(v)).isTrue();
    }
}
