package com.moneymaker.entity;

import com.moneymaker.util.BracketMode;
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
     * Whether this strategy's generated config trades the <b>opposite</b> leg of
     * the one the trend was detected on (changeset 040).
     *
     * <p>{@code false} (the default) keeps the detected-side behaviour every
     * sell-side strategy wants: PE downtrending → a PE config. {@code true} is
     * the mirror-trade shape {@code Strategy3} needs — the day the PE ends in a
     * downtrend (index rising) is the day it wants a <i>CE BUY</i> config, so
     * that at the market moment strategy 1 sells the PE, strategy 3 buys the
     * CE. The generated config's bracket basis is then measured on the leg it
     * will actually trade, not the detected one.</p>
     */
    @Column(name = "opposite_side", nullable = false)
    private Boolean oppositeSide;

    /**
     * Which bracket column this strategy's trades take their profit target from:
     * {@code POINTS} = {@code trade_config.target}, {@code PERCENT} =
     * {@code target_pct} x entry premium. See changeset 041.
     *
     * <p>Read it through {@link #targetMode()} rather than directly — that is
     * what turns the stored string into a {@link BracketMode} and what treats a
     * missing value as the legacy {@code PERCENT} rule.</p>
     */
    @Column(name = "target_mode", nullable = false, length = 8)
    private String targetMode;

    /** Stop-loss side of {@link #targetMode}: {@code stop_loss} vs {@code sl_pct}. */
    @Column(name = "sl_mode", nullable = false, length = 8)
    private String slMode;

    /**
     * Changeset 048. When set, every trade this strategy opens trails on a
     * chandelier stop at {@code trail_atr_multiple × ATR} of the signal bar
     * (frozen onto {@code trade_order.trail_atr_distance_at_entry}) instead of
     * the config's ladder. Null = ladder / fixed stop, as before.
     */
    @Column(name = "trail_atr_multiple", precision = 6, scale = 2)
    private BigDecimal trailAtrMultiple;

    /** Null-safe read — a pre-040 in-memory instance behaves as "detected side". */
    public boolean tradesOppositeSide() {
        return Boolean.TRUE.equals(oppositeSide);
    }

    /**
     * The profit-target bracket this strategy exits on, defaulting to the legacy
     * {@code PERCENT} rule when the column is unset.
     *
     * @throws IllegalArgumentException if the column holds an unrecognised value
     */
    public BracketMode targetMode() {
        return BracketMode.parse(targetMode);
    }

    /**
     * The stop-loss bracket this strategy exits on. See {@link #targetMode()}.
     *
     * @throws IllegalArgumentException if the column holds an unrecognised value
     */
    public BracketMode slMode() {
        return BracketMode.parse(slMode);
    }

    /**
     * The fields that must match for two strategies to be able to share one
     * generated {@code trade_config}.
     *
     * <p>Deliberately excludes {@link #strategyId} and {@link #autoConfigEnabled}:
     * the first is what differs between strategies sharing a block, and the second
     * gates generation rather than describing the config. {@link #oppositeSide}
     * is included — a flipped and an unflipped strategy write configs for
     * different legs and must never share a row. See
     * {@code EodDowntrendDetectionService.resolveConfigGroups}.</p>
     * <p>{@code target_mode} / {@code sl_mode} (041) are deliberately excluded,
     * which is the opposite call to {@link #oppositeSide} above. They change how
     * an already-generated config is *read* at order time, not what the generated
     * row contains — every row carries both the points and the percentage columns
     * regardless — so two strategies differing only in bracket mode can share one
     * config and still exit differently. Splitting them would emit a duplicate row
     * that differs in nothing.</p>
     */
    public String configSignature() {
        return transactionType + "|" + lotQuantity + "|"
                + (maxLoss == null ? "-" : maxLoss.stripTrailingZeros().toPlainString()) + "|"
                + noOfTrades + "|" + noOfParallelTrades + "|"
                + tradesOppositeSide();
    }
}
