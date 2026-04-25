package com.moneymaker.broker.groww;

import com.moneymaker.login.config.BrokerProperties;
import com.moneymaker.login.exception.BrokerLoginException;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerLoginRequest;
import com.moneymaker.login.model.BrokerLoginResponse;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.login.service.BrokerLoginService;
import com.moneymaker.login.util.TotpGenerator;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;

import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.Map;

/**
 * Groww login adapter. Groww uses a TOTP-driven flow to mint a daily access
 * token via {@code POST /v1/token/api/access} with body {@code {api_key, totp}}.
 * The TOTP is derived from the Base32 secret stored in
 * {@code broker.groww.totp-secret}; alternatively a one-time TOTP can be
 * supplied through {@link BrokerLoginRequest#getTotp()} (e.g. typed in by
 * the user in the UI).
 */
@Slf4j
@Service
@ConditionalOnProperty(name = "broker.groww.enabled", havingValue = "true", matchIfMissing = true)
public class GrowwLoginService implements BrokerLoginService {

    private final BrokerProperties properties;
    private final RestTemplate http;

    public GrowwLoginService(BrokerProperties properties, RestTemplate brokerRestTemplate) {
        this.properties = properties;
        this.http = brokerRestTemplate;
    }

    @Override
    public Broker getBroker() {
        return Broker.GROWW;
    }

    @Override
    public String getLoginUrl() {
        // Groww has no hosted OAuth page – send the user to our manual form.
        return "/login/manual?broker=GROWW";
    }

    @Override
    public BrokerLoginResponse completeLogin(BrokerLoginRequest request) {
        BrokerProperties.Groww cfg = properties.getGroww();
        if (cfg.getApiKey() == null || cfg.getApiKey().isBlank()) {
            throw new BrokerLoginException("Groww api-key is not configured", "MISSING_CREDENTIALS", null);
        }
        String totp = (request != null && request.getTotp() != null && !request.getTotp().isBlank())
                ? request.getTotp()
                : TotpGenerator.generate(cfg.getTotpSecret());

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-API-KEY", cfg.getApiKey());

        Map<String, String> body = new HashMap<>();
        body.put("api_key", cfg.getApiKey());
        body.put("totp", totp);

        try {
            ResponseEntity<GrowwTokenResponse> resp = http.exchange(
                    cfg.getApiBaseUrl() + "/v1/token/api/access",
                    HttpMethod.POST,
                    new HttpEntity<>(body, headers),
                    GrowwTokenResponse.class);

            GrowwTokenResponse payload = resp.getBody();
            if (payload == null || payload.getPayload() == null
                    || payload.getPayload().getAccessToken() == null) {
                return BrokerLoginResponse.fail("EMPTY_RESPONSE",
                        payload != null ? payload.getMessage() : "Empty response from Groww");
            }
            return BrokerLoginResponse.ok(toSession(payload));
        } catch (RestClientException e) {
            log.error("Groww access-token call failed", e);
            return BrokerLoginResponse.fail("HTTP_ERROR", e.getMessage());
        }
    }

    @Override
    public boolean validateSession(BrokerSession session) {
        if (session == null || session.getAccessToken() == null) return false;
        BrokerProperties.Groww cfg = properties.getGroww();
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "Bearer " + session.getAccessToken());
        headers.set("X-API-KEY", cfg.getApiKey());
        try {
            ResponseEntity<String> resp = http.exchange(
                    cfg.getApiBaseUrl() + "/v1/user/profile",
                    HttpMethod.GET,
                    new HttpEntity<>(headers),
                    String.class);
            return resp.getStatusCode().is2xxSuccessful();
        } catch (Exception e) {
            log.warn("Groww session validation failed: {}", e.getMessage());
            return false;
        }
    }

    @Override
    public void logout(BrokerSession session) {
        // Groww access tokens are short-lived; nothing to invalidate server-side.
        log.debug("Groww logout is a no-op (token will expire naturally).");
    }

    /* ---------- mapping ---------- */

    private BrokerSession toSession(GrowwTokenResponse payload) {
        GrowwTokenResponse.Payload p = payload.getPayload();
        Map<String, Object> raw = new HashMap<>();
        raw.put("status", payload.getStatus());
        raw.put("payload", p);

        Instant expiresAt;
        if (p.getExpiryEpochMs() != null) {
            expiresAt = Instant.ofEpochMilli(p.getExpiryEpochMs());
        } else if (p.getExpiresIn() != null) {
            expiresAt = Instant.now().plusSeconds(p.getExpiresIn());
        } else {
            // Default: end of day.
            expiresAt = Instant.now().truncatedTo(ChronoUnit.DAYS).plus(1, ChronoUnit.DAYS);
        }

        return BrokerSession.builder()
                .broker(Broker.GROWW)
                .userId(p.getUserId())
                .accessToken(p.getAccessToken())
                .refreshToken(p.getRefreshToken())
                .loginAt(Instant.now())
                .expiresAt(expiresAt)
                .valid(true)
                .raw(raw)
                .build();
    }
}

