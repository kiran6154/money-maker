package com.moneymaker.indicator.series;

/**
 * The session-anchored average price the Pressure score compares {@code close}
 * against — an expanding mean of typical price from the session open.
 *
 * <pre>
 *   typical[i] = (high[i] + low[i] + close[i]) / 3
 *   anchor[i]  = mean( typical[0..i] )        // reset each session
 * </pre>
 *
 * <h3>This is NOT a VWAP, and the name matters</h3>
 * The Pressure specification calls this term "Session VWAP", and the reference
 * implementation that produced the 1,560-ticket 2024 book <b>did not use volume
 * at all</b> — it is an unweighted expanding mean of HLC typical price
 * (confirmed by the strategy's author, 2026-09-05: <i>"I should have called it
 * session typical-price mean"</i>).
 *
 * <p>Taking the word "VWAP" literally is a trap this codebase already fell into
 * once. NIFTY is an index and has no traded volume — 19,572 of the 19,602
 * {@code historical_spot_candles} rows for 2024 carry {@code volume = 0} — so an
 * earlier version of this class went looking for a substitute and weighted each
 * bar by front-weekly option-chain volume. That produced a <i>different
 * indicator</i>, which would have made every comparison against the reference
 * book meaningless while looking entirely plausible in the output. The class is
 * named for what it computes so that cannot happen again.</p>
 *
 * <h3>Weights are still supported, and deliberately unused by default</h3>
 * {@link #compute(double[], double[])} accepts an optional weight series. Passing
 * {@code null} — the default, and what reproduces the reference — yields the
 * plain mean. The weighted path is retained for one specific future experiment
 * the author proposed: a genuine volume-weighted price built from the
 * <b>option tape</b> (ATM ±2 strikes, both rights), which is a real traded
 * volume rather than an index's absent one.
 *
 * <p>That experiment is not a drop-in improvement — it changes what trades get
 * taken, so the reference book would have to be re-marked against it before any
 * of its figures could be compared. See {@code app.pressure.anchor-mode} and
 * S22 in {@code docs/STRATEGY_ANALYSIS_TODO.md}.</p>
 */
public final class SessionAnchoredPrice {

    private SessionAnchoredPrice() {
    }

    /**
     * The reference formula: unweighted expanding mean of typical price.
     *
     * @param typicalPrices per-bar {@code (H+L+C)/3}, session bars only, ascending
     */
    public static double[] compute(double[] typicalPrices) {
        return compute(typicalPrices, null);
    }

    /**
     * As {@link #compute(double[])}, optionally weighting each bar.
     *
     * @param weights per-bar weight, or {@code null} for the unweighted mean.
     *                Zero, negative and {@link Bars#NA} weights are treated as
     *                "no weight" for that bar, which then contributes to the
     *                unweighted running mean instead of being dropped —
     *                excluding it would silently shorten the session.
     */
    public static double[] compute(double[] typicalPrices, double[] weights) {
        int n = typicalPrices.length;
        double[] out = new double[n];
        double weighted = 0d;
        double weight = 0d;
        double plain = 0d;
        int plainCount = 0;

        for (int i = 0; i < n; i++) {
            double tp = typicalPrices[i];
            if (Bars.isNa(tp)) {
                // Carry the previous value rather than emitting NA: a single
                // unusable bar must not blank the anchor for the rest of the
                // session, and PressureScore reads NA as "term does not score".
                out[i] = i > 0 ? out[i - 1] : Bars.NA;
                continue;
            }
            plain += tp;
            plainCount++;

            double w = (weights == null || i >= weights.length) ? 0d : weights[i];
            if (!Bars.isNa(w) && w > 0d) {
                weighted += tp * w;
                weight += w;
            }
            out[i] = weight > 0d ? (weighted / weight) : (plain / plainCount);
        }
        return out;
    }
}
