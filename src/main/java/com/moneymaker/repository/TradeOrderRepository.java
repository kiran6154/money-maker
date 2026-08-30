package com.moneymaker.repository;

import com.moneymaker.entity.TradeOrder;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

@Repository
public interface TradeOrderRepository extends JpaRepository<TradeOrder, Long> {

    /**
     * Returns the open trade for an option contract identified by its option token
     * (unique per strike+expiry+type). Used by {@code OrderService} to decide
     * whether an incoming signal closes the existing position or opens a new one.
     *
     * <p>Scoped by {@code strategyId} as well as the config: since changeset 031
     * one config can be tagged with several strategies, and each holds its own
     * position on the same leg. Without the strategy in the predicate one
     * strategy's exit signal would close the other strategy's open trade.</p>
     */
    Optional<TradeOrder> findFirstByTradeConfigIdAndStrategyIdAndOptionTokenAndStatus(
            Integer tradeConfigId, Integer strategyId, String optionToken, String status);

    /**
     * Counts all trades for a given {@code (config, strategy)} whose entry
     * timestamp falls in the window — used by {@code OrderService} to enforce the
     * {@code TradeConfig.numberOfTradesPerDay} cap. Counts across all option
     * tokens (strikes), all statuses (OPEN + CLOSED) — i.e. "how many entries
     * has this strategy produced from this config today, total".
     *
     * <p>The cap is <b>per strategy</b>, not shared across the strategies tagged
     * on one config (changeset 031): two strategies on the same config each get
     * their own {@code numberOfTradesPerDay} budget, otherwise whichever fired
     * first would starve the other for the rest of the day.</p>
     */
    long countByTradeConfigIdAndStrategyIdAndEntryTimeBetween(
            Integer tradeConfigId, Integer strategyId,
            LocalDateTime fromInclusive, LocalDateTime toInclusive);

    /**
     * Returns all trades in {@code status} whose entry timestamp falls in the
     * given window. Used by {@code OrderService.forceCloseOpenPositions} at
     * end-of-day to clean up any leftover OPEN intraday positions whose
     * strike fell out of the active-strike set before the close signal could fire.
     */
    List<TradeOrder> findByStatusAndEntryTimeBetween(
            String status, LocalDateTime fromInclusive, LocalDateTime toInclusive);

    /**
     * Returns every trade in the given status. Used by {@code PositionService}
     * to walk OPEN trades each monitor tick and update peak P&L / detect SL or
     * target breaches.
     */
    List<TradeOrder> findByStatus(String status);

    /**
     * Row count for a status, without materialising the rows.
     *
     * <p>Exists because {@code BacktestAnalysisService} needs "how many CLOSED
     * trades are there" twice per tick for its DEBUG delta line, and was getting
     * it from {@code findByStatusAndEntryTimeBetween("CLOSED", 1970, 9999).size()}
     * — which loads the entire ledger into the persistence context on every tick,
     * growing more expensive the longer the run gets.
     */
    long countByStatus(String status);

    /**
     * Row count for a status within an entry-time window, without materialising
     * the rows. Backs the per-day trade_order delta in the backtest summary.
     */
    long countByStatusAndEntryTimeBetween(
            String status, LocalDateTime fromInclusive, LocalDateTime toInclusive);

    /**
     * Counts trades in {@code status} for a given {@code (config, strategy)} and
     * entry direction. Used by {@code OrderService} to enforce the
     * {@code TradeConfig.numberOfParallelTrades} cap — i.e. "max simultaneous
     * OPEN trades in the same direction for this strategy on this config".
     *
     * <p>Per strategy for the same reason the per-day cap is — see
     * {@link #countByTradeConfigIdAndStrategyIdAndEntryTimeBetween}.</p>
     */
    long countByTradeConfigIdAndStrategyIdAndEntryDirectionAndStatus(
            Integer tradeConfigId, Integer strategyId, String entryDirection, String status);

    /**
     * True when a row already exists with this exact
     * {@code (configId, strategyId, optionToken, entryDirection, entryTime)} key —
     * regardless of {@code status}. Used by {@code OrderService} to suppress
     * duplicate inserts when the same backtest is re-run, or when the same
     * tick somehow queues the same signal twice. Legitimate re-entries on the
     * same strike later in the day fire at a different {@code entryTime} and
     * are unaffected.
     *
     * <p>{@code strategyId} is part of the key because two strategies tagged on
     * one config legitimately produce the same {@code (optionToken, direction,
     * entryTime)} on the same candle. Without it the second strategy's entry
     * would be silently swallowed as a duplicate, and it would look as though
     * that strategy never fired.</p>
     */
    boolean existsByTradeConfigIdAndStrategyIdAndOptionTokenAndEntryDirectionAndEntryTime(
            Integer tradeConfigId, Integer strategyId, String optionToken,
            String entryDirection, LocalDateTime entryTime);

    /**
     * Sums the realised per-share P&L from CLOSED trades for this
     * {@code (config, strategy)} whose entry timestamp falls inside the window.
     * Returns 0 when no rows match. Used by {@code OrderService} to enforce the
     * {@code TradeConfig.maxLoss} daily cap — i.e. "stop opening new trades
     * for this strategy once it has bled more than the configured per-day
     * loss". Only CLOSED trades count because OPEN positions still have
     * floating P&L; the {@code max_loss} cap is a *realised-loss* gate.
     *
     * <p>Per strategy since changeset 031: a losing strategy must not be able to
     * spend the daily loss budget of another strategy tagged on the same
     * config.</p>
     */
    @Query("SELECT COALESCE(SUM(t.profit), 0) FROM TradeOrder t " +
            "WHERE t.tradeConfigId = :tradeConfigId " +
            "AND t.strategyId = :strategyId " +
            "AND t.status = 'CLOSED' " +
            "AND t.entryTime BETWEEN :fromInclusive AND :toInclusive")
    BigDecimal sumRealisedProfitForDay(
            @Param("tradeConfigId") Integer tradeConfigId,
            @Param("strategyId") Integer strategyId,
            @Param("fromInclusive") LocalDateTime fromInclusive,
            @Param("toInclusive") LocalDateTime toInclusive);

    /**
     * Returns every trade — OPEN or CLOSED — whose entry timestamp falls in
     * the given window. Used by {@code DaySummaryScheduler} to compose the
     * end-of-day Telegram digest.
     */
    List<TradeOrder> findByEntryTimeBetween(LocalDateTime fromInclusive, LocalDateTime toInclusive);

    /**
     * True when any trade_order row references this trade_config. Used by
     * the trade-config admin to block destructive edits (delete) on configs
     * that already have an audit trail of executed trades.
     */
    boolean existsByTradeConfigId(Integer tradeConfigId);

    /**
     * How many trades this config currently has in a given status. Used by the
     * trade-config admin to decide whether an edit needs confirming: a change to
     * a field the order did <b>not</b> snapshot at entry alters the behaviour of
     * positions that are still live (GAPS #8).
     */
    long countByTradeConfigIdAndStatus(Integer tradeConfigId, String status);

    /**
     * Counts the trade rows attached to a set of configs. Used by the bulk
     * auto-config delete to tell the user how much history a forced delete
     * would take with it, before they confirm it.
     */
    long countByTradeConfigIdIn(Collection<Integer> tradeConfigIds);

    /**
     * Deletes every trade row belonging to the given configs and returns how
     * many went. Only reachable from the bulk auto-config delete with
     * {@code force=true} — the audit trail is otherwise immutable from the app.
     */
    long deleteByTradeConfigIdIn(Collection<Integer> tradeConfigIds);
}
