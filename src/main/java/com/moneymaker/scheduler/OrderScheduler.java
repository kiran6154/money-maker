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

    /**
     * Run mode, from the same {@code app.mode} key the Telegram backtest gate
     * reads ({@code TelegramNotifier}). Constructor-injected rather than
     * field-injected so a unit test can build the bean in either mode.
     */
    private final String appMode;

    public OrderScheduler(OrderService orderService,
                          MarketHoursService marketHours,
                          @Value("${app.mode:live}") String appMode) {
        this.orderService = Objects.requireNonNull(orderService, "orderService must not be null");
        this.marketHours = Objects.requireNonNull(marketHours, "marketHours must not be null");
        this.appMode = appMode == null ? "" : appMode.trim();
    }

    /**
     * The wall-clock entry point: every 5 minutes during NSE trading hours.
     *
     * <p>This method holds <b>only</b> wall-clock concerns — the backtest gate
     * and the live market-hours gate — and nothing the replay needs. That is
     * the split invariant 8 asks for: {@code BacktestAnalysisService} calls
     * {@link #processOrders()} below directly, so a mode check placed there
     * would silence the replay itself.</p>
     *
     * <p>In {@code app.mode=backtest} the trigger still fires (the bean is
     * needed by the replay, so it cannot be {@code @ConditionalOnProperty}-ed
     * away) but does no work — the simulated clock, not the wall clock, drives
     * the pipeline. See {@code docs/GAPS.md} #4.</p>
     */
    @Scheduled(cron = "0 0/5 9-16 * * MON-FRI")
    public void scheduledTick() {
        if ("backtest".equalsIgnoreCase(appMode)) {
            log.debug("OrderScheduler cron tick ignored - app.mode=backtest drives processOrders() directly");
            return;
        }
        if ("live".equalsIgnoreCase(appMode) && !marketHours.isOpenNow()) {
            log.debug("OrderScheduler skipped: outside market hours");
            return;
        }
        processOrders();
    }

    /**
     * Drains {@code SharedData.tradeSignals} once. Called by {@link #scheduledTick()}
     * in live mode and by {@code BacktestAnalysisService} per replayed tick — the
     * body is identical in both, and deliberately carries no mode branch.
     */
    public void processOrders() {
        log.debug("OrderScheduler tick");
        try {
            orderService.processOrders();
        } catch (Exception ex) {
            log.error("OrderScheduler failed", ex);
        }
    }
}
