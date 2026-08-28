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

