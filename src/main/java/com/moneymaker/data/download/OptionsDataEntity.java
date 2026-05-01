package com.moneymaker.data.download;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * Persistent record of options data for NIFTY and BANKNIFTY.
 */
@Entity
@Table(name = "options_data")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class OptionsDataEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "symbol", nullable = false, length = 20)
    private String symbol; // NIFTY or BANKNIFTY

    @Column(name = "strike", nullable = false, precision = 10, scale = 2)
    private BigDecimal strike;

    @Column(name = "expiry", nullable = false, length = 20)
    private String expiry;

    @Column(name = "type", nullable = false, length = 2)
    private String type; // CE or PE

    @Column(name = "data_date", nullable = false)
    private LocalDate dataDate;

    @Column(name = "last_price", nullable = false, precision = 10, scale = 2)
    private BigDecimal lastPrice;

    @Column(name = "oi", nullable = false)
    private Integer oi;

    @Column(name = "volume", nullable = false)
    private Integer volume;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;
}
