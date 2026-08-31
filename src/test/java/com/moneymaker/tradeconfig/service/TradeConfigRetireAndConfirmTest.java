package com.moneymaker.tradeconfig.service;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.repository.InstrumentRepository;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.strategy.StrategyFactory;
import com.moneymaker.tradeconfig.dto.TradeConfigFormDTO;
import com.moneymaker.tradeconfig.dto.TradeConfigViewDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * GAPS #7 (retire instead of delete) and GAPS #8 (confirm an edit that open
 * trades will feel).
 *
 * <p>Both are about the same asymmetry: a trade-config is not just a record, it
 * is a live instruction, and the ledger holds it down. You cannot delete one
 * that has traded, and you should not silently re-point one that is trading
 * right now.
 */
class TradeConfigRetireAndConfirmTest {

    private static final Integer ID = 42;
    private static final LocalDate TRADING_DATE = LocalDate.of(2026, 8, 31);

    private TradeConfigRepository tradeConfigRepository;
    private TradeOrderRepository tradeOrderRepository;
    private SmaTimeframeRepository smaTimeframeRepository;
    private InstrumentRepository instrumentRepository;
    private TradeConfigAdminService service;

    private TradeConfig stored;

    @BeforeEach
    void setUp() {
        tradeConfigRepository = mock(TradeConfigRepository.class);
        tradeOrderRepository = mock(TradeOrderRepository.class);
        smaTimeframeRepository = mock(SmaTimeframeRepository.class);
        instrumentRepository = mock(InstrumentRepository.class);
        TradeConfigScheduler scheduler = mock(TradeConfigScheduler.class);
        StrategyFactory strategyFactory = mock(StrategyFactory.class);

        Instrument instrument = new Instrument();
        instrument.setId(1);
        instrument.setInsName("NIFTY");

        stored = new TradeConfig();
        stored.setId(ID);
        stored.setInstrument(instrument);
        stored.setTradingDate(TRADING_DATE);
        stored.setTradingSide("CALL");
        stored.setTransactionType("SELL");
        stored.setLotQuantity(75);
        stored.setNumberOfTradesPerDay(4);
        stored.setNumberOfParallelTrades(2);
        stored.setStratergyId(1);
        stored.setStrategyIds("1");
        stored.setTarget(new BigDecimal("20"));
        stored.setStopLoss(new BigDecimal("30"));
        stored.setSource("MANUAL");

        when(tradeConfigRepository.findById(ID)).thenReturn(Optional.of(stored));
        when(tradeConfigRepository.save(any(TradeConfig.class))).thenAnswer(inv -> inv.getArgument(0));
        when(tradeConfigRepository.getReferenceById(ID)).thenReturn(stored);
        when(smaTimeframeRepository.findByTradeConfigId(ID)).thenReturn(List.of());
        when(instrumentRepository.existsById(anyInt())).thenReturn(true);
        when(instrumentRepository.getReferenceById(1)).thenReturn(instrument);
        when(strategyFactory.availableStrategyIds()).thenReturn(List.of(1, 2));

        service = new TradeConfigAdminService(tradeConfigRepository, smaTimeframeRepository,
                instrumentRepository, tradeOrderRepository, scheduler, strategyFactory,
                mock(com.moneymaker.journal.JournalRecorder.class));
        // Not "live", so afterMutation stops at the cache invalidation and does not
        // try to rebuild SharedData.combinedDto from a mocked scheduler.
        ReflectionTestUtils.setField(service, "appMode", "backtest");
    }

    /** A form that matches {@link #stored} exactly — the baseline "no change" edit. */
    private TradeConfigFormDTO unchangedForm() {
        TradeConfigFormDTO f = new TradeConfigFormDTO();
        f.setInstrumentId(1);
        f.setTradingDate(TRADING_DATE);
        f.setStrategyId(1);
        f.setTradingSide("CALL");
        f.setTransactionType("SELL");
        f.setLotQuantity(75);
        f.setNumberOfTradesPerDay(4);
        f.setNumberOfParallelTrades(2);
        f.setTarget(new BigDecimal("20"));
        f.setStopLoss(new BigDecimal("30"));
        return f;
    }

