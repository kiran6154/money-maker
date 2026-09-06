package com.moneymaker.tradeconfig.service;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.repository.InstrumentRepository;
import com.moneymaker.repository.SmaTimeframeRepository;
import com.moneymaker.repository.TradeConfigRepository;
import com.moneymaker.repository.TradeOrderRepository;
import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.strategy.StrategyFactory;
import com.moneymaker.tradeconfig.dto.PagedResponse;
import com.moneymaker.tradeconfig.dto.TradeConfigViewDTO;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * The admin list's strategy filter.
 *
 * <p>Two things are worth pinning. First, a config that runs several strategies
 * must appear under <b>each</b> of them: the tag column decides dispatch, so
 * filtering on {@code stratergy_id} alone would hide half the fleet from the
 * strategy actually trading it. Second, the filter runs <b>before</b> paging —
 * otherwise the row count and the pager describe the unfiltered set, and a
 * strategy whose four configs are spread over five pages looks like it has one.
 */
class TradeConfigListStrategyFilterTest {

    private static final LocalDate DAY = LocalDate.of(2026, 9, 4);

    private TradeConfigRepository tradeConfigRepository;
    private TradeConfigAdminService service;

    @BeforeEach
    void setUp() {
        tradeConfigRepository = mock(TradeConfigRepository.class);
        service = new TradeConfigAdminService(tradeConfigRepository,
                mock(SmaTimeframeRepository.class),
                mock(InstrumentRepository.class),
                mock(TradeOrderRepository.class),
                mock(TradeConfigScheduler.class),
                mock(StrategyFactory.class),
                mock(com.moneymaker.journal.JournalRecorder.class));
        ReflectionTestUtils.setField(service, "appMode", "backtest");
    }

    private TradeConfig config(int id, Integer primaryStrategy, String strategyIds) {
        TradeConfig tc = new TradeConfig();
        tc.setId(id);
        Instrument i = new Instrument();
        i.setId(1);
        i.setInsName("NIFTY");
        tc.setInstrument(i);
        tc.setTradingDate(DAY);
        tc.setTradingSide("CE");
        tc.setTransactionType("BUY");
        tc.setStratergyId(primaryStrategy);
        tc.setStrategyIds(strategyIds);
        tc.setSource("MANUAL");
        return tc;
    }

    private void givenForDay(TradeConfig... configs) {
        when(tradeConfigRepository.findByTradingDate(DAY))
                .thenReturn(new ArrayList<>(List.of(configs)));
    }

    private static List<Integer> ids(PagedResponse<TradeConfigViewDTO> page) {
        return page.getItems().stream().map(TradeConfigViewDTO::getId).toList();
    }

    @Test
    @DisplayName("null strategyId returns every config for the date")
    void noFilterReturnsAll() {
        givenForDay(config(1, 1, null), config(2, 2, null), config(3, 3, null));

        PagedResponse<TradeConfigViewDTO> page = service.list(DAY, null, 0, 10);

        assertThat(ids(page)).containsExactly(3, 2, 1);
        assertThat(page.getTotalItems()).isEqualTo(3);
    }

    @Test
    @DisplayName("a tagged config shows under every strategy it runs, not just its primary")
    void tagSetDecidesMembership() {
        // Primary 1, but tagged "1,2" — this row really does trade under S2.
        givenForDay(config(10, 1, "1,2"), config(11, 2, null), config(12, 3, "3"));

        assertThat(ids(service.list(DAY, 1, 0, 10))).containsExactly(10);
        assertThat(ids(service.list(DAY, 2, 0, 10))).containsExactly(11, 10);
        assertThat(ids(service.list(DAY, 3, 0, 10))).containsExactly(12);
    }

    @Test
    @DisplayName("a blank tag column falls back to the primary id, matching dispatch")
    void blankTagsFallBackToPrimary() {
        givenForDay(config(20, 2, null), config(21, 2, "   "), config(22, 5, ""));

        assertThat(ids(service.list(DAY, 2, 0, 10))).containsExactly(21, 20);
        assertThat(ids(service.list(DAY, 5, 0, 10))).containsExactly(22);
    }

    @Test
    @DisplayName("the filter is applied before paging, so count and pager describe the filtered set")
    void filterRunsBeforePaging() {
        // Four S2 configs scattered through twelve rows. Filtering the page the
        // browser already had would report one or two of them, not four.
        List<TradeConfig> all = new ArrayList<>();
        for (int id = 1; id <= 12; id++) {
            all.add(config(id, id % 3 == 0 ? 2 : 1, null));
        }
        when(tradeConfigRepository.findByTradingDate(DAY)).thenReturn(all);

        PagedResponse<TradeConfigViewDTO> first = service.list(DAY, 2, 0, 2);

        assertThat(first.getTotalItems()).isEqualTo(4);
        assertThat(first.getTotalPages()).isEqualTo(2);
        assertThat(ids(first)).containsExactly(12, 9);

        PagedResponse<TradeConfigViewDTO> second = service.list(DAY, 2, 1, 2);
        assertThat(ids(second)).containsExactly(6, 3);
    }

    @Test
    @DisplayName("a strategy with no configs returns an empty page, not the unfiltered list")
    void unmatchedStrategyReturnsNothing() {
        givenForDay(config(30, 1, "1"), config(31, 2, "2"));

        PagedResponse<TradeConfigViewDTO> page = service.list(DAY, 9, 0, 10);

        assertThat(page.getItems()).isEmpty();
        assertThat(page.getTotalItems()).isZero();
    }

    @Test
    @DisplayName("with no date, the filter still applies across every date")
    void filterAppliesToTheAllDatesView() {
        when(tradeConfigRepository.findAll()).thenReturn(new ArrayList<>(List.of(
                config(40, 1, "1"), config(41, 2, "1,2"), config(42, 3, "3"))));

        assertThat(ids(service.list(null, 2, 0, 10))).containsExactly(41);
        assertThat(ids(service.list(null, null, 0, 10))).containsExactly(42, 41, 40);
    }
}
