package com.moneymaker.strategy;

import com.moneymaker.dto.TradeConfigCombinedDTO;

/**
 * Contract for trading strategy implementations.
 * Each strategy is identified by an integer id that maps to
 * {@code TradeConfig#strategyId}.
 */
public interface Strategy {

    /**
     * @return the id this strategy handles (matches
     * {@link com.moneymaker.entity.TradeConfig#getStrategyId()}).
     */
    int getId();

    /**
     * Execute the strategy for the given combined trade configuration.
     */
    void execute(TradeConfigCombinedDTO config);
}

