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
    /** The config's primary strategy — what the edit form binds to. */
    private Integer strategyId;

    /**
     * Every strategy this config actually runs under, parsed from its
     * {@code strategy_ids} column (changesets 031/035), ascending.
     *
     * <p>Read-only. Tagging is a DB-level operation by design, but the list view
     * must not show a config running {@code [1, 2]} as plain "1" — that reads as
     * "this runs one strategy" and is how someone mis-reads a doubled position as
     * a duplicate-trade bug.</p>
     *
     * <p>Falls back to {@link #strategyId} when the config has no tags, matching
     * what the dispatch fallback does.</p>
     */
    private List<Integer> strategyIds;
    private Integer numberOfTradesPerDay;
    private Integer numberOfParallelTrades;
    private Integer itmDepth;
    private Integer otmDepth;
    private Integer atmDepth;

    /** Inclusive premium band a signal must fall inside to open a trade. Null = unbounded. */
    private BigDecimal minOptionPrice;
    private BigDecimal maxOptionPrice;

    /** Exit bracket as a fraction of entry premium; null = the absolute target / stopLoss applies. */
    private BigDecimal targetPct;
    private BigDecimal slPct;

    /** Ceiling in premium points on the resolved stop-loss; the lower of the two applies. */
    private BigDecimal maxSlPoints;

    /** Trailing rungs, canonical {@code "25:2,50:25"}; null = this config does not trail. */
    private String trailLadder;
    private List<SmaTimeframeDTO> timeframes;

    /** {@code MANUAL} or {@code AUTO_DOWNTREND} — drives the row badge. */
    private String source;

    /** Last write; shown so a generated row can be traced back to its run. */
    private LocalDateTime updatedDate;
}
