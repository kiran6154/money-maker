package com.moneymaker.scheduler;

import com.moneymaker.entity.TradeOrder;
import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.state.DailyEventGuard;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link DaySummaryScheduler}.
 *
 * <p>Covers: app-mode gate, DailyEventGuard once-per-day gate, summary text
 * shape (per-trade-result counts), and the no-trades fallback message.
 */
class DaySummarySchedulerTest {

    @Mock private OrderService orderService;
    @Mock private TradeOrderRepository tradeOrderRepository;
    @Mock private MarketHoursService marketHours;
    @Mock private NotificationService notifier;
    @Mock private DailyEventGuard dailyEventGuard;

    private DaySummaryScheduler scheduler;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        scheduler = new DaySummaryScheduler(
                orderService, tradeOrderRepository, marketHours, notifier, dailyEventGuard);
        ReflectionTestUtils.setField(scheduler, "appMode", "live");
        lenient().when(marketHours.zone()).thenReturn(ZoneId.of("Asia/Kolkata"));
        lenient().when(marketHours.marketCloseToday())
                .thenReturn(LocalDate.now().atTime(15, 30));
        lenient().when(marketHours.marketOpenToday())
                .thenReturn(LocalDate.now().atTime(9, 15));
        lenient().when(marketHours.forceCloseToday())
                .thenReturn(LocalDate.now().atTime(15, 25));
    }

    @Test
    void runEndOfDay_noop_in_backtest_mode() {
        ReflectionTestUtils.setField(scheduler, "appMode", "backtest");
        scheduler.runEndOfDay();
        verify(orderService, never()).forceCloseOpenPositions(any(), any());
        verify(notifier, never()).alertDaySummary(any());
    }

    @Test
    void runEndOfDay_noop_when_both_guard_keys_already_fired() {
        when(dailyEventGuard.alreadyFired(eq("day-summary-forceclose"), any())).thenReturn(true);
        when(dailyEventGuard.alreadyFired(eq("day-summary-telegram"), any())).thenReturn(true);

        scheduler.runEndOfDay();

        verify(orderService, never()).forceCloseOpenPositions(any(), any());
        verify(notifier, never()).alertDaySummary(any());
    }

    @Test
    void M51_only_telegram_runs_when_forceClose_already_marked() {
        // Recovery scenario: force-close succeeded earlier, telegram failed.
        // Next cron tick must skip force-close (already done) and retry
        // only the telegram half.
        when(dailyEventGuard.alreadyFired(eq("day-summary-forceclose"), any())).thenReturn(true);
        when(dailyEventGuard.alreadyFired(eq("day-summary-telegram"), any())).thenReturn(false);
        lenient().when(dailyEventGuard.firstTime(any(), any())).thenReturn(true);
        when(tradeOrderRepository.findByEntryTimeBetween(any(), any())).thenReturn(List.of());

        scheduler.runEndOfDay();

        verify(orderService, never()).forceCloseOpenPositions(any(), any());
        verify(notifier).alertDaySummary(anyString());
    }

    @Test
    void M51_telegram_guard_NOT_marked_when_send_fails() {
        // Telegram throws → guard for telegram half stays unmarked so the
        // next tick retries. Force-close half succeeds → its guard IS marked.
        when(dailyEventGuard.alreadyFired(eq("day-summary-forceclose"), any())).thenReturn(false);
        when(dailyEventGuard.alreadyFired(eq("day-summary-telegram"), any())).thenReturn(false);
        when(dailyEventGuard.firstTime(any(), any())).thenReturn(true);
        when(orderService.forceCloseOpenPositions(any(), any())).thenReturn(0);
        when(tradeOrderRepository.findByEntryTimeBetween(any(), any())).thenReturn(List.of());
        doThrow(new RuntimeException("telegram down"))
                .when(notifier).alertDaySummary(anyString());

        scheduler.runEndOfDay();

        verify(dailyEventGuard).firstTime(eq("day-summary-forceclose"), any());
        verify(dailyEventGuard, never()).firstTime(eq("day-summary-telegram"), any());
    }

    @Test
    void M52_force_true_bypasses_both_guards() {
        // Manual re-trigger with force=true must run both halves even if
        // both guards say already-fired. Guard marks are NOT updated.
        when(dailyEventGuard.alreadyFired(any(), any())).thenReturn(true);
        when(orderService.forceCloseOpenPositions(any(), any())).thenReturn(2);
        when(tradeOrderRepository.findByEntryTimeBetween(any(), any())).thenReturn(List.of());

        DaySummaryScheduler.RunSummary summary = scheduler.runForDate(LocalDate.now(), true);

        assertThat(summary.ranForceClose()).isTrue();
        assertThat(summary.ranTelegram()).isTrue();
        verify(orderService).forceCloseOpenPositions(any(), any());
        verify(notifier).alertDaySummary(anyString());
        // Guards untouched when force=true.
        verify(dailyEventGuard, never()).firstTime(any(), any());
    }

    @Test
    void runEndOfDay_runs_forceClose_then_builds_and_sends_summary() {
        when(dailyEventGuard.alreadyFired(eq("day-summary-forceclose"), any())).thenReturn(false);
        when(dailyEventGuard.alreadyFired(eq("day-summary-telegram"), any())).thenReturn(false);
        lenient().when(dailyEventGuard.firstTime(any(), any())).thenReturn(true);
        when(orderService.forceCloseOpenPositions(any(), any())).thenReturn(1);
        when(tradeOrderRepository.findByEntryTimeBetween(any(), any()))
                .thenReturn(List.of(
                        closedTrade(1, "TARGET", new BigDecimal("10")),
                        closedTrade(2, "STOP_LOSS", new BigDecimal("-5"))));

        scheduler.runEndOfDay();

        ArgumentCaptor<String> capturedSummary = ArgumentCaptor.forClass(String.class);
        verify(notifier).alertDaySummary(capturedSummary.capture());

        String body = capturedSummary.getValue();
        assertThat(body).contains("trades      : 2");
        assertThat(body).contains("winners     : 1");
        assertThat(body).contains("losers      : 1");
        assertThat(body).contains("force-closed: 1");
        assertThat(body).contains("TARGET=1");
        assertThat(body).contains("STOP_LOSS=1");
    }

    @Test
    void runEndOfDay_emits_no_trades_message_when_ledger_empty() {
        when(dailyEventGuard.alreadyFired(eq("day-summary-forceclose"), any())).thenReturn(false);
        when(dailyEventGuard.alreadyFired(eq("day-summary-telegram"), any())).thenReturn(false);
        lenient().when(dailyEventGuard.firstTime(any(), any())).thenReturn(true);
        when(orderService.forceCloseOpenPositions(any(), any())).thenReturn(0);
        when(tradeOrderRepository.findByEntryTimeBetween(any(), any())).thenReturn(List.of());

        scheduler.runEndOfDay();

        ArgumentCaptor<String> body = ArgumentCaptor.forClass(String.class);
        verify(notifier).alertDaySummary(body.capture());
        assertThat(body.getValue()).contains("no trades");
    }

    @Test
    void runEndOfDay_continues_when_forceClose_throws() {
        when(dailyEventGuard.alreadyFired(eq("day-summary-forceclose"), any())).thenReturn(false);
        when(dailyEventGuard.alreadyFired(eq("day-summary-telegram"), any())).thenReturn(false);
        lenient().when(dailyEventGuard.firstTime(any(), any())).thenReturn(true);
        when(orderService.forceCloseOpenPositions(any(), any()))
                .thenThrow(new RuntimeException("broker down"));
        when(tradeOrderRepository.findByEntryTimeBetween(any(), any())).thenReturn(List.of());

        scheduler.runEndOfDay();

        // Summary still fires even though force-close failed.
        verify(notifier).alertDaySummary(anyString());
    }

    /* ---------------- helpers ---------------- */

    private static TradeOrder closedTrade(long id, String exitReason, BigDecimal profit) {
        TradeOrder t = new TradeOrder();
        t.setId(id);
        t.setTradeConfigId(1);
        t.setInstrumentName("NIFTY");
        t.setOptionStrike(24000);
        t.setOptionType("CE");
        t.setEntryTime(LocalDateTime.of(2026, 4, 1, 10, 0));
        t.setStatus("CLOSED");
        t.setExitReason(exitReason);
        t.setProfit(profit);
        return t;
    }
}
