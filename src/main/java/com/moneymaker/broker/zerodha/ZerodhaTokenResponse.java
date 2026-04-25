package com.moneymaker.broker.zerodha;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import lombok.Data;

import java.util.Map;

/**
 * Raw payload returned by {@code POST https://api.kite.trade/session/token}.
 * Kite uses snake_case JSON ({@code access_token}, {@code public_token},
 * {@code user_id}, {@code error_type}) so we apply
 * {@link PropertyNamingStrategies.SnakeCaseStrategy} on both the outer and
 * inner DTOs – without this Jackson silently leaves every token field null
 * and login appears to "succeed with empty body".
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public class ZerodhaTokenResponse {

    private String status;
    private String message;
    private String errorType;
    private Data data;

    @lombok.Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public static class Data {
        private String userId;
        private String userName;
        private String userShortname;
        private String email;
        private String userType;
        private String broker;
        private String accessToken;
        private String publicToken;
        private String refreshToken;
        private String apiKey;
        private Map<String, Object> meta;
    }
}
