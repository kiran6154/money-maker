package com.moneymaker.market.instrument;

import java.util.ArrayList;
import java.util.List;

/**
 * Resolves "the single contract at a signed points offset from ATM" into an
 * ordered list of candidate strikes.
 *
 * <p>Used only by configs that set {@code trade_config.strike_offset_points}.
 * Everything else keeps the {@code itm_depth} / {@code otm_depth} strike-<i>set</i>
 * expansion in {@code AnalysisScheduler}, unchanged.</p>
 *
 * <h3>ATM is rounded, not floored</h3>
 * {@code AnalysisScheduler.calculateStrikesForCandles} derives its base strike
 * with {@code floor(close / step) * step}. The Pressure spec says
 * {@code round(spot / 50) * 50}, and the difference is not academic: with a
 * 50-point grid, flooring biases the chosen strike downward by an average of 25
 * points on every single trade, which on a CE leg means systematically less ITM
 * and on a PE leg systematically more. This class rounds, and it leaves the
 * flooring path alone for the strategies that have always used it — changing
 * that shared line would move every strike strategies 1-4 pick.
 *
 * <h3>The step comes from the config, not the instrument</h3>
 * {@code instrument.strike_points} says 100 for NIFTY while the imported
 * {@code historical_option_candles} are on a 50-point grid. Both are right for
 * their own consumer, so the caller passes the step it wants and
 * {@code trade_config.strike_step_points} is where the Pressure books say 50.
 * See changeset 042 for why the instrument row is deliberately not edited.
 *
 * <h3>Fallback order</h3>
 * The spec says "if exact strike missing, nearest available +/-50 then +/-100".
 * That is expressed here as an ordered candidate list rather than a lookup,
 * because whether a strike is "available" is only knowable by trying to fetch
 * its candles — the historical resolver encodes a symbol for any strike you ask
 * for. The caller walks the list and stops at the first that yields data.
 *
 * <p>Ties go to the strike <b>further from</b> the money for a short and closer
 * for a long? No — ties are broken by taking the lower strike first
 * ({@code -step} before {@code +step}), uniformly and regardless of side. A
 * side-dependent tie-break would silently make the CE and PE books
 * non-comparable, and the fallback is rare enough that a uniform, explicable
 * rule is worth more than a marginally better fill.</p>
 */
public final class OffsetStrikeSelector {

    private OffsetStrikeSelector() {
    }

    /** How far the fallback search may wander, as a multiple of the step. */
    private static final int MAX_FALLBACK_STEPS = 2;

    /**
     * ATM for a spot price on a given strike grid: {@code round(spot/step)*step}.
     *
     * @param step grid width in index points; must be positive
     */
    public static int atm(double spotClose, int step) {
        if (step <= 0) throw new IllegalArgumentException("strike step must be positive, got " + step);
        return (int) (Math.round(spotClose / step) * (long) step);
    }

    /**
     * The exact strike this config wants, before any availability fallback.
     *
     * <pre>
     *   CE:  ATM - offset      offset &gt; 0 is ITM for a call
     *   PE:  ATM + offset      offset &gt; 0 is ITM for a put
     * </pre>
     *
     * @param optionType {@code "CE"} or {@code "PE"}
     * @param offsetPoints signed points ITM; 0 = ATM, negative = OTM
     */
    public static int exactStrike(int atm, String optionType, int offsetPoints) {
        boolean call = optionType != null && optionType.trim().toUpperCase().startsWith("C");
        return call ? atm - offsetPoints : atm + offsetPoints;
    }

    /**
     * Candidate strikes in preference order: the exact strike, then one step
     * either side, then two steps either side.
     *
     * <p>The caller fetches them in this order and stops at the first with
     * candles, so in the normal case — a dense ladder, which is what our 2024
     * data has — exactly one fetch happens.</p>
     */
    public static List<Integer> candidates(int atm, String optionType, int offsetPoints, int step) {
        if (step <= 0) throw new IllegalArgumentException("strike step must be positive, got " + step);
        int exact = exactStrike(atm, optionType, offsetPoints);
        List<Integer> out = new ArrayList<>(1 + 2 * MAX_FALLBACK_STEPS);
        out.add(exact);
        for (int k = 1; k <= MAX_FALLBACK_STEPS; k++) {
            out.add(exact - k * step);
            out.add(exact + k * step);
        }
        return out;
    }
}
