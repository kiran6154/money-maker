package com.moneymaker.strategy;

import com.moneymaker.dto.TradeConfigCombinedDTO;

import java.time.LocalDateTime;

/**
 * Contract for trading strategy implementations.
 * Each strategy is identified by an integer id that maps to
 * {@code TradeConfig#stratergyId}.
 */
public interface Strategy {

    /**
     * @return the id this strategy handles (matches
     * {@link com.moneymaker.entity.TradeConfig#getStratergyId()}).
     */
    int getId();

    /**
     * Execute the strategy for the given combined trade configuration.
     *
     * @param asOf the moment being evaluated — the backtest tick, or wall-clock
     *             in live. A strategy must not act on a bar that belongs to an
     *             earlier session than this: the candle series spans the whole
     *             SMA lookback, so the newest <i>settled</i> bar of a coarse
     *             timeframe is still the previous session's close until that
     *             timeframe's first bucket of the day completes.
     */
    void execute(TradeConfigCombinedDTO config, LocalDateTime asOf);
}

