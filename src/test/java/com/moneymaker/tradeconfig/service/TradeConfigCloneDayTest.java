package com.moneymaker.tradeconfig.service;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.repository.InstrumentRepository;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.strategy.StrategyFactory;
import com.moneymaker.tradeconfig.dto.CloneResultDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * GAPS #9 — "clone yesterday's configs to today".
 *
 * <p>The workflow it replaces is a hand-written
 * {@code INSERT … SELECT … WHERE trading_date='yesterday'}, which is not just
 * tedious: it bypasses {@code TradeConfigAdminService} and therefore the
 * cache-invalidation contract, so the rows exist while the running pipeline
 * cannot see them until the next restart.
 */
class TradeConfigCloneDayTest {

    private static final LocalDate YESTERDAY = LocalDate.of(2026, 8, 28);
    private static final LocalDate TODAY = LocalDate.of(2026, 8, 31);

    private TradeConfigRepository tradeConfigRepository;
    private SmaTimeframeRepository smaTimeframeRepository;
    private TradeConfigScheduler scheduler;
    private TradeConfigAdminService service;

    private int nextId = 100;

    @BeforeEach
    void setUp() {
        tradeConfigRepository = mock(TradeConfigRepository.class);
        smaTimeframeRepository = mock(SmaTimeframeRepository.class);
        InstrumentRepository instrumentRepository = mock(InstrumentRepository.class);
        TradeOrderRepository tradeOrderRepository = mock(TradeOrderRepository.class);
        scheduler = mock(TradeConfigScheduler.class);
        StrategyFactory strategyFactory = mock(StrategyFactory.class);

        when(instrumentRepository.existsById(anyInt())).thenReturn(true);
        when(tradeConfigRepository.save(any(TradeConfig.class))).thenAnswer(inv -> {
            TradeConfig tc = inv.getArgument(0);
            if (tc.getId() == null) tc.setId(nextId++);
            return tc;
        });
        when(tradeConfigRepository.getReferenceById(anyInt())).thenAnswer(inv -> {
            TradeConfig ref = new TradeConfig();
            ref.setId(inv.getArgument(0));
            return ref;
        });
        when(smaTimeframeRepository.findByTradeConfigId(anyInt())).thenReturn(List.of());
        when(tradeConfigRepository.findByTradingDate(any(LocalDate.class))).thenReturn(new ArrayList<>());

        service = new TradeConfigAdminService(tradeConfigRepository, smaTimeframeRepository,
                instrumentRepository, tradeOrderRepository, scheduler, strategyFactory);
        ReflectionTestUtils.setField(service, "appMode", "backtest");
    }

    private static Instrument instrument(int id, String name) {
        Instrument i = new Instrument();
        i.setId(id);
        i.setInsName(name);
        return i;
    }

    private TradeConfig config(int id, LocalDate date, String side, String txn, int strategyId, String source) {
        TradeConfig tc = new TradeConfig();
        tc.setId(id);
        tc.setInstrument(instrument(1, "NIFTY"));
        tc.setTradingDate(date);
        tc.setTradingSide(side);
        tc.setTransactionType(txn);
        tc.setStratergyId(strategyId);
        tc.setStrategyIds(String.valueOf(strategyId));
        tc.setLotQuantity(75);
        tc.setNumberOfTradesPerDay(4);
        tc.setNumberOfParallelTrades(2);
        tc.setTarget(new BigDecimal("20"));
        tc.setStopLoss(new BigDecimal("30"));
        tc.setTargetPct(new BigDecimal("0.2000"));
        tc.setMaxSlPoints(new BigDecimal("60"));
        tc.setTrailLadder("25:2,50:25");
        tc.setMinOptionPrice(new BigDecimal("80"));
        tc.setMaxOptionPrice(new BigDecimal("250"));
        tc.setSource(source);
        return tc;
    }

    private void givenSource(TradeConfig... configs) {
        when(tradeConfigRepository.findByTradingDate(YESTERDAY)).thenReturn(new ArrayList<>(List.of(configs)));
    }

