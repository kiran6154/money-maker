package com.moneymaker.admin.controller;

import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.scheduler.DaySummaryScheduler;
import com.moneymaker.state.DailyEventGuard;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * GAPS #6 — the manual re-run for end-of-day work.
 *
 * <p>The point of the endpoint is that <b>idempotency is not new code</b>. The
 * two-key sent-marker gate from GAPS #5 already knows which half of the day's
 * work completed, so an un-forced re-run runs the pending half and skips the
 * finished one, for free. These tests exercise the real
 * {@code DaySummaryScheduler} through the controller rather than mocking it, so
 * they pin that claim instead of restating it.
 *
 * <p>{@code force=true} is the deliberate override for the one case the marker
 * cannot see: the digest was delivered, and it was wrong.
 */
class DaySummaryManualRerunTest {

    private static final String KEY_FORCE_CLOSE = "day-summary-forceclose";
    private static final String KEY_TELEGRAM = "day-summary-telegram";

    /** A Monday, so the weekend short-circuit is never what makes a test pass. */
    private static final LocalDate MONDAY = LocalDate.of(2026, 8, 31);
    private static final LocalDate SATURDAY = LocalDate.of(2026, 9, 5);

    private OrderService orderService;
    private NotificationService notifier;
    private DailyEventGuard guard;
    private MarketHoursService marketHours;
    private DaySummaryAdminController controller;

    @BeforeEach
    void setUp() {
        orderService = mock(OrderService.class);
        notifier = mock(NotificationService.class);
        guard = mock(DailyEventGuard.class);
        marketHours = mock(MarketHoursService.class);
        TradeOrderRepository tradeOrderRepository = mock(TradeOrderRepository.class);
        TradeConfigRepository tradeConfigRepository = mock(TradeConfigRepository.class);

        when(marketHours.zone()).thenReturn(ZoneId.of("Asia/Kolkata"));
        when(marketHours.marketCloseOn(any(LocalDate.class))).thenAnswer(
                inv -> inv.getArgument(0, LocalDate.class).atTime(15, 30));
        when(marketHours.marketOpenOn(any(LocalDate.class))).thenAnswer(
                inv -> inv.getArgument(0, LocalDate.class).atTime(9, 15));
        when(tradeOrderRepository.findByEntryTimeBetween(any(), any())).thenReturn(List.of());
        when(orderService.forceCloseOpenPositions(any(LocalDate.class), any(LocalDateTime.class))).thenReturn(2);
        when(notifier.alertDaySummary(anyString())).thenReturn(true);

        DaySummaryScheduler scheduler = new DaySummaryScheduler(orderService, tradeOrderRepository,
                tradeConfigRepository, marketHours, notifier, guard);
        controller = new DaySummaryAdminController(scheduler, marketHours);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> body(ResponseEntity<Map<String, Object>> response) {
        return response.getBody();
    }

    /* ---------------- the missed-run case the endpoint exists for ---------------- */

    @Test
    @DisplayName("a missed run replays both halves")
    void missed_run_replays_everything() {
        // Nothing marked: the 15:31 cron never fired.
        ResponseEntity<Map<String, Object>> response = controller.rerunDaySummary(MONDAY, false);

        assertThat(response.getStatusCode().value()).isEqualTo(200);
        assertThat(body(response)).containsEntry("ran", true).containsEntry("forceClosed", 2);
        verify(orderService).forceCloseOpenPositions(eq(MONDAY), eq(MONDAY.atTime(15, 30)));
        verify(notifier).alertDaySummary(anyString());
    }

    /* ---------------- idempotency, which comes from the GAPS #5 gate ---------------- */

    @Test
    @DisplayName("re-running a completed day repeats neither half — no new force-close, no second digest")
    void completed_day_is_a_no_op() {
        when(guard.alreadyFired(KEY_FORCE_CLOSE, MONDAY)).thenReturn(true);
        when(guard.alreadyFired(KEY_TELEGRAM, MONDAY)).thenReturn(true);

        controller.rerunDaySummary(MONDAY, false);

        verifyNoInteractions(orderService);
        verify(notifier, never()).alertDaySummary(anyString());
    }

    @Test
    @DisplayName("hammering the endpoint is safe: repeated un-forced calls stay a no-op")
    void repeated_calls_stay_a_no_op() {
        when(guard.alreadyFired(KEY_FORCE_CLOSE, MONDAY)).thenReturn(true);
        when(guard.alreadyFired(KEY_TELEGRAM, MONDAY)).thenReturn(true);

        for (int i = 0; i < 5; i++) {
            controller.rerunDaySummary(MONDAY, false);
        }

        verifyNoInteractions(orderService);
        verify(notifier, never()).alertDaySummary(anyString());
    }

    @Test
    @DisplayName("the half that failed is the only half that re-runs")
    void only_the_pending_half_replays() {
        // Force-close succeeded at 15:31; the Telegram POST did not.
        when(guard.alreadyFired(KEY_FORCE_CLOSE, MONDAY)).thenReturn(true);
        when(guard.alreadyFired(KEY_TELEGRAM, MONDAY)).thenReturn(false);

        controller.rerunDaySummary(MONDAY, false);

        verifyNoInteractions(orderService);
        verify(notifier).alertDaySummary(anyString());
    }

    /* ---------------- force ---------------- */

    @Test
    @DisplayName("force=true bypasses both markers and re-sends a digest that already went out")
    void force_bypasses_the_guard() {
        when(guard.alreadyFired(KEY_FORCE_CLOSE, MONDAY)).thenReturn(true);
        when(guard.alreadyFired(KEY_TELEGRAM, MONDAY)).thenReturn(true);

        ResponseEntity<Map<String, Object>> response = controller.rerunDaySummary(MONDAY, true);

        assertThat(body(response)).containsEntry("force", true);
        verify(orderService).forceCloseOpenPositions(eq(MONDAY), any(LocalDateTime.class));
        verify(notifier).alertDaySummary(anyString());
    }

    /* ---------------- date handling ---------------- */

    @Test
    @DisplayName("a back-dated re-run force-closes at THAT day's close, not today's")
    void back_dated_rerun_uses_the_right_close_moment() {
        LocalDate lastFriday = LocalDate.of(2026, 8, 28);

        controller.rerunDaySummary(lastFriday, false);

        // The whole reason marketCloseOn(date) exists: stamping last Friday's
        // leftover positions with this afternoon's timestamp would be a lie in the
        // ledger, and the exit time is what every downstream report reads.
        verify(orderService).forceCloseOpenPositions(eq(lastFriday), eq(lastFriday.atTime(15, 30)));
    }

    @Test
    @DisplayName("omitting date targets today in the configured market zone")
    void date_defaults_to_today() {
        LocalDate today = LocalDate.now(ZoneId.of("Asia/Kolkata"));

        ResponseEntity<Map<String, Object>> response = controller.rerunDaySummary(null, false);

        assertThat(body(response)).containsEntry("date", today);
    }

    @Test
    @DisplayName("a weekend date is rejected with a reason rather than silently doing nothing")
    void weekend_is_rejected() {
        ResponseEntity<Map<String, Object>> response = controller.rerunDaySummary(SATURDAY, false);

        assertThat(response.getStatusCode().value()).isEqualTo(400);
        assertThat(body(response)).containsEntry("ran", false);
        assertThat((String) body(response).get("message")).contains("SATURDAY");
        verifyNoInteractions(orderService, notifier);
    }
}
