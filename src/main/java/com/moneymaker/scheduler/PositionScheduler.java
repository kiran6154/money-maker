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

    /**
     * Run mode, from the same {@code app.mode} key the Telegram backtest gate
     * reads ({@code TelegramNotifier}). Constructor-injected rather than
     * field-injected so a unit test can build the bean in either mode.
     */
    private final String appMode;

    public PositionScheduler(PositionService positionService,
                             MarketHoursService marketHours,
                             @Value("${app.mode:live}") String appMode) {
        this.positionService = Objects.requireNonNull(positionService, "positionService must not be null");
        this.marketHours = Objects.requireNonNull(marketHours, "marketHours must not be null");
        this.appMode = appMode == null ? "" : appMode.trim();
    }

    /**
     * The wall-clock entry point: every 5 minutes during NSE trading hours.
     *
     * <p>Holds only wall-clock concerns — the backtest gate, and the live
     * market-hours gate that stops SL / target monitoring the moment
     * {@code DaySummaryScheduler} has force-closed everything. The replayable
     * work lives in {@link #processPositions()}, which
     * {@code BacktestAnalysisService} calls directly and which therefore must
     * stay mode-free (invariant 8).</p>
     *
     * <p>In {@code app.mode=backtest} the trigger still fires but does no work.
     * See {@code docs/GAPS.md} #4.</p>
     */
    @Scheduled(cron = "0 0/5 9-16 * * MON-FRI")
    public void scheduledTick() {
        if ("backtest".equalsIgnoreCase(appMode)) {
            log.debug("PositionScheduler cron tick ignored - app.mode=backtest drives processPositions() directly");
            return;
        }
        if ("live".equalsIgnoreCase(appMode) && !marketHours.isOpenNow()) {
            log.debug("PositionScheduler skipped: outside market hours");
            return;
        }
        processPositions();
    }

    /**
     * Walks the OPEN {@code trade_order} rows once. Called by
     * {@link #scheduledTick()} in live mode and by {@code BacktestAnalysisService}
     * per replayed tick — identical body, no mode branch.
     */
    public void processPositions() {
        log.debug("PositionScheduler tick");
        try {
            positionService.processPositions();
        } catch (Exception ex) {
            log.error("PositionScheduler failed", ex);
        }
    }
}
