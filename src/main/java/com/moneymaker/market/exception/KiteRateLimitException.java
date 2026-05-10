package com.moneymaker.market.exception;

/**
 * Thrown by {@code MarketDataService} when the underlying broker call fails
 * specifically due to rate limiting ("Too many requests" / HTTP 429). Wired
 * to Resilience4j {@code @Retry} so only true rate-limit hits trigger backoff
 * — auth failures, bad symbols, network-down errors fall through immediately.
 */
public class KiteRateLimitException extends RuntimeException {

    public KiteRateLimitException(String message, Throwable cause) {
        super(message, cause);
    }
}
