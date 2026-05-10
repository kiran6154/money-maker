package com.moneymaker.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * A trade intent emitted by a strategy and consumed by the order service.
 *
 * <p>{@link #strikeKey} carries everything the order service needs to act
 * on, encoded as
 * {@code <instrumentToken>|<interval>|<optionType>|<strike>|<optionToken>|<itmDepth>|<otmDepth>}.
 * (See {@code AnalysisScheduler.toStrikeMarketDataKey}.)
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class TradeSignal {
    private String strikeKey;
    private TradeAction action;
    private Integer tradeConfigId;
    private LocalDateTime signalTime;
    private Integer primarySma;
    private String interval;
    /** Close price of the candle that triggered the signal — used for entry/exit price. */
    private BigDecimal price;
}
