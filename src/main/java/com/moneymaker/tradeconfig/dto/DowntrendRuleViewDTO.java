package com.moneymaker.tradeconfig.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalTime;
import java.util.List;

/**
 * One {@code sma_downtrend_rule} row as the Detection rules panel shows it.
 *
 * <p>The editable part is the changeset-039 grid — {@link #smaPeriods},
 * {@link #timeframesMinutes}, {@link #indicatorType} — plus {@link #enabled}.
 * Everything else is read-only context so the row is legible without opening
 * SQL: what the rule monitors, how strict it is, and the bracket/band its
 * generated configs will carry. Editing those stays a SQL operation (they are
 * NOT NULL trading thresholds; see EOD_DOWNTREND.md).</p>
 */
@Data
public class DowntrendRuleViewDTO {
    private Integer id;
    private Integer instrumentId;
    private String instrumentName;

    /** Primary strategy (the tag-table fallback). */
    private Integer strategyId;

    /** Strategies the rule actually generates for — enabled tags, or the primary. */
    private List<Integer> strategyIds;

    private Boolean enabled;

    /* ---- the editable detection grid (changeset 039) ---- */
    private String smaPeriods;
    private String timeframesMinutes;
    private String indicatorType;

    /* ---- read-only context ---- */
    private Integer maxDeviation;
    private LocalTime startTime;
    private BigDecimal targetPct;
    private BigDecimal slPct;
    private BigDecimal maxSlPoints;
    private String trailLadder;
    private BigDecimal minOptionPrice;
    private BigDecimal maxOptionPrice;
}
