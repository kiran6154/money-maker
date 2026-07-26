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
 * {@code {20, 50, 100, 200, 500} × {5min, 15min}} against the ATM strike
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

    @Column(name = "enabled", nullable = false)
    private Boolean enabled;
}
