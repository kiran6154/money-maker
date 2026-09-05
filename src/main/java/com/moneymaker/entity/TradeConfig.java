package com.moneymaker.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;

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

    /**
     * Caps OPEN trades per option <b>side</b> (CE / PE) for this
     * (config, strategy), regardless of strike — the second parallel-trades
     * variant (user decision 2026-08-31): with the default 1, one CE and one
     * PE may run concurrently but never two CE. {@code numberOfParallelTrades}
     * above stays the total/direction cap. Initialised to 1 so entity inserts
     * satisfy the NOT NULL column and new configs get the safe default.
     */
    @Column(name = "max_parallel_per_side")
    private Integer maxParallelPerSide = 1;

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
     * Whether this config still runs. {@code false} retires it: it keeps its id,
     * its history and its {@code trade_order} rows, but
     * {@code fetchCombinedByTradingDate} stops returning it, so no strategy scans
     * it and no new trade opens against it (changeset 037, GAPS #7).
     *
     * <p>Exists because a config that has ever traded cannot be hard-deleted —
     * the ledger references it — and the only previous way to stop one was to
     * move its {@code tradingDate} into the past, which falsifies the record of
     * what the config was for.</p>
     *
     * <p><b>Retiring does not close open trades.</b> Positions already on the
     * books keep being monitored to their own exit: {@code PositionService} walks
     * {@code trade_order} rows, not configs, and the bracket it applies was
     * snapshotted at entry. Retire means "open nothing further", not "abandon
     * what is open".</p>
     *
     * <p>Defaulted to {@code TRUE} in the field, not only in the DB: Hibernate
     * names every column in its INSERT, so a null field is written as an explicit
     * NULL and the column default never fires — the same trap that made
     * {@link #source} break every create through {@code TradeConfigAdminService}.</p>
     */
    @Column(name = "is_active", nullable = false)
    private Boolean isActive = Boolean.TRUE;

    // ------------------------------------------------------------------
    // Changeset 042 — the intraday clock, the exact-offset strike, and the
    // book id. Added for Strategy 5 (Pressure); see docs/PRESSURE_STRATEGY.md.
    //
    // Every field below is nullable (or defaults to FALSE) and every consumer
    // reads null as "the rule that applied before 042", so a config that sets
    // none of them behaves exactly as it did before. That is what keeps
    // strategies 1-4 bit-identical, and it is asserted by
    // PressureConfigColumnsAreOptionalTest.
    // ------------------------------------------------------------------

    /**
     * Earliest time-of-day at which a NEW entry may open, inclusive.
     * {@code null} = no lower bound, which is how every config behaved before
     * changeset 042.
     *
     * <p>Applies to entries only. An exit — target, stop, trail, time stop,
     * flatten — is never gated on this, because a window that could strand an
     * open position past its own stop-loss would be a risk control that creates
     * risk.</p>
     */
    @Column(name = "entry_from")
    private LocalTime entryFrom;

    /**
     * Latest time-of-day at which a NEW entry may open, inclusive.
     * {@code null} = no upper bound. See {@link #entryFrom}.
     */
    @Column(name = "entry_to")
    private LocalTime entryTo;

    /**
     * Maximum minutes a position may stay OPEN, measured from
     * {@code trade_order.entry_time}. {@code null} = no time stop, which is how
     * every config behaved before changeset 042.
     *
     * <p>Enforced by {@code PositionService}, which closes the trade with
     * {@code exit_reason = TIME_STOP} at the first monitored bar at or after the
     * deadline. Snapshotted onto the order at entry like the rest of the
     * bracket, so editing it mid-session cannot re-time trades already open.</p>
     */
    @Column(name = "max_hold_minutes")
    private Integer maxHoldMinutes;

    /**
     * Time-of-day at which any still-OPEN position of this config is closed
     * regardless of P&amp;L, with {@code exit_reason = FLATTEN}. {@code null} =
     * no intraday flatten.
     *
     * <p>Deliberately distinct from the two close-time mechanisms that already
     * exist. {@code CommonRules.isMarketCloseTime} (15:15) emits a <i>signal</i>
     * a strategy may act on, and the replay's {@code forceCloseOpenPositions}
     * sweep (15:20) runs only after the day's last tick. This one is a
     * position-level rule needing no strategy cooperation — which is what
     * Strategy 5 requires, since it emits entries only and has no exit
     * signal at all.</p>
     */
    @Column(name = "flatten_at")
    private LocalTime flattenAt;

    /**
     * Signed distance from ATM, in index points, identifying the single contract
     * this config trades. {@code null} = keep the {@link #itmDepth} /
     * {@link #otmDepth} strike-<i>set</i> expansion.
     *
     * <pre>
     *   &gt; 0   ITM by that many points     CE = ATM - offset,  PE = ATM + offset
     *   = 0   ATM
     *   &lt; 0   OTM by that many points
     * </pre>
     *
     * <p>The depth columns are counts of strike steps that expand into a set of
     * legs which {@code AbstractSmaCrossStrategy} then ranks by premium. Pressure
     * needs one exact contract instead, so this is expressed in points and
     * resolves to a single strike — see {@code OffsetStrikeSelector}.</p>
     */
    @Column(name = "strike_offset_points")
    private Integer strikeOffsetPoints;

    /**
     * The strike grid this config addresses, in index points. {@code null} =
     * fall back to {@code instrument.strike_points}.
     *
     * <p>Exists because those two disagree for NIFTY and both are right for
     * their own consumer: {@code instrument.strike_points} is 100, while the
     * imported {@code historical_option_candles} are on a 50-point grid. Editing
     * the instrument row would move every strike strategies 1-4 pick on
     * historical replay — a Rule 0 behaviour change needing its own measured
     * before/after — so the config carries its own step instead and the shared
     * row stays untouched.</p>
     */
    @Column(name = "strike_step_points")
    private Integer strikeStepPoints;

    /**
     * Comparison-bucket label shared by the configs that together make up one
     * book, e.g. {@code "SELL_ITM300"}. {@code null} = no book, and the
     * cross-config cap below does not apply.
     *
     * <p>What it buys: a book that sells CE on down-pressure and PE on
     * up-pressure is <b>two</b> configs, because {@code trading_side} is
     * single-valued. Every cap in {@code OrderService} keys on
     * {@code (trade_config_id, strategy_id)}, so those two configs hold two
     * independent budgets and could run a CE short and a PE short at the same
     * moment. Pressure allows exactly one position at a time across the whole
     * book, and this label is what lets the cap count across both legs.</p>
     *
     * <p>Deliberately a plain string and not a foreign key: a book is a bucket
     * in a measurement run, not a durable domain entity, and a shared label is
     * exactly enough to group by.</p>
     */
    @Column(name = "book_id", length = 32)
    private String bookId;

    /**
     * Whether this config trades the <b>underlying itself</b> rather than an
     * option leg. {@code false} (the default) is every config that has ever
     * existed.
     *
     * <p>{@code true} is the Pressure SPOT baseline book: same signals, same
     * clock, same brackets, but entry and exit are priced in index points off
     * {@code historical_spot_candles} instead of off a premium. It is the row
     * that separates "how good is the signal" from "how good are the option
     * mechanics".</p>
     *
     * <p>Not folded into {@code trading_side} as a third value, because
     * {@code resolveOptionType} in both {@code AnalysisScheduler} and
     * {@code AbstractSmaCrossStrategy} derives CE/PE from that column and reads
     * anything else as "fetch nothing" — a spot config would look like a broken
     * option config to two shared code paths. An explicit flag keeps the branch
     * visible at every call site.</p>
     *
     * <p>Defaulted in the field, not only in the DB, for the reason spelled out
     * on {@link #isActive}: Hibernate names every column in its INSERT, so a
     * null field is written as an explicit NULL and the column default never
     * fires.</p>
     */
    @Column(name = "underlying_leg", nullable = false)
    private Boolean underlyingLeg = Boolean.FALSE;

    /** Null-safe read — a pre-042 in-memory instance behaves as "trades an option". */
    public boolean tradesUnderlyingLeg() {
        return Boolean.TRUE.equals(underlyingLeg);
    }

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

