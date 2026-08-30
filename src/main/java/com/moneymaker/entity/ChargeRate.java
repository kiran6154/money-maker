package com.moneymaker.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * One brokerage / statutory charge rate, effective from a date.
 *
 * <p>Rates are versioned rather than configured as flat properties because they
 * change, and a backtest routinely spans a change: STT on option selling went
 * from 0.0625% to 0.1% of premium on 2024-10-01, and the NSE options transaction
 * charge was revised the same day. Costing a January trade with October's rates
 * (or vice-versa) misstates exactly the leg that dominates option selling.
 *
 * <p>{@link #value} is a <b>fraction</b> for the {@code *_PCT} types
 * ({@code 0.001} = 0.1%) and an absolute rupee amount for
 * {@code BROKERAGE_FLAT_PER_ORDER}.
 *
 * <p>The seeded rows are documented, unverified defaults — see changeset
 * {@code 029}. Correcting them is an {@code UPDATE}, not a code change.
 */
@Entity
@Table(name = "charge_rate")
@Getter
@Setter
public class ChargeRate {

    /** Flat rupee amount charged per executed order, capped against the pct below. */
    public static final String BROKERAGE_FLAT_PER_ORDER = "BROKERAGE_FLAT_PER_ORDER";
    /** Brokerage as a fraction of that leg's turnover; the lower of the two applies. */
    public static final String BROKERAGE_PCT_OF_TURNOVER = "BROKERAGE_PCT_OF_TURNOVER";
    /** Securities transaction tax, sell leg only for options. */
    public static final String STT_SELL_PCT = "STT_SELL_PCT";
    /** Exchange transaction charge, both legs. */
    public static final String EXCHANGE_TXN_PCT = "EXCHANGE_TXN_PCT";
    /** SEBI turnover fee, both legs. */
    public static final String SEBI_PCT = "SEBI_PCT";
    /** Stamp duty, buy leg only. */
    public static final String STAMP_DUTY_BUY_PCT = "STAMP_DUTY_BUY_PCT";
    /** GST, applied to brokerage + exchange transaction + SEBI. */
    public static final String GST_PCT = "GST_PCT";

    /** The only segment modelled today. */
    public static final String SEGMENT_NFO_OPT = "NFO_OPT";

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "charge_type", nullable = false, length = 48)
    private String chargeType;

    @Column(nullable = false, length = 24)
    private String segment;

    @Column(name = "effective_from", nullable = false)
    private LocalDate effectiveFrom;

    @Column(name = "value", nullable = false, precision = 16, scale = 10)
    private BigDecimal value;

    @Column(length = 255)
    private String notes;
}
