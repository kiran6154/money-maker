package com.moneymaker.scheduler;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.Map;

/**
 * Operational admin endpoints — currently just one: manual re-trigger of
 * the end-of-day summary (M5.2 / GAPS #6).
 *
 * <p>Use cases:
 * <ul>
 *   <li>JVM was down at 15:31 → manually fire today's summary.</li>
 *   <li>Telegram delivery failed silently in the past → re-fire for a
 *       prior date with {@code force=true}.</li>
 *   <li>Force-close failed earlier; the next cron tick will retry the
 *       unmarked half on its own, but the operator wants it now.</li>
 * </ul>
 *
 * <p><b>Auth:</b> no authentication on this endpoint. The whole
 * {@code /api/admin/*} surface is still anonymous like the rest of the
 * app. Filed under future hardening; out of scope for M5.
 */
@Slf4j
@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class AdminController {

    private final DaySummaryScheduler daySummaryScheduler;

    /**
     * Manually re-run the end-of-day summary for {@code date} (defaults to
     * today). When {@code force=true}, both DailyEventGuard keys
     * ({@code day-summary-forceclose}, {@code day-summary-telegram}) are
     * bypassed — every component runs regardless of prior firings. When
     * {@code force=false} (default), the standard idempotent guards apply,
     * so this endpoint is the safe recovery hook: an already-completed
     * half is left alone, an unmarked half is attempted.
     */
    @PostMapping("/day-summary")
    public ResponseEntity<?> reRunDaySummary(
            @RequestParam(value = "date", required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam(value = "force", defaultValue = "false") boolean force) {
        LocalDate target = (date != null) ? date : LocalDate.now();
        if (target.isAfter(LocalDate.now())) {
            return ResponseEntity.badRequest().body(Map.of(
                    "error", "date cannot be in the future",
                    "date", target.toString()));
        }
        try {
            DaySummaryScheduler.RunSummary summary = daySummaryScheduler.runForDate(target, force);
            log.info("[admin] day-summary manual re-run for {} force={} → {}", target, force, summary);
            return ResponseEntity.ok(summary);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }
}
