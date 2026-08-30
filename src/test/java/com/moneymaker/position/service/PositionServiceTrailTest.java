package com.moneymaker.position.service;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.journal.PositionJournal;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeOrderRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pins the trailing stop as {@code PositionService} enforces it.
 *
 * <p>Every case here is about a floor that must or must not move. The ladder is
 * only consulted on trades that get far enough to reach a rung, and it changes
 * the exit price rather than whether the trade exits at all — so a wrong floor
 * shows up as a slightly worse average, not as a failure anyone would notice.</p>
 *
 * <p>Entries are BUY at 100 so per-share P&amp;L is simply {@code price - 100}.</p>
 */
class PositionServiceTrailTest {

    private static final LocalDateTime ENTRY = LocalDateTime.of(2026, 5, 8, 9, 20);

    private TradeOrderRepository repo;
    private PositionMonitorService monitor;
    private OrderService orderService;
    private PositionService positionService;
    private TradeOrder order;

    @BeforeEach
    void setUp() {
        repo = mock(TradeOrderRepository.class);
        monitor = mock(PositionMonitorService.class);
        orderService = mock(OrderService.class);
        PositionMonitorFactory factory = mock(PositionMonitorFactory.class);
        when(factory.active()).thenReturn(monitor);

        positionService = new PositionService(repo, factory, orderService, mock(PositionJournal.class));

        order = new TradeOrder();
        order.setId(1L);
        order.setStatus("OPEN");
        order.setEntryDirection("BUY");
        order.setEntryPrice(new BigDecimal("100"));
        order.setEntryTime(ENTRY);
        order.setPeakProfit(BigDecimal.ZERO);
        order.setPeakLoss(BigDecimal.ZERO);
        order.setStopLossAtEntry(new BigDecimal("60"));
        order.setTargetAtEntry(new BigDecimal("500")); // out of reach; not under test
        order.setTrailLadderAtEntry("25:2,50:25,75:50");

        when(repo.findByStatus("OPEN")).thenReturn(List.of(order));
    }

    /** Feeds one monitor tick at {@code price}, one minute later each time. */
    private void tick(String price, int minutesAfterEntry) {
        when(monitor.currentQuote(order))
                .thenReturn(new Quote(new BigDecimal(price), ENTRY.plusMinutes(minutesAfterEntry)));
        positionService.processPositions();
    }

    @Test
    @DisplayName("no rung reached leaves the trade on its fixed stop")
    void belowFirstRungNoFloor() {
        tick("120", 5); // +20, first rung is 25

        assertThat(order.getTrailSlAt()).isNull();
        verify(orderService, never()).closeManually(any(), any(), any(), any());
    }

    @Test
    @DisplayName("reaching a rung sets the floor without closing the trade on that same tick")
    void rungArmsWithoutClosing() {
        // The trap this guards: peak and P&L are equal on the arming tick, so a
        // floor at or above the trigger would exit instantly at the rung price.
        tick("125", 5); // +25 exactly

        assertThat(order.getTrailSlAt()).isEqualByComparingTo("2");
        verify(orderService, never()).closeManually(any(), any(), any(), any());
    }

    @Test
    @DisplayName("the floor holds when price falls back — the ratchet does not loosen")
    void floorHoldsOnPullback() {
        tick("155", 5);  // +55 → floor +25
        assertThat(order.getTrailSlAt()).isEqualByComparingTo("25");

        tick("130", 10); // +30, back below the 50 rung
        assertThat(order.getTrailSlAt()).isEqualByComparingTo("25");
        verify(orderService, never()).closeManually(any(), any(), any(), any());
    }

    @Test
    @DisplayName("falling to the floor closes the trade green as TRAIL_SL")
    void trailFloorClosesGreen() {
        tick("155", 5);  // +55 → floor +25
        tick("124", 10); // +24, at or below the floor

        // The whole point: this trade was +55, reversed, and books the FLOOR —
        // +25, the resting SL order's fill (S4 decision) — where the fixed
        // 60-point stop would have let it run to -60.
        verify(orderService).closeManually(eq(1L), eq(new BigDecimal("125")),
                eq(ENTRY.plusMinutes(10)), eq("TRAIL_SL"));
    }

    @Test
    @DisplayName("a bar that touches the floor intra-bar fills it even when the close bounces back above")
    void floorTouchedIntraBarFillsAtFloor() {
        tick("155", 5); // +55 → floor +25

        // Close +30 (above the floor), but the bar's low went to +24 — a
        // resting SL order at +25 fills on the touch. Old close-only detection
        // would have held this trade.
        when(monitor.currentQuote(order)).thenReturn(new Quote(
                new BigDecimal("130"), ENTRY.plusMinutes(10),
                new BigDecimal("135"), new BigDecimal("124")));
        positionService.processPositions();

        verify(orderService).closeManually(eq(1L), eq(new BigDecimal("125")),
                eq(ENTRY.plusMinutes(10)), eq("TRAIL_SL"));
    }

    @Test
    @DisplayName("a candle that gaps past several rungs lands on the highest floor earned")
    void gapLandsOnHighestFloor() {
        tick("180", 5); // +80 in one candle → 75-rung floor of +50

        assertThat(order.getTrailSlAt()).isEqualByComparingTo("50");
    }

    @Test
    @DisplayName("before any rung arms, the fixed stop still closes the trade as STOP_LOSS")
    void fixedStopStillApplies() {
        tick("39", 5); // -61, past the 60-point stop, no rung ever reached

        // Fill is at the stop itself (entry 100 - 60 = 40), not the tick that
        // detected the breach — the resting-order model (S4 decision).
        verify(orderService).closeManually(eq(1L), eq(new BigDecimal("40")),
                eq(ENTRY.plusMinutes(5)), eq("STOP_LOSS"));
    }

    @Test
    @DisplayName("a trade with no ladder never reports TRAIL_SL")
    void noLadderNeverTrails() {
        order.setTrailLadderAtEntry(null);

        tick("155", 5);
        assertThat(order.getTrailSlAt()).isNull();

        tick("39", 10);
        verify(orderService).closeManually(eq(1L), any(), any(), eq("STOP_LOSS"));
    }

    @Test
    @DisplayName("the target still wins over the floor when both are breached")
    void targetOutranksTrail() {
        // Target is checked first because it is the better outcome and the one the
        // trade was opened for; a tick that reaches both should not book the floor.
        order.setTargetAtEntry(new BigDecimal("60"));

        tick("165", 5); // +65 — past the target and past every rung

        verify(orderService).closeManually(eq(1L), any(), any(), eq("TARGET"));
    }
}
