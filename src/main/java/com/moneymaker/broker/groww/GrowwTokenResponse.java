package com.moneymaker.broker.groww;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.Map;

/**
 * Raw payload returned by Groww's access-token endpoint. The exact shape
 * varies between API versions; only fields we need are mapped, the rest are
 * kept in {@code raw} on the standard {@code BrokerSession}.
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class GrowwTokenResponse {

    private String status;
    private String message;
    private Payload payload;

    @lombok.Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Payload {
        private String accessToken;
        private String refreshToken;
        private String userId;
        private Long expiresIn;     // seconds
        private Long expiryEpochMs; // absolute, when provided
        private Map<String, Object> extras;
    }
}

