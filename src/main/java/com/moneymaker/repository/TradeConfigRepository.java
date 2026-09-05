package com.moneymaker.repository;

import com.moneymaker.entity.TradeConfig;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

@Repository
public interface TradeConfigRepository extends JpaRepository<TradeConfig, Integer> {
    List<TradeConfig> findByTradingDate(LocalDate tradingDate);

    /** Idempotency probe for {@code EodDowntrendDetectionService}. */
    List<TradeConfig> findByTradingDateAndSource(LocalDate tradingDate, String source);

    // ------------------------------------------------------------------
    // Bulk-delete support for auto-generated configs
    // ------------------------------------------------------------------

    /**
     * Per-day counts for the bulk-delete calendar. Aggregated in SQL rather than by
     * loading rows: a wide month range would otherwise pull every config and its
     * timeframes just to count them.
     *
     * <p>Columns: {@code trading_date, total, ce, pe, combos, last_updated}.</p>
     */
    @Query(value = """
        SELECT tc.trading_date                                        AS trading_date,
               COUNT(*)                                               AS total,
               SUM(CASE WHEN tc.trading_side = 'CE' THEN 1 ELSE 0 END) AS ce,
               SUM(CASE WHEN tc.trading_side = 'PE' THEN 1 ELSE 0 END) AS pe,
               (SELECT COUNT(*) FROM sma_timeframe st
                 WHERE st.tc_id IN (SELECT i.id FROM trade_config i
                                     WHERE i.source = :source
                                       AND i.trading_date = tc.trading_date)) AS combos,
               MAX(tc.updated_date)                                   AS last_updated
          FROM trade_config tc
         WHERE tc.source = :source
           AND tc.trading_date BETWEEN :from AND :to
         GROUP BY tc.trading_date
         ORDER BY tc.trading_date
        """, nativeQuery = true)
    List<Object[]> autoCalendar(@Param("source") String source,
                                @Param("from") LocalDate from,
                                @Param("to") LocalDate to);

    /** Configs for the given trading dates. Source is pinned by the caller. */
    List<TradeConfig> findBySourceAndTradingDateIn(String source, List<LocalDate> tradingDates);

    /** Every config in a trading-date window — powers the backtest config picker. */
    List<TradeConfig> findByTradingDateBetween(LocalDate from, LocalDate to);

    /** One source's configs in a trading-date window — the bulk-update selector. */
    List<TradeConfig> findBySourceAndTradingDateBetween(String source, LocalDate from, LocalDate to);

    /** Every config of one source — bulk update with no date filter. */
    List<TradeConfig> findBySource(String source);

    /** Configs written inside a window — the "undo this generation run" selector. */
    List<TradeConfig> findBySourceAndUpdatedDateBetween(String source,
                                                        LocalDateTime updatedFrom,
                                                        LocalDateTime updatedTo);

    /** Distinct write timestamps, newest first; clustered into runs by the service. */
    @Query("SELECT DISTINCT tc.updatedDate FROM TradeConfig tc "
            + "WHERE tc.source = :source AND tc.updatedDate IS NOT NULL "
            + "ORDER BY tc.updatedDate DESC")
    List<LocalDateTime> distinctUpdatedDates(@Param("source") String source);

