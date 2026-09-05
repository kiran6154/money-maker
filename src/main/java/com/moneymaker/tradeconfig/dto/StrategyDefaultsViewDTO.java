package com.moneymaker.tradeconfig.dto;

import lombok.Data;

import java.math.BigDecimal;

/**
 * One {@code strategy_defaults} row as the Strategy bracket panel shows it.
 *
 * <p>The editable part is the changeset-041 pair — {@link #targetMode} and
 * {@link #slMode}, the POINTS/PERCENT switch that decides which of a config's
 * two bracket columns this strategy exits on. Everything else is read-only
 * context so a row is legible without opening SQL: which side the strategy
 * trades, how many trades it may take, and whether it generates at all.</p>
 *
 * <p>Those remaining fields stay SQL-only for the reason the Detection rules
 * panel gives for its thresholds — they are NOT NULL trading numbers with their
 * own changeset history (033/040), and this panel exists to make the bracket
 * mode switchable, not to become a second config editor.</p>
 */
@Data
public class StrategyDefaultsViewDTO {

    private Integer strategyId;

    /** Which of the two bracket columns the profit target resolves from. */
    private String targetMode;

    /** Which of the two bracket columns the stop-loss resolves from. */
    private String slMode;

    // ---- read-only context ----

    private String transactionType;
    private Integer lotQuantity;
    private BigDecimal maxLoss;
    private Integer noOfTrades;
    private Integer noOfParallelTrades;

    /** {@code true} = generated configs trade the mirror of the detected leg. */
    private Boolean oppositeSide;

    /** {@code false} = the EOD detector skips this strategy entirely. */
    private Boolean autoConfigEnabled;
}
