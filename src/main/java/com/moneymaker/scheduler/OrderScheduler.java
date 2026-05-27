package com.moneymaker.scheduler;

import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.order.service.OrderService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Objects;

@Slf4j
@Component
public class OrderScheduler {

    private final OrderService orderService;
    private final MarketHoursService marketHours;

    @Value("${app.mode:live}")
    private String appMode;

    public OrderScheduler(OrderService orderService, MarketHoursService marketHours) {
        this.orderService = Objects.requireNonNull(orderService, "orderService must not be null");
        this.marketHours = Objects.requireNonNull(marketHours, "marketHours must not be null");
    }

    /**
     * Live cadence: driven by {@link TradingPipelineScheduler#tick()} —
     * <b>not</b> via {@code @Scheduled} here. Live-mode market-hours gate
     * retained as defence-in-depth. Backtest calls directly each replay tick.
     */
    public void processOrders() {
        if ("live".equalsIgnoreCase(appMode) && !marketHours.isOpenNow()) {
            log.debug("OrderScheduler skipped: outside market hours");
            return;
        }
        log.debug("OrderScheduler tick");
        try {
            orderService.processOrders();
        } catch (Exception ex) {
            log.error("OrderScheduler failed", ex);
        }
    }
}
