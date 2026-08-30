package com.moneymaker.admin.controller;

import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.scheduler.DaySummaryScheduler;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Operator re-run for end-of-day work (GAPS #6).
 *
 * <p>{@code DaySummaryScheduler} fires once at 15:31 and
 * {@link com.moneymaker.state.DailyEventGuard} makes that stick across restarts.
 * That is correct until the run is <i>missed</i> — the JVM was down at 15:31, or
 * the digest fired before a delayed close — at which point restart-safe gating is
 * exactly what stops a fix. The only recovery before this endpoint was a manual
 * {@code DELETE FROM alert_state} and a wait for the next cron.
 *
 * <pre>
 *   POST /api/admin/day-summary                 re-run today
 *   POST /api/admin/day-summary?date=2026-08-28 re-run a specific trading date
 *   POST /api/admin/day-summary?force=true      ignore the guard and run both halves
 * </pre>
 *
 * <h3>Why {@code force} is not the default</h3>
 * Without it this is <b>idempotent for free</b>, and not by any new logic: the
 * two-key sent-marker gate from GAPS #5 already skips a half that has completed.
 * A missed run therefore does exactly what is wanted on a plain re-run — the
 * pending half executes and the finished one does not repeat. {@code force} is
 * for the one case the marker cannot see: the digest went out, and it was wrong.
 *
 * <p>Deliberately mode-agnostic, unlike the 15:31 cron's live-only guard: an
 * operator hitting this has asked for it explicitly. In backtest mode
 * {@code TelegramNotifier} suppresses the send anyway, and the placement factory
 * resolves to {@code BACKTESTING}, so nothing reaches a broker.
 */
@Slf4j
@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class DaySummaryAdminController {

    private final DaySummaryScheduler daySummaryScheduler;
    private final MarketHoursService marketHours;

    @PostMapping("/day-summary")
    public ResponseEntity<Map<String, Object>> rerunDaySummary(
            @RequestParam(value = "date", required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam(value = "force", defaultValue = "false") boolean force) {

        LocalDate target = date != null ? date : LocalDate.now(marketHours.zone());

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("date", target);
        body.put("force", force);

        // The scheduler itself no-ops on a weekend; saying so is more useful than
        // returning a silent success the caller has to interpret.
        if (target.getDayOfWeek() == DayOfWeek.SATURDAY || target.getDayOfWeek() == DayOfWeek.SUNDAY) {
            body.put("ran", false);
            body.put("message", target + " is a " + target.getDayOfWeek()
                    + " — there is no trading day to summarise.");
            return ResponseEntity.badRequest().body(body);
        }

        log.info("[day-summary] manual re-run requested for {} (force={})", target, force);
        int forceClosed = daySummaryScheduler.runEndOfDayFor(target, force);

        body.put("ran", true);
        body.put("forceClosed", forceClosed);
        body.put("message", force
                ? "Re-ran both halves for " + target + ", bypassing the sent markers."
                : "Re-ran " + target + "; halves already marked as done were skipped.");
        return ResponseEntity.ok(body);
    }
}
