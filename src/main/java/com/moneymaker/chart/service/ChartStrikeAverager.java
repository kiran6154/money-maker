package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.ChartCandleResponse;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeSet;

/**
 * Collapses several option legs into one synthetic candle series by averaging
 * their OHLC bar for bar.
 *
 * <p>Backs the dashboard's ATM±1 / ATM±2 panes: a single strike's premium is
 * noisy and jumps as the underlying walks across the strike grid, while the mean
 * of a ladder straddling the money moves with the underlying rather than with
 * which side of a strike it happens to be on. Averaging the ladder is also what
 * makes the pane symmetric in the money — for a CE the lower legs are ITM and
 * the upper OTM, for a PE the reverse — so one series reads the same either way.
 *
 * <h3>Every leg must be present, or the bar is dropped</h3>
 * A timestamp is emitted only when <b>all</b> legs have a candle for it. The
 * alternative — averaging whichever legs happen to be there — keeps the series
 * unbroken at the cost of making it mean something different from bar to bar:
 * the mean of five premiums sits well below the mean of the three innermost, so
 * a leg appearing or disappearing steps the whole level and drags an SMA through
 * it. That is a crossover the market never printed. A gap is honest; a step is
 * not.
 *
 * <p>Consequence worth knowing: an illiquid outer leg can shorten the series,
 * and a leg with no candles at all in the window yields nothing. Callers report
 * the legs that actually survived via
 * {@code MarketChartResponse.averagedStrikes} so the pane can name what it drew.
 *
 * <h3>The result is always a valid candle</h3>
 * Each leg satisfies {@code low <= open,close <= high}, and the mean preserves
 * every one of those inequalities, so the synthetic bar never renders inverted.
 *
 * <p>Source-agnostic on purpose: it takes candles, not strikes or tokens, so the
 * {@code TOKEN_BASED} and {@code HISTORICAL_ICICI} services share it rather than
 * growing an averaging pass each.
 */
@Service
public class ChartStrikeAverager {

    /** Matches the {@code precision = 12, scale = 4} the candle tables store. */
    private static final int PRICE_SCALE = 4;

    /**
     * @param legs one candle list per strike, in any order. Empty legs should be
     *             filtered out by the caller first — an empty leg here shares
     *             no timestamp with anything and would silently blank the whole
     *             series.
     * @return the averaged series, ascending by time, OHLC only. Overlays are
     *         left null for {@link ChartIndicatorService} to fill in after
     *         aggregation, exactly as for a single-strike series.
     */
    public List<ChartCandleResponse> average(Collection<List<ChartCandleResponse>> legs) {
        if (legs == null || legs.isEmpty()) {
            return List.of();
        }

        List<Map<OffsetDateTime, ChartCandleResponse>> byTime = new ArrayList<>(legs.size());
        for (List<ChartCandleResponse> leg : legs) {
            if (leg == null || leg.isEmpty()) {
                // One leg with nothing to contribute means no timestamp can have
                // a full set, so the whole series is empty. Say so directly
                // rather than letting the intersection below discover it.
                return List.of();
            }
            byTime.add(indexByTime(leg));
        }

        if (byTime.size() == 1) {
            return new ArrayList<>(byTime.get(0).values());
        }

        // Intersect on the smallest leg: the result can only ever contain
        // timestamps that leg already has, so walking a larger one first would
        // be wasted work on an illiquid outer strike.
        Map<OffsetDateTime, ChartCandleResponse> smallest = byTime.stream()
                .min((left, right) -> Integer.compare(left.size(), right.size()))
                .orElseThrow();

        List<ChartCandleResponse> out = new ArrayList<>(smallest.size());
        for (OffsetDateTime time : new TreeSet<>(smallest.keySet())) {
            ChartCandleResponse averaged = averageAt(time, byTime);
            if (averaged != null) {
                out.add(averaged);
            }
        }
        return out;
    }

    /**
     * One leg keyed by timestamp, ascending, last write winning on a duplicate.
     *
     * <p>Duplicates are not expected — the candle tables are natural-keyed on
     * (series, datetime) — but a duplicate must not be allowed to look like two
     * legs agreeing, which is what a plain count of matching rows would have
     * made it.
     */
    private Map<OffsetDateTime, ChartCandleResponse> indexByTime(List<ChartCandleResponse> leg) {
        Map<OffsetDateTime, ChartCandleResponse> map = new LinkedHashMap<>();
        leg.stream()
                .filter(Objects::nonNull)
                .filter(candle -> candle.getTime() != null)
                .sorted(java.util.Comparator.comparing(ChartCandleResponse::getTime))
                .forEach(candle -> map.put(candle.getTime(), candle));
        return map;
    }

    /** The averaged bar at {@code time}, or null if any leg is missing or partial. */
    private ChartCandleResponse averageAt(OffsetDateTime time,
                                          List<Map<OffsetDateTime, ChartCandleResponse>> byTime) {
        BigDecimal open = BigDecimal.ZERO;
        BigDecimal high = BigDecimal.ZERO;
        BigDecimal low = BigDecimal.ZERO;
        BigDecimal close = BigDecimal.ZERO;

        for (Map<OffsetDateTime, ChartCandleResponse> leg : byTime) {
            ChartCandleResponse candle = leg.get(time);
            if (candle == null
                    || candle.getOpen() == null || candle.getHigh() == null
                    || candle.getLow() == null || candle.getClose() == null) {
                return null;
            }
            open = open.add(candle.getOpen());
            high = high.add(candle.getHigh());
            low = low.add(candle.getLow());
            close = close.add(candle.getClose());
        }

        BigDecimal legCount = BigDecimal.valueOf(byTime.size());
        return ChartCandleResponse.ohlc(
                time,
                divide(open, legCount),
                divide(high, legCount),
                divide(low, legCount),
                divide(close, legCount)
        );
    }

    private BigDecimal divide(BigDecimal total, BigDecimal legCount) {
        return total.divide(legCount, PRICE_SCALE, RoundingMode.HALF_UP);
    }
}
