package com.moneymaker.tradeconfig.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;
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
    private List<SmaTimeframeDTO> timeframes;

    /** M4.3 (GAPS #7): false = pipeline skips this config. */
    private boolean active = true;

    /**
     * M4.4 (GAPS #8): count of OPEN trades referencing this config across
     * all dates (not just today). The UI shows a warning banner when this is
     * > 0 so editing target/SL/lot etc. is a conscious choice.
     */
    private long openTradeCount;

    /** Convenience flag computed from {@link #openTradeCount}. */
    public boolean isHasOpenTrades() {
        return openTradeCount > 0;
    }
}
