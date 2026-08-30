package com.moneymaker.order.service;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.journal.JournalRecorder;
import com.moneymaker.journal.ObservationContextFactory;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ConcurrentLinkedQueue;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.atLeastOnce;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pins what {@code OrderService} freezes onto a trade at entry: the exit bracket,
 * the points ceiling that can only tighten the stop, and the trailing ladder.
 *
 * <p>These three are snapshotted rather than read live, so an error here is
 * permanent for the life of the trade — {@code PositionService} has no way to
 * notice that the stop it is enforcing was resolved wrongly.</p>
 */
class OrderServiceBracketAtEntryTest {

    private static final String STRIKE_KEY = "256265|5|CE|24000|12345|0|0";

    private TradeOrderRepository repo;
    private OrderPlacementFactory placementFactory;
    private OrderPlacementService placement;
    private OrderService orderService;

    @BeforeEach
    void setUp() {
        repo = mock(TradeOrderRepository.class);
        placementFactory = mock(OrderPlacementFactory.class);
        placement = mock(OrderPlacementService.class);
        JournalRecorder journal = mock(JournalRecorder.class);

        when(placementFactory.active()).thenReturn(placement);
        when(placement.getName()).thenReturn("BACKTESTING");
        when(placement.place(any(), any())).thenReturn(null);
        // Echo the row back so openOrder's save() chain behaves like JPA's.
        when(repo.save(any(TradeOrder.class))).thenAnswer(inv -> inv.getArgument(0));
        when(repo.findFirstByTradeConfigIdAndStrategyIdAndOptionTokenAndStatus(
                any(), any(), anyString(), anyString())).thenReturn(Optional.empty());

        orderService = new OrderService(placementFactory, repo,
                mock(NotificationService.class), journal, mock(ObservationContextFactory.class));

        SharedData.tradeSignals = new ConcurrentLinkedQueue<>();
    }

    @AfterEach
    void tearDown() {
        SharedData.combinedDto = null;
        SharedData.tradeSignals = new ConcurrentLinkedQueue<>();
    }

    /** A config trading the standing 80-250 band with a 20% / 30% bracket. */
    private TradeConfig config(BigDecimal maxSlPoints, String trailLadder) {
        TradeConfig tc = new TradeConfig();
        tc.setId(7);
        tc.setStratergyId(1);
        tc.setTransactionType("SELL");
        tc.setLotQuantity(75);
        tc.setTargetPct(new BigDecimal("0.20"));
        tc.setSlPct(new BigDecimal("0.30"));
        tc.setMaxSlPoints(maxSlPoints);
        tc.setTrailLadder(trailLadder);
        return tc;
    }

    private TradeOrder openAt(BigDecimal entryPremium, TradeConfig tc) {
        Instrument instrument = new Instrument();
        SharedData.combinedDto = List.of(
                new TradeConfigCombinedDTO(tc, instrument, null, List.of(), 1));

        TradeSignal signal = new TradeSignal();
        signal.setStrikeKey(STRIKE_KEY);
        signal.setAction(TradeAction.SELL);
        signal.setTradeConfigId(7);
        signal.setStrategyId(1);
        signal.setSignalTime(LocalDateTime.of(2026, 5, 8, 9, 20));
        signal.setPrice(entryPremium);
        SharedData.tradeSignals.add(signal);

        orderService.processOrders();

        ArgumentCaptor<TradeOrder> saved = ArgumentCaptor.forClass(TradeOrder.class);
        verify(repo, atLeastOnce()).save(saved.capture());
        return saved.getValue();
    }

    @Test
    @DisplayName("the points ceiling wins when the percentage resolves above it")
    void capBindsAtTheTopOfTheBand() {
        // 30% of a 250-point leg is 75 points — 5,625 rupees on one 75-unit lot,
        // on a trade targeting 50. This is the case the ceiling exists for.
        TradeOrder order = openAt(new BigDecimal("250"), config(new BigDecimal("60"), null));

        assertThat(order.getStopLossAtEntry()).isEqualByComparingTo("60");
        // The target is deliberately uncapped: a short leg's gain is bounded by
        // its premium while its loss is not.
        assertThat(order.getTargetAtEntry()).isEqualByComparingTo("50.00");
    }

    @Test
    @DisplayName("the percentage wins when it resolves below the ceiling")
    void percentageWinsAtTheBottomOfTheBand() {
        // 30% of 80 is 24 — well inside the 60-point ceiling, so the cap must not
        // touch it. A cap that widened a stop would be worse than no cap.
        TradeOrder order = openAt(new BigDecimal("80"), config(new BigDecimal("60"), null));

        assertThat(order.getStopLossAtEntry()).isEqualByComparingTo("24.00");
    }

    @Test
    @DisplayName("no ceiling configured leaves the resolved stop alone")
    void noCeilingIsNeutral() {
        TradeOrder order = openAt(new BigDecimal("250"), config(null, null));

        assertThat(order.getStopLossAtEntry()).isEqualByComparingTo("75.00");
    }

    @Test
    @DisplayName("the ladder is snapshotted canonicalised, not read live")
    void ladderIsSnapshotted() {
        TradeOrder order = openAt(new BigDecimal("200"), config(new BigDecimal("60"), " 25 : 2 ,50:25"));

        assertThat(order.getTrailLadderAtEntry()).isEqualTo("25:2,50:25");
    }

    @Test
    @DisplayName("a ladder corrupted in SQL opens the trade without trailing rather than blocking it")
    void malformedLadderDegradesToNoTrailing() {
        // Answering a config typo with a silent trading outage is the worse
        // failure — the fixed stop still protects the trade.
        TradeOrder order = openAt(new BigDecimal("200"), config(new BigDecimal("60"), "25:2,oops"));

        assertThat(order.getTrailLadderAtEntry()).isNull();
        assertThat(order.getStopLossAtEntry()).isEqualByComparingTo("60");
    }
}
