package com.moneymaker.position.service;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.TradeOrder;

/**
 * Contract for venue-specific live-quote lookup used during position
 * monitoring. {@link PositionMonitorFactory} picks the active implementation
 * based on {@code app.mode} and {@code broker.active}.
 *
 * <p>Implementations should be cheap to call — the position scheduler invokes
 * {@link #currentQuote(TradeOrder)} once per OPEN order per tick.
 *
 * <p>The returned {@link Quote#asOf()} is used by {@code PositionService} as
 * both the {@code last_monitored_at} stamp and (on threshold breach) the
 * exit time. So implementations should return the candle / quote timestamp,
 * not wall-clock — backtest needs the candle time so the ledger is faithful
 * to the simulated moment of exit.
 */
public interface PositionMonitorService {

    /**
     * Identifier this implementation handles. Compared case-insensitively
     * against {@code app.mode} ("BACKTEST") and {@code broker.active}
     * ("ZERODHA", "GROWW", "ANGEL_ONE").
     */
    String getName();

    /**
     * Returns the latest quoted price for the option leg held by {@code order}
     * along with its applicable timestamp, or {@code null} if no quote can
     * be sourced (broker error, strike no longer in cache, etc.). The monitor
     * treats {@code null} as "skip this tick" rather than failing.
     */
    Quote currentQuote(TradeOrder order);
}
