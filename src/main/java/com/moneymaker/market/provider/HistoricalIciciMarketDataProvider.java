package com.moneymaker.market.provider;

import com.moneymaker.entity.HistoricalOptionCandle;
import com.moneymaker.entity.HistoricalSpotCandle;
import com.moneymaker.entity.MarketData;
import com.moneymaker.market.exception.HistoricalDataMissingException;
import com.moneymaker.market.historical.HistoricalSymbol;
import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.repository.HistoricalOptionCandleRepository;
import com.moneymaker.repository.HistoricalSpotCandleRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Primary;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/**
 * Serves backtest candles from {@code historical_spot_candles} /
 * {@code historical_option_candles} instead of the broker, so an imported CSV
 * data set can be replayed offline and deterministically.
 *
 * <p>Registered only when {@code backtest.data-source=HISTORICAL_ICICI}.
 * {@code MarketDataService} injects it by concrete type and calls it directly,
 * which skips the {@code kiteHistorical} rate limiter — that limiter exists to
 * protect the broker API and would only throttle local DB reads.
 *
 * <p>{@code @Primary} is load-bearing, not cosmetic. {@code ZerodhaMarketDataProvider}
 * declares {@code matchIfMissing = true}, so whenever this bean also exists there
 * are two {@link MarketDataProvider} candidates for the single-provider injection
 * point in {@code KiteHistoricalFetcher} and startup dies with
 * {@code NoUniqueBeanDefinitionException}. Winning that injection point is also
 * the safe outcome: with the historical source active, any path that still
 * reaches the fetcher reads imported candles rather than silently calling a broker.
 *
 * <h3>Interval support</h3>
 * The tables store 5-minute candles only. {@code 10minute} / {@code 15minute}
 * are aggregated from consecutive 5-minute buckets, mirroring what
 * {@code ChartTimeframeAggregator} does for the dashboard. {@code day} is not
 * supported — see {@link #DAY_INTERVAL}.
 */
@Slf4j
@Component
@Primary
@ConditionalOnProperty(name = "backtest.data-source", havingValue = "HISTORICAL_ICICI")
public class HistoricalIciciMarketDataProvider implements MarketDataProvider {

    public static final String NAME = "HISTORICAL_ICICI";

    /** Base granularity of both historical tables. */
    private static final String BASE_INTERVAL = "5minute";

    /**
     * Requested by {@code EodDowntrendDetectionService} for its ATR. Daily
     * candles are not derivable from an intraday-only import in a way that
     * matches broker daily bars, so this returns empty and the caller degrades
     * — {@code BacktestAnalysisService} skips EOD downtrend detection entirely
     * when this provider is active.
     */
    private static final String DAY_INTERVAL = "day";

    private static final int BASE_INTERVAL_MINUTES = 5;

    private final HistoricalSpotCandleRepository spotCandleRepository;
    private final HistoricalOptionCandleRepository optionCandleRepository;
    private final MarketHoursService marketHours;

    public HistoricalIciciMarketDataProvider(HistoricalSpotCandleRepository spotCandleRepository,
                                             HistoricalOptionCandleRepository optionCandleRepository,
                                             MarketHoursService marketHours) {
        this.spotCandleRepository = Objects.requireNonNull(spotCandleRepository, "spotCandleRepository must not be null");
        this.optionCandleRepository = Objects.requireNonNull(optionCandleRepository, "optionCandleRepository must not be null");
        this.marketHours = Objects.requireNonNull(marketHours, "marketHours must not be null");
        log.info("HistoricalIciciMarketDataProvider initialized — backtest candles will be read from "
                + "historical_spot_candles / historical_option_candles");
    }

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    @Transactional(readOnly = true)
    public List<MarketData> fetchHistoricalData(String symbol, LocalDateTime from, LocalDateTime to, String interval) {
        Objects.requireNonNull(symbol, "symbol must not be null");
        Objects.requireNonNull(from, "from must not be null");
        Objects.requireNonNull(to, "to must not be null");
        Objects.requireNonNull(interval, "interval must not be null");

        if (DAY_INTERVAL.equalsIgnoreCase(interval)) {
            log.warn("[historical] interval '{}' is not supported by the historical source (symbol={}) — returning empty",
                    DAY_INTERVAL, symbol);
            return List.of();
        }

        int intervalMinutes = intervalMinutesOf(interval, symbol);
        HistoricalSymbol.Parsed parsed = HistoricalSymbol.parse(symbol);

        List<MarketData> base = parsed.isSpot()
                ? fetchSpot(parsed, symbol, from, to)
                : fetchOption(parsed, symbol, from, to);

        // A wholly absent series is a data-set error the run must not paper over.
        // Gaps *inside* a present series are normal for illiquid strikes.
        if (base.isEmpty()) {
            throw new HistoricalDataMissingException(
                    "No historical candles for symbol=" + symbol + ", interval=" + interval
                            + ", window=[" + from + " .. " + to + "]. "
                            + "Import the CSV covering this series/date range, or switch backtest.data-source=BROKER.");
        }

        return intervalMinutes == BASE_INTERVAL_MINUTES ? base : aggregate(base, intervalMinutes);
    }

    private List<MarketData> fetchSpot(HistoricalSymbol.Parsed parsed, String symbol,
                                       LocalDateTime from, LocalDateTime to) {
        List<HistoricalSpotCandle> rows = spotCandleRepository.findRangeAsc(
                parsed.stockCode(), parsed.exchangeCode(), from, to);

        List<MarketData> candles = new ArrayList<>(rows.size());
        for (HistoricalSpotCandle row : rows) {
            candles.add(toMarketData(symbol, row.getDateTime(),
                    row.getOpen(), row.getHigh(), row.getLow(), row.getClose()));
        }
        return candles;
    }

