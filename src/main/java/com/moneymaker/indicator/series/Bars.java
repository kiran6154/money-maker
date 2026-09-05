package com.moneymaker.indicator.series;

import com.moneymaker.entity.MarketData;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

/**
 * Shared plumbing for the series indicators in this package: primitive
 * extraction and session slicing.
 *
 * <h3>Why a series package exists alongside {@code com.moneymaker.indicator}</h3>
 * The older {@link com.moneymaker.indicator.Indicator} SPI is
 * {@code List<MarketData> -> Double}: one scalar for the whole series. That
 * shape is fine for an SMA, which is a pure function of the trailing window, and
 * it is wrong for three of the five indicators the Pressure strategy needs:
 *
 * <ul>
 *   <li><b>Supertrend</b> is path-dependent. Its direction at bar <i>i</i> is a
 *       function of the direction at bar <i>i-1</i>, so there is no way to
 *       answer "what is the direction now" without walking the whole chain from
 *       the start. A scalar SPI called once per bar would recompute that chain
 *       every time — O(n squared) — and, worse, would silently produce a
 *       different answer depending on how much history the caller happened to
 *       pass.</li>
 *   <li><b>ADX / +DI / -DI</b> are Wilder-smoothed, which is the same recurrence
 *       one level down.</li>
 *   <li><b>Session VWAP</b> is anchored: it resets at the session open and
 *       expands within the day, so it is defined per bar, not per series.</li>
 * </ul>
 *
 * <p>So these compute a {@code double[]} aligned index-for-index with the input
 * bars, once, and callers index into it. {@link SpotFeatures} does that once per
 * replayed day and every tick slices the result.</p>
 *
 * <h3>Nothing here touches the existing indicators</h3>
 * {@code SMAIndicatorImpl}, {@code EMAIndicatorImpl}, {@code RSIIndicatorImpl}
 * and {@code IndicatorFactory} are untouched by this package. In particular
 * {@link WilderRsi} here is a <i>new</i> implementation and deliberately does not
 * replace {@code RSIIndicatorImpl}, whose {@code calculate} returns a hardcoded
 * {@code 0.0}: that stub is registered in {@code IndicatorFactory} and changing
 * it would be a behaviour change for anything that resolves "RSI" through the
 * factory. Strategies 1-4 do not, but proving that is not this change's job.
 */
public final class Bars {

    private Bars() {
    }

    /** {@code NaN} is the "not computable yet" marker every series here uses. */
    public static final double NA = Double.NaN;

    public static boolean isNa(double v) {
        return Double.isNaN(v);
    }

    public static double[] closes(List<MarketData> bars) {
        double[] out = new double[bars.size()];
        for (int i = 0; i < bars.size(); i++) out[i] = d(bars.get(i).getClose());
        return out;
    }

    public static double[] highs(List<MarketData> bars) {
        double[] out = new double[bars.size()];
        for (int i = 0; i < bars.size(); i++) out[i] = d(bars.get(i).getHigh());
        return out;
    }

    public static double[] lows(List<MarketData> bars) {
        double[] out = new double[bars.size()];
        for (int i = 0; i < bars.size(); i++) out[i] = d(bars.get(i).getLow());
        return out;
    }

    /** Typical price {@code (H+L+C)/3}, the VWAP convention the spec names. */
    public static double[] typicalPrices(List<MarketData> bars) {
        double[] out = new double[bars.size()];
        for (int i = 0; i < bars.size(); i++) {
            MarketData b = bars.get(i);
            out[i] = (d(b.getHigh()) + d(b.getLow()) + d(b.getClose())) / 3d;
        }
        return out;
    }

    private static double d(BigDecimal v) {
        return v == null ? NA : v.doubleValue();
    }

    /**
     * The bars belonging to {@code date} whose time-of-day falls inside
     * {@code [open, close]} inclusive, in input order.
     *
     * <p><b>This filter is not optional for anything session-anchored.</b>
     * {@code historical_spot_candles} carries out-of-session rows — 09:05, 09:10
     * and 15:35 on most days, plus one stray evening session, 762 of them across
     * 2024. Taking "the first bar of the day" without filtering anchors the VWAP
     * and the opening range to 09:05 instead of 09:15, which shifts both by two
     * bars of pre-open price on nearly every day in the set.</p>
     */
    public static List<MarketData> session(List<MarketData> bars, LocalDate date,
                                           LocalTime open, LocalTime close) {
        List<MarketData> out = new ArrayList<>();
        if (bars == null) return out;
        for (MarketData b : bars) {
            if (b == null || b.getTimestamp() == null) continue;
            if (!b.getTimestamp().toLocalDate().equals(date)) continue;
            LocalTime t = b.getTimestamp().toLocalTime();
            if (t.isBefore(open) || t.isAfter(close)) continue;
            out.add(b);
        }
        return out;
    }

    /**
     * Index of the last bar at or before {@code atOrBefore}, or {@code -1}.
     * Assumes ascending timestamps, which is what every repository query in this
     * project orders by.
     */
    public static int indexAtOrBefore(List<MarketData> bars, java.time.LocalDateTime atOrBefore) {
        int found = -1;
        for (int i = 0; i < bars.size(); i++) {
            MarketData b = bars.get(i);
            if (b == null || b.getTimestamp() == null) continue;
            if (b.getTimestamp().isAfter(atOrBefore)) break;
            found = i;
        }
        return found;
    }
}
