package com.moneymaker.entity;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;

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
     * Origin marker. {@code MANUAL} = inserted by hand (default). {@code AUTO_DOWNTREND}
     * = inserted by {@code EodDowntrendDetectionService} for the next trading day.
     * Used by the EOD generator to dedupe its own output across repeated backtest runs.
     */
    @Column(name = "source", nullable = false)
    private String source;
}

