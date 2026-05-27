package com.moneymaker.scheduler;

import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.position.service.PositionService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Objects;

@Slf4j
@Component
public class PositionScheduler {

    private final PositionService positionService;
    private final MarketHoursService marketHours;

    @Value("${app.mode:live}")
    private String appMode;

    public PositionScheduler(PositionService positionService, MarketHoursService marketHours) {
        this.positionService = Objects.requireNonNull(positionService, "positionService must not be null");
        this.marketHours = Objects.requireNonNull(marketHours, "marketHours must not be null");
    }

    /**
     * Every 5 minutes during NSE trading hours. Live mode short-circuits
     * outside the configured market window so SL / target monitoring stops
     * the moment {@code DaySummaryScheduler} has force-closed everything.
     */
    @Scheduled(cron = "0 0/5 9-16 * * MON-FRI")
    public void processPositions() {
        if ("live".equalsIgnoreCase(appMode) && !marketHours.isOpenNow()) {
            log.debug("PositionScheduler skipped: outside market hours");
            return;
        }
        log.debug("PositionScheduler tick");
        try {
            positionService.processPositions();
        } catch (Exception ex) {
            log.error("PositionScheduler failed", ex);
        }
    }
}
