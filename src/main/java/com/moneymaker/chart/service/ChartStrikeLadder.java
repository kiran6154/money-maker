package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.IndexSymbol;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * The exchange's strike grid for an index, and the ladders built on it.
 *
 * <p>This is contract metadata, not a trading rule — it is the spacing NSE lists
 * strikes at, the same constant the ATM rounding has always used. Both chart
 * services now read the step from here so "one strike up" and "round to ATM"
 * cannot drift apart: an ATM computed on a 50-point grid with a ladder stepped
 * by 100 would centre the average somewhere the underlying never was.
 */
final class ChartStrikeLadder {

    private ChartStrikeLadder() {
    }

    /** Gap between adjacent listed strikes. */
    static int stepFor(IndexSymbol indexSymbol) {
        return switch (indexSymbol) {
            case NIFTY -> 50;
            case BANKNIFTY -> 100;
        };
    }

    /** The nearest listed strike to {@code referencePrice}. */
    static BigDecimal atmStrike(IndexSymbol indexSymbol, BigDecimal referencePrice) {
        int step = stepFor(indexSymbol);
        return BigDecimal.valueOf(Math.round(referencePrice.doubleValue() / step) * step);
    }

    /**
     * {@code centre} widened by {@code span} steps either side, ascending.
     *
     * <p>A {@code span} of 0 is the single strike, so callers need no special
     * case for the ordinary chart. The list is symmetric by construction, which
     * is what makes the resulting average straddle the money for a CE and a PE
     * alike.
     */
    static List<BigDecimal> around(IndexSymbol indexSymbol, BigDecimal centre, int span) {
        if (centre == null || span <= 0) {
            return centre == null ? List.of() : List.of(centre);
        }

        BigDecimal step = BigDecimal.valueOf(stepFor(indexSymbol));
        List<BigDecimal> strikes = new ArrayList<>(span * 2 + 1);
        for (int offset = -span; offset <= span; offset++) {
            BigDecimal strike = centre.add(step.multiply(BigDecimal.valueOf(offset)));
            // A ladder wide enough to reach past zero is a nonsense contract, not
            // a strike the chart should ask the DB for.
            if (strike.signum() > 0) {
                strikes.add(strike);
            }
        }
        return strikes;
    }
}
