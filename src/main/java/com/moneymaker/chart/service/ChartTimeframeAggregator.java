package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.ChartCandleResponse;
import com.moneymaker.chart.dto.ChartTimeframe;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;

/**
 * Aggregates 5-minute base candles into the chart timeframes the dashboard offers.
 *
 * <p>Rules:
 * <ul>
 *   <li>5m  → returned as-is after ascending sort</li>
 *   <li>10m → 10-minute buckets anchored on the session open</li>
 *   <li>15m → 15-minute buckets anchored on the session open</li>
 * </ul>
 *
 * <p>Buckets are keyed on <em>(trading date, elapsed minutes since the session
 * open)</em> rather than on list position. Position-based chunking breaks as soon
 * as the input spans more than one day — an NSE session is 75 five-minute
 * candles, which is not divisible by 2, so 10-minute buckets would drift and
 * eventually merge one day's last candle with the next day's first. It also
 * shifts every later bar whenever an illiquid option series has a gap. Anchoring
 * on the open additionally puts boundaries where a broker puts them (09:15,
 * 09:30, … for 15-minute bars).
 *
 * <p>The input list is never mutated, and no indicator values are read or
 * carried: overlays are computed <b>after</b> aggregation by
 * {@link ChartIndicatorService}, on the series actually drawn.
 */
@Service
public class ChartTimeframeAggregator {

    /** Session open used as the bucket anchor. */
    private static final LocalTime MARKET_OPEN = LocalTime.of(9, 15);

    public List<ChartCandleResponse> aggregate(List<ChartCandleResponse> rawCandles,
                                               ChartTimeframe timeframe) {
        if (rawCandles == null || rawCandles.isEmpty() || timeframe == null) {
            return List.of();
        }

        List<ChartCandleResponse> sorted = rawCandles.stream()
                .filter(Objects::nonNull)
                .filter(candle -> candle.getTime() != null)
                .sorted(Comparator.comparing(ChartCandleResponse::getTime))
                .toList();

        if (sorted.isEmpty()) {
            return List.of();
        }

        return switch (timeframe) {
            case FIVE_MINUTES -> new ArrayList<>(sorted);
            case TEN_MINUTES -> aggregateBuckets(sorted, 10);
            case FIFTEEN_MINUTES -> aggregateBuckets(sorted, 15);
        };
    }

    private List<ChartCandleResponse> aggregateBuckets(List<ChartCandleResponse> sorted, int intervalMinutes) {
        int openMinute = MARKET_OPEN.getHour() * 60 + MARKET_OPEN.getMinute();

        List<ChartCandleResponse> out = new ArrayList<>();
        List<ChartCandleResponse> bucket = new ArrayList<>();
        LocalDate bucketDate = null;
        long bucketIndex = Long.MIN_VALUE;

        for (ChartCandleResponse candle : sorted) {
            OffsetDateTime time = candle.getTime();
            LocalDate date = time.toLocalDate();
            int minuteOfDay = time.getHour() * 60 + time.getMinute();
            long index = Math.floorDiv(minuteOfDay - openMinute, intervalMinutes);

            if (!date.equals(bucketDate) || index != bucketIndex) {
                if (!bucket.isEmpty()) {
                    out.add(aggregateBucket(bucket));
                    bucket = new ArrayList<>();
                }
                bucketDate = date;
                bucketIndex = index;
            }
            bucket.add(candle);
        }

        if (!bucket.isEmpty()) {
            out.add(aggregateBucket(bucket));
        }
        return out;
    }

    private ChartCandleResponse aggregateBucket(List<ChartCandleResponse> bucket) {
        ChartCandleResponse first = bucket.get(0);
        ChartCandleResponse last = bucket.get(bucket.size() - 1);

        BigDecimal high = null;
        BigDecimal low = null;
        for (ChartCandleResponse candle : bucket) {
            high = max(high, candle.getHigh());
            low = min(low, candle.getLow());
        }

        return ChartCandleResponse.ohlc(
                first.getTime(),
                first.getOpen(),
                high,
                low,
                last.getClose()
        );
    }

    private BigDecimal max(BigDecimal left, BigDecimal right) {
        if (left == null) return right;
        if (right == null) return left;
        return left.max(right);
    }

    private BigDecimal min(BigDecimal left, BigDecimal right) {
        if (left == null) return right;
        if (right == null) return left;
        return left.min(right);
    }
}
