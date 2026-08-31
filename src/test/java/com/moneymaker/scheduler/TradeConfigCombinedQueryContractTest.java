package com.moneymaker.scheduler;

import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.InstrumentDetails;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.repository.TradeConfigRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.data.jpa.repository.Query;

import java.lang.reflect.Method;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Pins the ordinal contract between
 * {@code TradeConfigRepository.fetchCombinedByTradingDate}'s SELECT list and the
 * three positional mappers in {@link TradeConfigScheduler}.
 *
 * <p><b>Why this test exists.</b> The query is native and consumed by index, so
 * the SELECT list <i>is</i> an API with no compiler behind it. Two distinct
 * failures have already happened on it, and neither produced an error:</p>
 *
 * <ul>
 *   <li><b>Silent inertness.</b> A column added to the entity but never added
 *       here leaves that field null on every DTO in {@code SharedData.combinedDto}.
 *       Downstream code takes its null branch and the feature simply never runs.
 *       That is what happened to {@code max_sl_points} / {@code trail_ladder}
 *       when changeset 036 landed: the trailing stop and the SL ceiling were
 *       dead in both live and backtest, with nothing logged. It happened again,
 *       for longer, to {@code target_pct} / {@code sl_pct} from changeset 027
 *       (S6 in {@code docs/STRATEGY_ANALYSIS_TODO.md}): every trade between 027
 *       and 2026-08-31 exited on the absolute {@code target} / {@code stop_loss}
 *       points while the UI, the docs and the detector all said otherwise. Both
 *       pairs are now wired and both are asserted below — that is the point of
 *       this file: a column that reaches the DB but not this SELECT list is a
 *       feature that does not exist at runtime.</li>
 *   <li><b>Silent shifting.</b> A column inserted in the <i>middle</i> slides
 *       every later index by one, so the instrument block starts reading
 *       trade_config values. That is the {@code NumberFormatException} on
 *       {@code "MANUAL"} the query's own Javadoc describes.</li>
 * </ul>
 *
 * <p>Unit tests that build a {@code TradeConfig} by hand cannot catch either,
 * because they never go through this query.</p>
 */
class TradeConfigCombinedQueryContractTest {

    /**
     * The SELECT list, in order. Append here and in the query together; anything
     * else — an insertion, a rename, a removal — should fail this test loudly
     * rather than shift a later block silently.
     */
    private static final List<String> EXPECTED_COLUMNS = List.of(
            // trade_config: 0..24
            "tc.id", "tc.trading_side", "tc.trading_date", "tc.target", "tc.stop_loss",
            "tc.p_instrument", "tc.max_loss", "tc.option_depth", "tc.transaction_type",
            "tc.lot_quantity", "tc.stratergy_id", "tc.no_of_trades", "tc.no_of_parrellel_trades",
            "tc.itm_depth", "tc.otm_depth", "tc.atm_depth", "tc.source",
            "tc.min_option_price", "tc.max_option_price", "tc.strategy_ids",
            "tc.max_sl_points", "tc.trail_ladder",
            "tc.target_pct", "tc.sl_pct",
            "tc.max_parallel_per_side",
            // instrument: 25..29
            "i.id", "i.ins_name", "i.ins_id", "i.lot_qty", "i.strike_points",
            // instrument_details: 30..41
            "id.instrument_token", "id.exchange_token", "id.tradingsymbol", "id.name",
            "id.last_price", "id.expiry", "id.strike", "id.tick_size", "id.lot_size",
            "id.instrument_type", "id.segment", "id.exchange");

    private static final int INSTRUMENT_START = 25;
    private static final int DETAILS_START = 30;

    private static List<String> selectedColumns() throws Exception {
        Method m = TradeConfigRepository.class
                .getMethod("fetchCombinedByTradingDate", LocalDate.class);
        String sql = m.getAnnotation(Query.class).value();
        String list = sql.substring(sql.indexOf("SELECT") + "SELECT".length(), sql.indexOf("FROM"));
        return Arrays.stream(list.split(","))
                .map(String::trim)
                .filter(c -> !c.isEmpty())
                .toList();
    }

