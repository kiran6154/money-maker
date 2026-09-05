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
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;

@Slf4j
@Service
@RequiredArgsConstructor
public class ChartDashboardService {

    private static final Set<Integer> SUPPORTED_SMA_PERIODS = Set.of(20, 50, 100, 200, 500);

    /**
     * Widest strike ladder a single request may average. The dashboard asks for
     * 1 and 2; the ceiling is here so a hand-written URL cannot turn one pane
     * into a hundred-leg fetch. Raising it is a cost decision, not a correctness
     * one — every extra step is two more contracts to read and align.
     */
    private static final int MAX_STRIKE_SPAN = 5;
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
    private final ChartStrikeAverager chartStrikeAverager;
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

        // A one-strike ladder is the ordinary chart, so the averaged panes share
        // this path rather than getting one of their own.
        List<BigDecimal> ladder =
                ChartStrikeLadder.around(request.getIndexSymbol(), strike, request.getStrikeSpan());
        Map<BigDecimal, List<ChartCandleResponse>> legs =
                fetchOptionLegs(request, expiryDate.get(), ladder);

        if (legs.isEmpty()) {
            return emptyResponse(request, expiryDate.get(), strike);
        }

        List<ChartCandleResponse> data = finish(
                chartStrikeAverager.average(legs.values()),
                request.getTimeframe(),
                request.getDate()
        );
        List<BigDecimal> averagedStrikes =
                request.getStrikeSpan() > 0 ? List.copyOf(legs.keySet()) : List.of();
        return buildResponse(request, expiryDate.get(), strike, averagedStrikes, data);
    }

    /**
     * One ascending OHLC leg per strike on the ladder, keyed by strike.
     *
     * <p>Unlike the historical source, this one is inherently per-strike: each
     * leg needs its own {@code instrument_details} token before {@code market_data}
     * can be queried at all, so there is no single range query to fold them into.
     *
     * <p>A strike whose token or candles are missing is simply absent, so the
     * caller can report the legs actually averaged. The average itself then holds
     * to the same all-legs rule as the historical path.
     */
    private Map<BigDecimal, List<ChartCandleResponse>> fetchOptionLegs(MarketChartRequest request,
                                                                       LocalDate expiryDate,
                                                                       List<BigDecimal> ladder) {
        String optionType = request.getChartType().name();
        Map<BigDecimal, List<ChartCandleResponse>> legs = new LinkedHashMap<>();

        for (BigDecimal strike : ladder) {
            Optional<InstrumentDetails> optionInstrument = instrumentDetailsRepository.findFirstByCriteria(
                    request.getIndexSymbol().name(),
                    expiryDate.toString(),
                    strike,
                    optionType
            );
            if (optionInstrument.isEmpty() || optionInstrument.get().getInstrumentToken() == null) {
                continue;
            }

            List<ChartCandleResponse> candles = fetchIntradayCandles(
                    optionInstrument.get().getInstrumentToken().toString(), request.getDate());
            if (!candles.isEmpty()) {
                legs.put(strike, new ArrayList<>(candles));
            }
        }
        return legs;
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
        if (request.getStrikeSpan() < 0 || request.getStrikeSpan() > MAX_STRIKE_SPAN) {
            throw new IllegalArgumentException(
                    "strikeSpan must be between 0 and " + MAX_STRIKE_SPAN);
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
        return ChartStrikeLadder.atmStrike(indexSymbol, referencePrice);
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
        return buildResponse(request, expiryDate, atmStrike, List.of(), data);
    }

    private MarketChartResponse buildResponse(MarketChartRequest request,
                                              LocalDate expiryDate,
                                              BigDecimal atmStrike,
                                              List<BigDecimal> averagedStrikes,
                                              List<ChartCandleResponse> data) {
        return new MarketChartResponse(
                request.getIndexSymbol(),
                request.getChartType(),
                request.getTimeframe(),
                request.getDate(),
                expiryDate,
                atmStrike,
                averagedStrikes,
                data
        );
    }

}
