package com.moneymaker.repository;

import com.moneymaker.entity.HistoricalSpotCandle;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * Reads over {@code historical_spot_candles} — the imported ICICI 5-minute
 * underlying candles.
 *
 * <h3>Why no {@code UPPER(...)} in these queries</h3>
 * Same reasoning as {@link HistoricalOptionCandleRepository}: a function on an
 * indexed column makes {@code uk_historical_spot_series_time} unusable and turns
 * every lookup into a full scan. The table collation
 * ({@code utf8mb4_0900_ai_ci}) already compares case-insensitively, and both
 * writers normalise to upper case before the value ever reaches the DB.
 *
 * <p><b>Do not "fix" a missing {@code UPPER} back in.</b>
 */
@Repository
public interface HistoricalSpotCandleRepository extends JpaRepository<HistoricalSpotCandle, Integer> {

    @Query("""
        SELECT c
        FROM HistoricalSpotCandle c
        WHERE c.stockCode = :stockCode
          AND c.exchangeCode = :exchangeCode
          AND c.dateTime <= :toInclusive
        ORDER BY c.dateTime DESC
    """)
    List<HistoricalSpotCandle> findRecentCandlesUpTo(
            @Param("stockCode") String stockCode,
            @Param("exchangeCode") String exchangeCode,
            @Param("toInclusive") LocalDateTime toInclusive,
            Pageable pageable);

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
        WHERE c.stockCode = :stockCode
          AND c.exchangeCode = :exchangeCode
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
     * Every distinct calendar date that has underlying candles — i.e. the trading
     * days the imported data actually covers. Backs {@code HistoricalTradingCalendar},
     * so a backtest replays the sessions the market really held rather than
     * assuming Mon–Fri.
     *
     * <p>Deliberately not filtered by {@code stock_code}: a session is market-wide,
     * so any index having candles for a date is enough to call it a trading day.
     *
     * <p>Native, and returning {@code java.sql.Date} rather than {@code LocalDate},
     * to keep the {@code DATE(...)} truncation and its type mapping explicit. The
     * table is small (~24k rows) and this runs once per JVM, so the full scan the
     * {@code DISTINCT} implies costs nothing worth optimising.
     */
    @Query(value = "SELECT DISTINCT DATE(datetime) FROM historical_spot_candles ORDER BY 1",
            nativeQuery = true)
    List<java.sql.Date> findDistinctTradingDates();
}
