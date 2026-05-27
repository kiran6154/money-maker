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
    }

    @Test
    void runEndOfDay_noop_in_backtest_mode() {
        ReflectionTestUtils.setField(scheduler, "appMode", "backtest");
        scheduler.runEndOfDay();
        verify(orderService, never()).forceCloseOpenPositions(any(), any());
        verify(notifier, never()).alertDaySummary(any());
    }

    @Test
    void runEndOfDay_noop_when_already_fired_for_today() {
        when(dailyEventGuard.firstTime(eq("day-summary"), any())).thenReturn(false);

        scheduler.runEndOfDay();

        verify(orderService, never()).forceCloseOpenPositions(any(), any());
        verify(notifier, never()).alertDaySummary(any());
    }

    @Test
    void runEndOfDay_runs_forceClose_then_builds_and_sends_summary() {
        when(dailyEventGuard.firstTime(eq("day-summary"), any())).thenReturn(true);
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
        when(dailyEventGuard.firstTime(eq("day-summary"), any())).thenReturn(true);
        when(orderService.forceCloseOpenPositions(any(), any())).thenReturn(0);
        when(tradeOrderRepository.findByEntryTimeBetween(any(), any())).thenReturn(List.of());

        scheduler.runEndOfDay();

        ArgumentCaptor<String> body = ArgumentCaptor.forClass(String.class);
        verify(notifier).alertDaySummary(body.capture());
        assertThat(body.getValue()).contains("no trades");
    }

    @Test
    void runEndOfDay_continues_when_forceClose_throws() {
        when(dailyEventGuard.firstTime(eq("day-summary"), any())).thenReturn(true);
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
