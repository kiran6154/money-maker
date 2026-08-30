package com.moneymaker.order.service;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.MarketData;
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

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pins the two halves of {@code forceCloseOpenPositions} (GAPS #1).
 *
 * <p>The live half is new: the end-of-day sweep now sends the opposite-side exit
 * to the broker instead of only flipping the ledger row. The backtest half must
 * stay exactly as it was — a replay's rows are compared against previous runs,
 * so an extra broker id or a moved {@code fill_status} would show up as a
 * behaviour change in a ledger that is supposed to be reproducible.</p>
 *
 * <p>The failure cases matter as much as the success one. A row whose broker
 * exit did not go out is a real position left open overnight while the DB claims
 * otherwise, and the only thing standing between that and an unpleasant morning
 * is the alert.</p>
 */
class OrderServiceForceCloseTest {

    private static final LocalDate TRADING_DATE = LocalDate.of(2026, 8, 31);
    private static final LocalDateTime CLOSE_AT = LocalDateTime.of(2026, 8, 31, 15, 30);
    private static final String OPTION_TOKEN = "12345";

    private TradeOrderRepository repo;
    private OrderPlacementFactory placementFactory;
    private OrderPlacementService placement;
    private NotificationService notifier;
    private OrderService orderService;

    @BeforeEach
    void setUp() {
        repo = mock(TradeOrderRepository.class);
        placementFactory = mock(OrderPlacementFactory.class);
        placement = mock(OrderPlacementService.class);
        notifier = mock(NotificationService.class);

        when(placementFactory.active()).thenReturn(placement);
        when(repo.save(any(TradeOrder.class))).thenAnswer(inv -> inv.getArgument(0));

        orderService = new OrderService(placementFactory, repo, notifier,
                mock(JournalRecorder.class), mock(ObservationContextFactory.class));

        SharedData.strikeMarketDataByInstrumentAndInterval = new ConcurrentHashMap<>();
    }

    @AfterEach
    void tearDown() {
        SharedData.combinedDto = null;
        SharedData.strikeMarketDataByInstrumentAndInterval = new ConcurrentHashMap<>();
    }

    /* ---------------- fixtures ---------------- */

    /** One SELL leg opened at 100, still OPEN when the bell goes. */
    private TradeOrder openSellTrade(String fillStatusAtEntry) {
        TradeOrder o = new TradeOrder();
        o.setId(11L);
        o.setTradeConfigId(7);
        o.setInstrumentName("NIFTY");
        o.setInstrumentToken("256265");
        o.setOptionStrike(24000);
        o.setOptionType("CE");
        o.setOptionToken(OPTION_TOKEN);
        o.setEntryDirection("SELL");
        o.setEntryTime(LocalDateTime.of(2026, 8, 31, 14, 50));
        o.setEntryPrice(new BigDecimal("100.00"));
        o.setStatus("OPEN");
        o.setFillStatus(fillStatusAtEntry);
        when(repo.findByStatusAndEntryTimeBetween(eq("OPEN"), any(), any())).thenReturn(List.of(o));
        return o;
    }

    /** A cached 15:25 candle at 70 — the price the sweep should exit on. */
    private void cachePriceAt(String close) {
        MarketData md = new MarketData();
        md.setTimestamp(LocalDateTime.of(2026, 8, 31, 15, 25));
        md.setClose(new BigDecimal(close));
        // Key shape must match AnalysisScheduler.toStrikeMarketDataKey, and the
        // interval segment must be a real Kite interval ("5minute") or
        // SharedData.latestCachedCandle sorts it as unparseable and skips it.
        SharedData.strikeMarketDataByInstrumentAndInterval.put(
                "256265|5minute|CE|24000|" + OPTION_TOKEN + "|0|0", List.of(md));
    }

    private void cacheConfig(Integer lotQuantity) {
        TradeConfig tc = new TradeConfig();
        tc.setId(7);
        tc.setStratergyId(1);
        tc.setTransactionType("SELL");
        tc.setLotQuantity(lotQuantity);
        SharedData.combinedDto = List.of(
                new TradeConfigCombinedDTO(tc, new Instrument(), null, List.of()));
    }

    private void runningLive() {
        when(placement.getName()).thenReturn("ZERODHA");
    }

    private void runningBacktest() {
        when(placement.getName()).thenReturn("BACKTESTING");
    }

    /* ---------------- backtest: unchanged ---------------- */

    @Test
    @DisplayName("backtest force-close touches no broker and leaves the row exactly as before")
    void backtestPathIsUnchanged() {
        runningBacktest();
        cachePriceAt("70.00");
        cacheConfig(75);
        TradeOrder order = openSellTrade("BACKTEST");

        int closed = orderService.forceCloseOpenPositions(TRADING_DATE, CLOSE_AT);

        assertThat(closed).isEqualTo(1);
        // No venue exists in a replay; calling one would also be the first place
        // a backtest could diverge from a previous run of the same range.
        verify(placement, never()).place(any(), any());
        assertThat(order.getStatus()).isEqualTo("CLOSED");
        assertThat(order.getExitReason()).isEqualTo("FORCE_CLOSE");
        assertThat(order.getExitTime()).isEqualTo(CLOSE_AT);
        assertThat(order.getExitPrice()).isEqualByComparingTo("70.00");
        assertThat(order.getProfit()).isEqualByComparingTo("30.00");
        // Both of these are what a re-run compares against, so both stay put.
        assertThat(order.getExitBrokerOrderId()).isNull();
        assertThat(order.getFillStatus()).isEqualTo("BACKTEST");
        verify(notifier).alertOrderForceClosed(order);
        verify(notifier, never()).alertForceCloseExitFailed(any(), anyString());
    }

    /* ---------------- live: the new exit ---------------- */

    @Test
    @DisplayName("live force-close sends the exit to the broker and reconciles the order id back")
    void livePathPlacesTheExit() {
        runningLive();
        cachePriceAt("70.00");
        cacheConfig(75);
        TradeOrder order = openSellTrade("COMPLETE");
        when(placement.place(any(), any())).thenReturn("250831000123");

        int closed = orderService.forceCloseOpenPositions(TRADING_DATE, CLOSE_AT);

        assertThat(closed).isEqualTo(1);
        // The row is already CLOSED when placement sees it — that is how the
        // placement service knows to invert the side into a BUY.
        verify(placement).place(order, SharedData.combinedDto.get(0));
        assertThat(order.getStatus()).isEqualTo("CLOSED");
        assertThat(order.getExitBrokerOrderId()).isEqualTo("250831000123");
        assertThat(order.getFillStatus()).isEqualTo("PENDING");
        verify(notifier, never()).alertForceCloseExitFailed(any(), anyString());
    }

    @Test
    @DisplayName("a broker that returns no order id leaves the row closed but alerts loudly")
    void livePathAlertsWhenNoOrderIdComesBack() {
        // Today's Zerodha reality: resolveTradingSymbol is a stub returning null,
        // so place() short-circuits to null. Silence here is the actual gap.
        runningLive();
        cachePriceAt("70.00");
        cacheConfig(75);
        TradeOrder order = openSellTrade("BACKTEST");
        when(placement.place(any(), any())).thenReturn(null);

        orderService.forceCloseOpenPositions(TRADING_DATE, CLOSE_AT);

        assertThat(order.getStatus()).isEqualTo("CLOSED");
        assertThat(order.getExitBrokerOrderId()).isNull();
        verify(notifier).alertOrderForceClosed(order);
        verify(notifier).alertForceCloseExitFailed(eq(order), anyString());
    }

    @Test
    @DisplayName("a broker that throws does not strand the rest of the batch")
    void livePathSurvivesAThrowingBroker() {
        runningLive();
        cachePriceAt("70.00");
        cacheConfig(75);
        TradeOrder order = openSellTrade("BACKTEST");
        when(placement.place(any(), any())).thenThrow(new IllegalStateException("connection reset"));

        int closed = orderService.forceCloseOpenPositions(TRADING_DATE, CLOSE_AT);

        assertThat(closed).isEqualTo(1);
        assertThat(order.getStatus()).isEqualTo("CLOSED");
        verify(notifier).alertForceCloseExitFailed(eq(order), eq("connection reset"));
    }

    @Test
    @DisplayName("no cached config means no exit is sent — a wrong-size exit is worse than none")
    void livePathRefusesToGuessTheQuantity() {
        // Placement services fall back to quantity=1 when the config is missing.
        // One unit against a 75-unit lot is not a close, it is a new position.
        runningLive();
        cachePriceAt("70.00");
        SharedData.combinedDto = List.of();
        TradeOrder order = openSellTrade("BACKTEST");

        orderService.forceCloseOpenPositions(TRADING_DATE, CLOSE_AT);

        verify(placement, never()).place(any(), any());
        verify(notifier).alertForceCloseExitFailed(eq(order), anyString());
    }

    @Test
    @DisplayName("an unresolvable placement service still closes the ledger, with an alert per row")
    void unresolvablePlacementDoesNotAbortTheSweep() {
        // A bad broker.active used to be irrelevant here because nothing called
        // the factory. Now it does, and "close nothing" would be the worse answer.
        when(placementFactory.active()).thenThrow(new IllegalStateException("No OrderPlacementService registered for: KRAKEN"));
        cachePriceAt("70.00");
        cacheConfig(75);
        TradeOrder order = openSellTrade("BACKTEST");

        int closed = orderService.forceCloseOpenPositions(TRADING_DATE, CLOSE_AT);

        assertThat(closed).isEqualTo(1);
        assertThat(order.getStatus()).isEqualTo("CLOSED");
        verify(notifier).alertForceCloseExitFailed(eq(order), anyString());
    }

    @Test
    @DisplayName("no open rows means the broker is never consulted at all")
    void emptySweepIsFree() {
        when(repo.findByStatusAndEntryTimeBetween(eq("OPEN"), any(), any())).thenReturn(List.of());

        assertThat(orderService.forceCloseOpenPositions(TRADING_DATE, CLOSE_AT)).isZero();
        verify(placementFactory, never()).active();
    }
}
