package com.moneymaker.order.service;

import com.moneymaker.dto.TradeAction;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.dto.TradeSignal;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.StrategyDefaults;
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
    private StrategyDefaultsRepository strategyDefaults;
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

        strategyDefaults = mock(StrategyDefaultsRepository.class);
        // No strategy_defaults row is the default state for most strategies —
        // changeset 033 seeded only strategy 1 — and must read as the legacy
        // PERCENT bracket.
        when(strategyDefaults.findById(any())).thenReturn(Optional.empty());

        orderService = new OrderService(placementFactory, repo,
                mock(NotificationService.class), journal, mock(ObservationContextFactory.class),
                strategyDefaults);

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

    // ------------------------------------------------------------------
    // Bracket mode (changeset 041) — which column the strategy exits on
    // ------------------------------------------------------------------

    /** Gives strategy 1 a strategy_defaults row carrying the two modes. */
    private void modes(String targetMode, String slMode) {
        StrategyDefaults defaults = new StrategyDefaults();
        defaults.setStrategyId(1);
        defaults.setTargetMode(targetMode);
        defaults.setSlMode(slMode);
        when(strategyDefaults.findById(1)).thenReturn(Optional.of(defaults));
    }

    /** The 80-250 band config, plus the absolute points columns POINTS mode reads. */
    private TradeConfig configWithBothShapes() {
        TradeConfig tc = config(new BigDecimal("60"), null);
        tc.setTarget(new BigDecimal("20"));
        tc.setStopLoss(new BigDecimal("20"));
        return tc;
    }

    @Test
    @DisplayName("no strategy_defaults row keeps the pre-041 percentage bracket")
    void missingDefaultsRowIsLegacyPercent() {
        // The behaviour-neutrality guarantee 041 ships on: adding the switch must
        // not move a ledger until someone flips it.
        TradeOrder order = openAt(new BigDecimal("200"), configWithBothShapes());

        assertThat(order.getTargetAtEntry()).isEqualByComparingTo("40.00");
        assertThat(order.getStopLossAtEntry()).isEqualByComparingTo("60");
    }

    @Test
    @DisplayName("PERCENT resolves both sides off the entry premium")
    void percentModeUsesThePercentages() {
        modes("PERCENT", "PERCENT");

        TradeOrder order = openAt(new BigDecimal("200"), configWithBothShapes());

        assertThat(order.getTargetAtEntry()).isEqualByComparingTo("40.00");
        assertThat(order.getStopLossAtEntry()).isEqualByComparingTo("60");
    }

    @Test
    @DisplayName("POINTS resolves both sides off the absolute columns")
    void pointsModeUsesTheAbsoluteColumns() {
        modes("POINTS", "POINTS");

        TradeOrder order = openAt(new BigDecimal("200"), configWithBothShapes());

        assertThat(order.getTargetAtEntry()).isEqualByComparingTo("20");
        assertThat(order.getStopLossAtEntry()).isEqualByComparingTo("20");
    }

    @Test
    @DisplayName("the two sides are independent — a points target with a percentage stop")
    void modesAreResolvedPerSide() {
        // The mixed bracket the split exists for, and the one the pre-041 rule
        // could not express: setting target points did nothing while sl_pct won.
        modes("POINTS", "PERCENT");

        TradeOrder order = openAt(new BigDecimal("200"), configWithBothShapes());

        assertThat(order.getTargetAtEntry()).isEqualByComparingTo("20");
        assertThat(order.getStopLossAtEntry()).isEqualByComparingTo("60");
    }

    @Test
    @DisplayName("the ceiling still caps a POINTS stop")
    void ceilingAppliesInPointsModeToo() {
        // capStopLoss sits outside the mode decision, so a hand-typed 90-point
        // stop is still ceilinged at 60. The cap is a ceiling on loss, not a
        // second stop rule competing with the first.
        modes("POINTS", "POINTS");
        TradeConfig tc = configWithBothShapes();
        tc.setStopLoss(new BigDecimal("90"));

        TradeOrder order = openAt(new BigDecimal("200"), tc);

        assertThat(order.getStopLossAtEntry()).isEqualByComparingTo("60");
    }

    @Test
    @DisplayName("POINTS falls back to the percentage when the points column is unset")
    void pointsModeFallsBackRatherThanResolvingToNoBracket() {
        // PositionService reads a null target as "never breaches", so resolving
        // to null here would silently delete the target exit for the whole trade.
        modes("POINTS", "POINTS");
        TradeConfig tc = configWithBothShapes();
        tc.setTarget(null);
        tc.setStopLoss(null);

        TradeOrder order = openAt(new BigDecimal("200"), tc);

        assertThat(order.getTargetAtEntry()).isEqualByComparingTo("40.00");
        assertThat(order.getStopLossAtEntry()).isEqualByComparingTo("60");
    }

    @Test
    @DisplayName("a mode corrupted in SQL degrades to PERCENT rather than blocking the trade")
    void malformedModeDegradesToPercent() {
        // Same call as the malformed ladder above: a config typo must not answer
        // itself with a silent trading outage.
        modes("POINT", "PERCENT");

        TradeOrder order = openAt(new BigDecimal("200"), configWithBothShapes());

        assertThat(order.getTargetAtEntry()).isEqualByComparingTo("40.00");
    }
}
