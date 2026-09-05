package com.moneymaker.indicator.series;

/**
 * Supertrend direction, computed for a whole series at once.
 *
 * <p>The Pressure spec uses {@code Supertrend(ATR 10, multiplier 3)} and reads
 * only {@code ST_dir}, so that is what this returns: {@code +1} for an uptrend,
 * {@code -1} for a downtrend, {@code 0} while the ATR is still warming.</p>
 *
 * <h3>Why this cannot be a scalar indicator</h3>
 * Supertrend is a <b>path-dependent</b> recurrence. Two things at bar <i>i</i>
 * depend on bar <i>i-1</i>:
 *
 * <ul>
 *   <li><b>Band clamping.</b> The upper band may only ratchet <i>down</i> while
 *       price stays below the previous upper band, and the lower band may only
 *       ratchet <i>up</i> while price stays above the previous lower band. Drop
 *       the clamp and the bands breathe with every ATR wiggle, producing far
 *       more flips than a real Supertrend.</li>
 *   <li><b>Direction carry.</b> Direction only changes when price actually
 *       crosses the active band; otherwise it is inherited.</li>
 * </ul>
 *
 * <p>So the answer at any bar is a function of the entire history before it, and
 * computing it from a truncated window silently returns a different series. That
 * is the concrete reason this package exists rather than another
 * {@code Indicator} implementation — see {@link Bars}.</p>
 *
 * <h3>Convention</h3>
 * Direction is seeded {@code +1} at the first bar where the ATR becomes
 * available. The seed is arbitrary in the sense that any Supertrend has to start
 * somewhere, and it washes out within a few bars; what matters is that
 * {@link SpotFeatures} feeds this a multi-day warmup window rather than a single
 * session, so no trading decision is ever taken on the seed itself.
 */
public final class Supertrend {

    private Supertrend() {
    }

    public static final int UP = 1;
    public static final int DOWN = -1;
    /** Not yet computable — ATR still warming. Never a tradeable direction. */
    public static final int UNKNOWN = 0;

    /**
     * @param atrPeriod ATR lookback (10 for the Pressure spec)
     * @param multiplier band width in ATRs (3 for the Pressure spec)
     * @return direction per bar: {@link #UP}, {@link #DOWN} or {@link #UNKNOWN}
     */
    public static int[] direction(double[] highs, double[] lows, double[] closes,
                                  int atrPeriod, double multiplier) {
        int n = closes.length;
        int[] dir = new int[n];
        if (n == 0) return dir;

        double[] atr = TrueRange.atr(highs, lows, closes, atrPeriod);

        double prevUpper = Double.NaN;
        double prevLower = Double.NaN;
        int prevDir = UNKNOWN;

        for (int i = 0; i < n; i++) {
            if (Bars.isNa(atr[i])) {
                dir[i] = UNKNOWN;
                continue;
            }
            double mid = (highs[i] + lows[i]) / 2d;
            double rawUpper = mid + multiplier * atr[i];
            double rawLower = mid - multiplier * atr[i];

            // The ratchet. Once in a downtrend the upper band may only fall; once
            // in an uptrend the lower band may only rise. Without this the band
            // follows the ATR up and down and the trend flips on noise.
            double upper = (Bars.isNa(prevUpper) || rawUpper < prevUpper || closes[i - 1 < 0 ? 0 : i - 1] > prevUpper)
                    ? rawUpper : prevUpper;
            double lower = (Bars.isNa(prevLower) || rawLower > prevLower || closes[i - 1 < 0 ? 0 : i - 1] < prevLower)
                    ? rawLower : prevLower;

            int d;
            if (prevDir == UNKNOWN) {
                // First computable bar. Seeded UP; see the class note on why the
                // seed is safe given the warmup window SpotFeatures supplies.
                d = UP;
            } else if (prevDir == UP && closes[i] < lower) {
                d = DOWN;
            } else if (prevDir == DOWN && closes[i] > upper) {
                d = UP;
            } else {
                d = prevDir;
            }

            dir[i] = d;
            prevDir = d;
            prevUpper = upper;
            prevLower = lower;
        }
        return dir;
    }
}
