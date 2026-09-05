package com.moneymaker.indicator.series;

import com.moneymaker.entity.MarketData;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Map;

/**
 * Every spot-derived input the Pressure strategy needs, computed once for one
 * trading day and then read by timestamp.
 *
 * <h3>Two different windows, deliberately</h3>
 * <ul>
 *   <li><b>RSI, Supertrend and ADX</b> are computed over the <i>warmup</i>
 *       series — the day being traded plus several sessions before it. All three
 *       are Wilder recurrences with unbounded memory (see {@link WilderRsi} and
 *       {@link Supertrend}), so restarting them at 09:15 would hand the first
 *       hour of every session a value that is still converging. On a 5-minute
 *       series a 14-period Wilder indicator needs well past midday to settle
 *       from a cold start, which would make the morning's pressure scores
 *       systematically different from the afternoon's for no reason a trader
 *       would recognise.</li>
 *   <li><b>VWAP and the opening range</b> are computed over the <i>session</i>
 *       series alone, because both are anchored to today's open by definition.
 *       Carrying them across days would be simply wrong.</li>
 * </ul>
 *
 * <h3>Computed once per day, not once per tick</h3>
 * The backtest replays ~73 ticks per day and every one of them would otherwise
 * re-walk the whole warmup series for three path-dependent indicators. Building
 * this object once at the day's first use and indexing into it thereafter is
 * what keeps the Pressure run in the same time envelope as the existing SMA
 * strategies. {@link #at(LocalDateTime)} is a lookup, not a computation.
 *
 * <h3>No lookahead</h3>
 * {@link #at(LocalDateTime)} resolves the last bar at or <i>before</i> the
 * requested moment and reads the arrays at that index only. Nothing in this
 * class can return a value derived from a bar the caller has not reached, and
 * the opening range additionally refuses to report at all until its window has
 * closed ({@link OpeningRange#isComplete()}).
 */
public final class SpotFeatures {

    /** One bar's worth of spot state. {@link Bars#NA} where not yet computable. */
    public record Snapshot(
            LocalDateTime timestamp,
            double close,
            double rsi,
            double anchorPrice,
            int supertrendDirection,
            double adx,
            double plusDi,
            double minusDi,
            double plusDi3BarsAgo,
            double minusDi3BarsAgo,
            double openingRangeHigh,
            double openingRangeLow,
            boolean openingRangeComplete) {
    }

    private final List<MarketData> warmup;
    private final double[] rsi;
    private final int[] stDir;
    private final double[] adx;
    private final double[] plusDi;
    private final double[] minusDi;

    private final List<MarketData> session;
    private final double[] anchorPrice;
    private final OpeningRange openingRange;

    /** Warmup index of each session bar, so one lookup serves both series. */
    private final Map<LocalDateTime, Integer> warmupIndexByTime;
    private final Map<LocalDateTime, Integer> sessionIndexByTime;

    /** Bars back for the DI-fading comparison. Fixed by the strategy spec. */
    private static final int DI_LOOKBACK_BARS = 3;

    private SpotFeatures(List<MarketData> warmup, double[] rsi, int[] stDir,
                         DirectionalIndex.Result di,
                         List<MarketData> session, double[] anchorPrice, OpeningRange openingRange) {
        this.warmup = warmup;
        this.rsi = rsi;
        this.stDir = stDir;
        this.adx = di.adx();
        this.plusDi = di.plusDi();
        this.minusDi = di.minusDi();
        this.session = session;
        this.anchorPrice = anchorPrice;
        this.openingRange = openingRange;
        this.warmupIndexByTime = indexByTime(warmup);
        this.sessionIndexByTime = indexByTime(session);
    }

    private static Map<LocalDateTime, Integer> indexByTime(List<MarketData> bars) {
        Map<LocalDateTime, Integer> m = new java.util.HashMap<>();
        for (int i = 0; i < bars.size(); i++) {
            MarketData b = bars.get(i);
            if (b != null && b.getTimestamp() != null) m.put(b.getTimestamp(), i);
        }
        return m;
    }

