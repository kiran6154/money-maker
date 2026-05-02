package com.moneymaker.entity;


import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDateTime;

@Entity
@Table(name = "market_data")
@Getter
@Setter
public class MarketData {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(nullable = false)
    private LocalDateTime timestamp;

    @Column(nullable = false, precision = 10, scale = 2)
    private BigDecimal open;

    @Column(nullable = false, precision = 10, scale = 2)
    private BigDecimal high;

    @Column(nullable = false, precision = 10, scale = 2)
    private BigDecimal low;

    @Column(nullable = false, precision = 10, scale = 2)
    private BigDecimal close;

    @Column(name = "instrumenttoken", nullable = false, length = 100)
    private String instrumenttoken;

    @Column(name = "sma_value50")
    private Double smaValue50;

    @Column(name = "sma_value100")
    private Double smaValue100;

    @Column(name = "sma_value200")
    private Double smaValue200;

    @Column(name = "sma_value500")
    private Double smaValue500;
}