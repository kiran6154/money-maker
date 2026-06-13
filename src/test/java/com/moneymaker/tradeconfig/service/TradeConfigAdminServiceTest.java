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
import com.moneymaker.tradeconfig.dto.SmaTimeframeDTO;
import com.moneymaker.tradeconfig.dto.TradeConfigFormDTO;
import com.moneymaker.tradeconfig.dto.TradeConfigViewDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link TradeConfigAdminService}. The service is the single
 * write-path for the trade-config admin UI; its contract is documented in
 * the class Javadoc as "persist + invalidate date-cache + (live + today)
 * rebuild SharedData.combinedDto".
 */
class TradeConfigAdminServiceTest {

    @Mock private TradeConfigRepository tradeConfigRepository;
    @Mock private SmaTimeframeRepository smaTimeframeRepository;
    @Mock private InstrumentRepository instrumentRepository;
    @Mock private TradeOrderRepository tradeOrderRepository;
    @Mock private TradeConfigScheduler tradeConfigScheduler;
    @Mock private StrategyFactory strategyFactory;

    private TradeConfigAdminService service;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        service = new TradeConfigAdminService(
                tradeConfigRepository, smaTimeframeRepository, instrumentRepository,
                tradeOrderRepository, tradeConfigScheduler, strategyFactory);
        // Default to backtest mode so afterMutation doesn't try to refresh SharedData.
        ReflectionTestUtils.setField(service, "appMode", "backtest");
        // Most happy-path tests use these.
        lenient().when(instrumentRepository.existsById(any())).thenReturn(true);
        lenient().when(strategyFactory.availableStrategyIds()).thenReturn(List.of(1, 2));
    }

    @Test
    void create_persists_config_and_invalidates_cache() {
        TradeConfigFormDTO form = validForm();
        when(instrumentRepository.getReferenceById(99)).thenReturn(new Instrument());
        when(tradeConfigRepository.save(any(TradeConfig.class)))
                .thenAnswer(inv -> { TradeConfig t = inv.getArgument(0); t.setId(42); return t; });
        when(tradeConfigRepository.findById(42)).thenReturn(Optional.of(stubConfig(42)));
        when(smaTimeframeRepository.findByTradeConfigId(42)).thenReturn(List.of());

        TradeConfigViewDTO result = service.create(form);

        assertThat(result.getId()).isEqualTo(42);
        verify(tradeConfigRepository).save(any(TradeConfig.class));
        verify(tradeConfigScheduler).invalidateConfigsCache();
    }

    @Test
    void create_replaces_smaTimeframes_via_delete_then_save() {
        TradeConfigFormDTO form = validForm();
        form.setTimeframes(List.of(
                new SmaTimeframeDTO(null, 5, 50, 0.0),
                new SmaTimeframeDTO(null, 15, 200, 0.0)));
        when(instrumentRepository.getReferenceById(99)).thenReturn(new Instrument());
        when(tradeConfigRepository.save(any(TradeConfig.class)))
                .thenAnswer(inv -> { TradeConfig t = inv.getArgument(0); t.setId(42); return t; });
        when(tradeConfigRepository.findById(42)).thenReturn(Optional.of(stubConfig(42)));
        when(tradeConfigRepository.getReferenceById(42)).thenReturn(stubConfig(42));
        when(smaTimeframeRepository.findByTradeConfigId(42)).thenReturn(List.of());

        service.create(form);

        verify(smaTimeframeRepository).deleteByTradeConfigId(42);
        verify(smaTimeframeRepository).saveAll(any());
    }

    @Test
    void create_validates_required_fields() {
        TradeConfigFormDTO noInstrument = validForm();
        noInstrument.setInstrumentId(null);
        assertThatThrownBy(() -> service.create(noInstrument))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("instrumentId");

        TradeConfigFormDTO noDate = validForm();
        noDate.setTradingDate(null);
        assertThatThrownBy(() -> service.create(noDate))
                .hasMessageContaining("tradingDate");

        TradeConfigFormDTO noStrategy = validForm();
        noStrategy.setStrategyId(null);
        assertThatThrownBy(() -> service.create(noStrategy))
                .hasMessageContaining("strategyId");
    }

    @Test
    void create_rejects_unknown_instrumentId() {
        when(instrumentRepository.existsById(99)).thenReturn(false);
        assertThatThrownBy(() -> service.create(validForm()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Unknown instrumentId");
    }

    @Test
    void create_rejects_unknown_strategyId() {
        TradeConfigFormDTO form = validForm();
        form.setStrategyId(99);
        assertThatThrownBy(() -> service.create(form))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Unknown strategyId");
    }

    @Test
    void delete_blocks_when_trade_order_history_exists() {
        when(tradeConfigRepository.findById(42)).thenReturn(Optional.of(stubConfig(42)));
        when(tradeOrderRepository.existsByTradeConfigId(42)).thenReturn(true);

        assertThatThrownBy(() -> service.delete(42))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("trade_order rows reference");
        verify(tradeConfigRepository, never()).deleteById(any());
    }

    @Test
    void delete_proceeds_when_no_trade_order_history() {
        when(tradeConfigRepository.findById(42)).thenReturn(Optional.of(stubConfig(42)));
        when(tradeOrderRepository.existsByTradeConfigId(42)).thenReturn(false);

        service.delete(42);

        verify(smaTimeframeRepository).deleteByTradeConfigId(42);
        verify(tradeConfigRepository).deleteById(42);
        verify(tradeConfigScheduler).invalidateConfigsCache();
    }

    @Test
    void cloneFromDate_copies_active_configs_with_smaTimeframes() {
        TradeConfig src = stubConfig(7);
        src.setStrategyId(1);
        when(tradeConfigRepository.findByTradingDateAndIsActiveTrue(LocalDate.of(2026, 4, 1)))
                .thenReturn(List.of(src));
        when(tradeConfigRepository.findByTradingDate(LocalDate.of(2026, 4, 2))).thenReturn(List.of());
        SmaTimeframe tf = new SmaTimeframe();
        tf.setTimePeriod(5);
        tf.setSma(50);
        when(smaTimeframeRepository.findByTradeConfigId(7)).thenReturn(List.of(tf));
        when(tradeConfigRepository.save(any(TradeConfig.class)))
                .thenAnswer(inv -> { TradeConfig t = inv.getArgument(0); t.setId(77); return t; });
        when(tradeConfigRepository.getReferenceById(77)).thenReturn(stubConfig(77));

        var summary = service.cloneFromDate(LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 2));

        assertThat(summary.cloned()).isEqualTo(1);
        assertThat(summary.skipped()).isZero();
        verify(smaTimeframeRepository).saveAll(any());
    }

    @Test
    void cloneFromDate_skips_when_target_already_has_same_shape() {
        TradeConfig src = stubConfig(7);
        TradeConfig existing = stubConfig(88);
        // existing has same (instrumentId, strategyId, side, txn) → dedupe.
        when(tradeConfigRepository.findByTradingDateAndIsActiveTrue(LocalDate.of(2026, 4, 1)))
                .thenReturn(List.of(src));
        when(tradeConfigRepository.findByTradingDate(LocalDate.of(2026, 4, 2)))
                .thenReturn(List.of(existing));

        var summary = service.cloneFromDate(LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 2));

        assertThat(summary.cloned()).isZero();
        assertThat(summary.skipped()).isEqualTo(1);
        verify(tradeConfigRepository, never()).save(any(TradeConfig.class));
    }

    @Test
    void cloneFromDate_rejects_same_date_and_null_args() {
        assertThatThrownBy(() -> service.cloneFromDate(LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 1)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("must differ");
        assertThatThrownBy(() -> service.cloneFromDate(null, LocalDate.of(2026, 4, 1)))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> service.cloneFromDate(LocalDate.of(2026, 4, 1), null))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void list_view_populates_openTradeCount_and_hasOpenTrades() {
        when(tradeConfigRepository.findByTradingDate(LocalDate.of(2026, 4, 1)))
                .thenReturn(List.of(stubConfig(1)));
        when(smaTimeframeRepository.findByTradeConfigId(1)).thenReturn(List.of());
        when(tradeOrderRepository.countByTradeConfigIdAndStatus(1, "OPEN")).thenReturn(2L);

        var paged = service.list(LocalDate.of(2026, 4, 1), 0, 10);

        assertThat(paged.getItems()).hasSize(1);
        TradeConfigViewDTO v = paged.getItems().get(0);
        assertThat(v.getOpenTradeCount()).isEqualTo(2L);
        assertThat(v.isHasOpenTrades()).isTrue();
    }

    @Test
    void list_sorts_descending_by_id_and_paginates() {
        when(tradeConfigRepository.findByTradingDate(LocalDate.of(2026, 4, 1)))
                .thenReturn(List.of(stubConfig(1), stubConfig(3), stubConfig(2)));
        when(smaTimeframeRepository.findByTradeConfigId(any())).thenReturn(List.of());

        var paged = service.list(LocalDate.of(2026, 4, 1), 0, 2);

        // Sorted by id descending; page 0 size 2 → ids [3, 2].
        assertThat(paged.getItems()).hasSize(2);
        assertThat(paged.getItems().get(0).getId()).isEqualTo(3);
        assertThat(paged.getItems().get(1).getId()).isEqualTo(2);
        assertThat(paged.getTotalItems()).isEqualTo(3);
        assertThat(paged.getTotalPages()).isEqualTo(2);  // 3 items / 2 per page
    }

    /* ---------------- helpers ---------------- */

    private static TradeConfigFormDTO validForm() {
        TradeConfigFormDTO form = new TradeConfigFormDTO();
        form.setInstrumentId(99);
        form.setTradingDate(LocalDate.of(2026, 4, 1));
        form.setStrategyId(1);
        form.setTradingSide("CE");
        form.setTransactionType("SELL");
        form.setTarget(new BigDecimal("10"));
        form.setStopLoss(new BigDecimal("5"));
        form.setLotQuantity(50);
        return form;
    }

    private static TradeConfig stubConfig(int id) {
        TradeConfig t = new TradeConfig();
        t.setId(id);
        t.setTradingDate(LocalDate.of(2026, 4, 1));
        Instrument ins = new Instrument();
        ins.setId(99);
        ins.setInsName("NIFTY");
        t.setInstrument(ins);
        t.setStrategyId(1);
        return t;
    }
}
