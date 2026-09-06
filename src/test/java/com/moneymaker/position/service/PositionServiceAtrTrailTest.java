package com.moneymaker.position.service;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.journal.PositionJournal;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeOrderRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

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
 * The chandelier trail (changeset 048) on a short: the floor is
 * {@code peak_profit − trail_atr_distance_at_entry}, it only tightens, it can
 * sit below zero, and it yields to the fixed stop whenever the fixed stop is
 * the tighter of the two.
 */
class PositionServiceAtrTrailTest {

    private static final LocalDateTime ENTRY = LocalDateTime.of(2026, 9, 7, 10, 30);

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
        order.setId(8L);
        order.setStatus("OPEN");
        order.setEntryDirection("SELL");
        order.setEntryPrice(new BigDecimal("150"));
        order.setEntryTime(ENTRY);
        order.setStopLossAtEntry(new BigDecimal("45"));          // 30% cap
        order.setTargetAtEntry(null);                             // target_mode NONE
        order.setTrailLadderAtEntry(null);                        // replaced by the distance
        order.setTrailAtrDistanceAtEntry(new BigDecimal("16"));   // 2 × ATR 8
        when(repo.findByStatus("OPEN")).thenReturn(List.of(order));
    }

    private void tick(String price, int minutesAfterEntry) {
        when(monitor.currentQuote(order))
                .thenReturn(new Quote(new BigDecimal(price), ENTRY.plusMinutes(minutesAfterEntry)));
        positionService.processPositions();
    }

    private void bar(String close, String high, String low, int minutesAfterEntry) {
        when(monitor.currentQuote(order))
                .thenReturn(new Quote(new BigDecimal(close), ENTRY.plusMinutes(minutesAfterEntry),
                        new BigDecimal(high), new BigDecimal(low)));
        positionService.processPositions();
    }

    private BigDecimal closedAt(String reason) {
        ArgumentCaptor<BigDecimal> price = ArgumentCaptor.forClass(BigDecimal.class);
        verify(orderService).closeManually(eq(8L), price.capture(), any(), eq(reason));
        return price.getValue();
    }

    @Test
    @DisplayName("the first tick floors the stop at entry + distance, below the 30% cap")
    void initialFloorIsEntryPlusDistance() {
        tick("150", 5);
        assertThat(order.getTrailSlAt()).isEqualByComparingTo("-16");
        verify(orderService, never()).closeManually(any(), any(), any(), any());
    }

    @Test
    @DisplayName("premium rising through entry + distance exits TRAIL_SL at that level, not at the cap")
    void adverseMoveHitsChandelier() {
        tick("150", 5);
        tick("170", 10);      // adverse −20 ≤ floor −16
        assertThat(closedAt("TRAIL_SL")).isEqualByComparingTo("166");
    }

    @Test
    @DisplayName("the floor follows the lowest low at a fixed distance and yields the exit at the floor")
    void floorRatchetsWithPeak() {
        tick("120", 5);       // peak +30 → floor +14
        assertThat(order.getTrailSlAt()).isEqualByComparingTo("14");
        tick("130", 10);      // peak unchanged, floor unchanged
        assertThat(order.getTrailSlAt()).isEqualByComparingTo("14");
        tick("110", 15);      // peak +40 → floor +24
        assertThat(order.getTrailSlAt()).isEqualByComparingTo("24");
        tick("128", 20);      // pnl +22 ≤ 24 → out at 150 − 24
        assertThat(closedAt("TRAIL_SL")).isEqualByComparingTo("126");
    }

    @Test
    @DisplayName("a bar whose high crosses the floor exits on the extreme, not the close")
    void intrabarHighTriggers() {
        tick("150", 5);
        bar("152", "168", "149", 10);   // close is fine, the high breached 166
        assertThat(closedAt("TRAIL_SL")).isEqualByComparingTo("166");
    }

    @Test
    @DisplayName("a distance wider than the cap leaves the fixed stop in charge")
    void fixedStopWhenChandelierLooser() {
        order.setTrailAtrDistanceAtEntry(new BigDecimal("60"));
        tick("150", 5);
        assertThat(order.getTrailSlAt()).isEqualByComparingTo("-60");
        tick("196", 10);      // adverse −46: fixed floor −45 is tighter than −60
        assertThat(closedAt("STOP_LOSS")).isEqualByComparingTo("195");
    }

    @Test
    @DisplayName("no distance on the row → the ladder path is untouched")
    void nullDistanceKeepsLadder() {
        order.setTrailAtrDistanceAtEntry(null);
        order.setTrailLadderAtEntry("25:2,50:25");
        tick("120", 5);       // peak +30 ≥ rung 25 → ladder floor 2
        assertThat(order.getTrailSlAt()).isEqualByComparingTo("2");
    }
}
