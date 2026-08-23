package com.moneymaker.repository;

import com.moneymaker.entity.HistoricalSpotCandle;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface HistoricalSpotCandleRepository extends JpaRepository<HistoricalSpotCandle, Integer> {

    @Query("""
        SELECT c
        FROM HistoricalSpotCandle c
        WHERE UPPER(c.stockCode) = UPPER(:stockCode)
          AND UPPER(c.exchangeCode) = UPPER(:exchangeCode)
          AND c.dateTime <= :toInclusive
        ORDER BY c.dateTime DESC
    """)
    List<HistoricalSpotCandle> findRecentCandlesUpTo(
            @Param("stockCode") String stockCode,
            @Param("exchangeCode") String exchangeCode,
            @Param("toInclusive") LocalDateTime toInclusive,
            Pageable pageable);

    Optional<HistoricalSpotCandle> findByStockCodeIgnoreCaseAndExchangeCodeIgnoreCaseAndDateTime(
            String stockCode,
            String exchangeCode,
            LocalDateTime dateTime);

    /**
     * Ascending candle range for one spot series. Backs the DB-backed backtest
     * market-data provider.
     *
     * <p>Ascending order is load-bearing: {@code BacktestMarketDataCache.slice}
     * stops at the first candle after its upper bound, and {@code Strategy1}
     * treats {@code list.get(size - 1)} as the latest candle.
     */
    @Query("""
        SELECT c
        FROM HistoricalSpotCandle c
        WHERE UPPER(c.stockCode) = UPPER(:stockCode)
          AND UPPER(c.exchangeCode) = UPPER(:exchangeCode)
          AND c.dateTime >= :from
          AND c.dateTime <= :to
        ORDER BY c.dateTime ASC
    """)
    List<HistoricalSpotCandle> findRangeAsc(
            @Param("stockCode") String stockCode,
            @Param("exchangeCode") String exchangeCode,
            @Param("from") LocalDateTime from,
            @Param("to") LocalDateTime to);

    /**
     * All rows of a series within a datetime window, used by the CSV importer to
     * resolve a whole chunk's natural keys in one query instead of one SELECT
     * per row.
     */
    List<HistoricalSpotCandle> findByStockCodeIgnoreCaseAndExchangeCodeIgnoreCaseAndDateTimeBetween(
            String stockCode,
            String exchangeCode,
            LocalDateTime from,
            LocalDateTime to);
}
