package com.moneymaker.tradeconfig.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

@Data
public class TradeConfigViewDTO {
    private Integer id;
    private Integer instrumentId;
    private String instrumentName;
    private LocalDate tradingDate;
    private String tradingSide;
    private String transactionType;
    private BigDecimal target;
    private BigDecimal stopLoss;
    private BigDecimal maxLoss;
    private Integer optionDepth;
    private Integer lotQuantity;
    private Integer strategyId;
    private Integer numberOfTradesPerDay;
    private Integer numberOfParallelTrades;
    private Integer itmDepth;
    private Integer otmDepth;
    private Integer atmDepth;

    /** Inclusive premium band a signal must fall inside to open a trade. Null = unbounded. */
    private BigDecimal minOptionPrice;
    private BigDecimal maxOptionPrice;
    private List<SmaTimeframeDTO> timeframes;

    /** {@code MANUAL} or {@code AUTO_DOWNTREND} — drives the row badge. */
    private String source;

    /** Last write; shown so a generated row can be traced back to its run. */
    private LocalDateTime updatedDate;
}
