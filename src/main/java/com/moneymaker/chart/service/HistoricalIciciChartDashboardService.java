package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.ChartCandleResponse;
import com.moneymaker.chart.dto.ChartType;
import com.moneymaker.chart.dto.IndexSymbol;
import com.moneymaker.chart.dto.MarketChartRequest;
import com.moneymaker.chart.dto.MarketChartResponse;
import com.moneymaker.entity.HistoricalOptionCandle;
import com.moneymaker.entity.HistoricalSpotCandle;
import com.moneymaker.repository.HistoricalOptionCandleRepository;
import com.moneymaker.repository.HistoricalSpotCandleRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Deque;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class HistoricalIciciChartDashboardService {

    private static final String SPOT_EXCHANGE = "NSE";
    private static final String OPTION_EXCHANGE = "NFO";
    private static final LocalTime MARKET_OPEN = LocalTime.of(9, 15);
    private static final LocalTime MARKET_CLOSE = LocalTime.of(23, 59, 59);
    private static final ZoneId INDIA_ZONE = ZoneId.of("Asia/Kolkata");
    private static final int MAX_SMA_PERIOD = 500;
    private static final int LOOKBACK_BUFFER_CANDLES = 96;

    private final HistoricalSpotCandleRepository spotCandleRepository;
    private final HistoricalOptionCandleRepository optionCandleRepository;
    private final ChartTimeframeAggregator chartTimeframeAggregator;

    public MarketChartResponse getMarketChartData(MarketChartRequest request) {
        return switch (request.getChartType()) {
            case UNDERLYING -> getUnderlyingChart(request);
            case CE, PE -> getOptionChart(request);
        };
    }

    private MarketChartResponse getUnderlyingChart(MarketChartRequest request) {
        List<ChartCandleResponse> candles = fetchSpotCandlesWithRuntimeSma(
                request.getIndexSymbol(),
                request.getDate()
        );
        List<ChartCandleResponse> data = chartTimeframeAggregator.aggregate(candles, request.getTimeframe());
        return buildResponse(request, null, null, data);
    }

    private MarketChartResponse getOptionChart(MarketChartRequest request) {
        List<ChartCandleResponse> spotCandles = fetchSpotCandlesWithRuntimeSma(
                request.getIndexSymbol(),
                request.getDate()
        );
        if (spotCandles.isEmpty()) {
            return buildResponse(request, null, null, List.of());
        }

        BigDecimal referencePrice = resolveReferencePrice(spotCandles);
        if (referencePrice == null) {
            return buildResponse(request, null, null, List.of());
        }

        BigDecimal atmStrike = calculateAtmStrike(request.getIndexSymbol(), referencePrice);
        Optional<LocalDate> expiryDate = resolveExpiryDate(request.getIndexSymbol(), request.getDate());
        if (expiryDate.isEmpty()) {
            return buildResponse(request, null, atmStrike, List.of());
        }

        List<ChartCandleResponse> optionCandles = fetchOptionCandlesWithRuntimeSma(
                request.getIndexSymbol(),
                expiryDate.get(),
                atmStrike,
                request.getChartType(),
                request.getDate()
        );
        List<ChartCandleResponse> data = chartTimeframeAggregator.aggregate(optionCandles, request.getTimeframe());
        return buildResponse(request, expiryDate.get(), atmStrike, data);
    }

    private List<ChartCandleResponse> fetchSpotCandlesWithRuntimeSma(IndexSymbol indexSymbol, LocalDate tradingDate) {
        LocalDateTime dayEnd = tradingDate.atTime(MARKET_CLOSE);
        List<HistoricalSpotCandle> recentCandles = spotCandleRepository.findRecentCandlesUpTo(
                indexSymbol.name(),
                SPOT_EXCHANGE,
                dayEnd,
                PageRequest.of(0, MAX_SMA_PERIOD + LOOKBACK_BUFFER_CANDLES)
        );

        List<ChartCandleResponse> chronological = recentCandles.stream()
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(HistoricalSpotCandle::getDateTime))
                .map(this::toChartCandle)
                .toList();

        return applyRuntimeSma(chronological).stream()
                .filter(candle -> candle.getTime() != null
                        && tradingDate.equals(candle.getTime().toLocalDate()))
                .toList();
    }

    private List<ChartCandleResponse> fetchOptionCandlesWithRuntimeSma(IndexSymbol indexSymbol,
                                                                       LocalDate expiryDate,
                                                                       BigDecimal strikePrice,
                                                                       ChartType chartType,
                                                                       LocalDate tradingDate) {
        LocalDateTime dayEnd = tradingDate.atTime(MARKET_CLOSE);
        List<HistoricalOptionCandle> recentCandles = optionCandleRepository.findRecentCandlesUpTo(
                indexSymbol.name(),
                OPTION_EXCHANGE,
                expiryDate,
                strikePrice,
                chartType.name(),
                dayEnd,
                PageRequest.of(0, MAX_SMA_PERIOD + LOOKBACK_BUFFER_CANDLES)
        );

        List<ChartCandleResponse> chronological = recentCandles.stream()
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(HistoricalOptionCandle::getDateTime))
                .map(this::toChartCandle)
                .toList();

        return applyRuntimeSma(chronological).stream()
                .filter(candle -> candle.getTime() != null
                        && tradingDate.equals(candle.getTime().toLocalDate()))
                .toList();
    }

    private Optional<LocalDate> resolveExpiryDate(IndexSymbol indexSymbol, LocalDate selectedDate) {
        return optionCandleRepository.findAvailableExpiriesOnOrAfter(
                        indexSymbol.name(),
                        OPTION_EXCHANGE,
                        selectedDate
                )
                .stream()
                .findFirst();
    }

    private ChartCandleResponse toChartCandle(HistoricalSpotCandle candle) {
        return new ChartCandleResponse(
                candle.getDateTime().atZone(INDIA_ZONE).toOffsetDateTime(),
                candle.getOpen(),
                candle.getHigh(),
                candle.getLow(),
                candle.getClose(),
                null,
                null,
                null,
                null,
                null
        );
    }

    private ChartCandleResponse toChartCandle(HistoricalOptionCandle candle) {
        return new ChartCandleResponse(
                candle.getDateTime().atZone(INDIA_ZONE).toOffsetDateTime(),
                candle.getOpen(),
                candle.getHigh(),
                candle.getLow(),
                candle.getClose(),
                null,
                null,
                null,
                null,
                null
        );
    }

    private BigDecimal resolveReferencePrice(List<ChartCandleResponse> sortedCandles) {
        return sortedCandles.stream()
                .filter(candle -> candle.getTime() != null
                        && candle.getClose() != null
                        && !candle.getTime().toLocalTime().isBefore(MARKET_OPEN))
                .map(ChartCandleResponse::getClose)
                .findFirst()
                .orElseGet(() -> sortedCandles.stream()
                        .map(ChartCandleResponse::getClose)
                        .filter(Objects::nonNull)
                        .findFirst()
                        .orElse(null));
    }

    private BigDecimal calculateAtmStrike(IndexSymbol indexSymbol, BigDecimal referencePrice) {
        int step = switch (indexSymbol) {
            case NIFTY -> 50;
            case BANKNIFTY -> 100;
        };

        return BigDecimal.valueOf(Math.round(referencePrice.doubleValue() / step) * step);
    }

    private List<ChartCandleResponse> applyRuntimeSma(List<ChartCandleResponse> candles) {
        if (candles.isEmpty()) {
            return List.of();
        }

        RollingSma rolling20 = new RollingSma(20);
        RollingSma rolling50 = new RollingSma(50);
        RollingSma rolling100 = new RollingSma(100);
        RollingSma rolling200 = new RollingSma(200);
        RollingSma rolling500 = new RollingSma(500);

        List<ChartCandleResponse> out = new ArrayList<>(candles.size());
        for (ChartCandleResponse candle : candles) {
            BigDecimal close = candle.getClose();
            out.add(new ChartCandleResponse(
                    candle.getTime(),
                    candle.getOpen(),
                    candle.getHigh(),
                    candle.getLow(),
                    candle.getClose(),
                    rolling20.add(close),
                    rolling50.add(close),
                    rolling100.add(close),
                    rolling200.add(close),
                    rolling500.add(close)
            ));
        }
        return out;
    }

    private MarketChartResponse buildResponse(MarketChartRequest request,
                                              LocalDate expiryDate,
                                              BigDecimal atmStrike,
                                              List<ChartCandleResponse> data) {
        return new MarketChartResponse(
                request.getIndexSymbol(),
                request.getChartType(),
                request.getTimeframe(),
                request.getDate(),
                expiryDate,
                atmStrike,
                data
        );
    }

    private static final class RollingSma {
        private final int period;
        private final Deque<BigDecimal> window = new ArrayDeque<>();
        private BigDecimal sum = BigDecimal.ZERO;

        private RollingSma(int period) {
            this.period = period;
        }

        private BigDecimal add(BigDecimal value) {
            if (value == null) {
                return window.size() >= period
                        ? sum.divide(BigDecimal.valueOf(period), 4, RoundingMode.HALF_UP)
                        : null;
            }

            window.addLast(value);
            sum = sum.add(value);

            if (window.size() > period) {
                sum = sum.subtract(window.removeFirst());
            }

            if (window.size() < period) {
                return null;
            }

            return sum.divide(BigDecimal.valueOf(period), 4, RoundingMode.HALF_UP);
        }
    }
}
