package com.moneymaker.entity;



import jakarta.persistence.*;
import lombok.Getter;
import lombok.Setter;

@Entity
@Table(name = "sma_timeframe")
@Getter
@Setter
public class SmaTimeframe {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "time_period")
    private Integer timePeriod;

    @Column(name = "sma")
    private Integer sma;

    @ManyToOne
    @JoinColumn(name = "tc_id", referencedColumnName = "id")
    private TradeConfig tradeConfig;

    @Column(name = "slope")
    private Double slope;
}