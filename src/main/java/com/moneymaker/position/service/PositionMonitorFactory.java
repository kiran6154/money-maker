package com.moneymaker.position.service;

import com.moneymaker.login.config.BrokerProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Resolves the active {@link PositionMonitorService} based on configuration —
 * mirrors {@code OrderPlacementFactory}.
 *
 * <p>If {@code app.mode=backtest}, the {@code BACKTESTING} implementation is
 * always selected regardless of {@code broker.active}. Otherwise the
 * implementation registered for {@code broker.active} ({@code ZERODHA} /
 * {@code GROWW} / {@code ANGEL_ONE}) is returned.
 */
@Slf4j
@Service
public class PositionMonitorFactory {

    private static final String BACKTESTING_NAME = "BACKTESTING";

    private final Map<String, PositionMonitorService> services = new HashMap<>();
    private final BrokerProperties brokerProperties;
    private final String appMode;

    public PositionMonitorFactory(List<PositionMonitorService> implementations,
                                  BrokerProperties brokerProperties,
                                  @Value("${app.mode:live}") String appMode) {
        this.brokerProperties = brokerProperties;
        this.appMode = appMode;
        for (PositionMonitorService impl : implementations) {
            String key = normalize(impl.getName());
            services.put(key, impl);
            log.info("Registered PositionMonitorService: {}", key);
        }
    }

    public PositionMonitorService active() {
        String key = resolveActiveName();
        PositionMonitorService svc = services.get(key);
        if (svc == null) {
            throw new IllegalStateException(
                    "No PositionMonitorService registered for: " + key
                            + " (available: " + services.keySet() + ")");
        }
        return svc;
    }

    private String resolveActiveName() {
        if (appMode != null && "backtest".equalsIgnoreCase(appMode.trim())) {
            return BACKTESTING_NAME;
        }
        return normalize(brokerProperties.getActive());
    }

    private static String normalize(String value) {
        if (value == null) return "";
        return value.trim().toUpperCase(Locale.ROOT).replace('-', '_');
    }
}
