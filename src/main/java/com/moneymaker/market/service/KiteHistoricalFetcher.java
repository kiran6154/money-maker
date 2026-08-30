package com.moneymaker.market.service;

import com.moneymaker.entity.MarketData;
import com.moneymaker.market.exception.KiteRateLimitException;
import com.moneymaker.market.provider.MarketDataProvider;
import com.moneymaker.market.provider.MarketDataProviderFactory;
import com.moneymaker.telegram.NotificationService;
import io.github.resilience4j.ratelimiter.annotation.RateLimiter;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/**
 * Throttled HTTP wrapper around the active {@link MarketDataProvider}. Lives
 * in a sibling bean (not inside {@link MarketDataService}) because Spring AOP
 * proxies only intercept calls that arrive through the bean reference — a
 * cache-then-fetch path inside one class would skip {@code @RateLimiter} /
 * {@code @Retry} on self-invocation.
 *
 * <p>The provider itself comes from {@link MarketDataProviderFactory}, which owns
 * the "which provider is running" decision — see that class for the rule.
 *
 * <p>Behaviour is identical to the previous {@code MarketDataService.fetchHistoricalData}:
 * the call is permit-acquired through {@code kiteHistorical}, retried on
 * rate-limit, and surfaces "market data down/up" notifications.
 */
@Slf4j
@Service
public class KiteHistoricalFetcher {

    /** Resilience4j instance name configured in application.properties. */
    private static final String LIMITER_NAME = "kiteHistorical";

    private final MarketDataProvider marketDataProvider;
    private final NotificationService notifier;

    /**
     * Takes the {@link MarketDataProviderFactory} rather than a single
     * {@link MarketDataProvider} bean (GAPS #20). The old single-bean parameter is
     * what made a second provider an ambiguous injection and forced a
     * {@code @Primary} annotation to arbitrate; going through the factory moves
     * that decision into one readable, testable place.
     */
    public KiteHistoricalFetcher(MarketDataProviderFactory providerFactory,
                                 NotificationService notifier) {
        this.marketDataProvider = Objects.requireNonNull(providerFactory, "providerFactory must not be null")
                .active();
        this.notifier = Objects.requireNonNull(notifier, "notifier must not be null");
    }

    /**
     * Single throttled hop to the broker. Other failures propagate as
     * {@link RuntimeException}; rate-limit failures are rethrown as
     * {@link KiteRateLimitException} so the {@code @Retry} instance can
     * pick them up.
     */
    @RateLimiter(name = LIMITER_NAME)
    @Retry(name = LIMITER_NAME)
    public List<MarketData> fetch(String symbol, LocalDateTime from, LocalDateTime to, String interval) {
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
                log.warn("Provider rate-limit hit for symbol={}, interval={} — will retry", symbol, interval);
                throw new KiteRateLimitException("Rate limited: " + ex.getMessage(), ex);
            }
            String reason = ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage();
            notifier.alertMarketDataDown(reason);
            log.error("Error fetching historical data for symbol: {} using provider: {}",
                    symbol, marketDataProvider.getName(), ex);
            throw new RuntimeException("Failed to fetch market data: " + ex.getMessage(), ex);
        }
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
