package com.moneymaker.broker.angelone;

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
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Angel One SmartAPI login adapter.
 *
 * Login flow (per ui-java/docs/10-TRADE-AUTOMATION-REQUIREMENTS.md FR-01):
 * <ol>
 *   <li>Generate a 6-digit TOTP from the configured Base32 secret.</li>
 *   <li>POST {@code /rest/auth/angelbroking/user/v1/loginByPassword} with
 *       JSON body {@code {clientcode, password, totp}} and the standard
 *       SmartAPI headers (X-PrivateKey, X-UserType, X-SourceID, …).</li>
 *   <li>Map {@code data.jwtToken} into our standard {@link BrokerSession}.</li>
 * </ol>
 *
 * Tokens are valid for ~24 hours.
 */
@Slf4j
@Service
@ConditionalOnProperty(name = "broker.angel-one.enabled", havingValue = "true", matchIfMissing = true)
public class AngelOneLoginService implements BrokerLoginService {

    private static final String LOGIN_PATH    = "/rest/auth/angelbroking/user/v1/loginByPassword";
    private static final String PROFILE_PATH  = "/rest/secure/angelbroking/user/v1/getProfile";
    private static final String LOGOUT_PATH   = "/rest/secure/angelbroking/user/v1/logout";

    private final BrokerProperties properties;
    private final RestTemplate http;

    public AngelOneLoginService(BrokerProperties properties, RestTemplate brokerRestTemplate) {
        this.properties = properties;
        this.http = brokerRestTemplate;
    }

    @Override
    public Broker getBroker() {
        return Broker.ANGEL_ONE;
    }

    @Override
    public String getLoginUrl() {
        // Angel One has no hosted OAuth page – send the user to our manual TOTP form.
        return "/login/manual?broker=ANGEL_ONE";
    }

    @Override
    public BrokerLoginResponse completeLogin(BrokerLoginRequest request) {
        BrokerProperties.AngelOne cfg = properties.getAngelOne();
        if (cfg.getApiKey() == null || cfg.getApiKey().isBlank()
                || cfg.getClientCode() == null || cfg.getClientCode().isBlank()
                || cfg.getPassword() == null || cfg.getPassword().isBlank()) {
            throw new BrokerLoginException(
                    "Angel One api-key/client-code/password are not configured",
                    "MISSING_CREDENTIALS", null);
        }

        String totp = (request != null && request.getTotp() != null && !request.getTotp().isBlank())
                ? request.getTotp()
                : TotpGenerator.generate(cfg.getTotpSecret());

        HttpHeaders headers = smartApiHeaders(cfg.getApiKey());

        Map<String, String> body = new LinkedHashMap<>();
        body.put("clientcode", cfg.getClientCode());
        body.put("password",   cfg.getPassword());
        body.put("totp",       totp);

        try {
            ResponseEntity<AngelOneTokenResponse> resp = http.exchange(
                    cfg.getApiBaseUrl() + LOGIN_PATH,
                    HttpMethod.POST,
                    new HttpEntity<>(body, headers),
                    AngelOneTokenResponse.class);

            AngelOneTokenResponse payload = resp.getBody();
            if (payload == null || !payload.isStatus()
                    || payload.getData() == null
                    || payload.getData().getJwtToken() == null) {
                return BrokerLoginResponse.fail(
                        payload != null ? payload.getErrorcode() : "EMPTY_RESPONSE",
                        payload != null ? payload.getMessage() : "Empty response from Angel One");
            }
            return BrokerLoginResponse.ok(toSession(payload, cfg));
        } catch (RestClientException e) {
            log.error("Angel One loginByPassword call failed", e);
            return BrokerLoginResponse.fail("HTTP_ERROR", e.getMessage());
        }
    }

    @Override
    public boolean validateSession(BrokerSession session) {
        if (session == null || session.getAccessToken() == null) return false;
        BrokerProperties.AngelOne cfg = properties.getAngelOne();
        HttpHeaders headers = smartApiHeaders(cfg.getApiKey());
        headers.setBearerAuth(session.getAccessToken());
        try {
            ResponseEntity<String> resp = http.exchange(
                    cfg.getApiBaseUrl() + PROFILE_PATH,
                    HttpMethod.GET,
                    new HttpEntity<>(headers),
                    String.class);
            return resp.getStatusCode().is2xxSuccessful();
        } catch (Exception e) {
            log.warn("Angel One session validation failed: {}", e.getMessage());
            return false;
        }
    }

    @Override
    public void logout(BrokerSession session) {
        if (session == null || session.getAccessToken() == null) return;
        BrokerProperties.AngelOne cfg = properties.getAngelOne();
        try {
            HttpHeaders headers = smartApiHeaders(cfg.getApiKey());
            headers.setBearerAuth(session.getAccessToken());
            Map<String, String> body = Map.of("clientcode",
                    session.getUserId() == null ? cfg.getClientCode() : session.getUserId());
            http.exchange(cfg.getApiBaseUrl() + LOGOUT_PATH,
                    HttpMethod.POST,
                    new HttpEntity<>(body, headers),
                    String.class);
        } catch (Exception e) {
            log.warn("Angel One logout failed (ignored): {}", e.getMessage());
        }
    }

    /* ---------- helpers ---------- */

    private HttpHeaders smartApiHeaders(String apiKey) {
        HttpHeaders h = new HttpHeaders();
        h.setContentType(MediaType.APPLICATION_JSON);
        h.setAccept(java.util.List.of(MediaType.APPLICATION_JSON));
        h.set("X-UserType",      "USER");
        h.set("X-SourceID",      "WEB");
        h.set("X-ClientLocalIP", "127.0.0.1");
        h.set("X-ClientPublicIP","127.0.0.1");
        h.set("X-MACAddress",    "00:00:00:00:00:00");
        h.set("X-PrivateKey",    apiKey);
        return h;
    }

    private BrokerSession toSession(AngelOneTokenResponse payload, BrokerProperties.AngelOne cfg) {
        AngelOneTokenResponse.Data d = payload.getData();
        Map<String, Object> raw = new HashMap<>();
        raw.put("status", payload.isStatus());
        raw.put("message", payload.getMessage());
        raw.put("data", d);

        return BrokerSession.builder()
                .broker(Broker.ANGEL_ONE)
                .userId(cfg.getClientCode())
                .accessToken(d.getJwtToken())
                .refreshToken(d.getRefreshToken())
                .publicToken(d.getFeedToken())
                .loginAt(Instant.now())
                // SmartAPI tokens are valid for ~24 hours.
                .expiresAt(Instant.now().plusSeconds(24L * 3600L))
                .valid(true)
                .raw(raw)
                .build();
    }
}

