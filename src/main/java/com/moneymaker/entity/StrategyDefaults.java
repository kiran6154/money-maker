package com.moneymaker.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;

/**
 * The {@code trade_config} field block a strategy stamps on every config the
 * end-of-day downtrend detector generates for it. One row per strategy.
 *
 * <p>These are the fields that are a <i>convention of the strategy</i> rather than
 * a property of the detected downtrend: which side it trades, how much it is
 * willing to lose in a day, how many trades it may open. The detector reads them
 * here instead of from the hardcoded {@code strategyDefaults(int)} switch it used
 * to carry — that switch handled strategy 1 only and returned {@code null} for
 * everything else, which made the detector skip any rule tagged with another
 * strategy without generating anything.</p>
 *
 * <p>Everything shaped by the <i>downtrend</i> rather than the strategy — the
 * premium band, the ATR multipliers, the percentage bracket, the deviation
 * tolerance — stays on {@link SmaDowntrendRule}.</p>
 *
 * <p>See changeset 033 and {@code docs/EOD_DOWNTREND.md}.</p>
 */
@Entity
@Table(name = "strategy_defaults")
@Getter
@Setter
public class StrategyDefaults {

    /** Matches {@code Strategy#getId()}. Natural key — there is exactly one block per strategy. */
    @Id
    @Column(name = "strategy_id", nullable = false)
    private Integer strategyId;

    /** {@code BUY} / {@code SELL} — the side an entry signal must carry to open a trade. */
    @Column(name = "transaction_type", nullable = false, length = 8)
    private String transactionType;

    /**
     * Last-resort order quantity. The detector prefers {@code instrument.lot_qty},
     * because the order quantity goes to the broker verbatim and NFO only accepts
     * whole lots — so the contract defines it, not the strategy.
     */
    @Column(name = "lot_quantity", nullable = false)
    private Integer lotQuantity;

    /** Daily realised-loss cap copied to {@code trade_config.max_loss}. */
    @Column(name = "max_loss", nullable = false, precision = 12, scale = 4)
    private BigDecimal maxLoss;

    /** Copied to {@code trade_config.no_of_trades}. */
    @Column(name = "no_of_trades", nullable = false)
    private Integer noOfTrades;

    /** Copied to {@code trade_config.no_of_parrellel_trades} (the typo is in that schema). */
    @Column(name = "no_of_parallel_trades", nullable = false)
    private Integer noOfParallelTrades;

    /**
     * Whether the detector may generate configs for this strategy.
     *
     * <p>Parks a strategy without deleting its block. A rule tagged with a
     * disabled strategy is skipped with a warning naming it — never silently.</p>
     */
    @Column(name = "auto_config_enabled", nullable = false)
    private Boolean autoConfigEnabled;

    /**
     * The fields that must match for two strategies to be able to share one
     * generated {@code trade_config}.
     *
     * <p>Deliberately excludes {@link #strategyId} and {@link #autoConfigEnabled}:
     * the first is what differs between strategies sharing a block, and the second
     * gates generation rather than describing the config. See
     * {@code EodDowntrendDetectionService.resolveConfigGroups}.</p>
     */
    public String configSignature() {
        return transactionType + "|" + lotQuantity + "|"
                + (maxLoss == null ? "-" : maxLoss.stripTrailingZeros().toPlainString()) + "|"
                + noOfTrades + "|" + noOfParallelTrades;
    }
}
