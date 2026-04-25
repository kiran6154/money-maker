package com.moneymaker.broker.angelone;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.Data;

/**
 * Raw payload returned by Angel One SmartAPI
 * {@code POST /rest/auth/angelbroking/user/v1/loginByPassword}.
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class AngelOneTokenResponse {

    private boolean status;
    private String message;
    private String errorcode;
    private Data data;

    @lombok.Data
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Data {
        @JsonProperty("jwtToken")
        private String jwtToken;
        @JsonProperty("refreshToken")
        private String refreshToken;
        @JsonProperty("feedToken")
        private String feedToken;
    }
}

