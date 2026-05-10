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
}
