package com.moneymaker.scheduler;

import com.moneymaker.order.service.OrderService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Objects;

@Slf4j
@Component
public class OrderScheduler {

    private final OrderService orderService;

    public OrderScheduler(OrderService orderService) {
        this.orderService = Objects.requireNonNull(orderService, "orderService must not be null");
    }

    /** Every 5 minutes during NSE trading hours (Mon-Fri, 09:00-16:55 IST). */
    @Scheduled(cron = "0 0/5 9-16 * * MON-FRI")
    public void processOrders() {
        log.info("OrderScheduler tick");
        try {
            orderService.processOrders();
        } catch (Exception ex) {
            log.error("OrderScheduler failed", ex);
        }
    }
}
