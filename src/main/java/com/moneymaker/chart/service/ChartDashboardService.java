package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.ChartCandleResponse;
import com.moneymaker.chart.dto.ChartDataSource;
import com.moneymaker.chart.dto.ChartTimeframe;
import com.moneymaker.chart.dto.ChartType;
import com.moneymaker.chart.dto.IndexSymbol;
import com.moneymaker.chart.dto.MarketChartRequest;
import com.moneymaker.chart.dto.MarketChartResponse;
import com.moneymaker.chart.dto.StrikeOptionsResponse;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.MarketData;
import com.moneymaker.repository.InstrumentDetailsRepository;
import com.moneymaker.repository.InstrumentRepository;
import com.moneymaker.repository.MarketDataRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
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
import java.util.Set;

@Slf4j
@Service
@RequiredArgsConstructor
public class ChartDashboardService {

    private static final Set<Integer> SUPPORTED_SMA_PERIODS = Set.of(20, 50, 100, 200, 500);
    private static final LocalTime MARKET_OPEN = LocalTime.of(9, 15);
    private static final LocalTime MARKET_CLOSE = LocalTime.of(23, 59, 59);
    private static final ZoneId INDIA_ZONE = ZoneId.of("Asia/Kolkata");
    private static final int MAX_SMA_PERIOD = 500;
    private static final int LOOKBACK_BUFFER_CANDLES = 96;

    private final MarketDataRepository marketDataRepository;
    private final InstrumentRepository instrumentRepository;
    private final InstrumentDetailsRepository instrumentDetailsRepository;
    private final ChartExpiryResolver chartExpiryResolver;
    private final ChartTimeframeAggregator chartTimeframeAggregator;
    private final ChartIndicatorService chartIndicatorService;
    private final HistoricalIciciChartDashboardService historicalIciciChartDashboardService;

    public MarketChartResponse getMarketChartData(MarketChartRequest request) {
        validateRequest(request);
        if (request.getDataSource() == ChartDataSource.HISTORICAL_ICICI) {
            return historicalIciciChartDashboardService.getMarketChartData(request);
        }

        return switch (request.getChartType()) {
            case UNDERLYING -> getUnderlyingChart(request);
            case CE, PE -> getOptionChart(request);
        };
    }

    private MarketChartResponse getUnderlyingChart(MarketChartRequest request) {
        Optional<Instrument> instrument = resolveUnderlyingInstrument(request.getIndexSymbol());
        if (instrument.isEmpty() || instrument.get().getInsId() == null || instrument.get().getInsId().isBlank()) {
            return emptyResponse(request, null, null);
        }

        List<ChartCandleResponse> data = finish(
                fetchIntradayCandles(instrument.get().getInsId(), request.getDate()),
                request.getTimeframe(),
                request.getDate()
        );
        return buildResponse(request, null, null, data);
    }

    private MarketChartResponse getOptionChart(MarketChartRequest request) {
        Optional<Instrument> instrument = resolveUnderlyingInstrument(request.getIndexSymbol());
        if (instrument.isEmpty() || instrument.get().getInsId() == null || instrument.get().getInsId().isBlank()) {
            return emptyResponse(request, null, null);
        }

        // ATM is resolved off the selected day's underlying candles; no overlays needed.
        List<ChartCandleResponse> underlyingRaw = onSelectedDate(
                fetchIntradayCandles(instrument.get().getInsId(), request.getDate()),
                request.getDate()
        );
        if (underlyingRaw.isEmpty()) {
            return emptyResponse(request, null, null);
        }

        BigDecimal referencePrice = resolveReferencePrice(underlyingRaw);
        if (referencePrice == null) {
            return emptyResponse(request, null, null);
        }

        // An explicitly picked strike wins; otherwise fall back to ATM.
        BigDecimal atmStrike = calculateAtmStrike(request.getIndexSymbol(), referencePrice);
        BigDecimal strike = request.getStrike() != null ? request.getStrike() : atmStrike;
        Optional<LocalDate> expiryDate = chartExpiryResolver.resolve(request.getDate(), request.getIndexSymbol());
        if (expiryDate.isEmpty()) {
            return emptyResponse(request, null, strike);
        }

        String optionType = request.getChartType().name();
        Optional<InstrumentDetails> optionInstrument = instrumentDetailsRepository.findFirstByCriteria(
                request.getIndexSymbol().name(),
                expiryDate.get().toString(),
                strike,
                optionType
        );

        if (optionInstrument.isEmpty() || optionInstrument.get().getInstrumentToken() == null) {
            return emptyResponse(request, expiryDate.get(), strike);
        }

        List<ChartCandleResponse> data = finish(
                fetchIntradayCandles(optionInstrument.get().getInstrumentToken().toString(), request.getDate()),
                request.getTimeframe(),
                request.getDate()
        );
        return buildResponse(request, expiryDate.get(), strike, data);
    }

