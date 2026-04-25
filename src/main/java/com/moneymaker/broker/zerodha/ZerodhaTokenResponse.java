package com.moneymaker.broker.zerodha;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.Data;

import java.util.Map;

/**
 * Raw payload returned by {@code POST https://api.kite.trade/session/token}.
 * Mapped to the standard {@code BrokerSession} by {@link ZerodhaLoginService}.
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class ZerodhaTokenResponse {

    private String status;
    private String message;
    private String errorType;
    private Data data;

    @lombok.Data
    @JsonIgnoreProperties(ignoreUnknown = true)
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

