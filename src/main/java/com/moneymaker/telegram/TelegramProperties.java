package com.moneymaker.telegram;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Bound from {@code telegram.*} keys in {@code application.properties}.
 *
 * <p>{@link #backtestEnabled} is a master switch for backtest runs: when
 * {@code app.mode=backtest}, telegram only fires if this flag is also true.
 * Default is {@code false} so a multi-day replay can't flood the channel
 * even if {@link #enabled} is on for live mode.
 */
@Data
@Component
@ConfigurationProperties(prefix = "telegram")
public class TelegramProperties {

    private boolean enabled = false;
    private String botToken;
    private String chatId;
    private String apiBaseUrl = "https://api.telegram.org";

    /** When false, suppress all telegram traffic when {@code app.mode=backtest}. */
    private boolean backtestEnabled = false;
}
