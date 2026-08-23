package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.ChartCandleResponse;
import com.moneymaker.chart.dto.ChartTimeframe;
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
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.Comparator;
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
    private final ChartIndicatorService chartIndicatorService;

    public MarketChartResponse getMarketChartData(MarketChartRequest request) {
        return switch (request.getChartType()) {
            case UNDERLYING -> getUnderlyingChart(request);
            case CE, PE -> getOptionChart(request);
        };
    }

    private MarketChartResponse getUnderlyingChart(MarketChartRequest request) {
        List<ChartCandleResponse> data = finish(
                fetchSpotCandles(request.getIndexSymbol(), request.getDate()),
                request.getTimeframe(),
                request.getDate()
        );
        return buildResponse(request, null, null, data);
    }

    private MarketChartResponse getOptionChart(MarketChartRequest request) {
        // ATM is resolved off the *selected day's* spot candles, so this one is
        // filtered to the day without needing indicators.
        List<ChartCandleResponse> spotCandles = onSelectedDate(
                fetchSpotCandles(request.getIndexSymbol(), request.getDate()),
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

        List<ChartCandleResponse> data = finish(
                fetchOptionCandles(
                        request.getIndexSymbol(),
                        expiryDate.get(),
                        atmStrike,
                        request.getChartType(),
                        request.getDate()),
                request.getTimeframe(),
                request.getDate()
        );
        return buildResponse(request, expiryDate.get(), atmStrike, data);
    }

    /**
     * Aggregate to the requested timeframe, compute overlays on that series, then
     * trim to the visible day. Order matters: indicators must see the lookback
     * candles to warm up, and must be computed on the bars actually drawn.
     */
    private List<ChartCandleResponse> finish(List<ChartCandleResponse> lookbackCandles,
                                             ChartTimeframe timeframe,
                                             LocalDate tradingDate) {
        List<ChartCandleResponse> aggregated =
                chartTimeframeAggregator.aggregate(lookbackCandles, timeframe);
        chartIndicatorService.applyIndicators(aggregated);
        return onSelectedDate(aggregated, tradingDate);
    }

    private List<ChartCandleResponse> onSelectedDate(List<ChartCandleResponse> candles, LocalDate tradingDate) {
        return candles.stream()
                .filter(candle -> candle.getTime() != null
                        && tradingDate.equals(candle.getTime().toLocalDate()))
                .toList();
    }

    /** Full lookback window, ascending, OHLC only. */
    private List<ChartCandleResponse> fetchSpotCandles(IndexSymbol indexSymbol, LocalDate tradingDate) {
        LocalDateTime dayEnd = tradingDate.atTime(MARKET_CLOSE);
        List<HistoricalSpotCandle> recentCandles = spotCandleRepository.findRecentCandlesUpTo(
                indexSymbol.name(),
                SPOT_EXCHANGE,
                dayEnd,
                PageRequest.of(0, MAX_SMA_PERIOD + LOOKBACK_BUFFER_CANDLES)
        );

        return recentCandles.stream()
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(HistoricalSpotCandle::getDateTime))
                .map(this::toChartCandle)
                .toList();
    }

    /** Full lookback window, ascending, OHLC only. */
    private List<ChartCandleResponse> fetchOptionCandles(IndexSymbol indexSymbol,
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

        return recentCandles.stream()
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(HistoricalOptionCandle::getDateTime))
                .map(this::toChartCandle)
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
        return ChartCandleResponse.ohlc(
                candle.getDateTime().atZone(INDIA_ZONE).toOffsetDateTime(),
                candle.getOpen(),
                candle.getHigh(),
                candle.getLow(),
                candle.getClose()
        );
    }

    private ChartCandleResponse toChartCandle(HistoricalOptionCandle candle) {
        return ChartCandleResponse.ohlc(
                candle.getDateTime().atZone(INDIA_ZONE).toOffsetDateTime(),
                candle.getOpen(),
                candle.getHigh(),
                candle.getLow(),
                candle.getClose()
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

}
