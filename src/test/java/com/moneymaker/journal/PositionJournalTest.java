package com.moneymaker.journal;

import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.structure.MarketStructureAnalyzer;
import com.moneymaker.structure.MarketStructureAnalyzer.StructureEvent;
import com.moneymaker.structure.StructureEventCache;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pins the during-position journal: a MONITOR row per evaluated tick, and EVENT
 * rows only for structure breaks that were knowable at the tick recording them
 * and became knowable during the trade.
 *
 * <p>The structure fixture is deliberately checked against
 * {@link MarketStructureAnalyzer} rather than against hand-computed timestamps.
 * What is under test here is the <em>gating</em>, not the detector — using the
 * detector as the oracle keeps this test from breaking the day a swing rule is
 * tuned, while still failing loudly if an event is journalled a bar early.
 */
class PositionJournalTest {

    private static final LocalDateTime START = LocalDateTime.of(2026, 5, 8, 9, 15);
    private static final String TOKEN = "OPT-1";

    private JournalRecorder recorder;
    private ObservationContextFactory contexts;
    private PositionJournal positionJournal;

    private List<MarketData> series;
    private List<StructureEvent> oracle;
    private TradeOrder order;

    @BeforeEach
    void setUp() {
        recorder = mock(JournalRecorder.class);
        when(recorder.isEnabled()).thenReturn(true);
        contexts = mock(ObservationContextFactory.class);

        MarketStructureAnalyzer analyzer = new MarketStructureAnalyzer();
        positionJournal = new PositionJournal(recorder, contexts, new StructureEventCache(analyzer), analyzer);

        // A zig-zag with several confirmable swings, so the analyzer produces
        // breaks to gate on. Its exact shape does not matter; that it produces
        // events does, and the precondition below fails fast if it stops.
        series = seriesOf(100, 102, 104, 103, 101, 102, 105, 107, 104, 102,
                100, 99, 101, 104, 108, 106, 103, 99, 97, 101);
        oracle = analyzer.analyze(series);
        assertThat(oracle).as("fixture must produce structure breaks to gate on").isNotEmpty();

        order = new TradeOrder();
        order.setId(7L);
        order.setStatus("OPEN");
        order.setEntryDirection("SELL");
        order.setEntryPrice(new BigDecimal("100"));
        order.setEntryTime(START);
        order.setOptionToken(TOKEN);
        order.setOptionType("CE");
    }

    /** Context as the factory would build it: this leg's series, no index series. */
    private void contextAt(LocalDateTime observedAt) {
        when(contexts.forOpenPosition(order, observedAt)).thenReturn(new ObservationContext(
                ObservationKind.MONITOR, observedAt, 1, 2, order,
                "NIFTY", TOKEN, "CE", 21000, 5,
                series, List.of(), true));
    }

    private void observeAt(LocalDateTime observedAt, String decision) {
        contextAt(observedAt);
        positionJournal.observe(order, observedAt, new BigDecimal("3.5"), decision);
    }

    private List<StructureEvent> recordedEvents() {
        ArgumentCaptor<LocalDateTime> confirmable = ArgumentCaptor.forClass(LocalDateTime.class);
        verify(recorder, org.mockito.Mockito.atLeast(0))
                .recordEvent(any(), anyString(), anyString(), confirmable.capture(), anyMap());
        List<StructureEvent> matched = new ArrayList<>();
        for (LocalDateTime at : confirmable.getAllValues()) {
            oracle.stream().filter(e -> e.confirmableAt().equals(at)).findFirst().ifPresent(matched::add);
        }
        return matched;
    }

    @Test
    @DisplayName("every evaluated tick writes one MONITOR row carrying the monitor's own decision")
    void monitorRowPerTick() {
        observeAt(START.plusMinutes(30), null);
        observeAt(START.plusMinutes(35), "STOP_LOSS");

        ArgumentCaptor<ObservationContext> ctx = ArgumentCaptor.forClass(ObservationContext.class);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> features =
                ArgumentCaptor.forClass((Class<Map<String, Object>>) (Class<?>) Map.class);
        verify(recorder, org.mockito.Mockito.times(2))
                .record(ctx.capture(), eq(true), features.capture());

        assertThat(ctx.getAllValues()).extracting(ObservationContext::kind)
                .containsExactly(ObservationKind.MONITOR, ObservationKind.MONITOR);
        // A tick that held and a tick that stopped out are distinguishable, which
        // is what makes a blown stop interrogable tick by tick afterwards.
        assertThat(features.getAllValues().get(0)).containsEntry("monitor_decision", "HOLD");
        assertThat(features.getAllValues().get(1)).containsEntry("monitor_decision", "STOP_LOSS")
                .containsEntry("monitor_pnl", new BigDecimal("3.5"))
                .containsKey("monitor_minutes_since_entry");
    }

