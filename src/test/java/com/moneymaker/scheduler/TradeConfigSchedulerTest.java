package com.moneymaker.scheduler;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.state.DailyEventGuard;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDate;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link TradeConfigScheduler}.
 *
 * <p>Focus on the date-keyed cache (C9 in SEQUENCING_AND_CACHE.md):
 * populated dates hit cache; null / empty results bypass cache; explicit
 * invalidation clears it. The Telegram report path is gated by
 * {@link DailyEventGuard}.
 */
class TradeConfigSchedulerTest {

    @Mock private TradeConfigRepository tradeConfigRepository;
    @Mock private SmaTimeframeRepository smaTimeframeRepository;
    @Mock private NotificationService notifier;
    @Mock private DailyEventGuard dailyEventGuard;

    private TradeConfigScheduler scheduler;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        scheduler = new TradeConfigScheduler();
        ReflectionTestUtils.setField(scheduler, "tradeConfigRepository", tradeConfigRepository);
        ReflectionTestUtils.setField(scheduler, "smaTimeframeRepository", smaTimeframeRepository);
        ReflectionTestUtils.setField(scheduler, "notifier", notifier);
        ReflectionTestUtils.setField(scheduler, "dailyEventGuard", dailyEventGuard);
        ReflectionTestUtils.setField(scheduler, "appMode", "live");
        lenient().when(tradeConfigRepository.fetchCombinedByTradingDate(any())).thenReturn(List.of());
    }

    @Test
    void getConfigsForDate_returns_empty_list_for_null_date() {
        assertThat(scheduler.getConfigsForDate(null)).isEmpty();
        verify(tradeConfigRepository, never()).fetchCombinedByTradingDate(any());
    }

    @Test
    void getConfigsForDate_caches_populated_results() {
        Object[] row = stubRow(1);
        when(tradeConfigRepository.fetchCombinedByTradingDate(LocalDate.of(2026, 4, 1)))
                .thenReturn(java.util.Collections.singletonList(row));

        var first  = scheduler.getConfigsForDate(LocalDate.of(2026, 4, 1));
        var second = scheduler.getConfigsForDate(LocalDate.of(2026, 4, 1));

        assertThat(first).isNotEmpty();
        assertThat(second).isSameAs(first);
        // Repository called only once — second call served from cache.
        verify(tradeConfigRepository, times(1))
                .fetchCombinedByTradingDate(LocalDate.of(2026, 4, 1));
    }

    @Test
    void getConfigsForDate_does_not_cache_empty_results() {
        // Empty result means "no configs yet" — caller might add a row mid-session.
        when(tradeConfigRepository.fetchCombinedByTradingDate(LocalDate.of(2026, 4, 1)))
                .thenReturn(List.of());

        scheduler.getConfigsForDate(LocalDate.of(2026, 4, 1));
        scheduler.getConfigsForDate(LocalDate.of(2026, 4, 1));

        // Both calls hit the repo.
        verify(tradeConfigRepository, times(2))
                .fetchCombinedByTradingDate(LocalDate.of(2026, 4, 1));
    }

    @Test
    void invalidateConfigsCache_forces_next_call_to_refetch() {
        Object[] row = stubRow(1);
        when(tradeConfigRepository.fetchCombinedByTradingDate(LocalDate.of(2026, 4, 1)))
                .thenReturn(java.util.Collections.singletonList(row));

        scheduler.getConfigsForDate(LocalDate.of(2026, 4, 1));
        scheduler.invalidateConfigsCache();
        scheduler.getConfigsForDate(LocalDate.of(2026, 4, 1));

        verify(tradeConfigRepository, times(2))
                .fetchCombinedByTradingDate(LocalDate.of(2026, 4, 1));
    }

    @Test
    void reportConfigsForDay_skips_when_guard_says_already_fired() {
        when(dailyEventGuard.firstTime(eq("trade-configs"), any())).thenReturn(false);

        scheduler.reportConfigsForDay(LocalDate.of(2026, 4, 1), List.of(stubDto(1)));

        verify(notifier, never()).sendIfChanged(anyString(), anyString());
    }

    @Test
    void reportConfigsForDay_emits_no_active_message_when_configs_empty() {
        when(dailyEventGuard.firstTime(eq("trade-configs"), any())).thenReturn(true);

        scheduler.reportConfigsForDay(LocalDate.of(2026, 4, 1), List.of());

        verify(notifier).sendIfChanged(eq("trade-configs:2026-04-01"),
                org.mockito.ArgumentMatchers.contains("none active"));
    }

    @Test
    void reportConfigsForDay_emits_summary_when_configs_present() {
        when(dailyEventGuard.firstTime(eq("trade-configs"), any())).thenReturn(true);

        scheduler.reportConfigsForDay(LocalDate.of(2026, 4, 1), List.of(stubDto(1), stubDto(2)));

        verify(notifier).sendIfChanged(eq("trade-configs:2026-04-01"),
                org.mockito.ArgumentMatchers.contains("2 active"));
    }

    /* ---------------- helpers ---------------- */

    /**
     * Builds a 33-column row matching the fetchCombinedByTradingDate result
     * shape (12 trade_config + 5 instrument + 16 instrument_details).
     */
    private static Object[] stubRow(int id) {
        Object[] row = new Object[35];
        // trade_config (17 fields, indices 0-16, includes is_active per M4.3)
        row[0]  = id;
        row[1]  = "CE";
        row[2]  = java.sql.Date.valueOf(LocalDate.of(2026, 4, 1));
        row[3]  = new java.math.BigDecimal("10");   // target
        row[4]  = new java.math.BigDecimal("5");    // stopLoss
        row[5]  = 99;                                // p_instrument (skipped)
        row[6]  = new java.math.BigDecimal("500");  // maxLoss
        row[7]  = 5;                                 // optionDepth
        row[8]  = "SELL";
        row[9]  = 50;                                // lotQuantity
        row[10] = 1;                                 // strategyId
        row[11] = 5;                                 // numberOfTradesPerDay
        row[12] = 2;                                 // numberOfParallelTrades
        row[13] = 0;                                 // itmDepth
        row[14] = 0;                                 // otmDepth
        row[15] = 0;                                 // atmDepth
        row[16] = Boolean.TRUE;                      // is_active (M4.3)
        // instrument (5 fields starting at index 17)
        row[17] = 99;          // id
        row[18] = "NIFTY";     // insName
        row[19] = "256265";    // insId
        row[20] = 50;          // lotQty
        row[21] = new java.math.BigDecimal("50"); // strikePoints
        // instrument_details (12 fields starting at index 22)
        row[22] = 256265;      // instrumentToken
        row[23] = 256265;      // exchangeToken
        row[24] = "NIFTY24APR24000CE"; // tradingSymbol
        row[25] = "NIFTY";     // name
        row[26] = new java.math.BigDecimal("100");
        row[27] = "2026-04-03";  // expiry (skipped by impl)
        row[28] = new java.math.BigDecimal("24000");
        row[29] = new java.math.BigDecimal("0.05");
        row[30] = new java.math.BigDecimal("50");
        row[31] = "CE";
        row[32] = "NFO-OPT";
        row[33] = "NFO";
        return row;
    }

    private static TradeConfigCombinedDTO stubDto(int id) {
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();
        TradeConfig tc = new TradeConfig();
        tc.setId(id);
        tc.setTradingSide("CE");
        tc.setTransactionType("SELL");
        tc.setStratergyId(1);
        tc.setTarget(new java.math.BigDecimal("10"));
        tc.setStopLoss(new java.math.BigDecimal("5"));
        tc.setLotQuantity(50);
        tc.setNumberOfTradesPerDay(5);
        tc.setNumberOfParallelTrades(2);
        dto.setTradeConfig(tc);
        Instrument ins = new Instrument();
        ins.setInsName("NIFTY");
        dto.setInstrument(ins);
        return dto;
    }
}
