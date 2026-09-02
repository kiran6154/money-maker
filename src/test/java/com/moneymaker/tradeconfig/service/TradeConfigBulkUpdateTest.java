package com.moneymaker.tradeconfig.service;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.repository.InstrumentRepository;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.strategy.StrategyFactory;
import com.moneymaker.tradeconfig.dto.AutoDeleteRequestDTO;
import com.moneymaker.tradeconfig.dto.BulkUpdateRequestDTO;
import com.moneymaker.tradeconfig.dto.BulkUpdateResultDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Bulk update — one field-set applied across many configs in one call.
 *
 * <p>The contract under test: {@code null} fields are left untouched on every
 * row (a patch, not a replacement); {@code dryRun} writes nothing; the strategy
 * filter resolves tags the same way dispatch does; and a patch that would leave
 * any row with an inverted premium band rejects the whole batch.</p>
 */
class TradeConfigBulkUpdateTest {

    private static final LocalDate DAY_1 = LocalDate.of(2026, 8, 24);
    private static final LocalDate DAY_2 = LocalDate.of(2026, 8, 25);

    private TradeConfigRepository tradeConfigRepository;
    private TradeConfigScheduler scheduler;
    private TradeConfigAdminService service;

    @BeforeEach
    void setUp() {
        tradeConfigRepository = mock(TradeConfigRepository.class);
        scheduler = mock(TradeConfigScheduler.class);

        service = new TradeConfigAdminService(tradeConfigRepository,
                mock(SmaTimeframeRepository.class),
                mock(InstrumentRepository.class),
                mock(TradeOrderRepository.class),
                scheduler,
                mock(StrategyFactory.class),
                mock(com.moneymaker.journal.JournalRecorder.class));
        ReflectionTestUtils.setField(service, "appMode", "backtest");
    }

    private TradeConfig config(int id, LocalDate date, Integer primaryStrategy, String strategyIds) {
        TradeConfig tc = new TradeConfig();
        tc.setId(id);
        Instrument i = new Instrument();
        i.setId(1);
        i.setInsName("NIFTY");
        tc.setInstrument(i);
        tc.setTradingDate(date);
        tc.setTradingSide("CE");
        tc.setTransactionType("SELL");
        tc.setStratergyId(primaryStrategy);
        tc.setStrategyIds(strategyIds);
        tc.setTarget(new BigDecimal("20"));
        tc.setStopLoss(new BigDecimal("30"));
        tc.setTargetPct(new BigDecimal("0.2000"));
        tc.setSlPct(new BigDecimal("0.3000"));
        tc.setMaxSlPoints(new BigDecimal("60"));
        tc.setTrailLadder("25:2,50:25");
        tc.setMinOptionPrice(new BigDecimal("80"));
        tc.setMaxOptionPrice(new BigDecimal("250"));
        tc.setSource("AUTO_DOWNTREND");
        return tc;
    }

    private void givenAutoConfigs(TradeConfig... configs) {
        when(tradeConfigRepository.findBySource("AUTO_DOWNTREND"))
                .thenReturn(new ArrayList<>(List.of(configs)));
    }

    private static BulkUpdateRequestDTO request(boolean dryRun) {
        BulkUpdateRequestDTO r = new BulkUpdateRequestDTO();
        r.setDryRun(dryRun);
        return r;
    }

    @Test
    @DisplayName("dry run reports the matched set and writes nothing")
    void dryRunWritesNothing() {
        givenAutoConfigs(config(1, DAY_1, 1, "1"), config(2, DAY_2, 1, "1"));

        BulkUpdateRequestDTO r = request(true);
        r.setSlPct(new BigDecimal("0.25"));

        BulkUpdateResultDTO result = service.bulkUpdate(r);

        assertThat(result.getMatched()).isEqualTo(2);
        assertThat(result.getUpdated()).isZero();
        assertThat(result.isDryRun()).isTrue();
        assertThat(result.getChanges()).containsExactly("slPct = 0.25");
        verify(tradeConfigRepository, never()).saveAll(anyList());
        verify(scheduler, never()).invalidateConfigsCache();
    }

    @Test
    @DisplayName("only the named fields change; everything else keeps its per-row value")
    void patchTouchesOnlyNamedFields() {
        TradeConfig a = config(1, DAY_1, 1, "1");
        givenAutoConfigs(a);

        BulkUpdateRequestDTO r = request(false);
        r.setSlPct(new BigDecimal("0.25"));
        r.setMaxSlPoints(new BigDecimal("40"));

        BulkUpdateResultDTO result = service.bulkUpdate(r);

        assertThat(result.getUpdated()).isEqualTo(1);
        assertThat(a.getSlPct()).isEqualByComparingTo("0.25");
        assertThat(a.getMaxSlPoints()).isEqualByComparingTo("40");
        // Untouched fields keep what the row had.
        assertThat(a.getTargetPct()).isEqualByComparingTo("0.2000");
        assertThat(a.getTarget()).isEqualByComparingTo("20");
        assertThat(a.getTrailLadder()).isEqualTo("25:2,50:25");
        verify(tradeConfigRepository).saveAll(anyList());
        // The cache-invalidation contract — skipping it leaves the pipeline on
        // a stale snapshot until restart.
        verify(scheduler).invalidateConfigsCache();
    }

    @Test
    @DisplayName("strategy filter matches strategy_ids tags, or the primary for untagged rows")
    void strategyFilterUsesDispatchResolution() {
        TradeConfig tagged = config(1, DAY_1, 1, "1,2");   // runs under 2 via tag
        TradeConfig untagged = config(2, DAY_1, 2, null);  // runs under 2 via primary
        TradeConfig other = config(3, DAY_1, 1, "1");
        givenAutoConfigs(tagged, untagged, other);

        BulkUpdateRequestDTO r = request(true);
        r.setStrategyId(2);
        r.setSlPct(new BigDecimal("0.25"));

        BulkUpdateResultDTO result = service.bulkUpdate(r);

        assertThat(result.getIds()).containsExactly(1, 2);
    }