    private void givenOpenTrades(long count) {
        when(tradeOrderRepository.countByTradeConfigIdAndStatus(ID, "OPEN")).thenReturn(count);
    }

    /* ================= GAPS #7 — retire ================= */

    @Test
    @DisplayName("retiring flips is_active and keeps the row — nothing is deleted")
    void retire_keeps_the_row() {
        TradeConfigViewDTO view = service.setActive(ID, false);

        assertThat(stored.getIsActive()).isFalse();
        assertThat(view.isActive()).isFalse();
        verify(tradeConfigRepository).save(stored);
        verify(tradeConfigRepository, never()).deleteById(any());
        verify(smaTimeframeRepository, never()).deleteByTradeConfigId(any());
    }

    @Test
    @DisplayName("retiring is refused while trades are open — it would strand their broker exits")
    void retire_refused_with_open_trades() {
        givenOpenTrades(3);

        // A retired config leaves SharedData.combinedDto, and OrderService.findConfig
        // reads that list to size an EXIT. No DTO means no order goes out while the
        // ledger row is marked CLOSED -- the exact divergence GAPS #1 alerts on. A
        // confirmation dialog would not make that outcome any less wrong, so this is
        // one of the few places a hard refusal is the right shape.
        assertThatThrownBy(() -> service.setActive(ID, false))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("3 open trade(s)")
                .hasMessageContaining("Close them first");

        assertThat(stored.getIsActive()).isTrue();
        verify(tradeConfigRepository, never()).save(any(TradeConfig.class));
    }

    @Test
    @DisplayName("a config whose trades have all closed retires fine")
    void retire_allowed_once_flat() {
        when(tradeOrderRepository.existsByTradeConfigId(ID)).thenReturn(true);
        givenOpenTrades(0);

        assertThat(service.setActive(ID, false).isActive()).isFalse();
    }

    @Test
    @DisplayName("reinstating is never blocked — it can only add a config back to dispatch")
    void reinstate_never_blocked() {
        stored.setIsActive(false);
        givenOpenTrades(3);

        assertThat(service.setActive(ID, true).isActive()).isTrue();
    }

    @Test
    @DisplayName("reinstating puts it back")
    void reinstate_restores() {
        stored.setIsActive(false);

        assertThat(service.setActive(ID, true).isActive()).isTrue();
        assertThat(stored.getIsActive()).isTrue();
    }

    @Test
    @DisplayName("a config predating changeset 037 (null is_active) still reads as active")
    void null_is_active_reads_as_active() {
        stored.setIsActive(null);

        // Matches the COALESCE in fetchCombinedByTradingDate. If the list said
        // "retired" for a config dispatch is still running, the operator's picture
        // of what trades today would be wrong in the dangerous direction.
        assertThat(service.findById(ID).isActive()).isTrue();
    }

    @Test
    @DisplayName("delete of a traded config still refuses, and now points at the retire path")
    void delete_still_refuses_but_names_the_alternative() {
        when(tradeOrderRepository.existsByTradeConfigId(ID)).thenReturn(true);

        assertThatThrownBy(() -> service.delete(ID))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("kept for audit")
                .hasMessageContaining("/active?value=false");
    }

    /* ================= GAPS #8 — confirm ================= */

    @Test
    @DisplayName("with no open trades, any edit goes straight through")
    void no_open_trades_means_no_confirmation() {
        givenOpenTrades(0);
        TradeConfigFormDTO f = unchangedForm();
        f.setLotQuantity(150);
        f.setTransactionType("BUY");

        service.update(ID, f);

        assertThat(stored.getLotQuantity()).isEqualTo(150);
        assertThat(stored.getTransactionType()).isEqualTo("BUY");
    }

