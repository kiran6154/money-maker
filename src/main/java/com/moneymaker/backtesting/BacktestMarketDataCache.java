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
 * Candle cache used by {@code MarketDataService} during backtest to eliminate
 * per-tick refetches of the same historical window.
 *
 * <h3>Lifecycle (Phase 11 — cross-day retention)</h3>
 * <ol>
 *   <li>{@link #beginDay(LocalDateTime, LocalDateTime)} — set at day-start by
 *       {@code BacktestAnalysisService.run}. Marks the cache active, advances
 *       the day counter, and evicts series that have not been touched for
 *       {@link #EVICT_AFTER_DAYS} backtest days (an option series goes cold the
 *       day its expiry passes — its symbol is never requested again).</li>
 *   <li>For each {@code (symbol, interval)}, the first request triggers a
 *       fetch covering at least the entire {@code [dayFrom, dayTo]} window —
 *       the union of that window and the caller's — stored via {@link #put}
 *       alongside the window it covers. On later days, a series whose stored
 *       window is short only on the <em>right</em> is extended with a delta
 *       fetch via {@link #appendRight} instead of being refetched whole.</li>
 *   <li>Per-tick requests slice the cached list via {@link #slice}. A request
 *       reaching outside the covered window is reported as a miss so the caller
 *       refetches (or extends) instead of being handed a truncated series.</li>
 *   <li>{@link #endDay()} marks the cache inactive but — unlike the original
 *       per-day design — <b>keeps the candle series</b>. The rows are immutable
 *       imported data; day N+1's ~35-day lookback window overlaps day N's by
 *       ~97%, and refetching it bought nothing. The per-day wipe of
 *       {@code SharedData} (strike maps, {@code optionTokenMap} — the actual
 *       staleness hazards) is unchanged and lives in
 *       {@code BacktestAnalysisService}.</li>
 * </ol>
 *
 * <h3>Aggregated-series cache (Phase 8)</h3>
 * For coarse intervals (10/15-minute) the roll-up of the full base series is
 * cached once per {@code (symbol, interval)} via {@link #putAggregated} and
 * reused every tick, so the bucket objects — and the SMA values stamped on
 * them — survive across ticks. An entry remembers the exact base list it was
 * built from and {@link #aggregated} returns it only while that list is still
 * the stored one, so any base refetch or append invalidates it by identity,
 * with no bookkeeping to forget.
 *
 * <h3>Live-mode behaviour</h3>
 * The bean is always present but {@link #isActive()} stays {@code false}
 * outside backtest. {@link #slice} returns {@code null} for inactive cache,
 * which {@code MarketDataService} treats as a miss and routes through the
 * normal throttled fetch path. Live code pays one extra map-lookup per call.
 *
 * <h3>Parity guarantee</h3>
 * The slice over a populated series is byte-identical to what the source would
 * have returned for the same {@code [from, to]} window: same rows, ascending
 * timestamp order. Retention across days does not change that — the rows are
 * immutable, and a window is only ever served when {@code covers} says the
 * stored range fully contains the request.
 */
@Slf4j
@Component
public class BacktestMarketDataCache {

    /**
     * Backtest days a series may go untouched before eviction. Option series
     * are keyed by symbols that encode the expiry, so once a cycle rolls over
     * the old keys are never requested again; 5 days comfortably outlives any
     * intra-week gap without letting a year-long run accumulate every expired
     * series in memory.
     */
    private static final int EVICT_AFTER_DAYS = 5;

    /**
     * A cached series plus the window it was fetched over. The window is what
     * makes {@link #slice} honest: a series cached for one window cannot answer
     * a request that reaches outside it, and serving it anyway would return a
     * silently truncated history rather than a miss.
     */
    private record Series(List<MarketData> data, LocalDateTime from, LocalDateTime to) {

        boolean covers(LocalDateTime reqFrom, LocalDateTime reqTo) {
            if (reqFrom != null && from != null && reqFrom.isBefore(from)) return false;
            return !(reqTo != null && to != null && reqTo.isAfter(to));
        }
    }

    /** The stored window of a series, exposed so the caller can decide between a delta fetch and a full refetch. */
    public record Coverage(LocalDateTime from, LocalDateTime to) {}

    /**
     * A cached roll-up plus the identity of the base list it was built from.
     * Identity, not equality: any base refetch/append stores a new list object,
     * which invalidates this entry automatically.
     */
    private record Aggregated(List<MarketData> data, List<MarketData> builtFrom) {}

    private final Map<String, Series> seriesByKey = new ConcurrentHashMap<>();
    private final Map<String, Aggregated> aggregatedByKey = new ConcurrentHashMap<>();
    private final Map<String, Long> lastTouchedDay = new ConcurrentHashMap<>();

    private volatile LocalDateTime dayFrom;
    private volatile LocalDateTime dayTo;
    private volatile boolean active = false;
    private volatile long dayCounter = 0;

    /** Mark the cache active for a new backtest day; evict long-untouched series. */
    public void beginDay(LocalDateTime from, LocalDateTime to) {
        this.dayFrom = from;
        this.dayTo = to;
        this.dayCounter++;
        this.active = true;
        evictStale();
        log.debug("[cache] beginDay from={} to={} (day #{}, {} series retained)",
                from, to, dayCounter, seriesByKey.size());
    }

    /**
     * Mark the cache inactive. Series are retained (Phase 11) — the next
     * {@link #beginDay} decides what to evict.
     */
    public void endDay() {
        this.active = false;
        this.dayFrom = null;
        this.dayTo = null;
        log.debug("[cache] endDay — {} series retained", seriesByKey.size());
    }

    /** Drop everything. Not used by the replay loop; here for tests and manual resets. */
    public void clearAll() {
        seriesByKey.clear();
        aggregatedByKey.clear();
        lastTouchedDay.clear();
    }

    public boolean isActive() { return active; }

    /** Day-wide lower bound used by callers to fetch a superset window on miss. */
    public LocalDateTime dayFrom() { return dayFrom; }

    /** Day-wide upper bound used by callers to fetch a superset window on miss. */
    public LocalDateTime dayTo() { return dayTo; }

    /**
     * Store the series for {@code (symbol, interval)} together with the
     * {@code [from, to]} window it was actually fetched over. A later
     * {@code put} for the same key replaces the entry, so a wider refetch
     * upgrades the coverage rather than accumulating entries — and, because
     * the list object changes, drops any aggregated roll-up built from the
     * replaced one.
     */
    public void put(String symbol, String interval, List<MarketData> data,
                    LocalDateTime from, LocalDateTime to) {
        if (symbol == null || interval == null || data == null) return;
        String key = key(symbol, interval);
        seriesByKey.put(key, new Series(data, from, to));
        touch(key);
        log.debug("[cache] put symbol={} interval={} size={} window={}..{}",
                symbol, interval, data.size(), from, to);
    }

    /**
     * Phase 11: extend a stored series on the right with freshly fetched rows,
     * keeping everything already cached — and the SMA values stamped on it.
     * Rows at or before the stored upper bound are dropped (the delta fetch is
     * inclusive at its edges), so the series stays ascending and duplicate-free.
     *
     * <p>The extended series is stored as a <b>new</b> list object on purpose:
     * previously returned slices are unaffected (they hold references), and the
     * identity change invalidates any aggregated roll-up built from the old one.
     */
    public void appendRight(String symbol, String interval, List<MarketData> delta, LocalDateTime newTo) {
        if (symbol == null || interval == null) return;
        String key = key(symbol, interval);
        Series existing = seriesByKey.get(key);
        if (existing == null) {
            put(symbol, interval, delta, dayFrom, newTo);
            return;
        }
        List<MarketData> merged = new ArrayList<>(existing.data().size() + (delta == null ? 0 : delta.size()));
        merged.addAll(existing.data());
        int appended = 0;
        if (delta != null) {
            for (MarketData md : delta) {
                LocalDateTime ts = md == null ? null : md.getTimestamp();
                if (ts == null || (existing.to() != null && !ts.isAfter(existing.to()))) continue;
                merged.add(md);
                appended++;
            }
        }
        seriesByKey.put(key, new Series(merged, existing.from(), newTo));
        touch(key);
        log.debug("[cache] appendRight symbol={} interval={} appended={} window now {}..{}",
                symbol, interval, appended, existing.from(), newTo);
    }

    /** The stored window for {@code (symbol, interval)}, or {@code null} when nothing is cached. */
    public Coverage coverage(String symbol, String interval) {
        Series s = seriesByKey.get(key(symbol, interval));
        return s == null ? null : new Coverage(s.from(), s.to());
    }

    /**
     * The stored raw list for {@code (symbol, interval)} — the identity handle
     * the aggregated cache is validated against. {@code null} when absent.
     */
    public List<MarketData> storedData(String symbol, String interval) {
        Series s = seriesByKey.get(key(symbol, interval));
        return s == null ? null : s.data();
    }

    /**
     * The cached roll-up for {@code (symbol, interval)}, but only while it was
     * built from exactly {@code builtFrom} (identity comparison). Returns
     * {@code null} when absent or stale.
     */
    public List<MarketData> aggregated(String symbol, String interval, List<MarketData> builtFrom) {
        Aggregated a = aggregatedByKey.get(key(symbol, interval));
        if (a == null || a.builtFrom() != builtFrom) return null;
        return a.data();
    }

    /** A stale-or-fresh aggregated entry with the base list it was built from. */
    public record AggregatedEntry(List<MarketData> data, List<MarketData> builtFrom) {}

    /**
     * The stored roll-up for {@code (symbol, interval)} regardless of whether
     * its base is still current. The caller checks whether the current base is
     * an identity-extension of {@code builtFrom} and, if so, upgrades the entry
     * by rebuilding only the tail instead of the whole series — a full rebuild
     * per day was measured at seconds/day of BigDecimal restamping.
     */
    public AggregatedEntry aggregatedEntry(String symbol, String interval) {
        Aggregated a = aggregatedByKey.get(key(symbol, interval));
        return a == null ? null : new AggregatedEntry(a.data(), a.builtFrom());
    }

    /** Store a roll-up together with the base list identity it was built from. */
    public void putAggregated(String symbol, String interval, List<MarketData> data, List<MarketData> builtFrom) {
        if (symbol == null || interval == null || data == null || builtFrom == null) return;
        aggregatedByKey.put(key(symbol, interval), new Aggregated(data, builtFrom));
    }

    /**
     * Return candles in the cached series for {@code (symbol, interval)} whose
     * timestamp lies in {@code [from, to]}. Returns {@code null} when the cache
     * is inactive, the series isn't populated yet, or the cached window does not
     * cover the request — the caller treats all three as a miss and falls through
     * to the fetcher (possibly via {@link #appendRight}).
     *
     * <p>The coverage check is what lets a caller with a longer lookback than the
     * day window — {@code EodDowntrendDetectionService}, whose ATR wants ~30 days
     * and whose SMA grid wants up to 35 — get its history. Without it the day's
     * already-cached series answers the request and the extra history is dropped
     * on the floor with no miss and no log line.
     */
    public List<MarketData> slice(String symbol, String interval, LocalDateTime from, LocalDateTime to) {
        if (!active) return null;
        String key = key(symbol, interval);
        Series series = seriesByKey.get(key);
        if (series == null) return null;
        if (!series.covers(from, to)) {
            log.debug("[cache] miss symbol={} interval={} — request {}..{} outside cached {}..{}",
                    symbol, interval, from, to, series.from(), series.to());
            return null;
        }
        touch(key);

        // Sources return ascending-by-timestamp lists; we preserve that here so
        // strategy code can rely on list.get(size-1) being the latest candle.
        // Binary search for the start: a retained series can hold months of
        // rows (Phase 11), and a per-call linear scan from index 0 would grow
        // with run length.
        List<MarketData> full = series.data();
        int start = lowerBound(full, from);
        List<MarketData> result = new ArrayList<>(Math.max(16, full.size() - start));
        for (int i = start; i < full.size(); i++) {
            MarketData md = full.get(i);
            LocalDateTime ts = md == null ? null : md.getTimestamp();
            if (ts == null) continue;
            if (to != null && ts.isAfter(to)) break;
            result.add(md);
        }
        return result;
    }

    /** Index of the first candle with timestamp ≥ {@code from} (0 when {@code from} is null). */
    private static int lowerBound(List<MarketData> data, LocalDateTime from) {
        if (from == null) return 0;
        int lo = 0, hi = data.size();
        while (lo < hi) {
            int mid = (lo + hi) >>> 1;
            MarketData md = data.get(mid);
            LocalDateTime ts = md == null ? null : md.getTimestamp();
            // Null timestamps are skipped by the caller; treat them as "before"
            // so the scan simply starts one element earlier.
            if (ts == null || ts.isBefore(from)) lo = mid + 1;
            else hi = mid;
        }
        return lo;
    }

    private void touch(String key) {
        lastTouchedDay.put(key, dayCounter);
    }

    private void evictStale() {
        long cutoff = dayCounter - EVICT_AFTER_DAYS;
        if (cutoff <= 0) return;
        int before = seriesByKey.size();
        lastTouchedDay.entrySet().removeIf(e -> {
            if (e.getValue() >= cutoff) return false;
            seriesByKey.remove(e.getKey());
            aggregatedByKey.remove(e.getKey());
            return true;
        });
        int evicted = before - seriesByKey.size();
        if (evicted > 0) {
            log.debug("[cache] evicted {} series untouched for {} days", evicted, EVICT_AFTER_DAYS);
        }
    }

    private static String key(String symbol, String interval) {
        return symbol + "|" + interval;
    }
}
