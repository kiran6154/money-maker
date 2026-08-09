package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.ChartCandleResponse;
import com.moneymaker.chart.dto.ChartTimeframe;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Objects;

/**
 * Aggregates 5-minute base candles into the chart timeframes required by the
 * dashboard.
 *
 * <p>Rules:
 * <ul>
 *   <li>5m  â†’ returned as-is after ascending sort</li>
 *   <li>10m â†’ consecutive 2-candle buckets from sorted 5m input</li>
 *   <li>15m â†’ consecutive 3-candle buckets from sorted 5m input</li>
 * </ul>
 *
 * <p>The input list is never mutated. Aggregated SMA values are <b>not</b>
 * recalculated; the bucket keeps the last non-null source value for each SMA.
 */
@Service
public class ChartTimeframeAggregator {

    public List<ChartCandleResponse> aggregate(List<ChartCandleResponse> rawCandles,
                                               ChartTimeframe timeframe) {
        if (rawCandles == null || rawCandles.isEmpty() || timeframe == null) {
            return List.of();
        }

        List<ChartCandleResponse> sorted = rawCandles.stream()
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(ChartCandleResponse::getTime))
                .toList();

        if (sorted.isEmpty()) {
            return List.of();
        }

        return switch (timeframe) {
            case FIVE_MINUTES -> new ArrayList<>(sorted);
            case TEN_MINUTES -> aggregateBuckets(sorted, 2);
            case FIFTEEN_MINUTES -> aggregateBuckets(sorted, 3);
        };
    }

    private List<ChartCandleResponse> aggregateBuckets(List<ChartCandleResponse> sorted, int bucketSize) {
        List<ChartCandleResponse> out = new ArrayList<>();
        for (int i = 0; i < sorted.size(); i += bucketSize) {
            int endExclusive = Math.min(i + bucketSize, sorted.size());
            List<ChartCandleResponse> bucket = sorted.subList(i, endExclusive);
            out.add(aggregateBucket(bucket));
        }
        return out;
    }

    private ChartCandleResponse aggregateBucket(List<ChartCandleResponse> bucket) {
        ChartCandleResponse first = bucket.get(0);
        ChartCandleResponse last = bucket.get(bucket.size() - 1);

        BigDecimal high = null;
        BigDecimal low = null;
        BigDecimal sma20 = null;
        BigDecimal sma50 = null;
        BigDecimal sma100 = null;
        BigDecimal sma200 = null;
        BigDecimal sma500 = null;

        for (ChartCandleResponse candle : bucket) {
            high = max(high, candle.getHigh());
            low = min(low, candle.getLow());

            sma20 = lastNonNull(sma20, candle.getSma20());
            sma50 = lastNonNull(sma50, candle.getSma50());
            sma100 = lastNonNull(sma100, candle.getSma100());
            sma200 = lastNonNull(sma200, candle.getSma200());
            sma500 = lastNonNull(sma500, candle.getSma500());
        }

        return new ChartCandleResponse(
                first.getTime(),
                first.getOpen(),
                high,
                low,
                last.getClose(),
                sma20,
                sma50,
                sma100,
                sma200,
                sma500
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

    private BigDecimal lastNonNull(BigDecimal current, BigDecimal candidate) {
        return candidate != null ? candidate : current;
    }
}
