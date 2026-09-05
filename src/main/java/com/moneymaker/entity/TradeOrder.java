package com.moneymaker.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.LocalTime;

@Entity
@Table(name = "trade_order")
@Getter
@Setter
public class TradeOrder {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "trade_config_id", nullable = false)
    private Integer tradeConfigId;

    /** e.g. "NIFTY" */
    @Column(name = "instrument_name", length = 100)
    private String instrumentName;

    /** Underlying instrument token (e.g. 256265). */
    @Column(name = "instrument_token", nullable = false, length = 100)
    private String instrumentToken;

    /** e.g. 24000 */
    @Column(name = "option_strike")
    private Integer optionStrike;

    /** CE or PE */
    @Column(name = "option_type", length = 4)
    private String optionType;

    /** Option-leg instrument token. */
    @Column(name = "option_token", length = 100)
    private String optionToken;

    /** Side of the leg at entry: BUY or SELL. */
    @Column(name = "entry_direction", nullable = false, length = 8)
    private String entryDirection;

    @Column(name = "entry_time", nullable = false)
    private LocalDateTime entryTime;

    @Column(name = "entry_price", nullable = false, precision = 12, scale = 4)
    private BigDecimal entryPrice;

    @Column(name = "exit_time")
    private LocalDateTime exitTime;

    @Column(name = "exit_price", precision = 12, scale = 4)
    private BigDecimal exitPrice;

    /** Per-share P&L. exit-side mathematics handled by OrderService. */
    @Column(name = "profit", precision = 12, scale = 4)
    private BigDecimal profit;

    /** OPEN or CLOSED. */
    @Column(name = "status", nullable = false, length = 16)
    private String status;

    /** Broker-side order id for the entry leg (null in backtest). */
    @Column(name = "entry_broker_order_id", length = 64)
    private String entryBrokerOrderId;

    /** Broker-side order id for the exit leg (null until closed / in backtest). */
    @Column(name = "exit_broker_order_id", length = 64)
    private String exitBrokerOrderId;

    /**
     * Fill state of the most recently placed leg:
     * {@code PENDING}, {@code COMPLETE}, {@code REJECTED}, {@code CANCELLED}, or {@code BACKTEST}.
     */
    @Column(name = "fill_status", length = 16)
    private String fillStatus;

    // -------- Position-monitor fields (updated each PositionScheduler tick while OPEN) --------

    /** Highest unrealised per-share profit observed during the trade's lifetime. */
    @Column(name = "peak_profit", precision = 12, scale = 4)
    private BigDecimal peakProfit;

    /** Lowest (most-negative) unrealised per-share P&L observed during the trade. */
    @Column(name = "peak_loss", precision = 12, scale = 4)
    private BigDecimal peakLoss;

    /** Most recent quoted price seen by the monitor. */
    @Column(name = "last_monitored_price", precision = 12, scale = 4)
    private BigDecimal lastMonitoredPrice;

    /** When the monitor last touched this row. */
    @Column(name = "last_monitored_at")
    private LocalDateTime lastMonitoredAt;

    /**
     * Why the trade was closed: SIGNAL / TARGET / STOP_LOSS / TRAIL_SL /
     * FORCE_CLOSE. {@code TRAIL_SL} is the trailing floor (changeset 036) and is
     * kept distinct from {@code STOP_LOSS} because it is the opposite outcome —
     * a trailed exit closes green, the fixed stop closes red.
     */
    @Column(name = "exit_reason", length = 32)
    private String exitReason;

    /**
     * Which rule fired at entry — e.g. {@code "5min/SMA50"}. Snapshotted from
     * the triggering {@link com.moneymaker.dto.TradeSignal} so the ledger and
     * the order Telegram alert can show the trigger without re-deriving it.
     */
    @Column(name = "entry_reason", length = 64)
    private String entryReason;

    /**
     * Strategy id that owned the entry (e.g. 1 = Strategy1). Snapshotted from
     * {@code TradeConfig.stratergyId} at open so a config edit / re-mapping
     * later in the day can't change the historical attribution.
     */
    @Column(name = "strategy_id")
    private Integer strategyId;

    /**
     * Order quantity in units (75 = one NIFTY lot), snapshotted from
     * {@code TradeConfig.lotQuantity} at open.
     *
     * <p>Snapshotted for the same reason the bracket below is: it is what the
     * broker order actually carried, and editing the config's lot size later must
     * not restate historical trades. Before changeset 029 it was not persisted at
     * all, which meant rupee P&L could not be derived from the ledger.
     *
     * <p>Null on rows written before 029 — {@code TradeChargeService} reports
     * those as uncosted rather than assuming a lot size.
     */
    @Column(name = "quantity")
    private Integer quantity;

    /**
     * Per-share profit target snapshotted from {@code TradeConfig.target} at the
     * moment this trade was opened. Used by {@code PositionService} so a config
     * edit mid-trade can't retroactively close already-open positions.
     */
    @Column(name = "target_at_entry", precision = 12, scale = 4)
    private BigDecimal targetAtEntry;

    /**
     * Per-share stop-loss snapshotted from {@code TradeConfig.stopLoss} at order
     * open. Stored as a positive number; threshold breach = {@code pnl <= -stopLossAtEntry}.
     */
    @Column(name = "stop_loss_at_entry", precision = 12, scale = 4)
    private BigDecimal stopLossAtEntry;

    /**
     * Trailing ladder snapshotted from {@code TradeConfig.trailLadder} at open,
     * already canonicalised by {@code TrailLadder.canonical}. Null = this trade
     * does not trail.
     *
     * <p>Snapshotted for the same reason the bracket above is: editing a ladder
     * at 13:00 must not re-floor a trade that opened at 09:20.</p>
     */
    @Column(name = "trail_ladder_at_entry", length = 128)
    private String trailLadderAtEntry;

    /**
     * The currently latched trailing floor in signed premium points — {@code +2}
     * is a stop two points into profit. Null until the first rung is reached.
     *
     * <p>Written by {@code PositionService} as a ratchet: it only ever moves up,
     * so it records the best floor the trade earned, and survives on a closed row
     * as the explanation for a {@code TRAIL_SL} exit.</p>
     */
    @Column(name = "trail_sl_at", precision = 12, scale = 4)
    private BigDecimal trailSlAt;

    /**
     * Minutes from {@link #entryTime} after which this trade is closed with
     * {@code exit_reason = TIME_STOP}. {@code null} = no time stop, which is
     * every row written before changeset 043 and every config that does not set
     * {@code trade_config.max_hold_minutes}.
     *
     * <p>Snapshotted at entry for the same two reasons the bracket above is:
     * {@code PositionService} must not depend on the config caches still being
     * populated after a mid-session restart, and shortening the config's hold
     * limit at 13:00 must not instantly breach — and liquidate — every position
     * opened before 12:00.</p>
     */
    @Column(name = "max_hold_minutes_at_entry")
    private Integer maxHoldMinutesAtEntry;

    /**
     * Time-of-day at which this trade is closed regardless of P&amp;L, with
     * {@code exit_reason = FLATTEN}. {@code null} = no intraday flatten.
     *
     * <p>A time-of-day and not a timestamp: the trade carries its own
     * {@link #entryTime}, these are intraday strategies, and the end-of-day
     * sweep squares off the same session — so the date is never ambiguous and a
     * full timestamp would only admit rows whose flatten moment sits on a
     * different day from their entry.</p>
     *
     * <p>Distinct from {@code FORCE_CLOSE}, which is the replay's own 15:20
     * end-of-day sweep and means "the run ended with this still open". A
     * strategy that flattens on its own clock and one that had to be cleaned up
     * after are not the same result.</p>
     */
    @Column(name = "flatten_at_entry")
    private LocalTime flattenAtEntry;
}
