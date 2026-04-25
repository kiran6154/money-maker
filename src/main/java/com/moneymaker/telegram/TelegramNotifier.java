package com.moneymaker.telegram;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Thin Telegram bot client. No-op when disabled or when token/chat-id are blank.
 */
@Slf4j
@Component
public class TelegramNotifier {

    private final TelegramProperties properties;
    private final RestTemplate http;

    public TelegramNotifier(TelegramProperties properties, RestTemplate brokerRestTemplate) {
        this.properties = properties;
        this.http = brokerRestTemplate;
    }

    public void send(String message) {
        if (!properties.isEnabled()) {
            log.debug("[Telegram] disabled - skipping: {}", message);
            return;
        }
        if (isBlank(properties.getBotToken()) || isBlank(properties.getChatId())) {
            log.warn("[Telegram] bot-token or chat-id not configured - skipping message");
            return;
        }
        try {
            String url = properties.getApiBaseUrl() + "/bot" + properties.getBotToken() + "/sendMessage";
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);

            Map<String, Object> body = new LinkedHashMap<>();
            body.put("chat_id", properties.getChatId());
            body.put("text", message);
            body.put("parse_mode", "Markdown");
            body.put("disable_web_page_preview", true);

            http.exchange(url, HttpMethod.POST, new HttpEntity<>(body, headers), String.class);
        } catch (Exception e) {
            log.warn("[Telegram] sendMessage failed: {}", e.getMessage());
        }
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }
}

