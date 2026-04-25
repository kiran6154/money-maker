package com.moneymaker.broker.groww;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.util.Map;

/**
 * Raw payload returned by Groww's access-token endpoint. Groww uses
 * snake_case JSON; {@link JsonNaming} ensures fields like
 * {@code access_token}, {@code refresh_token}, {@code expires_in} bind to
 * our camelCase properties (otherwise they end up null and login appears
 * to "succeed with empty body").
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class GrowwTokenResponse {

    private String status;
    private String message;
    private Payload payload;

    @lombok.Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public static class Payload {
        private String accessToken;
        private String refreshToken;
        private String userId;
        private Long expiresIn;     // seconds
        private Long expiryEpochMs; // absolute, when provided
        private Map<String, Object> extras;
    }
}
