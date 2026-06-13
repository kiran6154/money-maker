package com.moneymaker.backtesting;

import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.telegram.NotificationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;

/**
 * Purges DB rows + in-memory caches that would otherwise carry state across
 * backtest runs and corrupt reproducibility.
 *
 * <p><b>Reset surface (per {@code SEQUENCING_AND_CACHE.md} §5):</b>
 * <ul>
 *   <li>{@code trade_order} rows whose {@code entry_time} falls in
 *       {@code [fromDate, toDate]}.</li>
 *   <li>{@code alert_state} rows whose {@code alert_date} falls in
 *       {@code [fromDate, toDate]}.</li>
 *   <li>{@link TradeConfigScheduler#invalidateConfigsCache()} — date-keyed
 *       cache (C9).</li>
 *   <li>{@link NotificationService#clearAllDedupeState()} — dedupe / throttle
 *       maps (C11 / C12).</li>
 * </ul>
 *
 * <p>The in-memory {@code SharedData} maps (C2 / C3 / C6) are wiped per-day
 * by {@link BacktestAnalysisService} already; no duplicate work here.
 *
 * <p>Live mode must never call this — would delete real trade history.
 * The {@link BacktestResetController} enforces the
 * {@code app.mode=backtest} gate.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BacktestResetService {

    private final JdbcTemplate jdbcTemplate;
    private final TradeConfigScheduler tradeConfigScheduler;
    private final NotificationService notifier;

    /** Convenience: reset everything in the range (start of day → end of day). */
    @Transactional
    public ResetSummary resetRange(LocalDate fromDate, LocalDate toDate) {
        if (fromDate == null || toDate == null) {
            throw new IllegalArgumentException("fromDate and toDate are required");
        }
        if (fromDate.isAfter(toDate)) {
            throw new IllegalArgumentException("fromDate must be on or before toDate");
        }

        LocalDateTime fromTs = fromDate.atStartOfDay();
        LocalDateTime toTs   = toDate.atTime(LocalTime.MAX);

        int tradeOrderRows = jdbcTemplate.update(
                "DELETE FROM trade_order WHERE entry_time BETWEEN ? AND ?",
                fromTs, toTs);
        int alertStateRows = jdbcTemplate.update(
                "DELETE FROM alert_state WHERE alert_date BETWEEN ? AND ?",
                fromDate, toDate);

        tradeConfigScheduler.invalidateConfigsCache();
        notifier.clearAllDedupeState();

        log.info("[backtest-reset] cleared {} trade_order rows + {} alert_state rows for [{} .. {}]; " +
                        "in-memory caches invalidated",
                tradeOrderRows, alertStateRows, fromDate, toDate);
        return new ResetSummary(tradeOrderRows, alertStateRows, fromDate, toDate);
    }

    /**
     * Result of a reset run. Returned as JSON from the controller so the
     * operator sees what was actually purged.
     */
    public record ResetSummary(int tradeOrderRowsDeleted, int alertStateRowsDeleted,
                               LocalDate fromDate, LocalDate toDate) {}
}
