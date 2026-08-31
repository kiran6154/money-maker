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
    /** Same-side (CE/PE) parallel cap; null on submit keeps the default 1. */
    private Integer maxParallelPerSide;
    private Integer itmDepth;
    private Integer otmDepth;
    private Integer atmDepth;

    /** Inclusive premium band a signal must fall inside to open a trade. Null = unbounded. */
    private BigDecimal minOptionPrice;
    private BigDecimal maxOptionPrice;

    /**
     * Exit bracket as a fraction of entry premium ({@code 0.20} = 20%). Null keeps
     * the absolute {@link #target} / {@link #stopLoss}; set, it overrides them.
     */
    private BigDecimal targetPct;
    private BigDecimal slPct;

    /**
     * Ceiling in premium points on the resolved stop-loss; the lower of the two
     * applies. Blank falls back to the standing 60, <b>not</b> to "uncapped" —
     * the cap is the exposure limit, and losing it by clearing a field is the
     * accident it exists to prevent.
     */
    private BigDecimal maxSlPoints;

    /**
     * Trailing rungs as {@code "25:2,50:25"}. Blank here really does mean "no
     * trailing", unlike {@link #maxSlPoints}: absence of a ladder is just the
     * pre-036 fixed stop, so it is the safe reading, and it gives the form an
     * off switch the cap does not need.
     */
    private String trailLadder;
    private List<SmaTimeframeDTO> timeframes = new ArrayList<>();
}