    @Test
    @DisplayName("bracket-only edits never ask, even with open trades — the order snapshotted them")
    void bracket_edits_do_not_ask() {
        givenOpenTrades(3);
        TradeConfigFormDTO f = unchangedForm();
        f.setTarget(new BigDecimal("35"));
        f.setStopLoss(new BigDecimal("18"));
        f.setMaxSlPoints(new BigDecimal("40"));
        f.setTrailLadder("25:2,50:25");

        service.update(ID, f);

        assertThat(stored.getTarget()).isEqualByComparingTo("35");
        assertThat(stored.getTrailLadder()).isEqualTo("25:2,50:25");
    }

    @Test
    @DisplayName("a no-op save with open trades does not ask either")
    void unchanged_form_does_not_ask() {
        givenOpenTrades(3);
        service.update(ID, unchangedForm());
        assertThat(stored.getLotQuantity()).isEqualTo(75);
    }

    @Test
    @DisplayName("lotQuantity change with open trades asks, and names the change")
    void lot_quantity_change_asks() {
        givenOpenTrades(2);
        TradeConfigFormDTO f = unchangedForm();
        f.setLotQuantity(150);

        assertThatThrownBy(() -> service.update(ID, f))
                .isInstanceOf(ConfirmationRequiredException.class)
                .hasMessageContaining("2 open trade(s)")
                .hasMessageContaining("lotQuantity: 75 -> 150");

        // Nothing was written: the caller has to come back with confirm.
        assertThat(stored.getLotQuantity()).isEqualTo(75);
        verify(tradeConfigRepository, never()).save(any(TradeConfig.class));
    }

    @Test
    @DisplayName("every non-snapshotted field trips the gate, and all of them are reported at once")
    void all_consequential_fields_are_reported() {
        givenOpenTrades(1);
        TradeConfigFormDTO f = unchangedForm();
        f.setTransactionType("BUY");
        f.setTradingSide("PUT");
        f.setLotQuantity(150);
        f.setNumberOfTradesPerDay(9);
        f.setNumberOfParallelTrades(5);
        f.setStrategyId(2);
        f.setTradingDate(TRADING_DATE.plusDays(1));

        assertThatThrownBy(() -> service.update(ID, f))
                .isInstanceOf(ConfirmationRequiredException.class)
                .satisfies(ex -> assertThat(((ConfirmationRequiredException) ex).getChanges())
                        .hasSize(7)
                        .anyMatch(c -> c.startsWith("transactionType:"))
                        .anyMatch(c -> c.startsWith("tradingSide:"))
                        .anyMatch(c -> c.startsWith("lotQuantity:"))
                        .anyMatch(c -> c.startsWith("numberOfTradesPerDay:"))
                        .anyMatch(c -> c.startsWith("numberOfParallelTrades:"))
                        .anyMatch(c -> c.startsWith("strategyId:"))
                        .anyMatch(c -> c.startsWith("tradingDate:")));
    }

    @Test
    @DisplayName("confirm=true applies the same edit — this is a warning, not a block")
    void confirm_applies_the_edit() {
        givenOpenTrades(2);
        TradeConfigFormDTO f = unchangedForm();
        f.setLotQuantity(150);
        f.setTransactionType("BUY");

        service.update(ID, f, true);

        assertThat(stored.getLotQuantity()).isEqualTo(150);
        assertThat(stored.getTransactionType()).isEqualTo("BUY");
    }

    @Test
    @DisplayName("a CLOSED-only history does not gate an edit — only live positions do")
    void closed_trades_do_not_gate() {
        // existsByTradeConfigId would be true here; the gate counts OPEN only.
        when(tradeOrderRepository.existsByTradeConfigId(ID)).thenReturn(true);
        givenOpenTrades(0);

        TradeConfigFormDTO f = unchangedForm();
        f.setNumberOfParallelTrades(5);

        service.update(ID, f);

        assertThat(stored.getNumberOfParallelTrades()).isEqualTo(5);
    }
}
