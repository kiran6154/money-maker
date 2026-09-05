package com.moneymaker.indicator.series;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.within;

/**
 * Behavioural pins for the two path-dependent indicators.
 *
 * <p>Unlike RSI there is no single canonical worked example for Supertrend or
 * ADX that every source agrees on, so these assert the <b>properties</b> that
 * make the indicators usable in the Pressure score: that direction persists and
 * only flips on a genuine reversal, that the bands ratchet, and that ADX rises
 * in a trend and DI separates in the right direction. A wrong implementation
 * fails at least one of them.</p>
 */
class SupertrendAndAdxTest {

    /** A clean rally: each bar higher than the last, small ranges. */
    private static double[][] rally(int n, double start, double step) {
        double[] h = new double[n], l = new double[n], c = new double[n];
        double p = start;
        for (int i = 0; i < n; i++) {
            c[i] = p;
            h[i] = p + 2;
            l[i] = p - 2;
            p += step;
        }
        return new double[][]{h, l, c};
    }

    // ---------------------------------------------------------------- ATR

    @Test
    @DisplayName("ATR on a constant-range series equals that range")
    void atrOnConstantRange() {
        int n = 40;
        double[] h = new double[n], l = new double[n], c = new double[n];
        for (int i = 0; i < n; i++) {
            h[i] = 110;
            l[i] = 100;
            c[i] = 105;
        }
        double[] atr = TrueRange.atr(h, l, c, 10);

        // Every true range is exactly 10 (high-low dominates, prev close is
        // inside the bar), so any correct smoothing converges on 10.
        assertThat(atr[n - 1]).isCloseTo(10d, within(1e-9));
    }

    @Test
    @DisplayName("ATR warmup is NA and the seed lands at period-1, not period")
    void atrSeedIndex() {
        double[][] s = rally(30, 100, 1);
        double[] atr = TrueRange.atr(s[0], s[1], s[2], 10);

        for (int i = 0; i < 9; i++) {
            assertThat(Bars.isNa(atr[i])).as("index %d", i).isTrue();
        }
        // TR[0] is defined on its own (unlike an RSI change, which needs two
        // bars), so the first window is [0..9] and the seed is at index 9.
        assertThat(Bars.isNa(atr[9])).isFalse();
    }

    // --------------------------------------------------------- Supertrend

    @Test
    @DisplayName("direction is UNKNOWN while the ATR warms, never a tradeable value")
    void supertrendWarmupIsUnknown() {
        double[][] s = rally(30, 100, 1);
        int[] dir = Supertrend.direction(s[0], s[1], s[2], 10, 3);

        for (int i = 0; i < 9; i++) {
            assertThat(dir[i])
                    .as("index %d must not be tradeable during warmup", i)
                    .isEqualTo(Supertrend.UNKNOWN);
        }
    }

    @Test
    @DisplayName("a sustained rally holds UP and does not flip on noise")
    void supertrendHoldsUpInARally() {
        double[][] s = rally(60, 100, 1);
        int[] dir = Supertrend.direction(s[0], s[1], s[2], 10, 3);

        for (int i = 20; i < 60; i++) {
            assertThat(dir[i]).as("index %d", i).isEqualTo(Supertrend.UP);
        }
    }

    @Test
    @DisplayName("flips to DOWN on a real reversal, and only after price breaks the band")
    void supertrendFlipsOnReversal() {
        // 40 bars up, then a hard 40-bar selloff steep enough to break a
        // 3xATR band.
        int n = 80;
        double[] h = new double[n], l = new double[n], c = new double[n];
        double p = 100;
        for (int i = 0; i < n; i++) {
            p += (i < 40) ? 1 : -6;
            c[i] = p;
            h[i] = p + 2;
            l[i] = p - 2;
        }
        int[] dir = Supertrend.direction(h, l, c, 10, 3);

        assertThat(dir[39]).as("still up at the top").isEqualTo(Supertrend.UP);
        assertThat(dir[n - 1]).as("down by the end of the selloff").isEqualTo(Supertrend.DOWN);

        // And it did not flip on the very first down bar — a 3xATR band should
        // absorb at least one.
        assertThat(dir[40]).isEqualTo(Supertrend.UP);
    }

