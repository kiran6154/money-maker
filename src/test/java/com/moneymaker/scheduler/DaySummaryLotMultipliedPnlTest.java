package com.moneymaker.scheduler;

import com.moneymaker.entity.TradeConfig;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.market.service.MarketHoursService;
import com.moneymaker.order.service.OrderService;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.state.DailyEventGuard;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Pins the rupee P&amp;L in the end-of-day digest (GAPS #2).
 *
 * <p>{@code trade_order.profit} is per-share — the premium move on one unit —
 * and the digest used to sum those straight into a line the reader takes for a
 * money figure. On a 75-unit NIFTY lot that under-reports the day by 75×, which
 * is the difference between "a flat afternoon" and "a bad one".</p>
 *
 * <p>The multiplier is {@code TradeConfig.lotQuantity} because that is the exact
 * number the placement services hand the broker as the order quantity — so the
 * reported P&amp;L and the size actually traded cannot drift apart.</p>
 */
class DaySummaryLotMultipliedPnlTest {

    private static final LocalDate MONDAY = LocalDate.of(2026, 8, 31);

    private TradeOrderRepository tradeOrderRepository;
    private TradeConfigRepository tradeConfigRepository;
    private NotificationService notifier;
    private DailyEventGuard guard;
    private DaySummaryScheduler scheduler;

    @BeforeEach
    void setUp() {
        OrderService orderService = mock(OrderService.class);
        tradeOrderRepository = mock(TradeOrderRepository.class);
        tradeConfigRepository = mock(TradeConfigRepository.class);
        MarketHoursService marketHours = mock(MarketHoursService.class);
        notifier = mock(NotificationService.class);
        guard = mock(DailyEventGuard.class);

        when(marketHours.marketCloseToday()).thenReturn(MONDAY.atTime(15, 30));
        when(marketHours.marketOpenToday()).thenReturn(MONDAY.atTime(9, 15));
        when(notifier.alertDaySummary(anyString())).thenReturn(true);

        scheduler = new DaySummaryScheduler(orderService, tradeOrderRepository, tradeConfigRepository,
                marketHours, notifier, guard);
    }

    /* ---------------- fixtures ---------------- */

    private TradeOrder closedTrade(long id, int configId, String perShareProfit) {
        TradeOrder o = new TradeOrder();
        o.setId(id);
        o.setTradeConfigId(configId);
        o.setInstrumentName("NIFTY");
        o.setOptionStrike(24000);
        o.setOptionType("CE");
        o.setEntryDirection("SELL");
        o.setEntryTime(LocalDateTime.of(2026, 8, 31, 10, 0));
        o.setEntryPrice(new BigDecimal("100.00"));
        o.setExitPrice(new BigDecimal("90.00"));
        o.setProfit(new BigDecimal(perShareProfit));
        o.setStatus("CLOSED");
        o.setExitReason("SIGNAL");
        return o;
    }

    private TradeConfig config(int id, Integer lotQuantity) {
        TradeConfig tc = new TradeConfig();
        tc.setId(id);
        tc.setLotQuantity(lotQuantity);
        return tc;
    }

    /** Runs the digest and hands back the body that went to Telegram. */
    private String digest(List<TradeOrder> trades, List<TradeConfig> configs) {
        when(tradeOrderRepository.findByEntryTimeBetween(any(), any())).thenReturn(trades);
        when(tradeConfigRepository.findAllById(any())).thenReturn(new ArrayList<>(configs));

        scheduler.runEndOfDayFor(MONDAY);

        ArgumentCaptor<String> body = ArgumentCaptor.forClass(String.class);
        verify(notifier).alertDaySummary(body.capture());
        return body.getValue();
    }

    /* ---------------- tests ---------------- */

    @Test
    @DisplayName("net P/L is the per-share figure multiplied by the config's lot quantity")
    void netIsLotMultiplied() {
        String body = digest(
                List.of(closedTrade(1L, 7, "10.00")),
                List.of(config(7, 75)));

        assertThat(body).contains("P/L (per-sh): 10.00");
        assertThat(body).contains("P/L (net)   : 750.00");
    }

    @Test
    @DisplayName("configs with different lot sizes are each multiplied by their own")
    void eachConfigUsesItsOwnLotSize() {
        // The single-multiplier shortcut ("just multiply the total by 75") breaks
        // exactly here, and a NIFTY + BANKNIFTY day is not unusual.
        String body = digest(
                List.of(closedTrade(1L, 7, "10.00"), closedTrade(2L, 9, "-4.00")),
                List.of(config(7, 75), config(9, 15)));

        // 10 × 75 = 750, -4 × 15 = -60.
        assertThat(body).contains("P/L (net)   : 690.00");
        assertThat(body).contains("by config   : #7=750.00, #9=-60.00");
    }

    @Test
    @DisplayName("per-share and net are both labelled, so neither line can be read as the other")
    void bothUnitsAreShownOnTheExtremes() {
        String body = digest(
                List.of(closedTrade(1L, 7, "10.00"), closedTrade(2L, 7, "-4.00")),
                List.of(config(7, 75)));

        assertThat(body).contains("best winner : id=1 NIFTY 24000 CE pnl/sh=10.00 net=750.00");
        assertThat(body).contains("worst loser : id=2 NIFTY 24000 CE pnl/sh=-4.00 net=-300.00");
    }

    @Test
    @DisplayName("a trade whose lot quantity is unknown is excluded from net and declared, not guessed at ×1")
    void unknownLotQuantityIsDeclaredNotAssumed() {
        // Config #9 was force-deleted, so its multiplier is gone. Folding the
        // trade in at ×1 would produce a number that looks like rupees and isn't.
        String body = digest(
                List.of(closedTrade(1L, 7, "10.00"), closedTrade(2L, 9, "-4.00")),
                List.of(config(7, 75)));

        assertThat(body).contains("P/L (per-sh): 6.00");
        assertThat(body).contains("P/L (net)   : 750.00");
        assertThat(body).contains("no lot qty  : 1 trade(s) excluded from net — config(s) #9");
        assertThat(body).contains("by config   : #7=750.00");
    }

    @Test
    @DisplayName("a non-positive lot quantity counts as unknown rather than as zero rupees")
    void zeroLotQuantityIsNotAMultiplier() {
        String body = digest(
                List.of(closedTrade(1L, 7, "10.00")),
                List.of(config(7, 0)));

        assertThat(body).contains("P/L (net)   : 0.00");
        assertThat(body).contains("no lot qty  : 1 trade(s) excluded from net — config(s) #7");
    }

    @Test
    @DisplayName("still-open rows contribute to neither total")
    void openRowsAreNotPricedIn() {
        TradeOrder stillOpen = closedTrade(2L, 7, "99.00");
        stillOpen.setStatus("OPEN");

        String body = digest(
                List.of(closedTrade(1L, 7, "10.00"), stillOpen),
                List.of(config(7, 75)));

        assertThat(body).contains("open left   : 1");
        assertThat(body).contains("P/L (net)   : 750.00");
    }
}
