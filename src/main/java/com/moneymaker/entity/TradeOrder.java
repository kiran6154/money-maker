package com.moneymaker.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDateTime;

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

    /** Why the trade was closed: SIGNAL / TARGET / STOP_LOSS / FORCE_CLOSE. */
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
     * Lot quantity snapshotted from {@code TradeConfig.lotQuantity} at order
     * open (M4.1). Used by {@code DaySummaryScheduler} to compute rupee P&L
     * (per-share profit × lot_quantity_at_entry). Snapshotted so a mid-day
     * config edit can't retroactively change historical rupee figures.
     * Default 0 means "not set" — DaySummary skips the rupee multiplication
     * for those rows, falling back to per-share P&L only.
     */
    @Column(name = "lot_quantity_at_entry", nullable = false)
    private Integer lotQuantityAtEntry = 0;
}
