package com.moneymaker.broker.zerodha;

import com.moneymaker.login.config.BrokerProperties;
import com.moneymaker.login.exception.BrokerLoginException;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerLoginRequest;
import com.moneymaker.login.model.BrokerLoginResponse;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.login.model.HeartbeatResult;
import com.moneymaker.login.model.HeartbeatStatus;
import com.moneymaker.login.service.BrokerLoginService;
import com.zerodhatech.kiteconnect.KiteConnect;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.HashMap;
import java.util.Map;

/**
 * Zerodha Kite Connect login adapter.
 *
 * Flow:
 * <ol>
 *   <li>User is redirected to {@link #getLoginUrl()} (Kite hosted login).</li>
 *   <li>Kite redirects back to our callback with {@code request_token}.</li>
 *   <li>{@link #completeLogin(BrokerLoginRequest)} POSTs
 *       {@code api_key + request_token + checksum(SHA256(api_key+request_token+api_secret))}
 *       to {@code /session/token} and converts the response to a
 *       {@link BrokerSession}.</li>
 * </ol>
 */
@Slf4j
@Service
@ConditionalOnProperty(name = "broker.zerodha.enabled", havingValue = "true", matchIfMissing = true)
public class ZerodhaLoginService implements BrokerLoginService {

    private final BrokerProperties properties;
    private final RestTemplate http;
    private final KiteConnect sharedKiteConnect;

    public ZerodhaLoginService(BrokerProperties properties,
                               RestTemplate brokerRestTemplate,
                               @Qualifier("sharedKiteConnect") KiteConnect sharedKiteConnect) {
        this.properties = properties;
        this.http = brokerRestTemplate;
        this.sharedKiteConnect = sharedKiteConnect;
    }

    @Override
    public Broker getBroker() {
        return Broker.ZERODHA;
    }

    @Override
    public String getLoginUrl() {
        BrokerProperties.Zerodha cfg = properties.getZerodha();
        return UriComponentsBuilder.fromHttpUrl(cfg.getLoginBaseUrl())
                .queryParam("api_key", cfg.getApiKey())
                .queryParam("v", "3")
                .toUriString();
    }

    @Override
    public BrokerLoginResponse completeLogin(BrokerLoginRequest request) {
        if (request == null || request.getRequestToken() == null || request.getRequestToken().isBlank()) {
            throw new BrokerLoginException("request_token is required for Zerodha login",
                    "MISSING_REQUEST_TOKEN", null);
        }
        BrokerProperties.Zerodha cfg = properties.getZerodha();
        if (cfg.getApiKey() == null || cfg.getApiSecret() == null) {
            throw new BrokerLoginException("Zerodha api-key/api-secret are not configured",
                    "MISSING_CREDENTIALS", null);
        }

        String checksum = sha256(cfg.getApiKey() + request.getRequestToken() + cfg.getApiSecret());

        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_FORM_URLENCODED);
        headers.set("X-Kite-Version", "3");

        MultiValueMap<String, String> body = new LinkedMultiValueMap<>();
        body.add("api_key", cfg.getApiKey());
        body.add("request_token", request.getRequestToken());
        body.add("checksum", checksum);

