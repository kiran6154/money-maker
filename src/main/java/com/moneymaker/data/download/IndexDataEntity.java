package com.moneymaker.data.download;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * Persistent OHLC candle for an index (e.g. NIFTY 50, NIFTY BANK) downloaded
 * via {@link IndexDataDownloadService}. Indices carry no volume/OI, so only
 * the candle OHLC is stored.
 */
@Entity
@Table(name = "index_data")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class IndexDataEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Integer id;

    @Column(name = "symbol", nullable = false, length = 50)
    private String symbol; // Kite tradingsymbol, e.g. "NIFTY 50"

    @Column(name = "instrument_token", nullable = false, length = 100)
    private String instrumentToken;

    @Column(name = "timeframe", nullable = false, length = 20)
    private String timeframe; // Kite interval, e.g. "5minute"

    @Column(name = "timestamp", nullable = false)
    private LocalDateTime timestamp;

    @Column(name = "open", nullable = false, precision = 10, scale = 2)
    private BigDecimal open;

    @Column(name = "high", nullable = false, precision = 10, scale = 2)
    private BigDecimal high;

    @Column(name = "low", nullable = false, precision = 10, scale = 2)
    private BigDecimal low;

    @Column(name = "close", nullable = false, precision = 10, scale = 2)
    private BigDecimal close;

    @Column(name = "created_at", nullable = false)
    private LocalDateTime createdAt;
}
