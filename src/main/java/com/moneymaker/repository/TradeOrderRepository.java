package com.moneymaker.repository;

import com.moneymaker.entity.TradeOrder;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

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
     * True when a trade for this {@code (config, optionToken, status)} combination
     * has an entry timestamp inside the given window. Used to prevent re-entering
     * an already-closed intraday trade in the same day.
     */
    boolean existsByTradeConfigIdAndOptionTokenAndStatusAndEntryTimeBetween(
            Integer tradeConfigId, String optionToken, String status,
            LocalDateTime fromInclusive, LocalDateTime toInclusive);

    /**
     * Returns all trades in {@code status} whose entry timestamp falls in the
     * given window. Used by {@code OrderService.forceCloseOpenPositions} at
     * end-of-day to clean up any leftover OPEN intraday positions whose
     * strike fell out of the active-strike set before the close signal could fire.
     */
    List<TradeOrder> findByStatusAndEntryTimeBetween(
            String status, LocalDateTime fromInclusive, LocalDateTime toInclusive);
}
