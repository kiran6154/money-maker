package com.moneymaker.scheduler;

import com.moneymaker.position.service.PositionService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Objects;

@Slf4j
@Component
public class PositionScheduler {

    private final PositionService positionService;

    public PositionScheduler(PositionService positionService) {
        this.positionService = Objects.requireNonNull(positionService, "positionService must not be null");
    }

    /** Every 5 minutes during NSE trading hours (Mon-Fri, 09:00-16:55 IST). */
    @Scheduled(cron = "0 0/5 9-16 * * MON-FRI")
    public void processPositions() {
        log.debug("PositionScheduler tick");
        try {
            positionService.processPositions();
        } catch (Exception ex) {
            log.error("PositionScheduler failed", ex);
        }
    }
}
