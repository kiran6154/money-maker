package com.moneymaker.repository;

import com.moneymaker.entity.TradeOrder;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface TradeOrderRepository extends JpaRepository<TradeOrder, Long> {

    /**
     * Returns the open trade for an option contract identified by its option token
     * (unique per strike+expiry+type). Used by {@code OrderService} to decide
     * whether an incoming signal closes the existing position or opens a new one.
     */
    Optional<TradeOrder> findFirstByTradeConfigIdAndOptionTokenAndStatus(
            Integer tradeConfigId, String optionToken, String status);

    /**
     * Counts all trades for a given trade config whose entry timestamp falls in
     * the window — used by {@code OrderService} to enforce the
     * {@code TradeConfig.numberOfTradesPerDay} cap. Counts across all option
     * tokens (strikes), all statuses (OPEN + CLOSED) — i.e. "how many entries
     * has this config produced today, total".
     */
    long countByTradeConfigIdAndEntryTimeBetween(
            Integer tradeConfigId,
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
     * Counts trades in {@code status} for a given config and entry direction.
     * Used by {@code OrderService} to enforce the
     * {@code TradeConfig.numberOfParallelTrades} cap — i.e. "max simultaneous
     * OPEN trades in the same direction for this config".
     */
    long countByTradeConfigIdAndEntryDirectionAndStatus(
            Integer tradeConfigId, String entryDirection, String status);

    /**
     * True when a row already exists with this exact
     * {@code (configId, optionToken, entryDirection, entryTime)} key —
     * regardless of {@code status}. Used by {@code OrderService} to suppress
     * duplicate inserts when the same backtest is re-run, or when the same
     * tick somehow queues the same signal twice. Legitimate re-entries on the
     * same strike later in the day fire at a different {@code entryTime} and
     * are unaffected.
     */
    boolean existsByTradeConfigIdAndOptionTokenAndEntryDirectionAndEntryTime(
            Integer tradeConfigId, String optionToken, String entryDirection, LocalDateTime entryTime);

    /**
     * Sums the realised per-share P&L from CLOSED trades for this config
     * whose entry timestamp falls inside the window. Returns 0 when no rows
     * match. Used by {@code OrderService} to enforce the
     * {@code TradeConfig.maxLoss} daily cap — i.e. "stop opening new trades
     * for this strategy once it has bled more than the configured per-day
     * loss". Only CLOSED trades count because OPEN positions still have
     * floating P&L; the {@code max_loss} cap is a *realised-loss* gate.
     */
    @Query("SELECT COALESCE(SUM(t.profit), 0) FROM TradeOrder t " +
            "WHERE t.tradeConfigId = :tradeConfigId " +
            "AND t.status = 'CLOSED' " +
            "AND t.entryTime BETWEEN :fromInclusive AND :toInclusive")
    BigDecimal sumRealisedProfitForDay(
            @Param("tradeConfigId") Integer tradeConfigId,
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
}
