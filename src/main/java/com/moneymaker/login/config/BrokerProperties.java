package com.moneymaker.login.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Centralised broker configuration.
 *
 * <pre>
 * broker.active=zerodha
 * broker.zerodha.api-key=...
 * broker.zerodha.api-secret=...
 * broker.zerodha.user-id=...
 * broker.zerodha.redirect-url=http://localhost:8080/login/callback
 *
 * broker.groww.api-key=...
 * broker.groww.api-secret=...
 * broker.groww.totp-secret=...
 * </pre>
 */
@Data
@Component
@ConfigurationProperties(prefix = "broker")
public class BrokerProperties {

    /** Currently active broker (zerodha | groww). */
    private String active = "zerodha";

    private Zerodha zerodha = new Zerodha();
    private Groww groww = new Groww();
    private AngelOne angelOne = new AngelOne();

    @Data
    public static class Zerodha {
        private boolean enabled = true;
        private String apiKey;
        private String apiSecret;
        private String userId;
        private String redirectUrl = "http://localhost:8080/login/callback";
        /** Override base URL only for testing. */
        private String apiBaseUrl = "https://api.kite.trade";
        private String loginBaseUrl = "https://kite.zerodha.com/connect/login";
    }

    @Data
    public static class Groww {
        private boolean enabled = false;
        private String apiKey;
        private String apiSecret;
        /** Base32 secret used to derive a TOTP for daily access-token issuance. */
        private String totpSecret;
        private String apiBaseUrl = "https://api.groww.in";
    }

    @Data
    public static class AngelOne {
        private boolean enabled = false;
        /** SmartAPI private key (a.k.a. apiKey). */
        private String apiKey;
        /** Angel One client (login) code, e.g. A123456. */
        private String clientCode;
        /** Account / API password (M-PIN). */
        private String password;
        /** Base32 TOTP secret printed when enabling 2FA. */
        private String totpSecret;
        private String apiBaseUrl = "https://apiconnect.angelone.in";
    }
}

