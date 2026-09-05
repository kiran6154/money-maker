package com.moneymaker.order.service;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.journal.JournalRecorder;
import com.moneymaker.journal.ObservationContextFactory;
import com.moneymaker.repository.StrategyDefaultsRepository;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ConcurrentLinkedQueue;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pins the same-SIDE parallel cap ({@code trade_config.max_parallel_per_side},
 * changeset 038 — user decision 2026-08-31): an OPEN CE trade blocks another CE
 * entry on ANY strike for the same (config, strategy), while the PE side stays
 * available. The pre-existing {@code numberOfParallelTrades} cap counted by
 * BUY/SELL direction only, which is how two CE SELLs on different strikes ran
 * concurrently (orders 1941/1942, 2024-02-01).
 */
class OrderServiceSameSideCapTest {

    private static final String CE_KEY = "256265|5|CE|24000|11111|0|0";
    private static final String PE_KEY = "256265|5|PE|24000|22222|0|0";

    private TradeOrderRepository repo;
    private OrderService orderService;

    @BeforeEach
    void setUp() {
        repo = mock(TradeOrderRepository.class);
        OrderPlacementFactory placementFactory = mock(OrderPlacementFactory.class);
        OrderPlacementService placement = mock(OrderPlacementService.class);
        when(placementFactory.active()).thenReturn(placement);
        when(placement.getName()).thenReturn("BACKTESTING");
        when(repo.save(any(TradeOrder.class))).thenAnswer(inv -> inv.getArgument(0));
        when(repo.findFirstByTradeConfigIdAndStrategyIdAndOptionTokenAndStatus(
                any(), any(), anyString(), anyString())).thenReturn(Optional.empty());

        orderService = new OrderService(placementFactory, repo,
                mock(NotificationService.class), mock(JournalRecorder.class),
                mock(ObservationContextFactory.class),
                mock(StrategyDefaultsRepository.class));

        SharedData.tradeSignals = new ConcurrentLinkedQueue<>();
    }

    @AfterEach
    void tearDown() {
        SharedData.combinedDto = null;
        SharedData.tradeSignals = new ConcurrentLinkedQueue<>();
    }

    private void configWithSideCap(Integer maxParallelPerSide) {
        TradeConfig tc = new TradeConfig();
        tc.setId(7);
        tc.setStratergyId(2);
        tc.setTransactionType("SELL");
        tc.setLotQuantity(75);
        tc.setMaxParallelPerSide(maxParallelPerSide);
        SharedData.combinedDto = List.of(
                new TradeConfigCombinedDTO(tc, new Instrument(), null, List.of(), 2));
    }

    private void signal(String strikeKey) {
        TradeSignal s = new TradeSignal();
        s.setStrikeKey(strikeKey);
        s.setAction(TradeAction.SELL);
        s.setTradeConfigId(7);
        s.setStrategyId(2);
        s.setSignalTime(LocalDateTime.of(2026, 5, 8, 9, 20));
        s.setPrice(new BigDecimal("150"));
        SharedData.tradeSignals.add(s);
        orderService.processOrders();
    }

    @Test
    @DisplayName("an OPEN CE trade blocks a second CE entry on a different strike")
    void secondSameSideEntryIsBlocked() {
        configWithSideCap(1);
        when(repo.countByTradeConfigIdAndStrategyIdAndOptionTypeAndStatus(
                eq(7), eq(2), eq("CE"), eq("OPEN"))).thenReturn(1L);

        signal(CE_KEY);

        verify(repo, never()).save(any(TradeOrder.class));
    }

    @Test
    @DisplayName("the PE side stays available while a CE trade is OPEN")
    void oppositeSideIsUnaffected() {
        configWithSideCap(1);
        when(repo.countByTradeConfigIdAndStrategyIdAndOptionTypeAndStatus(
                eq(7), eq(2), eq("CE"), eq("OPEN"))).thenReturn(1L);
        when(repo.countByTradeConfigIdAndStrategyIdAndOptionTypeAndStatus(
                eq(7), eq(2), eq("PE"), eq("OPEN"))).thenReturn(0L);

        signal(PE_KEY);

        verify(repo).save(any(TradeOrder.class));
    }

    @Test
    @DisplayName("a cap of 2 admits a second same-side trade, and a third is blocked")
    void capOfTwoAdmitsTwo() {
        configWithSideCap(2);
        when(repo.countByTradeConfigIdAndStrategyIdAndOptionTypeAndStatus(
                eq(7), eq(2), eq("CE"), eq("OPEN"))).thenReturn(1L);
        signal(CE_KEY);
        verify(repo).save(any(TradeOrder.class));

        when(repo.countByTradeConfigIdAndStrategyIdAndOptionTypeAndStatus(
                eq(7), eq(2), eq("CE"), eq("OPEN"))).thenReturn(2L);
        signal(CE_KEY);
        // still just the one save from the first signal
        verify(repo).save(any(TradeOrder.class));
    }

    @Test
    @DisplayName("a fresh entity defaults the side cap to 1 — the safe behaviour needs no configuration")
    void entityDefaultIsOne() {
        // configWithSideCap(null) would bypass the gate; the entity initialiser
        // is what guarantees new configs are born capped.
        org.assertj.core.api.Assertions.assertThat(new TradeConfig().getMaxParallelPerSide()).isEqualTo(1);
    }
}
