package com.moneymaker.position.service;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeOrderRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link PositionService}.
 *
 * <p>Three contract surfaces:
 * <ol>
 *   <li>Peak-P&L tracking — high-water on profit, low-water on loss.</li>
 *   <li>Same-candle-as-entry guard — never close on the candle that opened.</li>
 *   <li>Threshold breach — TARGET when pnl ≥ target; STOP_LOSS when pnl ≤ -stopLoss.
 *       Both thresholds are read from the row's snapshotted columns, not the
 *       live config (the "config edits don't retroactively close" invariant).</li>
 * </ol>
 */
class PositionServiceTest {

    @Mock private TradeOrderRepository tradeOrderRepository;
    @Mock private PositionMonitorFactory monitorFactory;
    @Mock private PositionMonitorService monitor;
    @Mock private OrderService orderService;

    private PositionService service;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        lenient().when(monitorFactory.active()).thenReturn(monitor);
        service = new PositionService(tradeOrderRepository, monitorFactory, orderService);
    }

    @Test
    void empty_open_list_is_noop() {
        when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of());
        service.processPositions();
        verify(monitor, never()).currentQuote(any());
    }

    @Test
    void tick_with_no_quote_is_skipped() {
        TradeOrder order = openOrder(100, "SELL", null, null);
        when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of(order));
        when(monitor.currentQuote(order)).thenReturn(null);

        service.processPositions();

        verify(tradeOrderRepository, never()).save(any());
    }

    @Test
    void tick_on_same_candle_as_entry_is_skipped() {
        TradeOrder order = openOrder(100, "SELL", null, null);
        order.setEntryTime(LocalDateTime.of(2026, 4, 1, 10, 0));
        when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of(order));
        // Same timestamp as entry → guard kicks in.
        when(monitor.currentQuote(order))
                .thenReturn(new Quote(new BigDecimal("90"), order.getEntryTime()));

        service.processPositions();

        verify(tradeOrderRepository, never()).save(any());
        verify(orderService, never()).closeManually(any(), any(), any(), any());
    }

    @Nested
    class PeakTracking {

        @Test
        void peak_profit_updates_when_pnl_exceeds_prior_peak() {
            TradeOrder order = openOrder(100, "SELL", null, null);
            order.setPeakProfit(new BigDecimal("3.00"));
            order.setPeakLoss(BigDecimal.ZERO);
            when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of(order));
            // SELL @ 100, current 95 → pnl = 5.
            when(monitor.currentQuote(order)).thenReturn(quoteAfterEntry(new BigDecimal("95")));

            service.processPositions();

            assertThat(order.getPeakProfit()).isEqualByComparingTo(new BigDecimal("5"));
            assertThat(order.getPeakLoss()).isEqualByComparingTo(BigDecimal.ZERO);
        }

        @Test
        void peak_loss_updates_when_pnl_drops_below_prior_trough() {
            TradeOrder order = openOrder(100, "SELL", null, null);
            order.setPeakProfit(BigDecimal.ZERO);
            order.setPeakLoss(new BigDecimal("-1.00"));
            when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of(order));
            // SELL @ 100, current 108 → pnl = -8.
            when(monitor.currentQuote(order)).thenReturn(quoteAfterEntry(new BigDecimal("108")));

            service.processPositions();

            assertThat(order.getPeakProfit()).isEqualByComparingTo(BigDecimal.ZERO);
            assertThat(order.getPeakLoss()).isEqualByComparingTo(new BigDecimal("-8"));
        }

        @Test
        void lastMonitoredPrice_and_lastMonitoredAt_are_updated() {
            TradeOrder order = openOrder(100, "SELL", null, null);
            LocalDateTime asOf = LocalDateTime.of(2026, 4, 1, 11, 30);
            when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of(order));
            when(monitor.currentQuote(order)).thenReturn(new Quote(new BigDecimal("95"), asOf));

            service.processPositions();

            assertThat(order.getLastMonitoredPrice()).isEqualByComparingTo(new BigDecimal("95"));
            assertThat(order.getLastMonitoredAt()).isEqualTo(asOf);
        }
    }

    @Nested
    class ThresholdBreach {

        @Test
        void TARGET_fires_when_pnl_reaches_or_exceeds_target() {
            // SELL @ 100, target snapshotted = 5. Current 95 → pnl = 5 → TARGET.
            TradeOrder order = openOrder(100, "SELL", new BigDecimal("5"), null);
            when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of(order));
            when(monitor.currentQuote(order)).thenReturn(quoteAfterEntry(new BigDecimal("95")));

            service.processPositions();

            verify(orderService).closeManually(
                    eq(order.getId()), eq(new BigDecimal("95")), any(), eq("TARGET"));
        }

        @Test
        void STOP_LOSS_fires_when_pnl_breaches_negative_stopLoss() {
            // SELL @ 100, stopLoss = 5 (stored positive). Current 106 → pnl = -6 → STOP_LOSS.
            TradeOrder order = openOrder(100, "SELL", null, new BigDecimal("5"));
            when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of(order));
            when(monitor.currentQuote(order)).thenReturn(quoteAfterEntry(new BigDecimal("106")));

            service.processPositions();

            verify(orderService).closeManually(
                    eq(order.getId()), eq(new BigDecimal("106")), any(), eq("STOP_LOSS"));
        }

        @Test
        void no_breach_when_pnl_within_band() {
            TradeOrder order = openOrder(100, "SELL", new BigDecimal("5"), new BigDecimal("5"));
            when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of(order));
            when(monitor.currentQuote(order)).thenReturn(quoteAfterEntry(new BigDecimal("98")));

            service.processPositions();

            verify(orderService, never()).closeManually(any(), any(), any(), any());
        }

        @Test
        void thresholds_read_from_row_not_live_config() {
            // The row carries no target/stopLoss snapshot. Even if "the live config"
            // would have triggered, the monitor must not close — invariant pin.
            TradeOrder order = openOrder(100, "SELL", null, null);
            when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of(order));
            when(monitor.currentQuote(order)).thenReturn(quoteAfterEntry(new BigDecimal("1")));  // huge profit

            service.processPositions();

            verify(orderService, never()).closeManually(any(), any(), any(), any());
        }
    }

    @Test
    void exception_in_one_tick_does_not_halt_the_rest() {
        TradeOrder bad  = openOrder(100, "SELL", null, null);  bad.setId(1L);
        TradeOrder good = openOrder(100, "SELL", null, null);  good.setId(2L);
        when(tradeOrderRepository.findByStatus("OPEN")).thenReturn(List.of(bad, good));
        when(monitor.currentQuote(bad)).thenThrow(new RuntimeException("simulated"));
        when(monitor.currentQuote(good)).thenReturn(quoteAfterEntry(new BigDecimal("95")));

        service.processPositions();

        // Good order was processed despite bad order's exception.
        ArgumentCaptor<TradeOrder> captor = ArgumentCaptor.forClass(TradeOrder.class);
        verify(tradeOrderRepository).save(captor.capture());
        assertThat(captor.getValue().getId()).isEqualTo(2L);
    }

    /* ---------------- helpers ---------------- */

    private static TradeOrder openOrder(double entry, String direction,
                                        BigDecimal target, BigDecimal stopLoss) {
        TradeOrder t = new TradeOrder();
        t.setId(42L);
        t.setTradeConfigId(1);
        t.setEntryDirection(direction);
        t.setEntryPrice(BigDecimal.valueOf(entry));
        t.setEntryTime(LocalDateTime.of(2026, 4, 1, 10, 0));
        t.setStatus("OPEN");
        t.setTargetAtEntry(target);
        t.setStopLossAtEntry(stopLoss);
        t.setOptionToken("OPT-100");
        return t;
    }

    private static Quote quoteAfterEntry(BigDecimal price) {
        // After the entry candle so the same-candle guard doesn't reject.
        return new Quote(price, LocalDateTime.of(2026, 4, 1, 10, 5));
    }
}