    @Test
    @DisplayName("direction is carried, not recomputed — a flat stretch never flips")
    void supertrendCarriesDirection() {
        int n = 60;
        double[] h = new double[n], l = new double[n], c = new double[n];
        double p = 100;
        for (int i = 0; i < n; i++) {
            if (i < 30) p += 1;           // establish an uptrend
            c[i] = p;
            h[i] = p + 1;
            l[i] = p - 1;
        }
        int[] dir = Supertrend.direction(h, l, c, 10, 3);

        // 30 bars of dead flat after the trend. Nothing crosses anything, so
        // the direction must simply persist. An implementation that recomputes
        // from the current bar alone would go undefined or oscillate here.
        for (int i = 35; i < n; i++) {
            assertThat(dir[i]).as("index %d", i).isEqualTo(Supertrend.UP);
        }
    }

    // ---------------------------------------------------------------- ADX

    @Test
    @DisplayName("+DI dominates -DI in an uptrend, and the reverse in a downtrend")
    void diSeparatesWithTrend() {
        double[][] up = rally(60, 100, 2);
        DirectionalIndex.Result r = DirectionalIndex.compute(up[0], up[1], up[2], 14);
        assertThat(r.plusDi()[59]).isGreaterThan(r.minusDi()[59]);

        double[][] down = rally(60, 200, -2);
        DirectionalIndex.Result d = DirectionalIndex.compute(down[0], down[1], down[2], 14);
        assertThat(d.minusDi()[59]).isGreaterThan(d.plusDi()[59]);
    }

    @Test
    @DisplayName("ADX reads strongly trending in a clean trend — the penalty tests it above 40")
    void adxIsHighInATrend() {
        double[][] s = rally(80, 100, 2);
        DirectionalIndex.Result r = DirectionalIndex.compute(s[0], s[1], s[2], 14);

        assertThat(Bars.isNa(r.adx()[79])).isFalse();
        assertThat(r.adx()[79])
                .as("a one-directional series should be strongly trending")
                .isGreaterThan(40d);
        // NOT asserted: that ADX keeps rising here. On a perfectly clean
        // one-directional series -DI is exactly 0, so DX pins at 100 and ADX
        // saturates. "Rises" is tested against a chop-then-trend series below,
        // which is the only shape where the question is meaningful.
    }

    @Test
    @DisplayName("ADX rises when a chop resolves into a trend")
    void adxRisesWhenChopBecomesTrend() {
        int chop = 60, trend = 60, n = chop + trend;
        double[] h = new double[n], l = new double[n], c = new double[n];
        double p = 100;
        for (int i = 0; i < n; i++) {
            p += (i < chop) ? (i % 2 == 0 ? 1 : -1) : 2;
            c[i] = p;
            h[i] = p + 1;
            l[i] = p - 1;
        }
        DirectionalIndex.Result r = DirectionalIndex.compute(h, l, c, 14);

        double duringChop = r.adx()[chop - 1];
        double duringTrend = r.adx()[n - 1];
        assertThat(Bars.isNa(duringChop)).isFalse();
        assertThat(duringTrend)
                .as("ADX must rise as the chop resolves: chop=%.2f trend=%.2f", duringChop, duringTrend)
                .isGreaterThan(duringChop);
    }

    @Test
    @DisplayName("ADX stays low in a chop — so the exhaustion penalty stays disarmed")
    void adxLowInChop() {
        int n = 100;
        double[] h = new double[n], l = new double[n], c = new double[n];
        for (int i = 0; i < n; i++) {
            double p = 100 + (i % 2 == 0 ? 1 : -1);
            c[i] = p;
            h[i] = p + 1;
            l[i] = p - 1;
        }
        DirectionalIndex.Result r = DirectionalIndex.compute(h, l, c, 14);

        assertThat(r.adx()[n - 1])
                .as("alternating bars are the definition of no trend")
                .isLessThan(40d);
    }

    @Test
    @DisplayName("a series shorter than the period yields all-NA rather than throwing")
    void tooShortIsAllNa() {
        DirectionalIndex.Result r = DirectionalIndex.compute(
                new double[]{1, 2}, new double[]{0, 1}, new double[]{1, 2}, 14);
        assertThat(Bars.isNa(r.adx()[1])).isTrue();
        assertThat(Bars.isNa(r.plusDi()[1])).isTrue();
    }
}