    private void givenDestination(TradeConfig... configs) {
        when(tradeConfigRepository.findByTradingDate(TODAY)).thenReturn(new ArrayList<>(List.of(configs)));
    }

    private List<TradeConfig> savedConfigs() {
        ArgumentCaptor<TradeConfig> captor = ArgumentCaptor.forClass(TradeConfig.class);
        verify(tradeConfigRepository, org.mockito.Mockito.atLeastOnce()).save(captor.capture());
        return captor.getAllValues();
    }

    /* ---------------- the happy path ---------------- */

    @Test
    @DisplayName("clones each config onto the new date and invalidates the cache")
    void clones_a_day() {
        givenSource(config(1, YESTERDAY, "CALL", "SELL", 1, "MANUAL"),
                    config(2, YESTERDAY, "PUT", "SELL", 1, "MANUAL"));

        CloneResultDTO result = service.cloneDay(YESTERDAY, TODAY, false);

        assertThat(result.cloned()).isEqualTo(2);
        assertThat(result.created()).hasSize(2);
        assertThat(savedConfigs()).allSatisfy(tc -> assertThat(tc.getTradingDate()).isEqualTo(TODAY));
        // Without this the rows exist but the running pipeline keeps its stale
        // snapshot — the exact failure the SQL workaround has.
        verify(scheduler, org.mockito.Mockito.atLeastOnce()).invalidateConfigsCache();
    }

    @Test
    @DisplayName("every trading field comes across, including the 027/036 bracket columns")
    void copies_the_whole_config() {
        givenSource(config(1, YESTERDAY, "CALL", "SELL", 1, "MANUAL"));

        service.cloneDay(YESTERDAY, TODAY, false);

        TradeConfig copy = savedConfigs().get(0);
        assertThat(copy.getLotQuantity()).isEqualTo(75);
        assertThat(copy.getNumberOfParallelTrades()).isEqualTo(2);
        assertThat(copy.getTargetPct()).isEqualByComparingTo("0.2000");
        assertThat(copy.getMaxSlPoints()).isEqualByComparingTo("60");
        assertThat(copy.getTrailLadder()).isEqualTo("25:2,50:25");
        assertThat(copy.getMinOptionPrice()).isEqualByComparingTo("80");
        assertThat(copy.getStrategyIds()).isEqualTo("1");
        assertThat(copy.getId()).as("a clone is a new row, not an update").isNotEqualTo(1);
    }

    @Test
    @DisplayName("sma_timeframe children are copied, not shared")
    void copies_timeframes() {
        TradeConfig src = config(1, YESTERDAY, "CALL", "SELL", 1, "MANUAL");
        SmaTimeframe tf = new SmaTimeframe();
        tf.setId(7);
        tf.setTimePeriod(5);
        tf.setSma(50);
        tf.setSlope(3.0);
        when(smaTimeframeRepository.findByTradeConfigId(1)).thenReturn(List.of(tf));
        givenSource(src);

        CloneResultDTO result = service.cloneDay(YESTERDAY, TODAY, false);

        assertThat(result.timeframesCopied()).isEqualTo(1);
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<SmaTimeframe>> captor = ArgumentCaptor.forClass(List.class);
        verify(smaTimeframeRepository).saveAll(captor.capture());
        SmaTimeframe copy = captor.getValue().get(0);
        assertThat(copy.getId()).as("a new child row, not the original re-parented").isNull();
        assertThat(copy.getTimePeriod()).isEqualTo(5);
        assertThat(copy.getSma()).isEqualTo(50);
        assertThat(copy.getSlope()).isEqualTo(3.0);
    }

    /* ---------------- the decisions ---------------- */

    @Test
    @DisplayName("an AUTO_DOWNTREND config clones as MANUAL, so the detector's dedupe is not poisoned")
    void clones_are_stamped_manual() {
        givenSource(config(1, YESTERDAY, "CALL", "SELL", 1, "AUTO_DOWNTREND"));

        service.cloneDay(YESTERDAY, TODAY, false);

        // Keeping AUTO_DOWNTREND would hand the row to EodDowntrendDetectionService's
        // dedupe key, which reads "a config already exists for this (day, strategy)"
        // as "I already generated" — so a clone would silently suppress the
        // detector's own output for that day.
        assertThat(savedConfigs().get(0).getSource()).isEqualTo("MANUAL");
    }

