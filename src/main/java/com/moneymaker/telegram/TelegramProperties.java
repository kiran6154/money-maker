package com.moneymaker.telegram;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Bound from {@code telegram.*} keys in {@code application.properties}.
 */
@Data
@Component
@ConfigurationProperties(prefix = "telegram")
public class TelegramProperties {

    private boolean enabled = false;
    private String botToken;
    private String chatId;
    private String apiBaseUrl = "https://api.telegram.org";
}

