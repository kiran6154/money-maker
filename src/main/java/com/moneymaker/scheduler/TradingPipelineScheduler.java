package com.moneymaker.scheduler;

import com.moneymaker.market.service.MarketHoursService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Objects;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.locks.ReentrantLock;

/**
 * Single cron entry-point that drives the live trading pipeline in a
 * <b>fixed, deterministic order</b>:
 * <pre>
 *   analysis  →  orders  →  positions
 * </pre>
 *
 * <h3>Why this exists</h3>
 * Before M1, each of the three pipeline schedulers carried its own
 * {@code @Scheduled(cron = "0 0/5 9-16 * * MON-FRI")}. They ran in
 * <i>alphabetical</i> order by accident (AnalysisScheduler → OrderScheduler →
 * PositionScheduler) on Spring's default single-thread scheduler. Two failure
 * modes were possible:
 * <ol>
 *   <li>A future rename ({@code PositionScheduler → ActivePositionScheduler})
 *       would silently flip the order. PositionScheduler would walk OPEN
 *       trades <i>before</i> Strategy could update them.</li>
 *   <li>Bumping {@code spring.task.scheduling.pool.size} above 1 (looks
 *       innocuous) would run all three concurrently. {@code OrderScheduler}
 *       could drain {@code SharedData.tradeSignals} before
 *       {@code AnalysisScheduler} finished producing — signals lost.</li>
 * </ol>
 *
 * <h3>Guards</h3>
 * <ul>
 *   <li><b>Market-hours gate.</b> Live-mode only; outside the configured
 *       window the tick is a no-op.</li>
 *   <li><b>Re-entrancy lock.</b> If a previous tick is still running (slow
 *       broker fetch), the next firing skips. Cumulative skip counter logged
 *       every 10 events so operations notice persistent overruns.</li>
 * </ul>
 *
 * <h3>Live ↔ backtest parity</h3>
 * Backtest replays the same three service methods directly via
 * {@code BacktestAnalysisService.runForDateTime}. The order is identical;
 * this class is the live-mode equivalent.
 */
@Slf4j
@Component
public class TradingPipelineScheduler {

    private final AnalysisScheduler analysisScheduler;
    private final OrderScheduler orderScheduler;
    private final PositionScheduler positionScheduler;
    private final MarketHoursService marketHours;

    private final ReentrantLock pipelineLock = new ReentrantLock();
    private final AtomicLong skippedTickCounter = new AtomicLong();

    @Value("${app.mode:live}")
    private String appMode;

    public TradingPipelineScheduler(AnalysisScheduler analysisScheduler,
                                    OrderScheduler orderScheduler,
                                    PositionScheduler positionScheduler,
                                    MarketHoursService marketHours) {
        this.analysisScheduler = Objects.requireNonNull(analysisScheduler, "analysisScheduler");
        this.orderScheduler = Objects.requireNonNull(orderScheduler, "orderScheduler");
        this.positionScheduler = Objects.requireNonNull(positionScheduler, "positionScheduler");
        this.marketHours = Objects.requireNonNull(marketHours, "marketHours");
    }

    /**
     * Single cron, fixed order. Runs every 5 minutes during market hours,
     * Mon–Fri. Live-mode only; backtest paths are unaffected (they call the
     * service methods directly).
     */
    @Scheduled(cron = "0 0/5 9-15 * * MON-FRI", zone = "Asia/Kolkata")
    public void tick() {
        if (!"live".equalsIgnoreCase(appMode)) {
            // Backtest mode — schedulers are quiet; BacktestAnalysisService drives.
            return;
        }
        if (!marketHours.isOpenNow()) {
            log.debug("[pipeline] tick skipped — outside market hours");
            return;
        }
        if (!pipelineLock.tryLock()) {
            long total = skippedTickCounter.incrementAndGet();
            if (total % 10 == 1) {
                // Log on the 1st, 11th, 21st… skip so we always notice the
                // first overrun and get a reminder every 10 thereafter.
                log.warn("[pipeline] previous tick still running — skipping (cumulative skips: {})", total);
            }
            return;
        }
        try {
            analysisScheduler.analyzeMarketData();
            orderScheduler.processOrders();
            positionScheduler.processPositions();
        } catch (Exception ex) {
            // The individual services already catch their own exceptions; this
            // is a belt-and-braces — anything that slips through doesn't kill
            // future ticks.
            log.error("[pipeline] tick failed", ex);
        } finally {
            pipelineLock.unlock();
        }
    }

    /** Test-only accessor for the skip counter. */
    long skippedTickCount() {
        return skippedTickCounter.get();
    }
}
