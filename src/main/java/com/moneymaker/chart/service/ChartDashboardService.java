package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.ChartCandleResponse;
import com.moneymaker.chart.dto.ChartDataSource;
import com.moneymaker.chart.dto.ChartTimeframe;
import com.moneymaker.chart.dto.ChartType;
import com.moneymaker.chart.dto.IndexSymbol;
import com.moneymaker.chart.dto.MarketChartRequest;
import com.moneymaker.chart.dto.MarketChartResponse;
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
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Deque;
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

        List<ChartCandleResponse> intradayCandles = fetchIntradayCandlesWithRuntimeSma(
                instrument.get().getInsId(),
                request.getDate()
        );
        List<ChartCandleResponse> data = chartTimeframeAggregator.aggregate(intradayCandles, request.getTimeframe());
        return buildResponse(request, null, null, data);
    }

    private MarketChartResponse getOptionChart(MarketChartRequest request) {
        Optional<Instrument> instrument = resolveUnderlyingInstrument(request.getIndexSymbol());
        if (instrument.isEmpty() || instrument.get().getInsId() == null || instrument.get().getInsId().isBlank()) {
            return emptyResponse(request, null, null);
        }

        List<ChartCandleResponse> underlyingRaw = fetchIntradayCandlesWithRuntimeSma(
                instrument.get().getInsId(),
                request.getDate()
        );
        if (underlyingRaw.isEmpty()) {
            return emptyResponse(request, null, null);
        }

        BigDecimal referencePrice = resolveReferencePrice(underlyingRaw);
        if (referencePrice == null) {
            return emptyResponse(request, null, null);
        }

        BigDecimal atmStrike = calculateAtmStrike(request.getIndexSymbol(), referencePrice);
        Optional<LocalDate> expiryDate = chartExpiryResolver.resolve(request.getDate(), request.getIndexSymbol());
        if (expiryDate.isEmpty()) {
            return emptyResponse(request, null, atmStrike);
        }

        String optionType = request.getChartType().name();
        Optional<InstrumentDetails> optionInstrument = instrumentDetailsRepository.findFirstByCriteria(
                request.getIndexSymbol().name(),
                expiryDate.get().toString(),
                atmStrike,
                optionType
        );

        if (optionInstrument.isEmpty() || optionInstrument.get().getInstrumentToken() == null) {
            return emptyResponse(request, expiryDate.get(), atmStrike);
        }

        List<ChartCandleResponse> optionRaw = fetchIntradayCandlesWithRuntimeSma(
                optionInstrument.get().getInstrumentToken().toString(),
                request.getDate()
        );
        List<ChartCandleResponse> data = chartTimeframeAggregator.aggregate(optionRaw, request.getTimeframe());
        return buildResponse(request, expiryDate.get(), atmStrike, data);
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

    private List<ChartCandleResponse> fetchIntradayCandlesWithRuntimeSma(String instrumentToken, LocalDate tradingDate) {
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

        List<ChartCandleResponse> chronologicalCandles = recentCandles.stream()
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(MarketData::getTimestamp))
                .map(this::toChartCandleWithoutSma)
                .toList();

        List<ChartCandleResponse> candlesWithRuntimeSma = applyRuntimeSma(chronologicalCandles);
        return candlesWithRuntimeSma.stream()
                .filter(candle -> candle.getTime() != null
                        && tradingDate.equals(candle.getTime().toLocalDate()))
                .toList();
    }

    private ChartCandleResponse toChartCandleWithoutSma(MarketData marketData) {
        return new ChartCandleResponse(
                marketData.getTimestamp().atZone(INDIA_ZONE).toOffsetDateTime(),
                marketData.getOpen(),
                marketData.getHigh(),
                marketData.getLow(),
                marketData.getClose(),
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

        return BigDecimal.valueOf(
                Math.round(referencePrice.doubleValue() / step) * step
        );
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

            BigDecimal sma20 = rolling20.add(close);
            BigDecimal sma50 = rolling50.add(close);
            BigDecimal sma100 = rolling100.add(close);
            BigDecimal sma200 = rolling200.add(close);
            BigDecimal sma500 = rolling500.add(close);

            out.add(new ChartCandleResponse(
                    candle.getTime(),
                    candle.getOpen(),
                    candle.getHigh(),
                    candle.getLow(),
                    candle.getClose(),
                    sma20,
                    sma50,
                    sma100,
                    sma200,
                    sma500
            ));
        }
        return out;
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
                BigDecimal removed = window.removeFirst();
                sum = sum.subtract(removed);
            }

            if (window.size() < period) {
                return null;
            }

            return sum.divide(BigDecimal.valueOf(period), 4, RoundingMode.HALF_UP);
        }
    }
}
