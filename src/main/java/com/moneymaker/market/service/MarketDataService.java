package com.moneymaker.market.service;

import com.moneymaker.backtesting.BacktestMarketDataCache;
import com.moneymaker.entity.MarketData;
import com.moneymaker.market.provider.HistoricalIciciMarketDataProvider;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/**
 * Façade callers use to fetch historical candles. Cache-aware:
 * <ol>
 *   <li>Tries {@link BacktestMarketDataCache#slice} first. In backtest the cache
 *       is active and a slice almost always satisfies the request after the
 *       first miss of the day. In live mode the cache is permanently inactive,
 *       slice returns {@code null}, and the call routes straight to the
 *       throttled fetcher — zero behaviour change for live.</li>
 *   <li>On miss, calls {@link KiteHistoricalFetcher#fetch} with a wider window
 *       ({@code [dayFrom, dayTo]}) so subsequent ticks within the day are
 *       served from the cache. In live mode, the request is forwarded
 *       verbatim — no widening.</li>
 * </ol>
 *
 * <p>The wider-window fetch in backtest is the entire Phase 1 speed-up:
 * approximately {@code ticks_per_day} fewer broker calls per
 * {@code (symbol, interval)} per day. See {@code docs/BACKTEST_PERFORMANCE.md}.
 */
@Slf4j
@Service
public class MarketDataService {

    private final KiteHistoricalFetcher fetcher;
    private final BacktestMarketDataCache cache;

    /**
     * Present only when {@code backtest.data-source=HISTORICAL_ICICI}. When set,
     * every candle comes from the imported historical tables instead of the
     * broker; when absent (live, or {@code BROKER}) this field is {@code null}
     * and the fetch path is exactly what it was before.
     */
    private final HistoricalIciciMarketDataProvider historicalProvider;

    public MarketDataService(KiteHistoricalFetcher fetcher,
                             BacktestMarketDataCache cache,
                             ObjectProvider<HistoricalIciciMarketDataProvider> historicalProvider) {
        this.fetcher = Objects.requireNonNull(fetcher, "fetcher must not be null");
        this.cache = Objects.requireNonNull(cache, "cache must not be null");
        this.historicalProvider = historicalProvider.getIfAvailable();
        log.info("MarketDataService initialized with provider: {}", getActiveProvider());
    }

    /**
     * Single hop to whichever source is active. The historical source is called
     * directly rather than through {@link KiteHistoricalFetcher}: the
     * {@code kiteHistorical} rate limiter and retry exist to protect the broker
     * API, and applying them to local DB reads would only slow the replay.
     */
    private List<MarketData> fetchFromSource(String symbol, LocalDateTime from, LocalDateTime to, String interval) {
        return historicalProvider != null
                ? historicalProvider.fetchHistoricalData(symbol, from, to, interval)
                : fetcher.fetch(symbol, from, to, interval);
    }

    public List<MarketData> fetchHistoricalData(String symbol, LocalDateTime from, LocalDateTime to, String interval) {
        Objects.requireNonNull(symbol, "symbol must not be null");
        Objects.requireNonNull(from, "from must not be null");
        Objects.requireNonNull(to, "to must not be null");
        Objects.requireNonNull(interval, "interval must not be null");

        // Fast path: backtest cache hit. In live mode isActive()=false and this
        // short-circuits to the throttled fetch below.
        if (cache.isActive()) {
            // The superset is the UNION of the day window and what the caller
            // asked for, never just the day window: EodDowntrendDetectionService
            // wants ~30 days for its ATR and up to 35 for its SMA grid, and
            // narrowing to [dayFrom, dayTo] silently handed it a few days and a
            // partial average. For the tick loop, whose windows already sit
            // inside the day window, the union *is* the day window — identical
            // behaviour and the same single fetch.
            LocalDateTime wideFrom = min(from, cache.dayFrom());
            LocalDateTime wideTo   = max(to, cache.dayTo());

            if (historicalProvider != null) {
                return fromBaseCache(symbol, from, to, interval, wideFrom, wideTo);
            }

            List<MarketData> hit = cache.slice(symbol, interval, from, to);
            if (hit != null && !hit.isEmpty()) {
                return dropIncompleteBars(hit, to, interval);
            }

            // Backtest cache miss — fetch a superset once, cache it, then slice.
            // All subsequent ticks for this (symbol, interval) hit the cache.
            List<MarketData> wide = fetchFromSource(symbol, wideFrom, wideTo, interval);
            cache.put(symbol, interval, wide, wideFrom, wideTo);

            List<MarketData> sliced = cache.slice(symbol, interval, from, to);
            return dropIncompleteBars(sliced != null ? sliced : wide, to, interval);
        }

        // Live path — same call shape as before Phase 1, then the same
        // completed-bars-only rule the backtest applies.
        return dropIncompleteBars(fetchFromSource(symbol, from, to, interval), to, interval);
    }

