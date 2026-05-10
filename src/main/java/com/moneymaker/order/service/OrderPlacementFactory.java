package com.moneymaker.order.service;

import com.moneymaker.login.config.BrokerProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Resolves the active {@link OrderPlacementService} based on configuration.
 *
 * <p>If {@code app.mode} is {@code backtest}, the
 * {@link com.moneymaker.backtesting.BacktestingOrderPlacementService} is used
 * regardless of the configured broker. Otherwise the implementation registered
 * for {@code broker.active} ({@code ZERODHA} / {@code GROWW} / {@code ANGEL_ONE})
 * is returned.
 */
@Slf4j
@Service
public class OrderPlacementFactory {

    private static final String BACKTESTING_NAME = "BACKTESTING";

    private final Map<String, OrderPlacementService> services = new HashMap<>();
    private final BrokerProperties brokerProperties;
    private final String appMode;

    public OrderPlacementFactory(List<OrderPlacementService> implementations,
                                 BrokerProperties brokerProperties,
                                 @Value("${app.mode:live}") String appMode) {
        this.brokerProperties = brokerProperties;
        this.appMode = appMode;
        for (OrderPlacementService impl : implementations) {
            String key = normalize(impl.getName());
            services.put(key, impl);
            log.info("Registered OrderPlacementService: {}", key);
        }
    }

    public OrderPlacementService active() {
        String key = resolveActiveName();
        OrderPlacementService svc = services.get(key);
        if (svc == null) {
            throw new IllegalStateException(
                    "No OrderPlacementService registered for: " + key
                            + " (available: " + services.keySet() + ")");
        }
        return svc;
    }

    private String resolveActiveName() {
        if (appMode != null && "backtest".equalsIgnoreCase(appMode.trim())) {
            return BACKTESTING_NAME;
        }
        String active = brokerProperties.getActive();
        return normalize(active);
    }

    private static String normalize(String value) {
        if (value == null) return "";
        return value.trim().toUpperCase(Locale.ROOT).replace('-', '_');
    }
}