    @Test
    @DisplayName("the SELECT list matches the ordinals the mappers assume, column for column")
    void selectListMatchesMapperOrdinals() throws Exception {
        assertThat(selectedColumns())
                .as("fetchCombinedByTradingDate's SELECT list drifted from the mapper ordinals. "
                        + "Append new columns to the END of their own block and bump the mapper "
                        + "start offsets (TradeConfigScheduler.mapToInstrument / mapToInstrumentDetails).")
                .containsExactlyElementsOf(EXPECTED_COLUMNS);
    }

    @Test
    @DisplayName("the block boundaries are where the mappers start reading")
    void blockBoundariesAreWhereMappersStart() throws Exception {
        List<String> cols = selectedColumns();

        assertThat(cols.get(INSTRUMENT_START))
                .as("mapToInstrument starts at index %d", INSTRUMENT_START)
                .startsWith("i.");
        assertThat(cols.get(INSTRUMENT_START - 1)).startsWith("tc.");
        assertThat(cols.get(DETAILS_START))
                .as("mapToInstrumentDetails starts at index %d", DETAILS_START)
                .startsWith("id.");
        assertThat(cols.get(DETAILS_START - 1)).startsWith("i.");
    }

    /**
     * A synthetic result row shaped exactly like the query's SELECT list, with a
     * distinctive value per column so a one-position shift cannot go unnoticed.
     */
    private static Object[] syntheticRow() {
        List<Object> row = new ArrayList<>();
        // trade_config 0..21
        row.add(7);                                   // id
        row.add("SELL");                              // trading_side
        row.add(java.sql.Date.valueOf("2026-05-08")); // trading_date
        row.add(new BigDecimal("50"));                // target
        row.add(new BigDecimal("30"));                // stop_loss
        row.add(1);                                   // p_instrument (skipped by the mapper)
        row.add(new BigDecimal("5000"));              // max_loss
        row.add(3);                                   // option_depth
        row.add("SELL");                              // transaction_type
        row.add(75);                                  // lot_quantity
        row.add(1);                                   // stratergy_id
        row.add(4);                                   // no_of_trades
        row.add(2);                                   // no_of_parrellel_trades
        row.add(1);                                   // itm_depth
        row.add(2);                                   // otm_depth
        row.add(3);                                   // atm_depth
        row.add("MANUAL");                            // source
        row.add(new BigDecimal("80"));                // min_option_price
        row.add(new BigDecimal("250"));               // max_option_price
        row.add("1,2");                               // strategy_ids
        row.add(new BigDecimal("60"));                // max_sl_points
        row.add("25:2,50:25");                        // trail_ladder
        row.add(new BigDecimal("0.20"));              // target_pct
        row.add(new BigDecimal("0.30"));              // sl_pct
        row.add(1);                                   // max_parallel_per_side
        // instrument 25..29
        row.add(11);                                  // i.id
        row.add("NIFTY");                             // ins_name
        row.add("256265");                            // ins_id
        row.add(75);                                  // lot_qty
        row.add(new BigDecimal("50"));                // strike_points
        // instrument_details 30..41
        row.add(256265);                              // instrument_token
        row.add(1001);                                // exchange_token
        row.add("NIFTY26MAY24000CE");                 // tradingsymbol
        row.add("NIFTY");                             // name
        row.add(new BigDecimal("123.45"));            // last_price
        row.add(java.sql.Date.valueOf("2026-05-28")); // expiry (skipped by the mapper)
        row.add(new BigDecimal("24000"));             // strike
        row.add(new BigDecimal("0.05"));              // tick_size
        row.add(new BigDecimal("75"));                // lot_size
        row.add("CE");                                // instrument_type
        row.add("NFO-OPT");                           // segment
        row.add("NFO");                               // exchange
        return row.toArray();
    }

    private static Object invokePrivate(TradeConfigScheduler s, String name,
                                        Class<?>[] types, Object[] args) throws Exception {
        Method m = TradeConfigScheduler.class.getDeclaredMethod(name, types);
        m.setAccessible(true);
        return m.invoke(s, args);
    }

    @Test
    @DisplayName("036's two columns actually reach the DTO — the bug that made the feature inert")
    void trailColumnsReachTheConfig() throws Exception {
        // The regression this whole file exists for. Both were on the entity and in
        // the DB, and neither was selected or mapped, so OrderService read null for
        // both and every trade ran uncapped and untrailed.
        TradeConfig tc = (TradeConfig) invokePrivate(new TradeConfigScheduler(), "mapToTradeConfig",
                new Class<?>[]{Object[].class}, new Object[]{syntheticRow()});

        assertThat(tc.getMaxSlPoints()).isEqualByComparingTo("60");
        assertThat(tc.getTrailLadder()).isEqualTo("25:2,50:25");
    }

