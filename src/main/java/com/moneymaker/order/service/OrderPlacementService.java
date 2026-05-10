package com.moneymaker.order.service;

import com.moneymaker.dto.FillSnapshot;
import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.TradeOrder;

/**
 * Contract for venue-specific order placement (Zerodha, Groww, Angel One,
 * Backtesting). {@link OrderPlacementFactory} picks the right one based on
 * {@code app.mode} and {@code broker.active}.
 *
 * <p>{@link #place(TradeOrder, TradeConfigCombinedDTO)} is called for both
 * entry and exit. The {@link TradeOrder#getStatus() status} field
 * discriminates: {@code OPEN} → entry leg, {@code CLOSED} → exit leg.
 *
 * <p>{@link #syncFill(String)} resolves the latest fill state against the
 * broker, given the broker-side order id captured at placement time.
 */
public interface OrderPlacementService {

    /**
     * Identifier this implementation handles. Compared case-insensitively
     * against {@code app.mode} ("BACKTEST") and {@code broker.active}
     * ("ZERODHA", "GROWW", "ANGEL_ONE").
     */
    String getName();

    /**
     * Fire the broker call for {@code order}. Returns the broker-side order
     * id on a successful dispatch, or {@code null} when not placed (skeleton,
     * skipped because not logged in, validation failure). The caller persists
     * the returned id on {@link TradeOrder#setEntryBrokerOrderId(String)} or
     * {@link TradeOrder#setExitBrokerOrderId(String)}.
     */
    String place(TradeOrder order, TradeConfigCombinedDTO config);

    /**
     * Resolve the latest fill state for {@code brokerOrderId}. Implementations
     * should return {@code null} when sync isn't supported (e.g. broker
     * skeleton not yet wired) or when the id is not found.
     */
    FillSnapshot syncFill(String brokerOrderId);
}
