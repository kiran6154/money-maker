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
 * <p>This used to carry {@code @Primary}, and it was load-bearing:
 * {@code ZerodhaMarketDataProvider} declares {@code matchIfMissing = true}, so
 * whenever this bean also existed there were two {@link MarketDataProvider}
 * candidates for the single-provider injection point in
 * {@code KiteHistoricalFetcher} and startup died with
 * {@code NoUniqueBeanDefinitionException}. {@code KiteHistoricalFetcher} now takes
 * {@link MarketDataProviderFactory} instead, so no single-provider injection point
 * remains and there is nothing left for {@code @Primary} to arbitrate (GAPS #20).
 * The preference it encoded did not go away, it just became legible: this provider
 * is first in {@code MarketDataProviderFactory.DEFAULT_PRECEDENCE}, for the same
 * reason it was {@code @Primary} — with the historical source active, any path
 * that still reaches the fetcher must read imported candles rather than silently
 * calling a broker.
 *
 * <h3>Interval support</h3>
 * The tables store 5-minute candles only. {@code 10minute} / {@code 15minute}
 * are aggregated from consecutive 5-minute buckets, mirroring what
 * {@code ChartTimeframeAggregator} does for the dashboard. {@code day} is the
 * same aggregation with a bucket wide enough to swallow a whole session — see
 * {@link #DAY_INTERVAL}.
 */
@Slf4j
@Component
@ConditionalOnProperty(name = "backtest.data-source", havingValue = "HISTORICAL_ICICI")
public class HistoricalIciciMarketDataProvider implements MarketDataProvider {

    public static final String NAME = "HISTORICAL_ICICI";

    /** Base granularity of both historical tables. */
    public static final String BASE_INTERVAL = "5minute";

    /**
     * Requested by {@code EodDowntrendDetectionService} for its ATR. Served by
     * rolling the session's 5-minute rows into one bar per trading date, which
     * is faithful for OHLC: a session's intraday high / low / last close
     * <i>are</i> the day's high / low / close, and its first candle's open is
     * the day's open. The one difference from a broker daily bar is the
     * timestamp — the day's first candle (09:15) rather than midnight — and no
     * caller reads it: {@code computeAtr} uses only high / low / close and the
     * ascending order they arrive in.
     */
    private static final String DAY_INTERVAL = "day";

    private static final int BASE_INTERVAL_MINUTES = 5;

    /**
     * Bucket width for {@link #DAY_INTERVAL}. Any value wider than a session
     * collapses the day into a single bar, because {@link #aggregate} keys its
     * buckets on <em>(trading date, elapsed minutes since the session open)</em>
     * and already breaks a bucket when the date changes.
     */
    private static final int MINUTES_PER_DAY = 1440;

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
        return aggregateTo(fetchBaseCandles(symbol, from, to, interval), symbol, interval);
    }

    /**
     * The raw 5-minute rows for {@code symbol} in {@code [from, to]}, before any
     * timeframe roll-up.
     *
     * <p>Exposed separately so {@code MarketDataService} can cache the <b>base</b>
     * series for a backtest day and roll it up per request, instead of caching an
     * already-aggregated series and slicing that. The difference is not
     * cosmetic — see {@link #aggregateTo}.
     *
     * <p>{@code interval} is only used to validate and to name the series in the
     * error message; the rows returned are always 5-minute.
     */
    @Transactional(readOnly = true)
    public List<MarketData> fetchBaseCandles(String symbol, LocalDateTime from, LocalDateTime to, String interval) {
        Objects.requireNonNull(symbol, "symbol must not be null");
        Objects.requireNonNull(from, "from must not be null");
        Objects.requireNonNull(to, "to must not be null");
        Objects.requireNonNull(interval, "interval must not be null");

        // Validate eagerly so an unsupported interval fails at the fetch, not
        // after the caller has already cached the rows.
        intervalMinutesOf2(interval, symbol);

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
        return base;
    }

    /**
     * Rolls a 5-minute series up to {@code interval}.
     *
     * <p><b>Call this on the rows the caller actually asked for, never on a wider
     * window that is then filtered by bar timestamp.</b> Aggregating first and
     * slicing after produces bars that are <i>complete</i> at a moment the caller
     * has not reached yet: for a 15-minute series, bucket {@code {09:30, 09:35,
     * 09:40}} is stamped {@code 09:30}, so a slice to {@code 09:35} keeps it and
     * hands the strategy 09:40's data at the 09:35 tick. A broker asked for
     * {@code to=09:35} returns that bar <i>partial</i>. Getting this backwards
     * gave backtest up to {@code interval - 5} minutes of look-ahead that live
     * never has.
     */
    public List<MarketData> aggregateTo(List<MarketData> base, String symbol, String interval) {
        int intervalMinutes = intervalMinutesOf2(interval, symbol);
        return intervalMinutes == BASE_INTERVAL_MINUTES ? base : aggregate(base, intervalMinutes);
    }

    /** Bar width in minutes, accepting {@link #DAY_INTERVAL} as well. */
    private int intervalMinutesOf2(String interval, String symbol) {
        return DAY_INTERVAL.equalsIgnoreCase(interval)
                ? MINUTES_PER_DAY
                : intervalMinutesOf(interval, symbol);
    }

    private List<MarketData> fetchSpot(HistoricalSymbol.Parsed parsed, String symbol,
                                       LocalDateTime from, LocalDateTime to) {
        List<HistoricalSpotCandle> rows = spotCandleRepository.findRangeAsc(
                parsed.stockCode(), parsed.exchangeCode(), from, to);

        List<MarketData> candles = new ArrayList<>(rows.size());
        for (HistoricalSpotCandle row : rows) {
            MarketData md = toMarketData(symbol, row.getDateTime(),
                    row.getOpen(), row.getHigh(), row.getLow(), row.getClose());
            md.setVolume(row.getVolume());
            candles.add(md);
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
            MarketData md = toMarketData(symbol, row.getDateTime(),
                    row.getOpen(), row.getHigh(), row.getLow(), row.getClose());
            md.setVolume(row.getVolume());
            md.setOpenInterest(row.getOpenInterest());
            candles.add(md);
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
        // Volume SUMS across the bucket; open interest is a level, not a flow,
        // so the bucket carries its LAST value rather than a total.
        Long volume = null;
        Long openInterest = null;

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
                    aggregated.add(bucketBar(symbol, timestamp, open, high, low, close, volume, openInterest));
                }
                bucketDate = date;
                bucketIndex = index;
                symbol = candle.getInstrumenttoken();
                timestamp = ts;
                open = candle.getOpen();
                high = candle.getHigh();
                low = candle.getLow();
                volume = null;
            }
            if (candle.getVolume() != null) {
                volume = (volume == null ? 0L : volume) + candle.getVolume();
            }
            if (candle.getOpenInterest() != null) {
                openInterest = candle.getOpenInterest();
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
            aggregated.add(bucketBar(symbol, timestamp, open, high, low, close, volume, openInterest));
        }
        return aggregated;
    }

    /**
     * Phase 8: rolls {@code slicedBase} up to {@code interval}, <b>reusing the
     * shared bucket objects</b> of {@code sharedAggregated} (the roll-up of the
     * full cached base series) for every bucket whose content is provably
     * identical to what aggregating the slice would produce. Sharing the
     * objects across ticks is what lets the SMA stamps on them survive — the
     * per-tick full rebuild was measured at ~+30% of replay wall time when it
     * went in (see {@code BACKTEST_PERFORMANCE.md}, Phase 2 fix).
     *
     * <p>Bucket-by-bucket equivalence argument, keyed on the same
     * <em>(trading date, elapsed-since-open ÷ interval)</em> ordinal
     * {@link #aggregate} uses:
     * <ul>
     *   <li><b>The leftmost bucket is rebuilt fresh every call.</b> The
     *       caller's {@code from} advances with the tick and can cut into the
     *       middle of a bucket, so its content (and first-candle timestamp)
     *       legitimately differs from the shared full bucket. It is built by
     *       {@link #aggregate} itself over exactly the sliced candles, so the
     *       semantics — including OI carry-over starting null — match a plain
     *       {@code aggregate(slice)} byte for byte.</li>
     *   <li><b>Interior buckets are shared.</b> A bucket with ordinal &gt; the
     *       left bucket's whose slot ends at or before {@code asOf} draws all
     *       its base candles from inside {@code [from, asOf)}, so the full-series
     *       roll-up and the slice roll-up see the same rows.</li>
     *   <li><b>Buckets whose slot ends after {@code asOf} are excluded.</b>
     *       In a plain {@code aggregate(slice)} they would come out partial and
     *       {@code dropIncompleteBars} would drop them; the shared versions are
     *       <em>complete</em> — built from the full day, i.e. the future — so
     *       serving them would be the exact look-ahead the Phase 2 fix removed.
     *       Excluding them here is equivalent and safe.</li>
     * </ul>
     *
     * <p>{@code day} requests bypass reuse entirely and take the plain
     * aggregation path: their session bar is exempt from the settled-bar rule
     * ({@code EodDowntrendDetectionService} wants the forming session), and the
     * exclusion rule above would wrongly withhold it.
     *
     * <p>The one member of the composed list that is a fresh object each call is
     * the leftmost (warm-up-region) bucket. {@code SMAIndicatorImpl}'s reuse
     * boundary was moved to {@code index >= period} in the same change so a
     * stamped value whose window could include that mutable first element is
     * never trusted.
     */
    public List<MarketData> aggregateSliceReusing(List<MarketData> sharedAggregated,
                                                  List<MarketData> slicedBase,
                                                  LocalDateTime asOf,
                                                  String interval,
                                                  String symbol) {
        int intervalMinutes = intervalMinutesOf2(interval, symbol);
        if (intervalMinutes == BASE_INTERVAL_MINUTES) {
            return slicedBase;
        }
        if (slicedBase == null || slicedBase.isEmpty()) {
            return new ArrayList<>();
        }
        if (intervalMinutes >= MINUTES_PER_DAY || sharedAggregated == null || sharedAggregated.isEmpty()
                || asOf == null) {
            return aggregate(slicedBase, intervalMinutes);
        }

        int openMinute = marketHours.open().getHour() * 60 + marketHours.open().getMinute();
        long leftOrdinal = bucketOrdinal(slicedBase.get(0).getTimestamp(), openMinute, intervalMinutes);

        // Rebuild the leftmost bucket from the sliced candles that belong to it.
        int leftEnd = 0;
        while (leftEnd < slicedBase.size()) {
            LocalDateTime ts = slicedBase.get(leftEnd).getTimestamp();
            if (ts == null || bucketOrdinal(ts, openMinute, intervalMinutes) != leftOrdinal) break;
            leftEnd++;
        }
        List<MarketData> out = new ArrayList<>(aggregate(slicedBase.subList(0, leftEnd), intervalMinutes));

        // Append the shared interior buckets: ordinal strictly after the left
        // bucket's, slot fully completed by asOf. Both bounds are monotonic
        // along the (ascending) shared list, so start near the request window
        // and stop at the first future slot.
        int start = firstIndexAtOrAfter(sharedAggregated, slicedBase.get(0).getTimestamp().minusMinutes(intervalMinutes));
        for (int i = start; i < sharedAggregated.size(); i++) {
            MarketData bucket = sharedAggregated.get(i);
            LocalDateTime ts = bucket == null ? null : bucket.getTimestamp();
            if (ts == null) continue;
            if (bucketOrdinal(ts, openMinute, intervalMinutes) <= leftOrdinal) continue;
            if (slotEndOf(ts, openMinute, intervalMinutes).isAfter(asOf)) break;
            out.add(bucket);
        }
        return out;
    }

    /**
     * The (date, bucket-index) pair {@link #aggregate} keys on, folded into one
     * comparable long. The index term is bounded by minutes-per-day ÷ 5, so the
     * 4096 stride cannot collide across dates.
     */
    private static long bucketOrdinal(LocalDateTime ts, int openMinute, int intervalMinutes) {
        int minuteOfDay = ts.getHour() * 60 + ts.getMinute();
        long index = Math.floorDiv(minuteOfDay - openMinute, intervalMinutes);
        return ts.toLocalDate().toEpochDay() * 4096 + (index + 1024);
    }

    /** The wall-clock end of the bucket slot containing {@code ts}. */
    private static LocalDateTime slotEndOf(LocalDateTime ts, int openMinute, int intervalMinutes) {
        int minuteOfDay = ts.getHour() * 60 + ts.getMinute();
        long index = Math.floorDiv(minuteOfDay - openMinute, intervalMinutes);
        return ts.toLocalDate().atStartOfDay().plusMinutes(openMinute + (index + 1) * intervalMinutes);
    }

    /** Index of the first bucket with timestamp ≥ {@code from}; binary search — shared series can span months. */
    private static int firstIndexAtOrAfter(List<MarketData> data, LocalDateTime from) {
        int lo = 0, hi = data.size();
        while (lo < hi) {
            int mid = (lo + hi) >>> 1;
            MarketData md = data.get(mid);
            LocalDateTime ts = md == null ? null : md.getTimestamp();
            if (ts == null || ts.isBefore(from)) lo = mid + 1;
            else hi = mid;
        }
        return lo;
    }

    /** {@link #toMarketData} plus the bucket's accumulated volume / last OI. */
    private MarketData bucketBar(String symbol, LocalDateTime timestamp,
                                 BigDecimal open, BigDecimal high, BigDecimal low, BigDecimal close,
                                 Long volume, Long openInterest) {
        MarketData bar = toMarketData(symbol, timestamp, open, high, low, close);
        bar.setVolume(volume);
        bar.setOpenInterest(openInterest);
        return bar;
    }
}
