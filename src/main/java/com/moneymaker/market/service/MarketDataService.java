package com.moneymaker.market.service;

import com.moneymaker.entity.MarketData;
import com.moneymaker.market.exception.KiteRateLimitException;
import com.moneymaker.market.provider.MarketDataProvider;
import com.moneymaker.telegram.NotificationService;
import io.github.resilience4j.ratelimiter.annotation.RateLimiter;
import io.github.resilience4j.retry.annotation.Retry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

@Service
public class MarketDataService {
    private static final Logger logger = LoggerFactory.getLogger(MarketDataService.class);

    /** Resilience4j instance name configured in application.properties. */
    private static final String LIMITER_NAME = "kiteHistorical";

    private final MarketDataProvider marketDataProvider;
    private final NotificationService notifier;

    public MarketDataService(MarketDataProvider marketDataProvider,
                             NotificationService notifier) {
        this.marketDataProvider = Objects.requireNonNull(marketDataProvider, "marketDataProvider must not be null");
        this.notifier = Objects.requireNonNull(notifier, "notifier must not be null");
        logger.info("MarketDataService initialized with provider: {}", marketDataProvider.getName());
    }

    /**
     * Fetches historical candles via the active provider. Throttled by the
     * {@code kiteHistorical} Resilience4j RateLimiter and retried on rate-limit
     * failures (only) by the matching Retry instance. Other failures propagate
     * immediately as {@link RuntimeException}.
     */
    @RateLimiter(name = LIMITER_NAME)
    @Retry(name = LIMITER_NAME)
    public List<MarketData> fetchHistoricalData(String symbol, LocalDateTime from, LocalDateTime to, String interval) {
        Objects.requireNonNull(symbol, "symbol must not be null");
        Objects.requireNonNull(from, "from must not be null");
        Objects.requireNonNull(to, "to must not be null");
        Objects.requireNonNull(interval, "interval must not be null");

        try {
            List<MarketData> result = marketDataProvider.fetchHistoricalData(symbol, from, to, interval);
            // Successful fetch — clear any previous "down" alert so the next
            // failure (potentially with a different reason) gets reported.
            notifier.alertMarketDataUp();
            return result;
        } catch (Exception ex) {
            if (isRateLimit(ex)) {
                logger.warn("Provider rate-limit hit for symbol={}, interval={} — will retry", symbol, interval);
                throw new KiteRateLimitException("Rate limited: " + ex.getMessage(), ex);
            }
            // After-retry / non-rate-limit failure — alert (deduped at the
            // notification layer, so identical reasons fire once until recovery).
            String reason = ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage();
            notifier.alertMarketDataDown(reason);
            logger.error("Error fetching historical data for symbol: {} using provider: {}", symbol, marketDataProvider.getName(), ex);
            throw new RuntimeException("Failed to fetch market data: " + ex.getMessage(), ex);
        }
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
        return marketDataProvider.getName();
    }

    /**
     * Walks the cause chain looking for a "too many requests" / 429 marker in
     * any throwable's message. Conservative — only matches text the broker
     * actually emits for rate limiting.
     */
    private static boolean isRateLimit(Throwable t) {
        while (t != null) {
            String msg = t.getMessage();
            if (msg != null) {
                String lower = msg.toLowerCase(Locale.ROOT);
                if (lower.contains("too many requests") || lower.contains("429")) {
                    return true;
                }
            }
            t = t.getCause();
        }
        return false;
    }
}
