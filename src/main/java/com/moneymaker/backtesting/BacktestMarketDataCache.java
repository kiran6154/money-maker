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
 *       broker fetch covering at least the entire {@code [dayFrom, dayTo]}
 *       window — the union of that window and the caller's, so a caller with a
 *       longer lookback still gets it — stored via {@link #put} alongside the
 *       window it covers.</li>
 *   <li>Subsequent per-tick requests slice the cached list via
 *       {@link #slice}, never re-hitting the broker. A request reaching outside
 *       the covered window is reported as a miss so the caller refetches wider
 *       instead of being handed a truncated series.</li>
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

    /**
     * A cached series plus the window it was fetched over. The window is what
     * makes {@link #slice} honest: a series cached for the day window cannot
     * answer a request that reaches further back, and serving it anyway returns
     * a silently truncated history rather than a miss.
     */
    private record Series(List<MarketData> data, LocalDateTime from, LocalDateTime to) {

        boolean covers(LocalDateTime reqFrom, LocalDateTime reqTo) {
            if (reqFrom != null && from != null && reqFrom.isBefore(from)) return false;
            return !(reqTo != null && to != null && reqTo.isAfter(to));
        }
    }

    private final Map<String, Series> seriesByKey = new ConcurrentHashMap<>();

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
     * Store the series for {@code (symbol, interval)} together with the
     * {@code [from, to]} window it was actually fetched over. Caller is
     * responsible for fetching the wide window once; subsequent per-tick
     * {@link #slice} calls return sub-ranges without re-hitting the broker.
     *
     * <p>A later {@code put} for the same key replaces the entry, so a wider
     * refetch upgrades the coverage rather than accumulating entries.
     */
    public void put(String symbol, String interval, List<MarketData> data,
                    LocalDateTime from, LocalDateTime to) {
        if (symbol == null || interval == null || data == null) return;
        seriesByKey.put(key(symbol, interval), new Series(data, from, to));
        log.debug("[cache] put symbol={} interval={} size={} window={}..{}",
                symbol, interval, data.size(), from, to);
    }

    /**
     * Return candles in the cached series for {@code (symbol, interval)} whose
     * timestamp lies in {@code [from, to]}. Returns {@code null} when the cache
     * is inactive, the series isn't populated yet, or the cached window does not
     * cover the request — the caller treats all three as a miss and falls through
     * to the throttled fetcher.
     *
     * <p>The coverage check is what lets a caller with a longer lookback than the
     * day window — {@code EodDowntrendDetectionService}, whose ATR wants ~30 days
     * and whose SMA grid wants up to 35 — get its history. Without it the day's
     * already-cached series answers the request and the extra history is dropped
     * on the floor with no miss and no log line.
     */
    public List<MarketData> slice(String symbol, String interval, LocalDateTime from, LocalDateTime to) {
        if (!active) return null;
        Series series = seriesByKey.get(key(symbol, interval));
        if (series == null) return null;
        if (!series.covers(from, to)) {
            log.debug("[cache] miss symbol={} interval={} — request {}..{} outside cached {}..{}",
                    symbol, interval, from, to, series.from(), series.to());
            return null;
        }

        // Brokers return ascending-by-timestamp lists; we preserve that here so
        // strategy code can rely on list.get(size-1) being the latest candle.
        List<MarketData> full = series.data();
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
