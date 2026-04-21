package com.moneymaker.entity;


import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import lombok.Getter;
import lombok.Setter;

import java.math.BigDecimal;


@Entity
@Table(name = "instrument_details")
@Getter
@Setter
public class InstrumentDetails {

    @Id
    @Column(name = "instrument_token")
    private Integer instrumentToken;

    @Column(name = "exchange_token", nullable = false)
    private Integer exchangeToken;

    @Column(name = "tradingsymbol", nullable = false)
    private String tradingSymbol;

    @Column(name = "name", nullable = false)
    private String name;

    @Column(name = "last_price", nullable = false)
    private BigDecimal lastPrice;

    @Column(name = "expiry", nullable = false)
    private String expiry;

    @Column(name = "strike", nullable = false)
    private BigDecimal strike;

    @Column(name = "tick_size", nullable = false)
    private BigDecimal tickSize;

    @Column(name = "lot_size", nullable = false)
    private BigDecimal lotSize;

    @Column(name = "instrument_type", nullable = false)
    private String instrumentType;

    @Column(name = "segment", nullable = false)
    private String segment;

    @Column(name = "exchange", nullable = false)
    private String exchange;


}
