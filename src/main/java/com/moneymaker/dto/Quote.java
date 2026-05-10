package com.moneymaker.dto;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Latest price + the timestamp the price applies to. Returned by
 * {@code PositionMonitorService.currentQuote(order)} so callers can stamp
 * monitor / exit timestamps with the *candle* time (in backtest) or wall-clock
 * (in live) consistently.
 */
public record Quote(BigDecimal price, LocalDateTime asOf) {
}
