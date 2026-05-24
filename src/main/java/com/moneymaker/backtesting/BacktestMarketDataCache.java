package com.moneymaker.backtesting;

import com.moneymaker.entity.MarketData;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Per-day candle cache used by {@code MarketDataService} during backtest to
 * eliminate per-tick HTTP refetches of the same historical window.
 *
 * <h3>Lifecycle</h3>
 * <ol>
 *   <li>{@link #beginDay(LocalDateTime, LocalDateTime)} — set at day-start by
 *       {@code BacktestAnalysisService.run}. Resets the underlying map and
 *       marks the cache active.</li>
 *   <li>For each {@code (symbol, interval)}, the first request triggers a
 *       broker fetch covering the entire {@code [dayFrom, dayTo]} window via
 *       {@link #put}.</li>
 *   <li>Subsequent per-tick requests slice the cached list via
 *       {@link #slice}, never re-hitting the broker.</li>
 *   <li>{@link #endDay()} clears state at day-end so the next iteration of
 *       the multi-day loop starts cold.</li>
 * </ol>
 *
 * <h3>Live-mode behaviour</h3>
 * The bean is always present but {@link #isActive()} stays {@code false}
 * outside backtest. {@link #slice} returns {@code null} for inactive cache,
 * which {@code MarketDataService} treats as a miss and routes through the
 * normal throttled fetch path. Live code therefore pays only one extra
 * map-lookup per call — measured in nanoseconds.
 *
 * <h3>Parity guarantee</h3>
 * The slice over a fully-populated daily series is byte-identical to what
 * the broker would have returned for the same {@code [from, to]} window,
 * because both rely on the same underlying candle data and the slice keeps
 * the broker's natural ascending timestamp order.
 */
@Slf4j
@Component
public class BacktestMarketDataCache {

    private final Map<String, List<MarketData>> seriesByKey = new ConcurrentHashMap<>();

    private volatile LocalDateTime dayFrom;
    private volatile LocalDateTime dayTo;
    private volatile boolean active = false;

    /** Mark the cache active for a new backtest day and clear any previous state. */
    public void beginDay(LocalDateTime from, LocalDateTime to) {
        this.dayFrom = from;
        this.dayTo = to;
        this.seriesByKey.clear();
        this.active = true;
        log.debug("[cache] beginDay from={} to={}", from, to);
    }

    /** Mark the cache inactive and drop all cached series. */
    public void endDay() {
        this.active = false;
        this.dayFrom = null;
        this.dayTo = null;
        int dropped = seriesByKey.size();
        this.seriesByKey.clear();
        log.debug("[cache] endDay dropped={} series", dropped);
    }

    public boolean isActive() { return active; }

    /** Day-wide lower bound used by callers to fetch a superset window on miss. */
    public LocalDateTime dayFrom() { return dayFrom; }

    /** Day-wide upper bound used by callers to fetch a superset window on miss. */
    public LocalDateTime dayTo() { return dayTo; }

    /**
     * Store the full {@code [dayFrom, dayTo]} series for {@code (symbol, interval)}.
     * Caller is responsible for fetching the wide window once; subsequent
     * per-tick {@link #slice} calls return sub-ranges without re-hitting the broker.
     */
    public void put(String symbol, String interval, List<MarketData> data) {
        if (symbol == null || interval == null || data == null) return;
        seriesByKey.put(key(symbol, interval), data);
        log.debug("[cache] put symbol={} interval={} size={}", symbol, interval, data.size());
    }

    /**
     * Return candles in the cached series for {@code (symbol, interval)} whose
     * timestamp lies in {@code [from, to]}. Returns {@code null} when the cache
     * is inactive or the series isn't populated yet — the caller treats both as
     * a miss and falls through to the throttled fetcher.
     */
    public List<MarketData> slice(String symbol, String interval, LocalDateTime from, LocalDateTime to) {
        if (!active) return null;
        List<MarketData> full = seriesByKey.get(key(symbol, interval));
        if (full == null) return null;

        // Brokers return ascending-by-timestamp lists; we preserve that here so
        // strategy code can rely on list.get(size-1) being the latest candle.
        List<MarketData> result = new ArrayList<>(full.size());
        for (MarketData md : full) {
            LocalDateTime ts = md == null ? null : md.getTimestamp();
            if (ts == null) continue;
            if (from != null && ts.isBefore(from)) continue;
            if (to != null && ts.isAfter(to)) break;
            result.add(md);
        }
        return result;
    }

    private static String key(String symbol, String interval) {
        return symbol + "|" + interval;
    }
}
