package com.moneymaker.dto;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Latest price + the timestamp the price applies to. Returned by
 * {@code PositionMonitorService.currentQuote(order)} so callers can stamp
 * monitor / exit timestamps with the *candle* time (in backtest) or wall-clock
 * (in live) consistently.
 *
 * <p>{@code high} / {@code low} are the extremes of the bar the price belongs
 * to, when the monitor has a bar at all — the backtest monitor supplies them
 * from the cached candle; live LTP monitors have only a tick and leave them
 * null. They exist for the resting-order stop model (S4 decision 2026-08-31):
 * a stop-loss floor is treated as an order resting at the broker, so breach
 * detection wants the bar's adverse extreme, not just its close. A null pair
 * degrades detection to the close price — the pre-existing behaviour.</p>
 */
public record Quote(BigDecimal price, LocalDateTime asOf, BigDecimal high, BigDecimal low) {

    /** Tick-only quote (live LTP monitors): no bar, extremes unknown. */
    public Quote(BigDecimal price, LocalDateTime asOf) {
        this(price, asOf, null, null);
    }
}
