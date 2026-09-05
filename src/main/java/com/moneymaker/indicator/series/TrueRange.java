package com.moneymaker.indicator.series;

/**
 * True range and Wilder-smoothed ATR, shared by {@link Supertrend} and
 * {@link DirectionalIndex} so the two cannot drift apart in how they smooth.
 *
 * <pre>
 *   TR[0] = high[0] - low[0]
 *   TR[i] = max( high-low, |high - prevClose|, |low - prevClose| )
 * </pre>
 */
public final class TrueRange {

    private TrueRange() {
    }

    public static double[] compute(double[] highs, double[] lows, double[] closes) {
        int n = highs.length;
        double[] tr = new double[n];
        if (n == 0) return tr;
        tr[0] = highs[0] - lows[0];
        for (int i = 1; i < n; i++) {
            double prevClose = closes[i - 1];
            double a = highs[i] - lows[i];
            double b = Math.abs(highs[i] - prevClose);
            double c = Math.abs(lows[i] - prevClose);
            tr[i] = Math.max(a, Math.max(b, c));
        }
        return tr;
    }

    /**
     * Wilder's smoothing of an already-computed series — the same recurrence RSI
     * uses, seeded on a simple mean of the first {@code period} values.
     *
     * <p>Seeded at index {@code period-1} rather than {@code period}: unlike RSI,
     * whose first usable value needs a <i>change</i> and therefore two bars,
     * {@code TR[0]} is defined on its own, so the first window is
     * {@code [0..period-1]}.</p>
     *
     * @return smoothed series, {@link Bars#NA} before the seed
     */
    public static double[] wilderSmooth(double[] values, int period) {
        int n = values.length;
        double[] out = new double[n];
        java.util.Arrays.fill(out, Bars.NA);
        if (period <= 0 || n < period) return out;

        double sum = 0d;
        for (int i = 0; i < period; i++) sum += values[i];
        double avg = sum / period;
        out[period - 1] = avg;

        for (int i = period; i < n; i++) {
            avg = (avg * (period - 1) + values[i]) / period;
            out[i] = avg;
        }
        return out;
    }

    /** Wilder ATR: {@link #wilderSmooth} over {@link #compute}. */
    public static double[] atr(double[] highs, double[] lows, double[] closes, int period) {
        return wilderSmooth(compute(highs, lows, closes), period);
    }
}
