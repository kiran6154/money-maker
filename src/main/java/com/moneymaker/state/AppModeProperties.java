package com.moneymaker.state;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Binds {@code app.*} keys. Today only {@code app.mode} is used.
 */
@Data
@Component
@ConfigurationProperties(prefix = "app")
public class AppModeProperties {
    /** {@link AppMode#LIVE} by default. */
    private AppMode mode = AppMode.LIVE;
}


