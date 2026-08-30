package com.moneymaker.telegram;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Thin Telegram bot client. No-op when:
 * <ul>
 *   <li>{@code telegram.enabled=false} (master switch).</li>
 *   <li>Bot token / chat-id are blank.</li>
 *   <li>{@code app.mode=backtest} AND {@code telegram.backtest-enabled=false}
 *       — the dedicated backtest gate prevents replay runs from flooding
 *       the channel.</li>
 * </ul>
 */
@Slf4j
@Component
public class TelegramNotifier {

    private final TelegramProperties properties;
    private final RestTemplate http;
    private final boolean backtestMode;

    /**
     * Telegram's bot API limits one chat to ~1 message/sec. A burst of order
     * alerts (e.g. multi-day backtest force-closes) easily breaches that and
     * the over-limit messages either drop silently or return 429. We serialize
     * sends through this monitor and sleep just over 1s between them.
     */
    private final Object sendLock = new Object();
    private long lastSendAt = 0L;
    private static final long MIN_SEND_INTERVAL_MS = 1100L;

    public TelegramNotifier(TelegramProperties properties,
                            RestTemplate brokerRestTemplate,
                            @Value("${app.mode:live}") String appMode) {
        this.properties = properties;
        this.http = brokerRestTemplate;
        this.backtestMode = "backtest".equalsIgnoreCase(appMode == null ? "" : appMode.trim());
    }

    /**
     * Posts {@code message} to the configured chat.
     *
     * <p>The return value answers exactly one question — <b>"is there anything a
     * retry could fix?"</b> — and nothing else:</p>
     * <ul>
     *   <li>{@code true} — the POST succeeded, <i>or</i> no POST was attempted
     *       because sending is switched off for this run (disabled, suppressed in
     *       backtest, bot-token / chat-id not configured). Retrying any of those
     *       produces the same non-send, so a caller that gates a
     *       "already delivered" marker on this value must treat them as settled.</li>
     *   <li>{@code false} — a POST was attempted and the Telegram API call threw.
     *       This is the transient case (network blip, 429) worth retrying.</li>
     * </ul>
     *
     * <p>Most callers ignore the result; {@code NotificationService.alertDaySummary}
     * is the one that propagates it, because {@code DaySummaryScheduler} only
     * writes its {@code day-summary-telegram} guard row once the digest is
     * actually out (GAPS #5).</p>
     */
    public boolean send(String message) {
        if (!properties.isEnabled()) {
            log.debug("[Telegram] disabled - skipping: {}", message);
            return true;
        }
        if (backtestMode && !properties.isBacktestEnabled()) {
            log.debug("[Telegram] suppressed in backtest (telegram.backtest-enabled=false): {}", message);
            return true;
        }
        if (isBlank(properties.getBotToken()) || isBlank(properties.getChatId())) {
            log.warn("[Telegram] bot-token or chat-id not configured - skipping message");
            return true;
        }
        synchronized (sendLock) {
            throttle();
            try {
                String url = properties.getApiBaseUrl() + "/bot" + properties.getBotToken() + "/sendMessage";
                HttpHeaders headers = new HttpHeaders();
                headers.setContentType(MediaType.APPLICATION_JSON);

                // No parse_mode — plain text. Markdown was rejecting messages
                // whose content looked like a malformed link (e.g. "[ORDER
                // FORCE-CLOSE]" followed by a newline) and the failure was
                // swallowed at WARN. The handful of `*bold*` markers in
                // login/heartbeat alerts now render as literal asterisks,
                // which is fine.
                Map<String, Object> body = new LinkedHashMap<>();
                body.put("chat_id", properties.getChatId());
                body.put("text", message);
                body.put("disable_web_page_preview", true);

                http.exchange(url, HttpMethod.POST, new HttpEntity<>(body, headers), String.class);
                return true;
            } catch (Exception e) {
                log.warn("[Telegram] sendMessage failed: {}", e.getMessage());
                return false;
            } finally {
                lastSendAt = System.currentTimeMillis();
            }
        }
    }

    /** Sleep until at least MIN_SEND_INTERVAL_MS has elapsed since the last send. */
    private void throttle() {
        long elapsed = System.currentTimeMillis() - lastSendAt;
        if (elapsed >= MIN_SEND_INTERVAL_MS) return;
        try {
            Thread.sleep(MIN_SEND_INTERVAL_MS - elapsed);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
        }
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}
