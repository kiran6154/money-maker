package com.moneymaker.indicator.series;

/**
 * Wilder's directional movement system: {@code +DI}, {@code -DI} and
 * {@code ADX}, computed for a whole series at once.
 *
 * <p>The Pressure spec uses all three, but only as a <b>penalty</b> term:</p>
 *
 * <pre>
 *   P_down -= 1  if  ADX &gt; 40  AND  -DI now &lt; -DI three bars ago
 *   P_up   -= 1  if  ADX &gt; 40  AND  +DI now &lt; +DI three bars ago
 * </pre>
 *
 * <p>i.e. "the trend is already strong <i>and</i> its own directional pressure is
 * fading" — an exhaustion filter, not an entry filter. That is why the three
 * series are returned together in one {@link Result}: they are only ever read as
 * a triple, and computing them separately would smooth the same true-range
 * series three times.</p>
 *
 * <h3>Wilder's smoothing, and the one place it is not a plain average</h3>
 * {@code +DM} / {@code -DM} / {@code TR} are accumulated with Wilder's running
 * total (the classic {@code sum = sum - sum/period + today} form) rather than an
 * arithmetic mean. This class routes all three through
 * {@link TrueRange#wilderSmooth} instead, which is the equivalent recurrence
 * expressed as a running average — the two differ only by a constant factor of
 * {@code period}, and since {@code DI} is a <i>ratio</i> of two of them that
 * factor cancels exactly. Sharing one smoother with {@link Supertrend}'s ATR is
 * worth more than matching Wilder's arithmetic literally.
 */
public final class DirectionalIndex {

    private DirectionalIndex() {
    }

    /**
     * The three series, aligned index-for-index with the input bars.
     * {@link Bars#NA} entries mean "not computable yet".
     */
    public record Result(double[] plusDi, double[] minusDi, double[] adx) {
    }

    public static Result compute(double[] highs, double[] lows, double[] closes, int period) {
        int n = closes.length;
        double[] plusDi = new double[n];
        double[] minusDi = new double[n];
        double[] adx = new double[n];
        java.util.Arrays.fill(plusDi, Bars.NA);
        java.util.Arrays.fill(minusDi, Bars.NA);
        java.util.Arrays.fill(adx, Bars.NA);
        if (period <= 0 || n <= period) return new Result(plusDi, minusDi, adx);

        double[] plusDm = new double[n];
        double[] minusDm = new double[n];
        for (int i = 1; i < n; i++) {
            double up = highs[i] - highs[i - 1];
            double down = lows[i - 1] - lows[i];
            // Only the LARGER of the two moves counts, and only if it is
            // positive. A bar that is an inside bar contributes neither; a bar
            // that is an outside bar contributes only to the dominant side.
            plusDm[i] = (up > down && up > 0) ? up : 0d;
            minusDm[i] = (down > up && down > 0) ? down : 0d;
        }

        double[] tr = TrueRange.compute(highs, lows, closes);
        double[] smTr = TrueRange.wilderSmooth(tr, period);
        double[] smPlus = TrueRange.wilderSmooth(plusDm, period);
        double[] smMinus = TrueRange.wilderSmooth(minusDm, period);

        double[] dx = new double[n];
        java.util.Arrays.fill(dx, Bars.NA);
        for (int i = 0; i < n; i++) {
            if (Bars.isNa(smTr[i]) || smTr[i] == 0d) continue;
            double p = 100d * smPlus[i] / smTr[i];
            double m = 100d * smMinus[i] / smTr[i];
            plusDi[i] = p;
            minusDi[i] = m;
            double sum = p + m;
            // sum == 0 means neither side registered any directional movement
            // across the whole smoothed window - a perfectly flat stretch. DX is
            // undefined there rather than zero, and leaving it NA keeps it out of
            // the ADX average instead of dragging the average down.
            if (sum != 0d) {
                dx[i] = 100d * Math.abs(p - m) / sum;
            }
        }

        // ADX is Wilder's smoothing of DX, seeded on the mean of the first
        // `period` computable DX values. Walk forward to find them rather than
        // assuming a fixed offset: DX's own first index depends on where the
        // true-range smoother seeded.
        int firstDx = -1;
        for (int i = 0; i < n; i++) {
            if (!Bars.isNa(dx[i])) {
                firstDx = i;
                break;
            }
        }
        if (firstDx < 0 || firstDx + period > n) {
            return new Result(plusDi, minusDi, adx);
        }
        double sum = 0d;
        int counted = 0;
        int i = firstDx;
        for (; i < n && counted < period; i++) {
            if (Bars.isNa(dx[i])) continue;
            sum += dx[i];
            counted++;
        }
        if (counted < period) {
            return new Result(plusDi, minusDi, adx);
        }
        double avg = sum / period;
        int seedIndex = i - 1;
        adx[seedIndex] = avg;
        for (int j = seedIndex + 1; j < n; j++) {
            if (Bars.isNa(dx[j])) {
                adx[j] = avg;
                continue;
            }
            avg = (avg * (period - 1) + dx[j]) / period;
            adx[j] = avg;
        }
        return new Result(plusDi, minusDi, adx);
    }
}