    @Test
    @DisplayName("a break is not journalled before the bar that confirms it has settled")
    void eventWaitsForConfirmation() {
        StructureEvent first = oracle.get(0);

        observeAt(first.confirmableAt().minusMinutes(1), null);

        verify(recorder, never()).recordEvent(any(), anyString(), anyString(), any(), anyMap());
    }

    @Test
    @DisplayName("once confirmed, the break is journalled with its confirmable time")
    void eventEmittedOnceConfirmed() {
        StructureEvent first = oracle.get(0);

        observeAt(first.confirmableAt(), null);

        List<StructureEvent> emitted = recordedEvents();
        assertThat(emitted).isNotEmpty();
        // The gate, stated as the property it protects: nothing recorded here
        // could have been known later than the tick that recorded it.
        assertThat(emitted).allSatisfy(e ->
                assertThat(e.confirmableAt()).isBeforeOrEqualTo(first.confirmableAt()));
        verify(recorder).recordEvent(any(), eq(first.type().name()), anyString(),
                eq(first.confirmableAt()), anyMap());
    }

    @Test
    @DisplayName("a break confirmed before entry is not replayed as a during-position warning")
    void preEntryBreakIsNotAnEvent() {
        StructureEvent first = oracle.get(0);
        order.setEntryTime(first.confirmableAt().plusMinutes(1));

        observeAt(last(series).getTimestamp(), null);

        assertThat(recordedEvents()).allSatisfy(e ->
                assertThat(e.confirmableAt()).isAfterOrEqualTo(order.getEntryTime()));
    }

    @Test
    @DisplayName("the same break is journalled once per trade, not once per tick")
    void eventIsNotRepeatedEveryTick() {
        LocalDateTime at = last(series).getTimestamp();
        observeAt(at, null);
        int firstPass = recordedEvents().size();
        assertThat(firstPass).isPositive();

        observeAt(at.plusMinutes(5), null);
        observeAt(at.plusMinutes(10), null);

        assertThat(recordedEvents()).hasSize(firstPass);
    }

    @Test
    @DisplayName("closing a trade drops its event state, so a reused id starts clean")
    void retainOpenDropsClosedTrades() {
        LocalDateTime at = last(series).getTimestamp();
        observeAt(at, null);
        int firstPass = recordedEvents().size();

        positionJournal.retainOpen(List.of(99L));   // 7 is no longer open
        observeAt(at.plusMinutes(5), null);

        assertThat(recordedEvents()).hasSize(firstPass * 2);
    }

    @Test
    @DisplayName("a journal that cannot write never reaches the caller")
    void writeFailureIsSwallowed() {
        doThrow(new IllegalStateException("db down"))
                .when(recorder).record(any(), anyBoolean(), anyMap());
        LocalDateTime at = START.plusMinutes(30);
        contextAt(at);

        assertThatCode(() -> positionJournal.observe(order, at, BigDecimal.ONE, null))
                .doesNotThrowAnyException();
    }

    @Test
    @DisplayName("nothing is written when the journal is disabled")
    void disabledJournalWritesNothing() {
        when(recorder.isEnabled()).thenReturn(false);

        observeAt(START.plusMinutes(30), null);

        verify(recorder, never()).record(any(), anyBoolean(), anyMap());
        verify(recorder, never()).recordEvent(any(), anyString(), anyString(), any(), anyMap());
    }

    // ---- fixture helpers ----

    private static List<MarketData> seriesOf(int... closes) {
        List<MarketData> list = new ArrayList<>(closes.length);
        for (int i = 0; i < closes.length; i++) {
            MarketData md = new MarketData();
            md.setTimestamp(START.plusMinutes(5L * i));
            md.setInstrumenttoken(TOKEN);
            md.setOpen(BigDecimal.valueOf(closes[i]));
            md.setClose(BigDecimal.valueOf(closes[i]));
            md.setHigh(BigDecimal.valueOf(closes[i] + 1));
            md.setLow(BigDecimal.valueOf(closes[i] - 1));
            list.add(md);
        }
        return list;
    }

    private static MarketData last(List<MarketData> candles) {
        return candles.get(candles.size() - 1);
    }
}
