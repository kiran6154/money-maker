package com.moneymaker.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

@Entity
@Table(name = "trade_config")
@Getter
@Setter
public class TradeConfig {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "trading_side")
    private String tradingSide;

    @Column(name = "trading_date")
    private LocalDate tradingDate;

    @Column(name = "target")
    private BigDecimal target;

    @Column(name = "stop_loss")
    private BigDecimal stopLoss;

    @ManyToOne
    @JoinColumn(name = "p_instrument")
    private Instrument instrument;

    @Column(name = "max_loss")
    private BigDecimal maxLoss;

    @Column(name = "option_depth")
    private Integer optionDepth;

    @Column(name = "transaction_type")
    private String transactionType;

    @Column(name = "lot_quantity")
    private Integer lotQuantity;

    @Column(name = "stratergy_id")
    private Integer stratergyId;

    /**
     * Every strategy that should scan this config, as ascending comma-separated
     * ids: {@code "1"}, {@code "1,2"}.
     *
     * <p>This is what lets one configuration be run by several strategies without
     * duplicating the row and its {@code sma_timeframe} children.
     * {@code TradeConfigScheduler} fans the config out into one
     * {@code TradeConfigCombinedDTO} per id, so dispatch still handles exactly one
     * strategy per DTO, and {@code (trade_config_id, strategy_id)} is the ledger
     * identity {@code OrderService} applies its caps against.</p>
     *
     * <p>Null or blank means "no tags" and resolves to {@link #stratergyId}, which
     * keeps every pre-existing config working unchanged.</p>
     *
     * <p><b>Parse and format only via {@code com.moneymaker.util.StrategyIds}.</b>
     * A comma-separated column is only sound while exactly one piece of code owns
     * its encoding. Replaced the {@code trade_config_strategy} child table in
     * changeset 035 — see that file for why the table was not worth its cost.</p>
     */
    @Column(name = "strategy_ids", length = 64)
    private String strategyIds;

    @Column(name = "no_of_trades")
    private Integer numberOfTradesPerDay;

    @Column(name = "no_of_parrellel_trades")
    private Integer numberOfParallelTrades;

    @Column(name = "itm_depth")
    private Integer itmDepth;

    @Column(name = "otm_depth")
    private Integer otmDepth;

    @Column(name = "atm_depth")
    private Integer atmDepth;

    /**
     * Lowest option premium this config will open a trade at, inclusive.
     * {@code null} = no lower bound.
     *
     * <p>Guards against entering legs so cheap that an absolute-points
     * {@code target} cannot physically be reached — selling a 6-point option
     * caps the gain at 6 — while the same {@code stopLoss} is several times the
     * premium. Evaluated at signal generation against that leg's premium at that
     * moment, not at strike-selection time, because a leg's premium moves
     * through the day.</p>
     */
    @Column(name = "min_option_price", precision = 12, scale = 4)
    private BigDecimal minOptionPrice;

    /**
     * Highest option premium this config will open a trade at, inclusive.
     * {@code null} = no upper bound.
     */
    @Column(name = "max_option_price", precision = 12, scale = 4)
    private BigDecimal maxOptionPrice;

    /**
     * Target as a fraction of the premium the trade opened at, e.g. {@code 0.2000}
     * = 20%. {@code null} = fall back to the absolute {@link #target} column.
     *
     * <p>Takes precedence over {@link #target} when set. {@code OrderService}
     * resolves it once at entry into {@code trade_order.target_at_entry}, so the
     * bracket is frozen per trade and {@code PositionService} keeps comparing a
     * plain points value.</p>
     *
     * <p>Exists because {@link #minOptionPrice}..{@link #maxOptionPrice} is a 3x
     * spread (80-250 as standing values) and one absolute points target cannot
     * serve both ends: it is a 12% move at the top of the band and a 38% move at
     * the bottom. See changeset 027 for the measured hit rates.</p>
     */
    @Column(name = "target_pct", precision = 6, scale = 4)
    private BigDecimal targetPct;

    /** Stop-loss as a fraction of entry premium. See {@link #targetPct}. */
    @Column(name = "sl_pct", precision = 6, scale = 4)
    private BigDecimal slPct;

    /**
     * Absolute ceiling, in premium points, on the stop-loss this config can
     * resolve to. The effective stop is {@code min(resolved, maxSlPoints)} —
     * whichever is lower. {@code null} = no ceiling.
     *
     * <p>Exists because {@link #slPct} is right about shape and wrong about
     * absolute exposure: 0.30 is a 24-point stop at the bottom of the 80-250
     * premium band and a 75-point stop at the top, but rupee risk is not a
     * function of the premium the leg happened to open at. The cap binds only at
     * the expensive end — see changeset 036 for the worked band.</p>
     *
     * <p>There is deliberately no matching cap on {@link #target}. A short
     * option's gain is bounded by the premium while its loss is not, and that
     * asymmetry is an argument for bounding the loss, not the gain.</p>
     *
     * <p>Applied once at entry by {@code OrderService}, so
     * {@code trade_order.stop_loss_at_entry} already carries the capped value
     * and {@code PositionService} needs no knowledge of the cap.</p>
     */
    @Column(name = "max_sl_points", precision = 12, scale = 4)
    private BigDecimal maxSlPoints;

    /**
     * Trailing stop-loss rungs as ascending {@code trigger:lock} pairs in
     * premium points: {@code "25:2,50:25,75:50"}. Null or blank = no trailing,
     * i.e. the fixed {@link #stopLoss} applies for the whole trade.
     *
     * <p><b>Parse and format only via {@code com.moneymaker.util.TrailLadder}</b>
     * — same one-owner rule as {@link #strategyIds}, and stricter, because a
     * silently dropped rung changes exits only on the trades nobody is watching.</p>
     *
     * <p>Latched off {@code trade_order.peak_profit}, so the ladder is a ratchet:
     * touching +50 fixes the +25 floor even if price falls back. Snapshotted onto
     * the order at entry like the rest of the bracket.</p>
     */
    @Column(name = "trail_ladder", length = 128)
    private String trailLadder;

    /**
     * Origin marker. {@code MANUAL} = inserted by hand (default). {@code AUTO_DOWNTREND}
     * = inserted by {@code EodDowntrendDetectionService} for the next trading day.
     * Used by the EOD generator to dedupe its own output across repeated backtest runs.
     */
    @Column(name = "source", nullable = false)
    private String source;

    /**
     * When this row was last written. Stamped automatically on every insert and
     * update — never set it by hand.
     *
     * <p>This is the axis the bulk-delete uses to undo a generation <i>run</i>. One
     * run of {@code EodDowntrendDetectionService} writes rows for several different
     * {@code tradingDate}s within a few seconds, so {@code tradingDate} cannot
     * identify a run while this can.</p>
     */
    @Column(name = "updated_date")
    private LocalDateTime updatedDate;

    @PrePersist
    @PreUpdate
    void stampUpdatedDate() {
        this.updatedDate = LocalDateTime.now();
    }
}

