package com.moneymaker.tradeconfig.generation;

import com.moneymaker.market.service.TradingCalendar;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Set;

/**
 * The trade-config domain's generation entry point: walks each trading session
 * in a window and runs the EOD downtrend detector for it.
 *
 * <p><b>Separation of concerns (user decision, 2026-08-31):</b> generating
 * configs and backtesting them are different tasks in different domains. This
 * service — and the whole {@code tradeconfig.generation} package — owns
 * <i>producing</i> configs; the backtesting domain only <i>consumes</i>
 * whatever configs exist and has no path that writes one. The replay's old
 * per-day detector call and its {@code generateConfigs} flag are gone, so a
 * measurement run structurally cannot mutate the config set it is measuring.</p>
 *
 * <p>Idempotent by the detector's own contract (it skips days whose configs
 * already exist). A per-day failure is recorded and the walk continues.</p>
 */
@Slf4j
@Service
public class TradeConfigGenerationService {

    private final EodDowntrendDetectionService detector;
    private final TradingCalendar tradingCalendar;

    public TradeConfigGenerationService(EodDowntrendDetectionService detector,
                                        TradingCalendar tradingCalendar) {
        this.detector = Objects.requireNonNull(detector, "detector must not be null");
        this.tradingCalendar = Objects.requireNonNull(tradingCalendar, "tradingCalendar must not be null");
    }

    /**
     * Per-window summary of a generation pass ({@code POST /api/trade-configs/generate}).
     * {@code strategyIds} echoes the requested scope; {@code null} = every tagged strategy.
     */
    public record GenerationResult(LocalDate fromDate, LocalDate toDate,
                                   int sessionsProcessed, int failures,
                                   List<String> failedDates, long durationMs,
                                   Set<Integer> strategyIds) {}

    /** Unscoped pass — every strategy tagged on the rules generates. */
    public GenerationResult generateForWindow(LocalDate fromDate, LocalDate toDate) {
        return generateForWindow(fromDate, toDate, null);
    }

    /**
     * Scoped pass: only strategies in {@code strategyIds} generate ({@code null}
     * or empty = all). The scope narrows the standing rule/tag setup for this run
     * only — it cannot make a strategy generate that the DB tags do not name.
     */
    public GenerationResult generateForWindow(LocalDate fromDate, LocalDate toDate,
                                              Set<Integer> strategyIds) {
        if (fromDate == null || toDate == null) {
            throw new IllegalArgumentException("fromDate and toDate must not be null");
        }
        if (fromDate.isAfter(toDate)) {
            throw new IllegalArgumentException("fromDate must be on or before toDate");
        }
        Set<Integer> scope = (strategyIds == null || strategyIds.isEmpty()) ? null : strategyIds;
        Instant startedAt = Instant.now();
        int sessions = 0;
        List<String> failed = new ArrayList<>();
        LocalDate d = fromDate;
        while (!d.isAfter(toDate)) {
            if (tradingCalendar.isTradingDay(d)) {
                sessions++;
                try {
                    detector.runForDay(d, scope);
                } catch (Exception ex) {
                    failed.add(d.toString());
                    log.error("[config-gen] {} — detector failed", d, ex);
                }
            }
            d = d.plusDays(1);
        }
        long ms = Duration.between(startedAt, Instant.now()).toMillis();
        log.info("[config-gen] {} -> {}: {} session(s), {} failure(s), {}ms (strategies={})",
                fromDate, toDate, sessions, failed.size(), ms, scope == null ? "all" : scope);
        return new GenerationResult(fromDate, toDate, sessions, failed.size(), failed, ms, scope);
    }
}
