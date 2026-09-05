package com.moneymaker.indicator.series;

/**
 * RSI with Wilder's smoothing, computed for a whole series at once.
 *
 * <p>Wilder's original formulation, not the "cutler" simple-moving-average
 * variant. The distinction matters and is not cosmetic: Wilder's is an
 * exponential recurrence with alpha = 1/period, so it has memory of the entire
 * series, while the SMA variant only remembers the last {@code period} bars. On
 * a 14-period RSI the two can differ by several points for dozens of bars after
 * a sharp move — precisely the moves the Pressure score is trying to detect at
 * its 40 / 60 thresholds.</p>
 *
 * <pre>
 *   seed (at i = period):   avgGain = mean(gains[1..period])
 *                           avgLoss = mean(losses[1..period])
 *   thereafter:             avgGain = (avgGain * (period-1) + gain) / period
 *                           avgLoss = (avgLoss * (period-1) + loss) / period
 *   rsi                   = 100 - 100 / (1 + avgGain/avgLoss)
 * </pre>
 *
 * <p>Bars before the seed are {@link Bars#NA}. The caller must treat NA as "no
 * opinion" rather than as a value — a 0.0 there would read as a permanent
 * oversold signal, which is exactly the failure mode of the stub
 * {@code RSIIndicatorImpl} this class deliberately does not touch.</p>
 */
public final class WilderRsi {

    private WilderRsi() {
    }

    /**
     * @param closes bar closes, ascending
     * @param period Wilder period (14 for the Pressure spec)
     * @return RSI per bar, {@link Bars#NA} until the seed is complete
     */
    public static double[] compute(double[] closes, int period) {
        int n = closes.length;
        double[] rsi = new double[n];
        java.util.Arrays.fill(rsi, Bars.NA);
        if (period <= 0 || n <= period) return rsi;

        double gainSum = 0d;
        double lossSum = 0d;
        for (int i = 1; i <= period; i++) {
            double change = closes[i] - closes[i - 1];
            if (change > 0) gainSum += change;
            else lossSum -= change;
        }
        double avgGain = gainSum / period;
        double avgLoss = lossSum / period;
        rsi[period] = fromAverages(avgGain, avgLoss);

        for (int i = period + 1; i < n; i++) {
            double change = closes[i] - closes[i - 1];
            double gain = change > 0 ? change : 0d;
            double loss = change < 0 ? -change : 0d;
            avgGain = (avgGain * (period - 1) + gain) / period;
            avgLoss = (avgLoss * (period - 1) + loss) / period;
            rsi[i] = fromAverages(avgGain, avgLoss);
        }
        return rsi;
    }

    /**
     * {@code avgLoss == 0} means an unbroken run of up-bars across the whole
     * smoothed window. RS is then infinite and RSI is 100 by definition —
     * returning that explicitly rather than letting the division produce
     * {@code Infinity} and then {@code NaN}, which would read as "not
     * computable" and silently drop the term from the pressure score.
     */
    private static double fromAverages(double avgGain, double avgLoss) {
        if (avgLoss == 0d) return avgGain == 0d ? 50d : 100d;
        double rs = avgGain / avgLoss;
        return 100d - (100d / (1d + rs));
    }
}
