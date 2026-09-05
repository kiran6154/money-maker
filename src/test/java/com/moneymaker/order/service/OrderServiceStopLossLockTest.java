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
import com.moneymaker.strategy.Strategy2;
import com.moneymaker.strategy.Strategy6;
import com.moneymaker.strategy.StrategyFactory;
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
 * Pins the stop-loss lock ({@code Strategy.stopLossLocksBookForDay()},
 * Strategy 6's third gate): once a (config, strategy) has exited
 * {@code STOP_LOSS} today, that strategy opens nothing further on that config.
 * The lock is a strategy declaration, so strategy 2 on the same ledger keeps
 * re-entering; and a service built without a {@code StrategyFactory} — every
 * pre-existing unit test — has no policy at all and behaves as before.
 */
class OrderServiceStopLossLockTest {

    private static final String CE_KEY = "256265|5|CE|24000|11111|2|2";

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
        orderService.strategyFactory = new StrategyFactory(List.of(new Strategy2(null), new Strategy6(null)));

        SharedData.tradeSignals = new ConcurrentLinkedQueue<>();
    }

    @AfterEach
    void tearDown() {
        SharedData.combinedDto = null;
        SharedData.tradeSignals = new ConcurrentLinkedQueue<>();
    }

    private void config(int strategyId) {
        TradeConfig tc = new TradeConfig();
        tc.setId(7);
        tc.setStratergyId(strategyId);
        tc.setTransactionType("SELL");
        tc.setLotQuantity(75);
        SharedData.combinedDto = List.of(
                new TradeConfigCombinedDTO(tc, new Instrument(), null, List.of(), strategyId));
    }

    private void sellSignal(int strategyId) {
        TradeSignal s = new TradeSignal();
        s.setStrikeKey(CE_KEY);
        s.setAction(TradeAction.SELL);
        s.setTradeConfigId(7);
        s.setStrategyId(strategyId);
        s.setSignalTime(LocalDateTime.of(2026, 9, 7, 11, 20));
        s.setPrice(new BigDecimal("150"));
        SharedData.tradeSignals.add(s);
        orderService.processOrders();
    }

    private void stoppedToday(int strategyId, boolean stopped) {
        when(repo.existsByTradeConfigIdAndStrategyIdAndExitReasonAndEntryTimeBetween(
                eq(7), eq(strategyId), eq("STOP_LOSS"), any(), any())).thenReturn(stopped);
    }

    @Test
    @DisplayName("strategy 6: a STOP_LOSS exit earlier today blocks every further entry on the config")
    void strategy6IsLockedAfterAStop() {
        config(6);
        stoppedToday(6, true);

        sellSignal(6);

        verify(repo, never()).save(any(TradeOrder.class));
    }

    @Test
    @DisplayName("strategy 6: no stop today → the entry opens")
    void strategy6OpensWhenNotStopped() {
        config(6);
        stoppedToday(6, false);

        sellSignal(6);

        verify(repo).save(any(TradeOrder.class));
    }

    @Test
    @DisplayName("strategy 2 does not declare the lock, so it re-enters after a stop")
    void strategy2KeepsReentering() {
        config(2);
        stoppedToday(2, true);

        sellSignal(2);

        verify(repo).save(any(TradeOrder.class));
        verify(repo, never()).existsByTradeConfigIdAndStrategyIdAndExitReasonAndEntryTimeBetween(
                any(), any(), anyString(), any(), any());
    }

    @Test
    @DisplayName("no StrategyFactory wired (manual construction) → no policy, the entry opens")
    void noFactoryMeansNoPolicy() {
        orderService.strategyFactory = null;
        config(6);
        stoppedToday(6, true);

        sellSignal(6);

        verify(repo).save(any(TradeOrder.class));
    }
}