    @Test
    @DisplayName("027's percentage bracket actually reaches the DTO — unwired from 027 until 2026-08-31")
    void percentageBracketReachesTheConfig() throws Exception {
        // The same regression as above, older and wider: OrderService.bracketAtEntry
        // prefers these over the absolute columns, so while they were null every
        // trade silently exited on trade_config.target / stop_loss instead. Wiring
        // them is a live behaviour change on every config — see S6 for the paired
        // before/after measurement that signed it off.
        TradeConfig tc = (TradeConfig) invokePrivate(new TradeConfigScheduler(), "mapToTradeConfig",
                new Class<?>[]{Object[].class}, new Object[]{syntheticRow()});

        assertThat(tc.getTargetPct()).isEqualByComparingTo("0.20");
        assertThat(tc.getSlPct()).isEqualByComparingTo("0.30");
    }

    @Test
    @DisplayName("the trade_config block still maps to the right fields either side of the new columns")
    void tradeConfigBlockIsNotShifted() throws Exception {
        TradeConfig tc = (TradeConfig) invokePrivate(new TradeConfigScheduler(), "mapToTradeConfig",
                new Class<?>[]{Object[].class}, new Object[]{syntheticRow()});

        assertThat(tc.getId()).isEqualTo(7);
        assertThat(tc.getTradingSide()).isEqualTo("SELL");
        assertThat(tc.getTradingDate()).isEqualTo(LocalDate.of(2026, 5, 8));
        assertThat(tc.getTarget()).isEqualByComparingTo("50");
        assertThat(tc.getStopLoss()).isEqualByComparingTo("30");
        assertThat(tc.getMaxLoss()).isEqualByComparingTo("5000");
        assertThat(tc.getLotQuantity()).isEqualTo(75);
        assertThat(tc.getSource()).isEqualTo("MANUAL");
        assertThat(tc.getMinOptionPrice()).isEqualByComparingTo("80");
        assertThat(tc.getMaxOptionPrice()).isEqualByComparingTo("250");
        assertThat(tc.getStrategyIds()).isEqualTo("1,2");
    }

    @Test
    @DisplayName("appending to trade_config did not shift the instrument or details blocks")
    void laterBlocksAreNotShifted() throws Exception {
        // The failure mode the query's Javadoc calls out: a shifted instrument block
        // reads "MANUAL" into a numeric field. Asserting real values here is what
        // makes an off-by-one fail as a wrong value rather than as a lucky pass.
        TradeConfigScheduler scheduler = new TradeConfigScheduler();
        Object[] row = syntheticRow();

        TradeConfig tc = (TradeConfig) invokePrivate(scheduler, "mapToTradeConfig",
                new Class<?>[]{Object[].class}, new Object[]{row});
        Instrument ins = (Instrument) invokePrivate(scheduler, "mapToInstrument",
                new Class<?>[]{Object[].class, TradeConfig.class}, new Object[]{row, tc});

        assertThat(ins.getId()).isEqualTo(11);
        assertThat(ins.getInsName()).isEqualTo("NIFTY");
        assertThat(ins.getInsId()).isEqualTo("256265");
        assertThat(ins.getLotQty()).isEqualTo(75);
        assertThat(ins.getStrikePoints()).isEqualByComparingTo("50");

        InstrumentDetails det = (InstrumentDetails) invokePrivate(scheduler, "mapToInstrumentDetails",
                new Class<?>[]{Object[].class, TradeConfig.class, Instrument.class},
                new Object[]{row, tc, ins});

        assertThat(det.getInstrumentToken()).isEqualTo(256265);
        assertThat(det.getExchangeToken()).isEqualTo(1001);
        assertThat(det.getTradingSymbol()).isEqualTo("NIFTY26MAY24000CE");
        assertThat(det.getName()).isEqualTo("NIFTY");
        assertThat(det.getLastPrice()).isEqualByComparingTo("123.45");
        assertThat(det.getStrike()).isEqualByComparingTo("24000");
        assertThat(det.getInstrumentType()).isEqualTo("CE");
        assertThat(det.getSegment()).isEqualTo("NFO-OPT");
        assertThat(det.getExchange()).isEqualTo("NFO");
    }
}
