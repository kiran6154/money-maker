package com.moneymaker.login.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Standard wrapper returned by every broker login operation.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class BrokerLoginResponse {

    private boolean success;
    private String message;
    private String errorCode;
    private BrokerSession session;

    public static BrokerLoginResponse ok(BrokerSession session) {
        return BrokerLoginResponse.builder()
                .success(true)
                .message("Login successful")
                .session(session)
                .build();
    }

    public static BrokerLoginResponse fail(String code, String message) {
        return BrokerLoginResponse.builder()
                .success(false)
                .errorCode(code)
                .message(message)
                .build();
    }
}