    /**
     * Drops trailing bars whose period has not finished by {@code asOf}.
     *
     * <p><b>Why this is not a backtest concern only.</b> A bar stamped {@code T}
     * covers {@code [T, T + width)}. A broker asked for data "up to now" returns
     * the current bar <em>partially formed</em>, and the strategy gate reads that
     * bar's open and close — so whether a signal fires depends on how far into the
     * bar the 5-minute cron happened to land. Two runs of the same live day, with
     * the cron firing a few seconds apart, can disagree. Evaluating only settled
     * bars removes that non-determinism.
     *
     * <p>In backtest the same rule removes an outright look-ahead: the candle
     * stamped {@code T} is <em>complete</em> in imported data, so including it fed
     * the strategy five minutes of price action that had not happened at {@code T}
     * and then stamped the trade at {@code T}. The newest admissible bar is the
     * one stamped {@code T - width}, which closed exactly at {@code T} — so its
     * close is the price actually transactable at {@code T}.
     *
     * <p>Intervals this cannot size — {@code day} in particular — are left alone.
     * {@code EodDowntrendDetectionService} asks for {@code day} bars at 15:20 for
     * its ATR, and the session's own bar is exactly what it wants; dropping it
     * would silently shorten every ATR window by a day.
     */
    private List<MarketData> dropIncompleteBars(List<MarketData> bars, LocalDateTime asOf, String interval) {
        if (bars == null || bars.isEmpty() || asOf == null) {
            return bars;
        }
        int width = barWidthMinutes(interval);
        if (width <= 0) {
            return bars;
        }

        int end = bars.size();
        while (end > 0) {
            MarketData last = bars.get(end - 1);
            LocalDateTime ts = last == null ? null : last.getTimestamp();
            // Complete when the bar's period ends at or before asOf.
            if (ts == null || !ts.plusMinutes(width).isAfter(asOf)) {
                break;
            }
            end--;
        }
        if (end == bars.size()) {
            return bars;
        }
        log.debug("[market-data] dropped {} forming bar(s) for symbol={} interval={} asOf={}",
                bars.size() - end, symbolSafe(bars), interval, asOf);
        return new ArrayList<>(bars.subList(0, end));
    }

    /** Bar width in minutes, or 0 for an interval this cannot size (e.g. {@code day}). */
    private static int barWidthMinutes(String interval) {
        if (interval == null) return 0;
        String normalized = interval.trim().toLowerCase(Locale.ROOT);
        if (!normalized.endsWith("minute")) return 0;
        try {
            return Integer.parseInt(normalized.substring(0, normalized.length() - "minute".length()));
        } catch (NumberFormatException ex) {
            return 0;
        }
    }

    /** Symbol off the first candle, for the debug line only. */
    private static String symbolSafe(List<MarketData> bars) {
        MarketData first = bars.isEmpty() ? null : bars.get(0);
        return first == null ? "?" : String.valueOf(first.getInstrumenttoken());
    }

    /**
     * Historical-source backtest read: cache the <b>base</b> 5-minute series for
     * the day, slice it to the caller's window, and only then roll it up to the
     * requested interval.
     *
     * <p>The ordering is the whole point. Caching an already-aggregated series
     * and slicing that by bar timestamp keeps any bucket whose <em>start</em>
     * falls inside the window — including buckets built from candles the caller
     * has not reached. On a 15-minute series that handed the strategy up to 10
     * minutes of future data at every tick, which live never has, because a
     * broker asked for {@code to=09:35} returns the 09:30 bar partial. Rolling up
     * after the slice reproduces the partial bar exactly.
     *
     * <p>Caching the base series also means one cached entry per symbol instead
     * of one per (symbol, interval): the 5-, 10- and 15-minute views of a strike
     * are now three roll-ups of the same cached rows, not three fetches.
     */
    private List<MarketData> fromBaseCache(String symbol, LocalDateTime from, LocalDateTime to,
                                           String interval, LocalDateTime wideFrom, LocalDateTime wideTo) {
        String baseInterval = HistoricalIciciMarketDataProvider.BASE_INTERVAL;

        // EXCLUSIVE upper bound. A candle stamped T covers [T, T + width), so it
        // has not finished forming at T — its close is the price at T + width and
        // its high/low describe five minutes that, at T, have not happened.
        // Including it let the strategy evaluate a completed future bar and stamp
        // the resulting trade at T: a look-ahead on the decision, not merely on
        // the fill. Assuming close(T) == open(T + width) does not rescue it, since
        // the gate reads the bar's whole shape, not just its last price.
        //
        // The newest admissible bar at T is therefore the one stamped T - width,
        // which completed exactly at T and whose close IS the price at T — so the
        // fill stays realistic while the decision uses only settled data.
        LocalDateTime lastCompleted = to.minusNanos(1);

        List<MarketData> base = cache.slice(symbol, baseInterval, from, lastCompleted);
        if (base == null || base.isEmpty()) {
            List<MarketData> wide = historicalProvider.fetchBaseCandles(symbol, wideFrom, wideTo, interval);
            cache.put(symbol, baseInterval, wide, wideFrom, wideTo);

            base = cache.slice(symbol, baseInterval, from, lastCompleted);
            if (base == null) {
                base = wide;
            }
        }
        // The roll-up can still produce a trailing partial bucket (at 09:40 the
        // 15-minute bucket 09:30 holds only 09:30 and 09:35). dropIncompleteBars
        // removes it, so both paths return settled bars only.
        return dropIncompleteBars(historicalProvider.aggregateTo(base, symbol, interval), to, interval);
    }

    public List<Double> extractClosePrices(List<MarketData> marketDataList) {
        List<Double> closePrices = new ArrayList<>();
        if (marketDataList == null || marketDataList.isEmpty()) {
            return closePrices;
        }
        for (MarketData data : marketDataList) {
            if (data.getClose() != null) {
                closePrices.add(data.getClose().doubleValue());
            }
        }
        return closePrices;
    }

    public String getActiveProvider() {
        return historicalProvider != null ? historicalProvider.getName() : fetcher.getActiveProvider();
    }

    /** Earlier of the two bounds; tolerates a null cache bound (inactive day). */
    private static LocalDateTime min(LocalDateTime a, LocalDateTime b) {
        if (a == null) return b;
        if (b == null) return a;
        return a.isBefore(b) ? a : b;
    }

    /** Later of the two bounds; tolerates a null cache bound (inactive day). */
    private static LocalDateTime max(LocalDateTime a, LocalDateTime b) {
        if (a == null) return b;
        if (b == null) return a;
        return a.isAfter(b) ? a : b;
    }
}