    /**
     * Combined config + instrument + instrument-details rows for one trading date.
     *
     * <p><b>The column list is explicit on purpose — do not change it to
     * {@code SELECT tc.*}.</b> The result is consumed positionally by
     * {@code TradeConfigScheduler.mapToTradeConfig / mapToInstrument /
     * mapToInstrumentDetails}, so ordinal position <i>is</i> the contract.
     * With {@code tc.*} the order came from the physical table layout, which
     * meant any {@code ALTER TABLE ... ADD COLUMN} silently shifted every
     * downstream index — that is exactly how {@code is_active} broke the
     * instrument mapping with {@code NumberFormatException: "MANUAL"}.
     * Naming the columns pins the order to this query, so a new table column
     * is simply not selected and nothing downstream moves.</p>
     *
     * <p>Index map consumed by the mappers:</p>
     * <ul>
     *   <li>{@code 0..24}  — trade_config ({@code max_parallel_per_side} last)</li>
     *   <li>{@code 25..29} — instrument</li>
     *   <li>{@code 30..41} — instrument_details</li>
     * </ul>
     *
     * <p>If you add a column here, append it to the <i>end</i> of its own
     * block and update the matching mapper — never insert into the middle.
     * Changeset 035 appended {@code strategy_ids} at index 19 and shifted both
     * later blocks by one; changeset 036 appended {@code max_sl_points} and
     * {@code trail_ladder} at 20-21 and shifted them by two more; wiring
     * changeset 027's {@code target_pct} / {@code sl_pct} appended them at 22-23
     * and shifted the later blocks by two again;
     * {@code TradeConfigScheduler}'s mappers carry the matching start offsets.</p>
     *
     * <p><b>A column missing from this list is not a cosmetic omission — it is a
     * feature that silently does not run.</b> The entity field stays null on every
     * DTO in {@code SharedData.combinedDto}, and code reading it downstream takes
     * its null branch with no error anywhere. That is what happened to
     * {@code max_sl_points} / {@code trail_ladder} between 036 landing and the
     * fix on 2026-08-30, and it was true of {@code target_pct} / {@code sl_pct}
     * from changeset 027 until they were wired here on 2026-08-31 — see S6 in
     * {@code docs/STRATEGY_ANALYSIS_TODO.md} for the measured before/after.
     * {@code TradeConfigCombinedQueryContractTest} pins the block boundaries so
     * the next appended column cannot repeat it.</p>
     */
    @Query(value = "SELECT " +
            "  tc.id, tc.trading_side, tc.trading_date, tc.target, tc.stop_loss, " +
            "  tc.p_instrument, tc.max_loss, tc.option_depth, tc.transaction_type, " +
            "  tc.lot_quantity, tc.stratergy_id, tc.no_of_trades, tc.no_of_parrellel_trades, " +
            "  tc.itm_depth, tc.otm_depth, tc.atm_depth, tc.source, " +
            "  tc.min_option_price, tc.max_option_price, tc.strategy_ids, " +
            "  tc.max_sl_points, tc.trail_ladder, " +
            "  tc.target_pct, tc.sl_pct, tc.max_parallel_per_side, " +
            // Changeset 042 — the Pressure intraday clock, the exact-offset
            // strike, and the book id. Appended to the END of the trade_config
            // block, never inserted, so no later index shifts.
            "  tc.entry_from, tc.entry_to, tc.max_hold_minutes, tc.flatten_at, " +
            "  tc.strike_offset_points, tc.strike_step_points, tc.book_id, tc.underlying_leg, " +
            "  i.id, i.ins_name, i.ins_id, i.lot_qty, i.strike_points, " +
            "  id.instrument_token, id.exchange_token, id.tradingsymbol, id.name, " +
            "  id.last_price, id.expiry, id.strike, id.tick_size, id.lot_size, " +
            "  id.instrument_type, id.segment, id.exchange " +
            "FROM trade_config tc " +
            "JOIN instrument i ON tc.p_instrument = i.id " +
            "JOIN instrument_details id ON i.ins_id = id.instrument_token " +
            "WHERE DATE(tc.trading_date) = :tradingDate " +
            // GAPS #7: retired configs keep their id, history and trade_order rows
            // but stop being dispatched. COALESCE rather than a bare `= TRUE` so a
            // row that predates changeset 037 -- or one written by a path that left
            // the column NULL -- still runs; "unknown" must mean active, because the
            // alternative is silently retiring every config on the day 037 lands.
            "  AND COALESCE(tc.is_active, TRUE) = TRUE", nativeQuery = true)
    List<Object[]> fetchCombinedByTradingDate(@Param("tradingDate") LocalDate tradingDate);
}
