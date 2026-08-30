package com.moneymaker.scheduler;

import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.state.DailyEventGuard;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pins the sent-marker contract of the end-of-day digest (GAPS #5).
 *
 * <p>The bug this replaces was quiet and total: the {@code alert_state} row went
 * in <i>before</i> the Telegram POST, so one dropped connection lost the day's
 * summary permanently — the guard then reported the day as done forever after.
 * The rule now is that a marker means "this actually happened", and the two
 * halves carry separate markers because they fail for unrelated reasons.</p>
 */
class DaySummarySentMarkerTest {

    private static final String LEGACY_KEY = "day-summary";
    private static final String KEY_FORCE_CLOSE = "day-summary-forceclose";
    private static final String KEY_TELEGRAM = "day-summary-telegram";

    /** A Monday, so the weekend short-circuit is never what makes a test pass. */
    private static final LocalDate MONDAY = LocalDate.of(2026, 8, 31);

    private OrderService orderService;
    private TradeOrderRepository tradeOrderRepository;
    private TradeConfigRepository tradeConfigRepository;
    private MarketHoursService marketHours;
    private NotificationService notifier;
    private DailyEventGuard guard;
    private DaySummaryScheduler scheduler;

    @BeforeEach
    void setUp() {
        orderService = mock(OrderService.class);
        tradeOrderRepository = mock(TradeOrderRepository.class);
        tradeConfigRepository = mock(TradeConfigRepository.class);
        marketHours = mock(MarketHoursService.class);
        notifier = mock(NotificationService.class);
        guard = mock(DailyEventGuard.class);

        when(marketHours.marketCloseOn(any(LocalDate.class))).thenAnswer(
                inv -> inv.getArgument(0, LocalDate.class).atTime(15, 30));
        when(marketHours.marketOpenOn(any(LocalDate.class))).thenAnswer(
                inv -> inv.getArgument(0, LocalDate.class).atTime(9, 15));
        when(tradeOrderRepository.findByEntryTimeBetween(any(), any())).thenReturn(List.of());
        when(orderService.forceCloseOpenPositions(any(LocalDate.class), any(LocalDateTime.class))).thenReturn(2);

        scheduler = new DaySummaryScheduler(orderService, tradeOrderRepository, tradeConfigRepository,
                marketHours, notifier, guard);
    }

    @Test
    @DisplayName("a delivered digest marks its own key, and force-close marks its own")
    void bothHalvesMarkOnSuccess() {
        when(notifier.alertDaySummary(anyString())).thenReturn(true);

        scheduler.runEndOfDayFor(MONDAY);

        verify(orderService).forceCloseOpenPositions(MONDAY, MONDAY.atTime(15, 30));
        verify(guard).firstTime(KEY_FORCE_CLOSE, MONDAY);
        verify(guard).firstTime(KEY_TELEGRAM, MONDAY);
    }

    @Test
    @DisplayName("a failed send leaves the telegram key unwritten so the next tick retries")
    void failedSendStaysUnmarked() {
        when(notifier.alertDaySummary(anyString())).thenReturn(false);

        scheduler.runEndOfDayFor(MONDAY);

        verify(notifier).alertDaySummary(anyString());
        verify(guard, never()).firstTime(eq(KEY_TELEGRAM), any());
        // The force-close half succeeded and must not be undone by the other
        // half's failure — that is the whole point of splitting the keys.
        verify(guard).firstTime(KEY_FORCE_CLOSE, MONDAY);
    }

    @Test
    @DisplayName("a send that throws is treated as undelivered, not as delivered")
    void thrownSendStaysUnmarked() {
        when(notifier.alertDaySummary(anyString())).thenThrow(new IllegalStateException("socket closed"));

        scheduler.runEndOfDayFor(MONDAY);

        verify(guard, never()).firstTime(eq(KEY_TELEGRAM), any());
    }

    @Test
    @DisplayName("the retry tick re-sends only the digest — it does not force-close twice")
    void retryTickOnlyResendsTheDigest() {
        when(guard.alreadyFired(KEY_FORCE_CLOSE, MONDAY)).thenReturn(true);
        when(notifier.alertDaySummary(anyString())).thenReturn(true);

        scheduler.runEndOfDayFor(MONDAY);

        verify(orderService, never()).forceCloseOpenPositions(any(), any());
        verify(notifier).alertDaySummary(anyString());
        verify(guard).firstTime(KEY_TELEGRAM, MONDAY);
    }

    @Test
    @DisplayName("a delivered digest is never sent twice, however often the cron fires")
    void deliveredDigestIsNotResent() {
        when(guard.alreadyFired(KEY_FORCE_CLOSE, MONDAY)).thenReturn(true);
        when(guard.alreadyFired(KEY_TELEGRAM, MONDAY)).thenReturn(true);

        scheduler.runEndOfDayFor(MONDAY);

        verify(notifier, never()).alertDaySummary(anyString());
        verify(orderService, never()).forceCloseOpenPositions(any(), any());
    }

    @Test
    @DisplayName("a force-close that throws leaves its key unwritten but still lets the digest go out")
    void forceCloseFailureDoesNotBlockTheDigest() {
        when(orderService.forceCloseOpenPositions(any(LocalDate.class), any(LocalDateTime.class)))
                .thenThrow(new IllegalStateException("db down"));
        when(notifier.alertDaySummary(anyString())).thenReturn(true);

        scheduler.runEndOfDayFor(MONDAY);

        verify(guard, never()).firstTime(eq(KEY_FORCE_CLOSE), any());
        // An operator with no positions to worry about still wants the digest.
        verify(notifier).alertDaySummary(anyString());
        verify(guard).firstTime(KEY_TELEGRAM, MONDAY);
    }

    @Test
    @DisplayName("a day the old single-key build already handled is left alone")
    void legacyKeySuppressesBothHalves() {
        // Deploying this change at 16:00 must not re-send a summary that the
        // previous build already delivered under the old "day-summary" key.
        when(guard.alreadyFired(LEGACY_KEY, MONDAY)).thenReturn(true);

        scheduler.runEndOfDayFor(MONDAY);

        verify(orderService, never()).forceCloseOpenPositions(any(), any());
        verify(notifier, never()).alertDaySummary(anyString());
    }

    @Test
    @DisplayName("weekends do no end-of-day work at all")
    void weekendIsSkipped() {
        scheduler.runEndOfDayFor(LocalDate.of(2026, 8, 30)); // Sunday

        verify(orderService, never()).forceCloseOpenPositions(any(), any());
        verify(notifier, never()).alertDaySummary(anyString());
    }
}