    private List<MarketData> fetchOption(HistoricalSymbol.Parsed parsed, String symbol,
                                         LocalDateTime from, LocalDateTime to) {
        List<HistoricalOptionCandle> rows = optionCandleRepository.findRangeAsc(
                parsed.stockCode(), parsed.exchangeCode(), parsed.expiryDate(),
                parsed.strikePrice(), parsed.optionRight(), from, to);

        List<MarketData> candles = new ArrayList<>(rows.size());
        for (HistoricalOptionCandle row : rows) {
            candles.add(toMarketData(symbol, row.getDateTime(),
                    row.getOpen(), row.getHigh(), row.getLow(), row.getClose()));
        }
        return candles;
    }

    /**
     * Builds a fresh, <b>transient</b> {@link MarketData} ({@code id == null}).
     *
     * <p>This must never return the managed historical entity: {@code SMAIndicatorImpl}
     * writes {@code smaValue20..500} onto every candle in place, and a managed
     * instance would be dirty-checked and flushed back into the historical
     * tables, corrupting the imported data set.
     *
     * <p>Volume and open interest are dropped because {@link MarketData} has no
     * such fields — identical to the broker path.
     */
    private MarketData toMarketData(String symbol, LocalDateTime timestamp,
                                    BigDecimal open, BigDecimal high, BigDecimal low, BigDecimal close) {
        MarketData candle = new MarketData();
        candle.setTimestamp(timestamp);
        candle.setOpen(open);
        candle.setHigh(high);
        candle.setLow(low);
        candle.setClose(close);
        candle.setInstrumenttoken(symbol);
        return candle;
    }

    /**
     * Bar width in minutes for a Kite-style interval string. Mirrors
     * {@code AnalysisScheduler.toMarketDataInterval}, which emits
     * {@code <minutes> + "minute"}.
     */
    private int intervalMinutesOf(String interval, String symbol) {
        String normalized = interval.trim().toLowerCase(Locale.ROOT);
        if (!normalized.endsWith("minute")) {
            throw new HistoricalDataMissingException(
                    "Unsupported interval '" + interval + "' for historical symbol " + symbol
                            + ". Supported: 5minute, 10minute, 15minute (multiples of " + BASE_INTERVAL + ").");
        }

        int minutes;
        try {
            minutes = Integer.parseInt(normalized.substring(0, normalized.length() - "minute".length()));
        } catch (NumberFormatException ex) {
            throw new HistoricalDataMissingException(
                    "Unparseable interval '" + interval + "' for historical symbol " + symbol);
        }

        if (minutes < BASE_INTERVAL_MINUTES || minutes % BASE_INTERVAL_MINUTES != 0) {
            throw new HistoricalDataMissingException(
                    "Interval '" + interval + "' cannot be derived from " + BASE_INTERVAL + " candles (symbol="
                            + symbol + "). Supported: multiples of " + BASE_INTERVAL_MINUTES + " minutes.");
        }
        return minutes;
    }

    /**
     * Rolls 5-minute candles into {@code intervalMinutes} bars:
     * open = first, high = max, low = min, close = last, timestamp = first.
     *
     * <p>Buckets are keyed on <em>(trading date, elapsed minutes since the session
     * open)</em>, not on list position. Index-based chunking would be wrong twice
     * over: an NSE session is 75 five-minute candles, which is not divisible by 2,
     * so 10-minute bars would drift and eventually merge the tail of one day with
     * the head of the next; and any gap in an illiquid strike's series would shift
     * every bar after it. Anchoring on the session open also puts bar boundaries
     * where the broker puts them (09:15, 09:30, … for 15-minute bars), so a run
     * that switches data source keeps comparable bars.
     *
     * <p>A trailing partial bucket is kept, matching the broker's behaviour of
     * returning a partial candle for the still-forming interval.
     */
    private List<MarketData> aggregate(List<MarketData> base, int intervalMinutes) {
        List<MarketData> aggregated = new ArrayList<>();
        int openMinute = marketHours.open().getHour() * 60 + marketHours.open().getMinute();

        LocalDate bucketDate = null;
        long bucketIndex = Long.MIN_VALUE;

        String symbol = null;
        LocalDateTime timestamp = null;
        BigDecimal open = null;
        BigDecimal high = null;
        BigDecimal low = null;
        BigDecimal close = null;

        for (MarketData candle : base) {
            LocalDateTime ts = candle.getTimestamp();
            if (ts == null) {
                continue;
            }
            LocalDate date = ts.toLocalDate();
            int minuteOfDay = ts.getHour() * 60 + ts.getMinute();
            // floorDiv keeps pre-open candles (if a feed ever carries them) in a
            // sane bucket instead of folding them into the first session bar.
            long index = Math.floorDiv(minuteOfDay - openMinute, intervalMinutes);

            if (!date.equals(bucketDate) || index != bucketIndex) {
                if (timestamp != null) {
                    aggregated.add(toMarketData(symbol, timestamp, open, high, low, close));
                }
                bucketDate = date;
                bucketIndex = index;
                symbol = candle.getInstrumenttoken();
                timestamp = ts;
                open = candle.getOpen();
                high = candle.getHigh();
                low = candle.getLow();
            }

            if (candle.getHigh() != null && (high == null || candle.getHigh().compareTo(high) > 0)) {
                high = candle.getHigh();
            }
            if (candle.getLow() != null && (low == null || candle.getLow().compareTo(low) < 0)) {
                low = candle.getLow();
            }
            close = candle.getClose();
        }

        if (timestamp != null) {
            aggregated.add(toMarketData(symbol, timestamp, open, high, low, close));
        }
        return aggregated;
    }
}
