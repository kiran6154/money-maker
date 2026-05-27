package com.moneymaker.tradeconfig.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

@Data
public class TradeConfigFormDTO {
    private Integer id;
    private Integer instrumentId;
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
    private List<SmaTimeframeDTO> timeframes = new ArrayList<>();
}
