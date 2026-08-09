package com.moneymaker.repository;

import com.moneymaker.entity.MarketData;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

/**
 * Spring Data repository for the {@code market_data} table — the OHLC ledger
 * used by both the index and per-option historical store.
 *
 * <p>Bulk option downloads (see {@code OptionsBulkDownloadService}) re-run
 * idempotently by deleting any existing rows for the same
 * {@code (instrumenttoken, timestamp-range)} before inserting the fresh fetch.
 */
@Repository
public interface MarketDataRepository extends JpaRepository<MarketData, Integer> {

    long deleteByInstrumenttokenAndTimestampBetween(
            String instrumenttoken, LocalDateTime fromInclusive, LocalDateTime toInclusive);

    List<MarketData> findByInstrumenttokenAndTimestampBetween(
            String instrumenttoken, LocalDateTime fromInclusive, LocalDateTime toInclusive);

    /**
     * Reads one trading day's 5-minute base candles for a single instrument
     * token, ordered oldest first so higher layers can compute reference price
     * and aggregate 10m / 15m buckets deterministically.
     */
    @Query("""
        SELECT m
        FROM MarketData m
        WHERE m.instrumenttoken = :instrumentToken
          AND FUNCTION('DATE', m.timestamp) = :tradingDate
        ORDER BY m.timestamp ASC
    """)
    List<MarketData> findCandlesForDate(
            @Param("instrumentToken") String instrumentToken,
            @Param("tradingDate") LocalDate tradingDate);

    /**
     * Reads the most recent 5-minute candles up to and including the supplied
     * timestamp. Used by the chart dashboard to build runtime SMA values from
     * prior-day lookback candles before filtering back down to the selected
     * trading date.
     */
    @Query("""
        SELECT m
        FROM MarketData m
        WHERE m.instrumenttoken = :instrumentToken
          AND m.timestamp <= :toInclusive
        ORDER BY m.timestamp DESC
    """)
    List<MarketData> findRecentCandlesUpTo(
            @Param("instrumentToken") String instrumentToken,
            @Param("toInclusive") LocalDateTime toInclusive,
            Pageable pageable);
}
