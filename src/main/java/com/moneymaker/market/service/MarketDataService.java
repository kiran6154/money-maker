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
            List<MarketData> hit = cache.slice(symbol, interval, from, to);
            if (hit != null && !hit.isEmpty()) {
                return hit;
            }

            // Backtest cache miss — fetch a superset once, cache it, then slice.
            // All subsequent ticks for this (symbol, interval) hit the cache.
            //
            // The superset is the UNION of the day window and what the caller
            // asked for, never just the day window: EodDowntrendDetectionService
            // wants ~30 days for its ATR and up to 35 for its SMA grid, and
            // narrowing to [dayFrom, dayTo] silently handed it a few days and a
            // partial average. For the tick loop, whose windows already sit
            // inside the day window, the union *is* the day window — identical
            // behaviour and the same single fetch per (symbol, interval).
            LocalDateTime wideFrom = min(from, cache.dayFrom());
            LocalDateTime wideTo   = max(to, cache.dayTo());
            List<MarketData> wide = fetchFromSource(symbol, wideFrom, wideTo, interval);
            cache.put(symbol, interval, wide, wideFrom, wideTo);

            List<MarketData> sliced = cache.slice(symbol, interval, from, to);
            return sliced != null ? sliced : wide;
        }

        // Live path — exact same call shape as before Phase 1.
        return fetchFromSource(symbol, from, to, interval);
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
