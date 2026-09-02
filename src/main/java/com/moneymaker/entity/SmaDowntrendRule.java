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
 * <p>The detector walks this rule's own grid —
 * {@link #smaPeriods} × {@link #timeframesMinutes}, defaulting to
 * {@code {50, 100, 200, 500} × {5min, 15min}} (changeset 039) — against the
 * ATM strike for both CE and PE. Anything that ends the day still down-trending
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

    /**
     * Which SMA periods this rule checks, as a comma-separated list —
     * {@code "50,100,200,500"} (the default, matching the old hardcoded grid),
     * {@code "50,100"} to skip the long ones. Parsed only via
     * {@code com.moneymaker.util.IntCsv}; blank falls back to the default grid
     * (disable the rule with {@link #enabled}, not by blanking this).
     *
     * <p>Only {@code {20, 50, 100, 200, 500}} are computable: those are the
     * periods {@code MarketData} carries trend flags for and
     * {@code SmaTrendCalculator} tracks. A period outside that set is dropped
     * with a WARN, not silently trend-tested — adding a genuinely new period is
     * still a code change (flag fields + calculator). Note 20 is selectable here
     * for <i>detection</i>, but the strategies' own SMA-20 rule case is
     * commented out, so a config generated from a 20-period combo will not
     * trade until that case is re-enabled.</p>
     */
    @Column(name = "sma_periods", nullable = false, length = 64)
    private String smaPeriods;

    /**
     * Which candle timeframes this rule checks, as comma-separated minutes —
     * {@code "5,15"} (the default), {@code "5"} to skip 15-minute. Parsed only
     * via {@code IntCsv}; blank falls back to the default. The value feeds the
     * market-data fetch interval as {@code "<n>minute"}, so it must be an
     * interval the active data source serves.
     */
    @Column(name = "timeframes_minutes", nullable = false, length = 32)
    private String timeframesMinutes;

    /**
     * Which {@code EodTrendScanner} runs this rule's scan. {@code SMA_DOWNTREND}
     * (the default, and the only shipped scanner) is the SMA grid walk described
     * above. Adding a different indicator rule = implement
     * {@code com.moneymaker.tradeconfig.generation.EodTrendScanner} as a Spring
     * bean returning a new type name, then point rows here at it — the detector
     * discovers scanners by injection and needs no change. An unknown value
     * skips the rule with a WARN naming the registered types.
     */
    @Column(name = "indicator_type", nullable = false, length = 32)
    private String indicatorType;
}