    /**
     * Strikes the picker can offer, for whichever data source is selected.
     * Routed here so the frontend has a single endpoint regardless of source.
     */
    public StrikeOptionsResponse getStrikeOptions(IndexSymbol indexSymbol,
                                                  LocalDate date,
                                                  ChartType chartType,
                                                  ChartDataSource dataSource) {
        if (dataSource == ChartDataSource.HISTORICAL_ICICI) {
            return historicalIciciChartDashboardService.getStrikeOptions(indexSymbol, date, chartType);
        }

        Optional<LocalDate> expiryDate = chartExpiryResolver.resolve(date, indexSymbol);
        if (expiryDate.isEmpty()) {
            return new StrikeOptionsResponse(null, null, List.of());
        }

        Optional<Instrument> instrument = resolveUnderlyingInstrument(indexSymbol);
        BigDecimal atmStrike = null;
        if (instrument.isPresent() && instrument.get().getInsId() != null && !instrument.get().getInsId().isBlank()) {
            List<ChartCandleResponse> underlying =
                    onSelectedDate(fetchIntradayCandles(instrument.get().getInsId(), date), date);
            BigDecimal referencePrice = underlying.isEmpty() ? null : resolveReferencePrice(underlying);
            atmStrike = referencePrice == null ? null : calculateAtmStrike(indexSymbol, referencePrice);
        }

        String optionType = (chartType == null || chartType == ChartType.UNDERLYING)
                ? ChartType.CE.name()
                : chartType.name();

        List<BigDecimal> strikes = instrumentDetailsRepository.findAvailableStrikes(
                indexSymbol.name(), expiryDate.get().toString(), optionType);

        return new StrikeOptionsResponse(expiryDate.get(), atmStrike, strikes);
    }

    /**
     * Aggregate to the requested timeframe, compute overlays on that series, then
     * trim to the visible day. Indicators need the lookback candles to warm up,
     * and must be computed on the bars actually drawn.
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

    private void validateRequest(MarketChartRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("request payload missing");
        }
        if (request.getDate() == null) {
            throw new IllegalArgumentException("date is required");
        }
        if (request.getIndexSymbol() == null) {
            throw new IllegalArgumentException("indexSymbol is required");
        }
        if (request.getChartType() == null) {
            throw new IllegalArgumentException("chartType is required");
        }
        if (request.getTimeframe() == null) {
            throw new IllegalArgumentException("timeframe is required");
        }
        if (request.getSmaPeriods() == null) {
            throw new IllegalArgumentException("smaPeriods is required");
        }
        if (request.getDataSource() == null) {
            throw new IllegalArgumentException("dataSource is required");
        }
        boolean invalidSma = request.getSmaPeriods().stream()
                .filter(Objects::nonNull)
                .anyMatch(period -> !SUPPORTED_SMA_PERIODS.contains(period));
        if (invalidSma) {
            throw new IllegalArgumentException("smaPeriods contains unsupported values");
        }
    }

    private Optional<Instrument> resolveUnderlyingInstrument(IndexSymbol indexSymbol) {
        Optional<Instrument> exact = instrumentRepository
                .findFirstByInsNameIgnoreCaseOrderByIdAsc(indexSymbol.name());
        if (exact.isPresent()) {
            return exact;
        }

        return instrumentRepository
                .findByInsNameStartingWithIgnoreCaseOrderByIdAsc(indexSymbol.name())
                .stream()
                .findFirst();
    }

    /** Full lookback window, ascending, OHLC only. */
    private List<ChartCandleResponse> fetchIntradayCandles(String instrumentToken, LocalDate tradingDate) {
        LocalDateTime dayEnd = tradingDate.atTime(MARKET_CLOSE);
        int lookbackSize = MAX_SMA_PERIOD + LOOKBACK_BUFFER_CANDLES;

        List<MarketData> recentCandles = marketDataRepository.findRecentCandlesUpTo(
                instrumentToken,
                dayEnd,
                PageRequest.of(0, lookbackSize)
        );

        if (recentCandles.isEmpty()) {
            return List.of();
        }

        return recentCandles.stream()
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(MarketData::getTimestamp))
                .map(this::toChartCandle)
                .toList();
    }

    private ChartCandleResponse toChartCandle(MarketData marketData) {
        return ChartCandleResponse.ohlc(
                marketData.getTimestamp().atZone(INDIA_ZONE).toOffsetDateTime(),
                marketData.getOpen(),
                marketData.getHigh(),
                marketData.getLow(),
                marketData.getClose()
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

        return BigDecimal.valueOf(
                Math.round(referencePrice.doubleValue() / step) * step
        );
    }

    private MarketChartResponse emptyResponse(MarketChartRequest request,
                                              LocalDate expiryDate,
                                              BigDecimal atmStrike) {
        return buildResponse(request, expiryDate, atmStrike, List.of());
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
