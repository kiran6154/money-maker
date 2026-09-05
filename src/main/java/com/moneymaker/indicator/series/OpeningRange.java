package com.moneymaker.indicator.series;

import com.moneymaker.entity.MarketData;

import java.time.LocalTime;
import java.util.List;

/**
 * High and low of the session's opening window — {@code [09:15, 09:30]} for the
 * Pressure spec.
 *
 * <h3>Both boundaries are inclusive, and that is a real decision</h3>
 * The spec says "bars with time in [09:15, 09:30]". On a 5-minute series that is
 * four bars: 09:15, 09:20, 09:25 and 09:30. A half-open reading would take three
 * and produce a materially narrower range — and since {@code close &lt; OR_low}
 * is a full point of the pressure score, a narrower range fires that term more
 * often. Inclusive is what the spec says and inclusive is what this does.
 *
 * <h3>Not available until the window closes</h3>
 * {@link #isComplete()} is false until a bar at or after the window end has been
 * seen. A caller must not score the {@code OR} term before then: a range built
 * from a partial window is guaranteed to be too narrow, so every early bar would
 * score the breakout term for free. This is the no-lookahead rule applied in the
 * one direction people forget — not "don't read the future", but "don't treat an
 * incomplete present as finished".
 *
 * <p>It also happens to be why the Pressure entry clock opens at 09:25 and not
 * at the session open, though the two constraints are independent: the clock is
 * config ({@code trade_config.entry_from}) and this is arithmetic.</p>
 */
public final class OpeningRange {

    private final double high;
    private final double low;
    private final boolean complete;

    private OpeningRange(double high, double low, boolean complete) {
        this.high = high;
        this.low = low;
        this.complete = complete;
    }

    /**
     * Builds the range from the session bars supplied.
     *
     * @param sessionBars bars for one day, already session-filtered and ascending
     * @param from        window start, inclusive (09:15)
     * @param to          window end, inclusive (09:30)
     */
    public static OpeningRange of(List<MarketData> sessionBars, LocalTime from, LocalTime to) {
        double hi = Double.NEGATIVE_INFINITY;
        double lo = Double.POSITIVE_INFINITY;
        boolean sawWindowEnd = false;
        int count = 0;

        for (MarketData b : sessionBars) {
            if (b == null || b.getTimestamp() == null) continue;
            LocalTime t = b.getTimestamp().toLocalTime();
            if (t.isBefore(from)) continue;
            if (t.isAfter(to)) {
                // A bar past the window proves the window is over even when the
                // exact closing bar is missing from the data.
                sawWindowEnd = true;
                break;
            }
            if (b.getHigh() != null) hi = Math.max(hi, b.getHigh().doubleValue());
            if (b.getLow() != null) lo = Math.min(lo, b.getLow().doubleValue());
            count++;
            if (!t.isBefore(to)) sawWindowEnd = true;
        }

        if (count == 0 || hi == Double.NEGATIVE_INFINITY || lo == Double.POSITIVE_INFINITY) {
            return new OpeningRange(Bars.NA, Bars.NA, false);
        }
        return new OpeningRange(hi, lo, sawWindowEnd);
    }

    /** True once the opening window has finished forming. See the class note. */
    public boolean isComplete() {
        return complete;
    }

    public double high() {
        return high;
    }

    public double low() {
        return low;
    }
}