    @Test
    @DisplayName("a retired config is left behind, and the count is reported not swallowed")
    void retired_configs_are_not_resurrected() {
        TradeConfig retired = config(1, YESTERDAY, "CALL", "SELL", 1, "MANUAL");
        retired.setIsActive(false);
        givenSource(retired, config(2, YESTERDAY, "PUT", "SELL", 1, "MANUAL"));

        CloneResultDTO result = service.cloneDay(YESTERDAY, TODAY, false);

        assertThat(result.matched()).isEqualTo(2);
        assertThat(result.skippedRetired()).isEqualTo(1);
        assertThat(result.cloned()).isEqualTo(1);
        assertThat(result.summary()).contains("retired and left behind");
    }

    @Test
    @DisplayName("clones start active")
    void clones_start_active() {
        givenSource(config(1, YESTERDAY, "CALL", "SELL", 1, "MANUAL"));
        service.cloneDay(YESTERDAY, TODAY, false);
        assertThat(savedConfigs().get(0).getIsActive()).isTrue();
    }

    /* ---------------- idempotency ---------------- */

    @Test
    @DisplayName("re-cloning skips configs the destination already carries")
    void second_clone_is_a_no_op() {
        givenSource(config(1, YESTERDAY, "CALL", "SELL", 1, "MANUAL"),
                    config(2, YESTERDAY, "PUT", "SELL", 1, "MANUAL"));
        // Destination already has the CALL leg — from an earlier clone, or built by hand.
        givenDestination(config(9, TODAY, "CALL", "SELL", 1, "MANUAL"));

        CloneResultDTO result = service.cloneDay(YESTERDAY, TODAY, false);

        assertThat(result.skippedExisting()).isEqualTo(1);
        assertThat(result.cloned()).isEqualTo(1);
        assertThat(savedConfigs()).singleElement()
                .satisfies(tc -> assertThat(tc.getTradingSide()).isEqualTo("PUT"));
    }

    @Test
    @DisplayName("two identical source configs collapse to one clone — doubling configs doubles positions")
    void duplicate_sources_collapse() {
        givenSource(config(1, YESTERDAY, "CALL", "SELL", 1, "MANUAL"),
                    config(2, YESTERDAY, "CALL", "SELL", 1, "MANUAL"));

        CloneResultDTO result = service.cloneDay(YESTERDAY, TODAY, false);

        assertThat(result.cloned()).isEqualTo(1);
        assertThat(result.skippedExisting()).isEqualTo(1);
    }

    /* ---------------- dry run + validation ---------------- */

    @Test
    @DisplayName("dryRun reports the same counts and writes nothing")
    void dry_run_writes_nothing() {
        givenSource(config(1, YESTERDAY, "CALL", "SELL", 1, "MANUAL"),
                    config(2, YESTERDAY, "PUT", "SELL", 1, "MANUAL"));

        CloneResultDTO result = service.cloneDay(YESTERDAY, TODAY, true);

        assertThat(result.dryRun()).isTrue();
        assertThat(result.cloned()).isEqualTo(2);
        assertThat(result.created()).isEmpty();
        assertThat(result.summary()).startsWith("Would clone 2 of 2");
        verify(tradeConfigRepository, never()).save(any(TradeConfig.class));
        verify(scheduler, never()).invalidateConfigsCache();
    }

    @Test
    @DisplayName("cloning a day onto itself is rejected — it would only duplicate everything")
    void self_clone_rejected() {
        assertThatThrownBy(() -> service.cloneDay(TODAY, TODAY, true))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("same day");
    }

    @Test
    @DisplayName("an empty source day says so rather than reporting a successful no-op")
    void empty_source_is_reported() {
        CloneResultDTO result = service.cloneDay(YESTERDAY, TODAY, false);

        assertThat(result.cloned()).isZero();
        assertThat(result.summary()).isEqualTo("No configs on " + YESTERDAY + " to clone.");
    }
}
