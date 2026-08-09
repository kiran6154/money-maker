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
import java.time.LocalDateTime;

@Entity
@Table(name = "historical_option_candles")
@Getter
@Setter
public class HistoricalOptionCandle {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "datetime", nullable = false)
    private LocalDateTime dateTime;

    @Column(name = "stock_code", nullable = false, length = 50)
    private String stockCode;

    @Column(name = "exchange_code", nullable = false, length = 20)
    private String exchangeCode;

    @Column(name = "expiry_date", nullable = false)
    private LocalDate expiryDate;

    @Column(name = "strike_price", nullable = false, precision = 12, scale = 4)
    private BigDecimal strikePrice;

    @Column(name = "option_right", nullable = false, length = 2)
    private String optionRight;

    @Column(nullable = false, precision = 12, scale = 4)
    private BigDecimal open;

    @Column(nullable = false, precision = 12, scale = 4)
    private BigDecimal high;

    @Column(nullable = false, precision = 12, scale = 4)
    private BigDecimal low;

    @Column(nullable = false, precision = 12, scale = 4)
    private BigDecimal close;

    @Column
    private Long volume;

    @Column(name = "open_interest")
    private Long openInterest;
}
