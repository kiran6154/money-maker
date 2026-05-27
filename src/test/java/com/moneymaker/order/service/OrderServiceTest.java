package com.moneymaker.order.service;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link OrderService}.
 *
 * <p>Highest-value behaviours from the order lifecycle: dedupe (open same
 * direction, opposite-direction close, exact-duplicate guard), all four
 * cap enforcement paths, and force-close semantics. Tests use Mockito for
 * the repository + placement factory + notifier; signals are placed directly
 * onto the static {@link SharedData#tradeSignals} queue and drained via
 * {@link OrderService#processOrders()}.
 */
class OrderServiceTest {

    @Mock private OrderPlacementFactory placementFactory;
    @Mock private OrderPlacementService placement;
    @Mock private TradeOrderRepository tradeOrderRepository;
    @Mock private NotificationService notifier;

    private OrderService service;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        // Default: BACKTESTING placement, no broker order id returned, fresh save returns input.
        lenient().when(placementFactory.active()).thenReturn(placement);
        lenient().when(placement.getName()).thenReturn("BACKTESTING");
        lenient().when(placement.place(any(), any())).thenReturn(null);
        lenient().when(tradeOrderRepository.save(any(TradeOrder.class)))
                .thenAnswer(inv -> {
                    TradeOrder t = inv.getArgument(0);
                    if (t.getId() == null) t.setId(1L);
                    return t;
                });
        service = new OrderService(placementFactory, tradeOrderRepository, notifier);

        // Establish a fresh shared state per test.
        SharedData.tradeSignals.clear();
        SharedData.combinedDto = java.util.List.of(buildConfig(1));
    }

    @AfterEach
    void tearDown() {
        SharedData.tradeSignals.clear();
        SharedData.combinedDto = null;
    }

    /* ---------------- happy path ---------------- */

    @Test
    void processOrders_with_empty_queue_is_noop() {
        service.processOrders();
        verify(tradeOrderRepository, never()).save(any());
    }

    @Test
    void processOrders_opens_new_trade_when_no_open_position_and_txn_matches() {
        when(tradeOrderRepository.findFirstByTradeConfigIdAndOptionTokenAndStatus(
                eq(1), eq("OPT-100"), eq("OPEN"))).thenReturn(Optional.empty());

        SharedData.tradeSignals.add(sellSignal());
        service.processOrders();

        ArgumentCaptor<TradeOrder> captor = ArgumentCaptor.forClass(TradeOrder.class);
        verify(tradeOrderRepository).save(captor.capture());
        TradeOrder saved = captor.getValue();
        assertThat(saved.getStatus()).isEqualTo("OPEN");
        assertThat(saved.getEntryDirection()).isEqualTo("SELL");
        assertThat(saved.getOptionStrike()).isEqualTo(24000);
        assertThat(saved.getOptionType()).isEqualTo("CE");
        assertThat(saved.getTradeConfigId()).isEqualTo(1);
        verify(notifier).alertOrderOpened(any());
    }

    @Test
    void open_trade_snapshots_target_and_stopLoss_at_entry() {
        when(tradeOrderRepository.findFirstByTradeConfigIdAndOptionTokenAndStatus(
                any(), anyString(), anyString())).thenReturn(Optional.empty());

        SharedData.tradeSignals.add(sellSignal());
        service.processOrders();

        ArgumentCaptor<TradeOrder> captor = ArgumentCaptor.forClass(TradeOrder.class);
        verify(tradeOrderRepository).save(captor.capture());
        TradeOrder saved = captor.getValue();
        // Config target was set to 10.0, stopLoss to 5.0.
        assertThat(saved.getTargetAtEntry()).isEqualByComparingTo(new BigDecimal("10.00"));
        assertThat(saved.getStopLossAtEntry()).isEqualByComparingTo(new BigDecimal("5.00"));
    }

    @Test
    void open_trade_seeds_peak_profit_and_loss_at_zero() {
        when(tradeOrderRepository.findFirstByTradeConfigIdAndOptionTokenAndStatus(
                any(), anyString(), anyString())).thenReturn(Optional.empty());

        SharedData.tradeSignals.add(sellSignal());
        service.processOrders();

        ArgumentCaptor<TradeOrder> captor = ArgumentCaptor.forClass(TradeOrder.class);
        verify(tradeOrderRepository).save(captor.capture());
        TradeOrder saved = captor.getValue();
        assertThat(saved.getPeakProfit()).isEqualByComparingTo(BigDecimal.ZERO);
        assertThat(saved.getPeakLoss()).isEqualByComparingTo(BigDecimal.ZERO);
    }

    @Nested
    class CloseSemantics {

        @Test
        void opposite_direction_signal_closes_open_position() {
            // Open SELL exists; BUY signal arrives → closeOrder called.
            TradeOrder existingOpen = openTradeOrder("SELL", 24000, "CE");
            when(tradeOrderRepository.findFirstByTradeConfigIdAndOptionTokenAndStatus(
                    eq(1), eq("OPT-100"), eq("OPEN"))).thenReturn(Optional.of(existingOpen));

            TradeSignal buySignal = sellSignal();
            buySignal.setAction(TradeAction.BUY);
            SharedData.tradeSignals.add(buySignal);

            service.processOrders();

            assertThat(existingOpen.getStatus()).isEqualTo("CLOSED");
            assertThat(existingOpen.getExitPrice()).isEqualByComparingTo(buySignal.getPrice());
            assertThat(existingOpen.getExitReason()).isEqualTo("SIGNAL");
            verify(notifier).alertOrderClosed(any());
        }

        @Test
        void same_direction_signal_is_skipped_when_open_exists() {
            // Open SELL exists; another SELL → dedupe; no save, no broker call.
            TradeOrder existingOpen = openTradeOrder("SELL", 24000, "CE");
            when(tradeOrderRepository.findFirstByTradeConfigIdAndOptionTokenAndStatus(
                    eq(1), eq("OPT-100"), eq("OPEN"))).thenReturn(Optional.of(existingOpen));

            SharedData.tradeSignals.add(sellSignal());

            service.processOrders();

            verify(tradeOrderRepository, never()).save(any());
            verify(notifier, never()).alertOrderOpened(any());
        }
    }

    @Nested
    class CapEnforcement {

        @Test
        void signal_skipped_when_transaction_type_does_not_match_action() {
            // Config transactionType=SELL; signal action=BUY (and no open exists) → skip
            when(tradeOrderRepository.findFirstByTradeConfigIdAndOptionTokenAndStatus(
                    any(), anyString(), anyString())).thenReturn(Optional.empty());

            TradeSignal buySignal = sellSignal();
            buySignal.setAction(TradeAction.BUY);
            SharedData.tradeSignals.add(buySignal);

            service.processOrders();

            verify(tradeOrderRepository, never()).save(any());
        }

        @Test
        void signal_skipped_when_numberOfTradesPerDay_reached() {
            TradeConfigCombinedDTO cfg = buildConfig(1);
            cfg.getTradeConfig().setNumberOfTradesPerDay(2);
            SharedData.combinedDto = java.util.List.of(cfg);

            when(tradeOrderRepository.findFirstByTradeConfigIdAndOptionTokenAndStatus(
                    any(), anyString(), anyString())).thenReturn(Optional.empty());
            when(tradeOrderRepository.countByTradeConfigIdAndEntryTimeBetween(
                    eq(1), any(), any())).thenReturn(2L);

            SharedData.tradeSignals.add(sellSignal());
            service.processOrders();

            verify(tradeOrderRepository, never()).save(any());
        }

        @Test
        void signal_skipped_when_max_loss_realised() {
            TradeConfigCombinedDTO cfg = buildConfig(1);
            cfg.getTradeConfig().setMaxLoss(new BigDecimal("500"));
            SharedData.combinedDto = java.util.List.of(cfg);

            when(tradeOrderRepository.findFirstByTradeConfigIdAndOptionTokenAndStatus(
                    any(), anyString(), anyString())).thenReturn(Optional.empty());
            // realised = -600 → already at -maxLoss (-500), skip new entries.
            when(tradeOrderRepository.sumRealisedProfitForDay(eq(1), any(), any()))
                    .thenReturn(new BigDecimal("-600"));

            SharedData.tradeSignals.add(sellSignal());
            service.processOrders();

            verify(tradeOrderRepository, never()).save(any());
        }

        @Test
        void signal_skipped_when_numberOfParallelTrades_reached() {
            TradeConfigCombinedDTO cfg = buildConfig(1);
            cfg.getTradeConfig().setNumberOfParallelTrades(1);
            SharedData.combinedDto = java.util.List.of(cfg);

            when(tradeOrderRepository.findFirstByTradeConfigIdAndOptionTokenAndStatus(
                    any(), anyString(), anyString())).thenReturn(Optional.empty());
            when(tradeOrderRepository.countByTradeConfigIdAndEntryDirectionAndStatus(
                    eq(1), eq("SELL"), eq("OPEN"))).thenReturn(1L);

            SharedData.tradeSignals.add(sellSignal());
            service.processOrders();

            verify(tradeOrderRepository, never()).save(any());
        }

        @Test
        void exact_duplicate_is_skipped() {
            when(tradeOrderRepository.findFirstByTradeConfigIdAndOptionTokenAndStatus(
                    any(), anyString(), anyString())).thenReturn(Optional.empty());
            when(tradeOrderRepository.existsByTradeConfigIdAndOptionTokenAndEntryDirectionAndEntryTime(
                    eq(1), eq("OPT-100"), eq("SELL"), any())).thenReturn(true);

            SharedData.tradeSignals.add(sellSignal());
            service.processOrders();

            verify(tradeOrderRepository, never()).save(any());
        }
    }

    @Nested
    class ForceCloseOpenPositions {

        @Test
        void closes_all_open_trades_in_day_with_FORCE_CLOSE_reason() {
            LocalDateTime closeAt = LocalDateTime.of(2026, 4, 1, 15, 20);
            TradeOrder open = openTradeOrder("SELL", 24000, "CE");
            open.setEntryPrice(new BigDecimal("100"));
            open.setOptionToken("OPT-100");
            when(tradeOrderRepository.findByStatusAndEntryTimeBetween(
                    eq("OPEN"), any(), any())).thenReturn(java.util.List.of(open));

            int closed = service.forceCloseOpenPositions(java.time.LocalDate.of(2026, 4, 1), closeAt);

            assertThat(closed).isEqualTo(1);
            assertThat(open.getStatus()).isEqualTo("CLOSED");
            assertThat(open.getExitReason()).isEqualTo("FORCE_CLOSE");
            assertThat(open.getExitTime()).isEqualTo(closeAt);
            // No cached price for OPT-100 → falls back to entry price (zero profit).
            assertThat(open.getExitPrice()).isEqualByComparingTo(new BigDecimal("100"));
            assertThat(open.getProfit()).isEqualByComparingTo(BigDecimal.ZERO);
            verify(notifier).alertOrderForceClosed(any());
        }

        @Test
        void returns_zero_when_no_open_positions() {
            when(tradeOrderRepository.findByStatusAndEntryTimeBetween(
                    eq("OPEN"), any(), any())).thenReturn(java.util.List.of());

            int closed = service.forceCloseOpenPositions(
                    java.time.LocalDate.of(2026, 4, 1),
                    LocalDateTime.of(2026, 4, 1, 15, 20));

            assertThat(closed).isZero();
            verify(tradeOrderRepository, never()).save(any());
        }
    }

    @Nested
    class CloseManually {

        @Test
        void closes_open_trade_with_given_reason_and_price() {
            TradeOrder open = openTradeOrder("SELL", 24000, "CE");
            open.setEntryPrice(new BigDecimal("100"));
            open.setId(42L);
            when(tradeOrderRepository.findById(42L)).thenReturn(Optional.of(open));

            LocalDateTime exitTime = LocalDateTime.of(2026, 4, 1, 12, 30);
            TradeOrder result = service.closeManually(42L, new BigDecimal("90"), exitTime, "TARGET");

            assertThat(result.getStatus()).isEqualTo("CLOSED");
            assertThat(result.getExitReason()).isEqualTo("TARGET");
            assertThat(result.getExitPrice()).isEqualByComparingTo(new BigDecimal("90"));
            assertThat(result.getExitTime()).isEqualTo(exitTime);
            // SELL profit when price drops: 100 - 90 = 10.
            assertThat(result.getProfit()).isEqualByComparingTo(new BigDecimal("10"));
        }

        @Test
        void skips_when_already_closed() {
            TradeOrder closed = openTradeOrder("SELL", 24000, "CE");
            closed.setStatus("CLOSED");
            closed.setId(42L);
            when(tradeOrderRepository.findById(42L)).thenReturn(Optional.of(closed));

            service.closeManually(42L, new BigDecimal("90"),
                    LocalDateTime.of(2026, 4, 1, 12, 30), "TARGET");

            // No state change (save not invoked for status flip).
            assertThat(closed.getExitReason()).isNull();
        }
    }

    /* ---------------- helpers ---------------- */

    private TradeSignal sellSignal() {
        TradeSignal sig = new TradeSignal();
        sig.setStrikeKey("256265|5minute|CE|24000|OPT-100|0|0");
        sig.setAction(TradeAction.SELL);
        sig.setTradeConfigId(1);
        sig.setSignalTime(LocalDateTime.of(2026, 4, 1, 10, 30));
        sig.setPrimarySma(50);
        sig.setInterval("5minute");
        sig.setPrice(new BigDecimal("95.00"));
        return sig;
    }

    private TradeOrder openTradeOrder(String direction, int strike, String optionType) {
        TradeOrder t = new TradeOrder();
        t.setTradeConfigId(1);
        t.setInstrumentName("NIFTY");
        t.setInstrumentToken("256265");
        t.setOptionStrike(strike);
        t.setOptionType(optionType);
        t.setOptionToken("OPT-100");
        t.setEntryDirection(direction);
        t.setEntryTime(LocalDateTime.of(2026, 4, 1, 10, 0));
        t.setEntryPrice(new BigDecimal("100.00"));
        t.setStatus("OPEN");
        return t;
    }

    private static TradeConfigCombinedDTO buildConfig(int id) {
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();
        TradeConfig tc = new TradeConfig();
        tc.setId(id);
        tc.setTradingSide("CE");
        tc.setTransactionType("SELL");
        tc.setTarget(new BigDecimal("10.00"));
        tc.setStopLoss(new BigDecimal("5.00"));
        tc.setStratergyId(1);
        dto.setTradeConfig(tc);

        Instrument ins = new Instrument();
        ins.setInsName("NIFTY");
        dto.setInstrument(ins);

        InstrumentDetails details = new InstrumentDetails();
        details.setInstrumentToken(256265);
        dto.setInstrumentDetails(details);
        return dto;
    }
}
