package com.moneymaker.repository;

import com.moneymaker.entity.HistoricalOptionCandle;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface HistoricalOptionCandleRepository extends JpaRepository<HistoricalOptionCandle, Integer> {

    @Query("""
        SELECT DISTINCT c.expiryDate
        FROM HistoricalOptionCandle c
        WHERE UPPER(c.stockCode) = UPPER(:stockCode)
          AND UPPER(c.exchangeCode) = UPPER(:exchangeCode)
          AND c.expiryDate >= :selectedDate
        ORDER BY c.expiryDate ASC
    """)
    List<LocalDate> findAvailableExpiriesOnOrAfter(
            @Param("stockCode") String stockCode,
            @Param("exchangeCode") String exchangeCode,
            @Param("selectedDate") LocalDate selectedDate);

    @Query("""
        SELECT c
        FROM HistoricalOptionCandle c
        WHERE UPPER(c.stockCode) = UPPER(:stockCode)
          AND UPPER(c.exchangeCode) = UPPER(:exchangeCode)
          AND c.expiryDate = :expiryDate
          AND c.strikePrice = :strikePrice
          AND UPPER(c.optionRight) = UPPER(:optionRight)
          AND c.dateTime <= :toInclusive
        ORDER BY c.dateTime DESC
    """)
    List<HistoricalOptionCandle> findRecentCandlesUpTo(
            @Param("stockCode") String stockCode,
            @Param("exchangeCode") String exchangeCode,
            @Param("expiryDate") LocalDate expiryDate,
            @Param("strikePrice") BigDecimal strikePrice,
            @Param("optionRight") String optionRight,
            @Param("toInclusive") LocalDateTime toInclusive,
            Pageable pageable);

    Optional<HistoricalOptionCandle> findByStockCodeIgnoreCaseAndExchangeCodeIgnoreCaseAndExpiryDateAndStrikePriceAndOptionRightIgnoreCaseAndDateTime(
            String stockCode,
            String exchangeCode,
            LocalDate expiryDate,
            BigDecimal strikePrice,
            String optionRight,
            LocalDateTime dateTime);

    /**
     * Ascending candle range for one option series. Backs the DB-backed backtest
     * market-data provider.
     *
     * <p>Ascending order is load-bearing: {@code BacktestMarketDataCache.slice}
     * stops at the first candle after its upper bound, and {@code Strategy1}
     * treats {@code list.get(size - 1)} as the latest candle.
     *
     * <p>{@code strikePrice} is compared numerically, so a {@code 21700} literal
     * matches a stored {@code 21700.0000}.
     */
    @Query("""
        SELECT c
        FROM HistoricalOptionCandle c
        WHERE UPPER(c.stockCode) = UPPER(:stockCode)
          AND UPPER(c.exchangeCode) = UPPER(:exchangeCode)
          AND c.expiryDate = :expiryDate
          AND c.strikePrice = :strikePrice
          AND UPPER(c.optionRight) = UPPER(:optionRight)
          AND c.dateTime >= :from
          AND c.dateTime <= :to
        ORDER BY c.dateTime ASC
    """)
    List<HistoricalOptionCandle> findRangeAsc(
            @Param("stockCode") String stockCode,
            @Param("exchangeCode") String exchangeCode,
            @Param("expiryDate") LocalDate expiryDate,
            @Param("strikePrice") BigDecimal strikePrice,
            @Param("optionRight") String optionRight,
            @Param("from") LocalDateTime from,
            @Param("to") LocalDateTime to);

    /**
     * Distinct strikes that actually have candles for one expiry and side.
     * Backs the dashboard's strike picker, so the list can only ever offer
     * strikes the chart can really draw.
     */
    @Query("""
        SELECT DISTINCT c.strikePrice
        FROM HistoricalOptionCandle c
        WHERE UPPER(c.stockCode) = UPPER(:stockCode)
          AND UPPER(c.exchangeCode) = UPPER(:exchangeCode)
          AND c.expiryDate = :expiryDate
          AND UPPER(c.optionRight) = UPPER(:optionRight)
        ORDER BY c.strikePrice ASC
    """)
    List<BigDecimal> findAvailableStrikes(
            @Param("stockCode") String stockCode,
            @Param("exchangeCode") String exchangeCode,
            @Param("expiryDate") LocalDate expiryDate,
            @Param("optionRight") String optionRight);

    /**
     * All rows of a series within a datetime window, used by the CSV importer to
     * resolve a whole chunk's natural keys in one query instead of one SELECT
     * per row.
     */
    List<HistoricalOptionCandle> findByStockCodeIgnoreCaseAndExchangeCodeIgnoreCaseAndDateTimeBetween(
            String stockCode,
            String exchangeCode,
            LocalDateTime from,
            LocalDateTime to);
}
