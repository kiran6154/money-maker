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

    /**
     * Traded quantity for the bar. Nullable: the historical tables carry it, the
     * broker path does not supply it yet, and a null must stay distinguishable
     * from a genuine zero-volume bar.
     */
    @Column(name = "volume")
    private Long volume;

    /**
     * Open interest for the bar. Options only - the spot feed has none.
     *
     * <p>Carried because it is among the most informative inputs for a premium
     * SELLER: rising OI alongside a rising premium is fresh buying against the
     * position, while falling OI is unwinding. It was previously read from
     * historical_option_candles and then discarded, because this class had
     * nowhere to put it.
     */
    @Column(name = "open_interest")
    private Long openInterest;

    @Column(name = "sma_value20")
    private Double smaValue20;

    @Column(name = "sma_value50")
    private Double smaValue50;

    @Column(name = "sma_value100")
    private Double smaValue100;

    @Column(name = "sma_value200")
    private Double smaValue200;

    @Column(name = "sma_value500")
    private Double smaValue500;

    // ---- Runtime-computed trend flags (not persisted) ----
    @Transient
    private boolean sma20DownTrending;
    @Transient
    private boolean sma50DownTrending;
    @Transient
    private boolean sma100DownTrending;
    @Transient
    private boolean sma200DownTrending;
    @Transient
    private boolean sma500DownTrending;

    @Transient
    private boolean sma20UpTrending;
    @Transient
    private boolean sma50UpTrending;
    @Transient
    private boolean sma100UpTrending;
    @Transient
    private boolean sma200UpTrending;
    @Transient
    private boolean sma500UpTrending;
}