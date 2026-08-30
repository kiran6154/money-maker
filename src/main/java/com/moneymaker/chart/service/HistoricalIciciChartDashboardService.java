package com.moneymaker.chart.service;

import com.moneymaker.chart.dto.ChartCandleResponse;
import com.moneymaker.chart.dto.ChartTimeframe;
import com.moneymaker.chart.dto.ChartType;
import com.moneymaker.chart.dto.IndexSymbol;
import com.moneymaker.chart.dto.MarketChartRequest;
import com.moneymaker.chart.dto.MarketChartResponse;
import com.moneymaker.chart.dto.StrikeOptionsResponse;
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

    /** Five-minute candles in one NSE session (09:15-15:30). */
    private static final int CANDLES_PER_SESSION = 75;

    /**
     * Ceiling on how many calendar days a continuous window may fetch. A
     * year of five-minute candles is ~18k rows per series, which is a chart
     * nobody can read and a payload nobody wants; the cap keeps an
     * accidental multi-year range from stalling the page.
     */
    private static final int MAX_WINDOW_DAYS = 90;

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
                fetchSpotCandles(request.getIndexSymbol(), request.getFromDate(), request.getDate()),
                request.getTimeframe(),
                request.getFromDate(),
                request.getDate()
        );
        return buildResponse(request, null, null, data);
    }

    private MarketChartResponse getOptionChart(MarketChartRequest request) {
        // ATM is resolved off the *selected day's* spot candles, so this one is
        // filtered to the day without needing indicators.
        List<ChartCandleResponse> spotCandles = onSelectedDate(
                fetchSpotCandles(request.getIndexSymbol(), null, request.getDate()),
                request.getDate()
        );
        if (spotCandles.isEmpty()) {
            return buildResponse(request, null, null, List.of());
        }

        BigDecimal referencePrice = resolveReferencePrice(spotCandles);
        if (referencePrice == null) {
            return buildResponse(request, null, null, List.of());
        }

        // An explicitly picked strike wins; otherwise fall back to ATM.
        BigDecimal atmStrike = calculateAtmStrike(request.getIndexSymbol(), referencePrice);
        BigDecimal strike = request.getStrike() != null ? request.getStrike() : atmStrike;
        Optional<LocalDate> expiryDate = resolveExpiryDate(request.getIndexSymbol(), request.getDate());
        if (expiryDate.isEmpty()) {
            return buildResponse(request, null, strike, List.of());
        }

        // NOTE: expiry and strike are resolved from the selected date. An option
        // series only exists within its own expiry cycle, so a range spanning an
        // expiry shows candles only where THIS contract traded - the series stops
        // rather than silently splicing in a different contract.
        List<ChartCandleResponse> data = finish(
                fetchOptionCandles(
                        request.getIndexSymbol(),
                        expiryDate.get(),
                        strike,
                        request.getChartType(),
                        request.getFromDate(),
                        request.getDate()),
                request.getTimeframe(),
                request.getFromDate(),
                request.getDate()
        );
        return buildResponse(request, expiryDate.get(), strike, data);
    }

    /**
     * Strikes the picker can offer for this date/index, plus the auto (ATM)
     * choice. Only strikes with candles for the resolved expiry are returned.
     */
    public StrikeOptionsResponse getStrikeOptions(IndexSymbol indexSymbol, LocalDate date, ChartType chartType) {
        Optional<LocalDate> expiryDate = resolveExpiryDate(indexSymbol, date);
        if (expiryDate.isEmpty()) {
            return new StrikeOptionsResponse(null, null, List.of());
        }

        List<ChartCandleResponse> spotCandles = onSelectedDate(fetchSpotCandles(indexSymbol, null, date), date);
        BigDecimal referencePrice = spotCandles.isEmpty() ? null : resolveReferencePrice(spotCandles);
        BigDecimal atmStrike = referencePrice == null ? null : calculateAtmStrike(indexSymbol, referencePrice);

        String optionRight = (chartType == null || chartType == ChartType.UNDERLYING)
                ? ChartType.CE.name()
                : chartType.name();

        List<BigDecimal> strikes = optionCandleRepository.findAvailableStrikes(
                indexSymbol.name(), OPTION_EXCHANGE, expiryDate.get(), optionRight);

        return new StrikeOptionsResponse(expiryDate.get(), atmStrike, strikes);
    }

    /**
     * Aggregate to the requested timeframe, compute overlays on that series, then
     * trim to the visible day. Order matters: indicators must see the lookback
     * candles to warm up, and must be computed on the bars actually drawn.
     */
    private List<ChartCandleResponse> finish(List<ChartCandleResponse> lookbackCandles,
                                             ChartTimeframe timeframe,
                                             LocalDate fromDate,
                                             LocalDate tradingDate) {
        List<ChartCandleResponse> aggregated =
                chartTimeframeAggregator.aggregate(lookbackCandles, timeframe);
        chartIndicatorService.applyIndicators(aggregated);
        return inWindow(aggregated, fromDate, tradingDate);
    }

    private List<ChartCandleResponse> onSelectedDate(List<ChartCandleResponse> candles, LocalDate tradingDate) {
        return inWindow(candles, null, tradingDate);
    }

    /**
     * Trims to {@code [from, to]} inclusive, or to {@code to} alone when
     * {@code from} is null.
     *
     * <p>The lookback fetched for SMA continuity is deliberately wider than the
     * window drawn - that is what makes the first bar of the window carry a real
     * SMA instead of a null - so everything outside it is dropped here rather
     * than at the query.
     */
    private List<ChartCandleResponse> inWindow(List<ChartCandleResponse> candles,
                                               LocalDate from, LocalDate to) {
        return candles.stream()
                .filter(candle -> {
                    if (candle.getTime() == null) return false;
                    LocalDate d = candle.getTime().toLocalDate();
                    if (d.isAfter(to)) return false;
                    return from == null ? to.equals(d) : !d.isBefore(from);
                })
                .toList();
    }

    /**
     * Candles to fetch so the drawn window is fully covered <em>and</em> the
     * longest SMA is warm at its first bar.
     *
     * <p>The fixed {@code MAX_SMA_PERIOD + LOOKBACK_BUFFER_CANDLES} page was
     * sized for a single day. A continuous window needs the days themselves on
     * top, or the chart silently starts partway through the range: 596 candles
     * is only about eight sessions of five-minute data.
     */
    private int pageSizeFor(LocalDate from, LocalDate to) {
        int windowCandles = 0;
        if (from != null && to != null && !from.isAfter(to)) {
            long days = java.time.temporal.ChronoUnit.DAYS.between(from, to) + 1;
            windowCandles = (int) Math.min(days, MAX_WINDOW_DAYS) * CANDLES_PER_SESSION;
        }
        return MAX_SMA_PERIOD + LOOKBACK_BUFFER_CANDLES + windowCandles;
    }

    /** Full lookback window, ascending, OHLC only. */
    private List<ChartCandleResponse> fetchSpotCandles(IndexSymbol indexSymbol,
                                                       LocalDate fromDate,
                                                       LocalDate tradingDate) {
        LocalDateTime dayEnd = tradingDate.atTime(MARKET_CLOSE);
        List<HistoricalSpotCandle> recentCandles = spotCandleRepository.findRecentCandlesUpTo(
                indexSymbol.name(),
                SPOT_EXCHANGE,
                dayEnd,
                PageRequest.of(0, pageSizeFor(fromDate, tradingDate))
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
                                                         LocalDate fromDate,
                                                         LocalDate tradingDate) {
        LocalDateTime dayEnd = tradingDate.atTime(MARKET_CLOSE);
        List<HistoricalOptionCandle> recentCandles = optionCandleRepository.findRecentCandlesUpTo(
                indexSymbol.name(),
                OPTION_EXCHANGE,
                expiryDate,
                strikePrice,
                chartType.name(),
                dayEnd,
                PageRequest.of(0, pageSizeFor(fromDate, tradingDate))
        );

        return recentCandles.stream()
                .filter(Objects::nonNull)
                .sorted(Comparator.comparing(HistoricalOptionCandle::getDateTime))
                .map(this::toChartCandle)
                .toList();
    }

    private Optional<LocalDate> resolveExpiryDate(IndexSymbol indexSymbol, LocalDate selectedDate) {
        return optionCandleRepository.findNearestExpiryOnOrAfter(
                indexSymbol.name(),
                OPTION_EXCHANGE,
                selectedDate
        );
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
