package com.moneymaker.position.service;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.journal.PositionJournal;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeOrderRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * Pins the journal wiring on the position monitor: which ticks produce an
 * observation, and — the part that matters — that observing can neither change
 * an exit nor prevent one.
 *
 * <p>Entries are BUY at 100, so per-share P&amp;L is {@code price - 100}.
 */
class PositionServiceJournalTest {

    private static final LocalDateTime ENTRY = LocalDateTime.of(2026, 5, 8, 9, 20);

    private TradeOrderRepository repo;
    private PositionMonitorService monitor;
    private OrderService orderService;
    private PositionJournal positionJournal;
    private PositionService positionService;
    private TradeOrder order;

    @BeforeEach
    void setUp() {
        repo = mock(TradeOrderRepository.class);
        monitor = mock(PositionMonitorService.class);
        orderService = mock(OrderService.class);
        positionJournal = mock(PositionJournal.class);
        PositionMonitorFactory factory = mock(PositionMonitorFactory.class);
        when(factory.active()).thenReturn(monitor);

        positionService = new PositionService(repo, factory, orderService, positionJournal);

        order = new TradeOrder();
        order.setId(1L);
        order.setStatus("OPEN");
        order.setEntryDirection("BUY");
        order.setEntryPrice(new BigDecimal("100"));
        order.setEntryTime(ENTRY);
        order.setStopLossAtEntry(new BigDecimal("60"));
        order.setTargetAtEntry(new BigDecimal("50"));

        when(repo.findByStatus("OPEN")).thenReturn(List.of(order));
    }

    private void tick(String price, int minutesAfterEntry) {
        when(monitor.currentQuote(order))
                .thenReturn(new Quote(new BigDecimal(price), ENTRY.plusMinutes(minutesAfterEntry)));
        positionService.processPositions();
    }

    @Test
    @DisplayName("each monitored open trade is observed once per evaluated tick, with that tick's P&L")
    void observesEveryEvaluatedTick() {
        tick("110", 5);
        tick("120", 10);

        verify(positionJournal).observe(eq(order), eq(ENTRY.plusMinutes(5)),
                eq(new BigDecimal("10")), isNull());
        verify(positionJournal).observe(eq(order), eq(ENTRY.plusMinutes(10)),
                eq(new BigDecimal("20")), isNull());
    }

    @Test
    @DisplayName("the monitor's decision is recorded with the tick that made it, before the close")
    void recordsTheDecisionAndStillCloses() {
        tick("155", 5); // +55, past the 50-point target

        InOrder order2 = inOrder(positionJournal, orderService);
        // The MONITOR row lands first so the timeline ends where the EXIT row
        // begins, rather than after it.
        order2.verify(positionJournal).observe(eq(order), eq(ENTRY.plusMinutes(5)),
                eq(new BigDecimal("55")), eq("TARGET"));
        order2.verify(orderService).closeManually(eq(1L), eq(new BigDecimal("155")),
                eq(ENTRY.plusMinutes(5)), eq("TARGET"));
    }

    @Test
    @DisplayName("a tick the monitor skipped produces no row — no quote")
    void noQuoteNoObservation() {
        when(monitor.currentQuote(order)).thenReturn(null);

        positionService.processPositions();

        verify(positionJournal, never()).observe(any(), any(), any(), any());
    }

    @Test
    @DisplayName("a tick the monitor skipped produces no row — the entry-candle guard")
    void sameCandleGuardObservesNothing() {
        tick("120", 0); // quote asOf == entry_time

        verify(positionJournal, never()).observe(any(), any(), any(), any());
    }

    @Test
    @DisplayName("a journal failure neither aborts the tick nor changes the exit")
    void journalFailureIsIsolated() {
        doThrow(new IllegalStateException("journal down"))
                .when(positionJournal).observe(any(), any(), any(), anyString());

        tick("39", 5); // -61, past the 60-point stop

        // The stop still fires, with the same price, time and reason it would
        // have had if nothing were being journalled. The price is the stop's
        // resting-order fill (entry 100 - 60 = 40), per the S4 decision.
        verify(orderService).closeManually(eq(1L), eq(new BigDecimal("40")),
                eq(ENTRY.plusMinutes(5)), eq("STOP_LOSS"));
    }

    @Test
    @DisplayName("a journal failure on a holding tick still saves the monitor columns")
    void journalFailureStillSavesTheRow() {
        doThrow(new IllegalStateException("journal down"))
                .when(positionJournal).observe(any(), any(), any(), any());

        tick("110", 5);

        verify(repo).save(order);
        assertThat(order.getPeakProfit()).isEqualByComparingTo("10");
        assertThat(order.getLastMonitoredAt()).isEqualTo(ENTRY.plusMinutes(5));
    }

    @Test
    @DisplayName("event state is bounded by the open set the monitor is about to walk")
    void retainsOnlyOpenTrades() {
        tick("110", 5);

        verify(positionJournal).retainOpen(List.of(1L));
    }

    @Test
    @DisplayName("no open rows means no journal traffic at all")
    void noOpenPositionsNoJournal() {
        when(repo.findByStatus("OPEN")).thenReturn(List.of());

        positionService.processPositions();

        verifyNoInteractions(positionJournal);
    }
}
