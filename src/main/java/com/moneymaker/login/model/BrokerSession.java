package com.moneymaker.login.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * Standard, broker-agnostic representation of an authenticated broker session.
 * Every {@code BrokerLoginService} implementation MUST translate its native
 * API response into this type so the rest of the application sees a single,
 * uniform contract.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class BrokerSession {

    /** Which broker issued this session. */
    private Broker broker;

    /** Broker-side user identifier (e.g. Zerodha client ID). */
    private String userId;

    /** Bearer/access token used to call broker REST APIs. */
    private String accessToken;

    /** Optional refresh token (Groww supports this; Zerodha does not). */
    private String refreshToken;

    /** Optional public token (Zerodha streaming). */
    private String publicToken;

    /** When this session was issued. */
    private Instant loginAt;

    /** When this session expires. */
    private Instant expiresAt;

    /** Whether the session is currently considered valid. */
    private boolean valid;

    /** Raw broker response, kept for debugging / broker-specific consumers. */
    @Builder.Default
    private Map<String, Object> raw = new HashMap<>();

    public boolean isExpired() {
        return expiresAt != null && Instant.now().isAfter(expiresAt);
    }
}