    /**
     * @param allBars        spot bars spanning the warmup window AND the day, ascending
     * @param date           the session being traded
     * @param sessionOpen    session open (09:15)
     * @param sessionClose   session close (15:30)
     * @param orWindowEnd    opening-range window end, inclusive (09:30)
     * @param volumeWeightByBar per-bar weight, or null for the reference
     *                          unweighted mean; see {@link SessionAnchoredPrice}
     * @param rsiPeriod      14
     * @param atrPeriod      10
     * @param stMultiplier   3
     * @param adxPeriod      14
     */
    public static SpotFeatures build(List<MarketData> allBars,
                                     LocalDate date,
                                     LocalTime sessionOpen,
                                     LocalTime sessionClose,
                                     LocalTime orWindowEnd,
                                     Map<LocalDateTime, Double> volumeWeightByBar,
                                     int rsiPeriod, int atrPeriod, double stMultiplier, int adxPeriod) {

        // The warmup series is session-filtered too, across every day it spans.
        // historical_spot_candles carries 09:05 / 09:10 / 15:35 rows and a stray
        // evening session; leaving them in would feed the Wilder recurrences
        // bars that no trading decision could ever be taken on, and would put a
        // pre-open gap inside every true range.
        List<MarketData> warmup = new java.util.ArrayList<>();
        for (MarketData b : allBars) {
            if (b == null || b.getTimestamp() == null) continue;
            if (b.getTimestamp().toLocalDate().isAfter(date)) continue;
            LocalTime t = b.getTimestamp().toLocalTime();
            if (t.isBefore(sessionOpen) || t.isAfter(sessionClose)) continue;
            warmup.add(b);
        }

        double[] closes = Bars.closes(warmup);
        double[] highs = Bars.highs(warmup);
        double[] lows = Bars.lows(warmup);

        double[] rsi = WilderRsi.compute(closes, rsiPeriod);
        int[] stDir = Supertrend.direction(highs, lows, closes, atrPeriod, stMultiplier);
        DirectionalIndex.Result di = DirectionalIndex.compute(highs, lows, closes, adxPeriod);

        List<MarketData> session = Bars.session(warmup, date, sessionOpen, sessionClose);
        double[] tp = Bars.typicalPrices(session);
        double[] weights = new double[session.size()];
        for (int i = 0; i < session.size(); i++) {
            LocalDateTime ts = session.get(i).getTimestamp();
            Double w = volumeWeightByBar == null ? null : volumeWeightByBar.get(ts);
            weights[i] = w == null ? 0d : w;
        }
        double[] anchorPrice = SessionAnchoredPrice.compute(tp, weights);
        OpeningRange or = OpeningRange.of(session, sessionOpen, orWindowEnd);

        return new SpotFeatures(warmup, rsi, stDir, di, session, anchorPrice, or);
    }

    /**
     * State as of the last bar at or before {@code asOf}, or {@code null} when
     * that moment precedes the first session bar.
     *
     * <p>Resolved by exact-timestamp lookup first (the common case — the replay
     * ticks on bar boundaries) and by scan otherwise, so a tick that lands
     * between bars still reads the last <i>settled</i> bar rather than the next
     * one.</p>
     */
    public Snapshot at(LocalDateTime asOf) {
        Integer si = sessionIndexByTime.get(asOf);
        int sessionIdx = si != null ? si : Bars.indexAtOrBefore(session, asOf);
        if (sessionIdx < 0) return null;

        MarketData bar = session.get(sessionIdx);
        Integer wi = warmupIndexByTime.get(bar.getTimestamp());
        int warmupIdx = wi != null ? wi : Bars.indexAtOrBefore(warmup, bar.getTimestamp());
        if (warmupIdx < 0) return null;

        int back = warmupIdx - DI_LOOKBACK_BARS;
        double plus3 = back >= 0 ? plusDi[back] : Bars.NA;
        double minus3 = back >= 0 ? minusDi[back] : Bars.NA;

        return new Snapshot(
                bar.getTimestamp(),
                bar.getClose() == null ? Bars.NA : bar.getClose().doubleValue(),
                rsi[warmupIdx],
                anchorPrice[sessionIdx],
                stDir[warmupIdx],
                adx[warmupIdx],
                plusDi[warmupIdx],
                minusDi[warmupIdx],
                plus3,
                minus3,
                openingRange.high(),
                openingRange.low(),
                openingRange.isComplete());
    }

    /** Session bar count — used only for logging and tests. */
    public int sessionBarCount() {
        return session.size();
    }

    /** Warmup bar count — used only for logging and tests. */
    public int warmupBarCount() {
        return warmup.size();
    }
}