    @Test
    @DisplayName("a request with no fields set is rejected, not applied as a no-op")
    void noFieldsRejected() {
        assertThatThrownBy(() -> service.bulkUpdate(request(true)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Nothing to update");
    }

    @Test
    @DisplayName("a patch that would invert any row's premium band rejects the whole batch")
    void invertedBandRejectsBatch() {
        TradeConfig cheap = config(1, DAY_1, 1, "1");
        cheap.setMaxOptionPrice(new BigDecimal("100"));
        givenAutoConfigs(config(2, DAY_1, 1, "1"), cheap);

        BulkUpdateRequestDTO r = request(false);
        r.setMinOptionPrice(new BigDecimal("120")); // above cheap's max of 100

        assertThatThrownBy(() -> service.bulkUpdate(r))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("config 1")
                .hasMessageContaining("inverted premium band");
        verify(tradeConfigRepository, never()).saveAll(anyList());
    }

    @Test
    @DisplayName("blank trailLadder removes the ladder; null leaves it alone")
    void blankLadderClears() {
        TradeConfig a = config(1, DAY_1, 1, "1");
        givenAutoConfigs(a);

        BulkUpdateRequestDTO r = request(false);
        r.setTrailLadder("");

        service.bulkUpdate(r);

        assertThat(a.getTrailLadder()).isNull();
    }

    @Test
    @DisplayName("a half-set date window is rejected")
    void halfSetWindowRejected() {
        BulkUpdateRequestDTO r = request(true);
        r.setSlPct(new BigDecimal("0.25"));
        r.setFromDate(DAY_1);

        assertThatThrownBy(() -> service.bulkUpdate(r))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("fromDate and toDate");
    }

    @Test
    @DisplayName("MANUAL rows are reachable only by explicit opt-in")
    void manualNeedsOptIn() {
        when(tradeConfigRepository.findBySource("MANUAL")).thenReturn(List.of());

        BulkUpdateRequestDTO r = request(true);
        r.setSource(AutoDeleteRequestDTO.Source.MANUAL);
        r.setSlPct(new BigDecimal("0.25"));

        service.bulkUpdate(r);

        verify(tradeConfigRepository).findBySource("MANUAL");
        verify(tradeConfigRepository, never()).findBySource("AUTO_DOWNTREND");
    }

    @Test
    @DisplayName("value rules match the single-config form: targetPct must stay inside (0, 1)")
    void valueRulesEnforced() {
        givenAutoConfigs(config(1, DAY_1, 1, "1"));

        BulkUpdateRequestDTO r = request(false);
        r.setTargetPct(BigDecimal.ONE);

        assertThatThrownBy(() -> service.bulkUpdate(r))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("targetPct");
    }

    @Test
    @DisplayName("prefill returns the values the whole fleet shares, scale-insensitively")
    void prefillReturnsSharedValues() {
        TradeConfig a = config(1, DAY_1, 1, "1");
        TradeConfig b = config(2, DAY_2, 1, "1");
        // Same value at different scale must still read as shared…
        a.setSlPct(new BigDecimal("0.30"));
        b.setSlPct(new BigDecimal("0.3000"));
        // …while a real disagreement marks the field mixed.
        b.setMaxSlPoints(new BigDecimal("40"));
        // All-null contributes to neither map.
        a.setMaxLoss(null);
        b.setMaxLoss(null);
        givenAutoConfigs(a, b);

        var prefill = service.bulkUpdatePrefill(null, null);

        assertThat(prefill.getMatched()).isEqualTo(2);
        assertThat(prefill.getValues())
                .containsEntry("slPct", "0.3")
                .containsEntry("targetPct", "0.2")
                .containsEntry("trailLadder", "25:2,50:25")
                .doesNotContainKeys("maxSlPoints", "maxLoss");
        assertThat(prefill.getMixedFields()).containsExactly("maxSlPoints");
    }

    @Test
    @DisplayName("prefill honours the strategy filter — the set shown is the set an apply writes")
    void prefillHonoursStrategyFilter() {
        TradeConfig s1 = config(1, DAY_1, 1, "1");
        s1.setSlPct(new BigDecimal("0.10"));
        TradeConfig s2 = config(2, DAY_1, 2, "2");
        s2.setSlPct(new BigDecimal("0.30"));
        givenAutoConfigs(s1, s2);

        var prefill = service.bulkUpdatePrefill(null, 2);

        assertThat(prefill.getMatched()).isEqualTo(1);
        assertThat(prefill.getValues()).containsEntry("slPct", "0.3");
        assertThat(prefill.getMixedFields()).isEmpty();
    }

    @Test
    @DisplayName("a dated window uses the windowed query")
    void datedWindowUsesWindowedQuery() {
        when(tradeConfigRepository.findBySourceAndTradingDateBetween(anyString(), any(), any()))
                .thenReturn(List.of(config(1, DAY_1, 1, "1")));

        BulkUpdateRequestDTO r = request(true);
        r.setSlPct(new BigDecimal("0.25"));
        r.setFromDate(DAY_1);
        r.setToDate(DAY_2);

        BulkUpdateResultDTO result = service.bulkUpdate(r);

        assertThat(result.getMatched()).isEqualTo(1);
        verify(tradeConfigRepository).findBySourceAndTradingDateBetween("AUTO_DOWNTREND", DAY_1, DAY_2);
        verify(tradeConfigRepository, never()).findBySource(anyString());
    }
}
