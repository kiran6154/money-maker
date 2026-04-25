package com.moneymaker.login.model;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.HashMap;
import java.util.Map;

/**
 * Inputs needed to complete a broker login flow. Different brokers
 * use different fields:
 * <ul>
 *   <li>Zerodha: {@code requestToken} (returned via OAuth redirect).</li>
 *   <li>Groww: {@code totp} (TOTP-based access-token issuance).</li>
 * </ul>
 * Use {@code extraParams} for any broker-specific overrides.
 */
@Data
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class BrokerLoginRequest {

    private String requestToken;
    private String totp;

    @Builder.Default
    private Map<String, String> extraParams = new HashMap<>();
}

