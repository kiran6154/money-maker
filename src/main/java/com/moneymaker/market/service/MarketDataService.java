package com.moneymaker.market.service;

import com.moneymaker.backtesting.BacktestMarketDataCache;
import com.moneymaker.entity.MarketData;
import lombok.extern.slf4j.Slf4j;
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

    public MarketDataService(KiteHistoricalFetcher fetcher,
                             BacktestMarketDataCache cache) {
        this.fetcher = Objects.requireNonNull(fetcher, "fetcher must not be null");
        this.cache = Objects.requireNonNull(cache, "cache must not be null");
        log.info("MarketDataService initialized with provider: {}", fetcher.getActiveProvider());
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

            // Backtest cache miss — fetch the entire day's [dayFrom, dayTo]
            // superset once, cache it, then slice. All subsequent ticks for
            // this (symbol, interval) hit the cache.
            LocalDateTime wideFrom = cache.dayFrom() != null ? cache.dayFrom() : from;
            LocalDateTime wideTo   = cache.dayTo()   != null ? cache.dayTo()   : to;
            List<MarketData> wide = fetcher.fetch(symbol, wideFrom, wideTo, interval);
            cache.put(symbol, interval, wide);

            List<MarketData> sliced = cache.slice(symbol, interval, from, to);
            return sliced != null ? sliced : wide;
        }

        // Live path — exact same call shape as before Phase 1.
        return fetcher.fetch(symbol, from, to, interval);
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
        return fetcher.getActiveProvider();
    }
}
