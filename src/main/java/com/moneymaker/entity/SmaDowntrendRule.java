package com.moneymaker.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalTime;

/**
 * Static rule that drives the end-of-day downtrend detector. One row per
 * {@code (strategy_id, underlying instrument)} the user wants monitored.
 *
 * <p>The detector internally walks the fixed SMA grid
 * {@code {50, 100, 200, 500} × {5min, 15min}} against the ATM strike
 * for both CE and PE. Anything that ends the day still down-trending
 * (per {@link #maxDeviation} starting at {@link #startTime}) becomes a
 * {@code sma_timeframe} row under a freshly inserted, next-day
 * {@code trade_config} stamped {@code source='AUTO_DOWNTREND'}.</p>
 *
 * <p>Trade_config fields that are strategy conventions —
 * {@code transactionType}, {@code lotQuantity}, {@code maxLoss},
 * {@code numberOfTradesPerDay}, {@code numberOfParallelTrades} — are picked
 * by the detector based on {@link #strategyId}. They do <b>not</b> live
 * here.</p>
 *
 * <p>{@link #minOptionPrice} / {@link #maxOptionPrice} are the exception: the
 * premium band gates whether a signal opens a trade at all, so it is a
 * trading-behaviour threshold and belongs in config rather than in a strategy
 * constant. The detector copies it verbatim onto each config it writes.</p>
 *
 * <p>See {@code docs/EOD_DOWNTREND.md} for the full pipeline.</p>
 */
@Entity
@Table(name = "sma_downtrend_rule")
@Getter
@Setter
public class SmaDowntrendRule {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "strategy_id", nullable = false)
    private Integer strategyId;

    @ManyToOne
    @JoinColumn(name = "instrument_id", nullable = false)
    private Instrument instrument;

    @Column(name = "max_deviation", nullable = false)
    private Integer maxDeviation;

    @Column(name = "start_time", nullable = false)
    private LocalTime startTime;

    @Column(name = "atr_periods", nullable = false)
    private Integer atrPeriods;

    @Column(name = "target_multiplier", nullable = false, precision = 10, scale = 4)
    private BigDecimal targetMultiplier;

    @Column(name = "sl_multiplier", nullable = false, precision = 10, scale = 4)
    private BigDecimal slMultiplier;

    /**
     * Target the detector stamps on each generated config, as a fraction of the
     * premium the trade opens at ({@code 0.2000} = 20%). Copied verbatim onto
     * {@code trade_config.target_pct}, which takes precedence over the absolute
     * {@code target} the {@link #targetMultiplier} block below computes.
     *
     * <p>This is the bracket that actually decides exits. The absolute column is
     * kept alongside it because {@code CommonRules.profitTarget} reads
     * {@code trade_config.target} as an SMA-separation gate at <i>entry</i> — a
     * different use of the same column — and because a config with no percentage
     * still needs a working points bracket.</p>
     *
     * <p>NOT NULL for the same reason the premium band is (changeset 026): a null
     * here silently reverts the generated config to the ATR points bracket, which
     * triggered on 3.6% of entries. See changeset 027.</p>
     */
    @Column(name = "target_pct", nullable = false, precision = 6, scale = 4)
    private BigDecimal targetPct;

    /** Stop-loss as a fraction of entry premium. See {@link #targetPct}. */
    @Column(name = "sl_pct", nullable = false, precision = 6, scale = 4)
    private BigDecimal slPct;

    /**
     * Ceiling in premium points on the stop-loss a generated config resolves to,
     * copied onto {@code trade_config.max_sl_points}. The effective stop is
     * {@code min(slPct * entry, maxSlPoints)}.
     *
     * <p>NOT NULL for the reason {@link #slPct} is: Hibernate writes every column
     * explicitly, so {@code trade_config}'s own default never reaches a generated
     * row, and a null would leave the whole AUTO_DOWNTREND fleet uncapped at the
     * expensive end of the premium band. See changeset 036.</p>
     */
    @Column(name = "max_sl_points", nullable = false, precision = 12, scale = 4)
    private BigDecimal maxSlPoints;

    /**
     * Trailing stop-loss rungs copied onto {@code trade_config.trail_ladder}, as
     * ascending {@code trigger:lock} pairs in premium points. Parsed only by
     * {@code com.moneymaker.util.TrailLadder}. NOT NULL — see {@link #maxSlPoints}.
     */
    @Column(name = "trail_ladder", nullable = false, length = 128)
    private String trailLadder;

    /**
     * Lowest premium a generated config will open a trade at, copied onto
     * {@code trade_config.min_option_price}. Defaults to the desk's standing
     * 80 (changeset 026), the same floor manual configs get.
     *
     * <p>NOT NULL by design: {@code AbstractSmaCrossStrategy.outsidePriceBand} reads a null bound
     * as <i>unbounded</i>, and an unbounded auto-generated config is what let
     * the detector open 6-point legs against a 30-point target.</p>
     */
    @Column(name = "min_option_price", nullable = false, precision = 12, scale = 4)
    private BigDecimal minOptionPrice;

    /** Highest premium a generated config will open a trade at. See {@link #minOptionPrice}. */
    @Column(name = "max_option_price", nullable = false, precision = 12, scale = 4)
    private BigDecimal maxOptionPrice;

    @Column(name = "enabled", nullable = false)
    private Boolean enabled;
}
