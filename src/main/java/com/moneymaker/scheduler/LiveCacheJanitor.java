package com.moneymaker.scheduler;

import com.moneymaker.shared.data.SharedData;
import com.moneymaker.telegram.NotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.DayOfWeek;
import java.time.LocalDateTime;

/**
 * Daily janitor for live-mode in-memory caches that would otherwise grow
 * unbounded across multi-day uptime (SEQ #6 in
 * {@code docs/SEQUENCING_AND_CACHE.md}).
 *
 * <p>Caches cleared:
 * <ul>
 *   <li>{@link SharedData#optionTokenMap} (C7) — strike → option token
 *       lookups accrue every distinct strike the analysis pipeline has ever
 *       seen.</li>
 *   <li>{@link SharedData#strikesByInstrumentAndInterval} (C4) — derived
 *       strike sets keyed by {@code (instrument, interval)}.</li>
 *   <li>{@link NotificationService#clearAllDedupeState()} (C11 + C12) —
 *       dedupe and throttle maps that would otherwise suppress an alert
 *       on day N that legitimately needs to re-fire on day N+1.</li>
 * </ul>
 *
 * <p><b>Triggers (architect's pushback during planning):</b>
 * <ul>
 *   <li>{@code @Scheduled} at 08:00 IST Mon-Fri — before the day's login.</li>
 *   <li>{@code @EventListener(ApplicationReadyEvent.class)} — also runs at
 *       app start so a JVM that restarts after 08:00 still gets a fresh
 *       cache before the day's first 5-min tick.</li>
 * </ul>
 *
 * <p><b>Mode-gated:</b> live only. Backtest's per-day wipe in
 * {@code BacktestAnalysisService.runForDateTime} already takes care of
 * cache hygiene per replay day.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class LiveCacheJanitor {

    private final NotificationService notifier;

    @Value("${app.mode:live}")
    private String appMode;

    /** 08:00 IST Mon-Fri — before {@code LoginScheduler.ensureSessionAtMarketOpen}. */
    @Scheduled(cron = "0 0 8 * * MON-FRI", zone = "Asia/Kolkata")
    public void daily() {
        if (!"live".equalsIgnoreCase(appMode)) return;
        if (isWeekend()) return;
        clear("daily 08:00 cron");
    }

    /**
     * Also fires when the application is fully ready. A JVM that restarts
     * mid-morning (after the 08:00 cron has already fired in a prior JVM)
     * still gets a fresh cache before the first analysis tick.
     */
    @EventListener(ApplicationReadyEvent.class)
    public void onStartup() {
        if (!"live".equalsIgnoreCase(appMode)) return;
        if (isWeekend()) return;
        clear("ApplicationReadyEvent");
    }

    void clear(String trigger) {
        int optionTokensBefore  = SharedData.optionTokenMap.size();
        int strikeSetsBefore    = SharedData.strikesByInstrumentAndInterval.size();

        SharedData.optionTokenMap.clear();
        SharedData.strikesByInstrumentAndInterval.clear();
        notifier.clearAllDedupeState();

        log.info("[live-cache-janitor] {} — cleared optionTokenMap={} strikeSets={} + all dedupe state",
                trigger, optionTokensBefore, strikeSetsBefore);
    }

    private static boolean isWeekend() {
        DayOfWeek dow = LocalDateTime.now().getDayOfWeek();
        return dow == DayOfWeek.SATURDAY || dow == DayOfWeek.SUNDAY;
    }
}