        try {
            ResponseEntity<ZerodhaTokenResponse> resp = http.exchange(
                    cfg.getApiBaseUrl() + "/session/token",
                    HttpMethod.POST,
                    new HttpEntity<>(body, headers),
                    ZerodhaTokenResponse.class);

            ZerodhaTokenResponse payload = resp.getBody();
            if (payload == null || payload.getData() == null
                    || payload.getData().getAccessToken() == null) {
                String diag;
                if (payload == null) {
                    diag = "Empty response body from Zerodha";
                } else if (payload.getMessage() != null && !payload.getMessage().isBlank()) {
                    diag = payload.getMessage();
                } else {
                    diag = "Zerodha responded with status=" + payload.getStatus()
                            + " but access_token was missing (data="
                            + (payload.getData() == null ? "null" : "present") + ")";
                }
                log.error("Zerodha session/token unexpected payload: {}", payload);
                return BrokerLoginResponse.fail(
                        payload != null && payload.getErrorType() != null ? payload.getErrorType() : "EMPTY_RESPONSE",
                        diag);
            }
            BrokerSession session = toSession(payload);
            applyKiteSession(session);
            return BrokerLoginResponse.ok(session);
        } catch (RestClientException e) {
            log.error("Zerodha session/token call failed", e);
            String msg = e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName();
            return BrokerLoginResponse.fail("HTTP_ERROR", msg);
        }
    }

    @Override
    public boolean validateSession(BrokerSession session) {
        if (session == null || session.getAccessToken() == null) return false;
        BrokerProperties.Zerodha cfg = properties.getZerodha();
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "token " + cfg.getApiKey() + ":" + session.getAccessToken());
        headers.set("X-Kite-Version", "3");
        try {
            ResponseEntity<String> resp = http.exchange(
                    cfg.getApiBaseUrl() + "/user/profile",
                    HttpMethod.GET,
                    new HttpEntity<>(headers),
                    String.class);
            return resp.getStatusCode().is2xxSuccessful();
        } catch (Exception e) {
            log.warn("Zerodha session validation failed: {}", e.getMessage());
            return false;
        }
    }

    @Override
    public void logout(BrokerSession session) {
        if (session == null || session.getAccessToken() == null) return;
        BrokerProperties.Zerodha cfg = properties.getZerodha();
        try {
            String url = UriComponentsBuilder.fromHttpUrl(cfg.getApiBaseUrl() + "/session/token")
                    .queryParam("api_key", cfg.getApiKey())
                    .queryParam("access_token", session.getAccessToken())
                    .toUriString();
            http.exchange(url, HttpMethod.DELETE, HttpEntity.EMPTY, String.class);
        } catch (Exception e) {
            log.warn("Zerodha logout failed (ignored): {}", e.getMessage());
        }
    }

    /** NIFTY 50 LTP probe – fast, always tradable, requires the same auth headers as live trading calls. */
    @Override
    public HeartbeatResult fetchHeartbeatQuote(BrokerSession session) {
        if (session == null || session.getAccessToken() == null) {
            return HeartbeatResult.of(HeartbeatStatus.NO_SESSION, "no session");
        }
        BrokerProperties.Zerodha cfg = properties.getZerodha();
        HttpHeaders headers = new HttpHeaders();
        headers.set("Authorization", "token " + cfg.getApiKey() + ":" + session.getAccessToken());
        headers.set("X-Kite-Version", "3");
        try {
            String url = UriComponentsBuilder.fromHttpUrl(cfg.getApiBaseUrl() + "/quote/ltp")
                    .queryParam("i", "NSE:NIFTY 50")
                    .toUriString();
            ResponseEntity<String> resp = http.exchange(url, HttpMethod.GET,
                    new HttpEntity<>(headers), String.class);
            if (!resp.getStatusCode().is2xxSuccessful() || resp.getBody() == null) {
                return HeartbeatResult.of(HeartbeatStatus.NO_DATA, "http " + resp.getStatusCode());
            }
            // Kite LTP response doesn't include a tick timestamp; treat HTTP 200 + non-empty body as fresh.
            return HeartbeatResult.ok(Instant.now());
        } catch (Exception e) {
            log.warn("Zerodha LTP probe failed: {}", e.getMessage());
            return HeartbeatResult.of(HeartbeatStatus.HTTP_ERROR, e.getMessage());
        }
    }

    /* ---------- mapping ---------- */

    private BrokerSession toSession(ZerodhaTokenResponse payload) {
        ZerodhaTokenResponse.Data d = payload.getData();
        Map<String, Object> raw = new HashMap<>();
        raw.put("status", payload.getStatus());
        raw.put("data", d);

        return BrokerSession.builder()
                .broker(Broker.ZERODHA)
                .userId(d.getUserId())
                .accessToken(d.getAccessToken())
                .refreshToken(d.getRefreshToken())
                .publicToken(d.getPublicToken())
                .loginAt(Instant.now())
                .expiresAt(nextZerodhaExpiry())
                .valid(true)
                .raw(raw)
                .build();
    }

    private void applyKiteSession(BrokerSession session) {
        sharedKiteConnect.setAccessToken(session.getAccessToken());
        if (session.getPublicToken() != null && !session.getPublicToken().isBlank()) {
            sharedKiteConnect.setPublicToken(session.getPublicToken());
        }
    }

    /** Zerodha access tokens expire daily at ~06:00 IST. */
    private Instant nextZerodhaExpiry() {
        ZoneId ist = ZoneId.of("Asia/Kolkata");
        ZonedDateTime sixAmToday = LocalDate.now(ist).atTime(LocalTime.of(6, 0)).atZone(ist);
        ZonedDateTime expiry = Instant.now().isAfter(sixAmToday.toInstant())
                ? sixAmToday.plusDays(1)
                : sixAmToday;
        return expiry.toInstant();
    }

    private static String sha256(String input) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] digest = md.digest(input.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(digest.length * 2);
            for (byte b : digest) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) {
            throw new BrokerLoginException("Unable to compute SHA-256 checksum", e);
        }
    }
}

