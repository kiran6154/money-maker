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

/**
 * Reads over {@code historical_option_candles} — the imported ICICI 5-minute
 * option candles, natural-keyed rather than token-keyed.
 *
 * <h3>Why no {@code UPPER(...)} in these queries</h3>
 * Every query here matches {@code stock_code} / {@code exchange_code} /
 * {@code option_right} with a plain {@code =}, deliberately. Wrapping an indexed
 * column in a function makes the index unusable — MySQL cannot seek on
 * {@code UPPER(stock_code)} when the B-tree holds {@code stock_code}. Measured on
 * the same row set, the {@code UPPER}-wrapped form of {@link #findRangeAsc}
 * planned as {@code type: ALL, key: NULL, rows: 103585} (full scan + filesort)
 * where the plain form plans as {@code type: range,
 * key: uk_historical_option_series_time, rows: 378}. At the ~3.8M rows the full
 * CSV set imports, that difference is the backtest's whole runtime.
 *
 * <p>Case-insensitive matching is not lost by dropping it. The table collation is
 * {@code utf8mb4_0900_ai_ci}, so {@code =} is already case-insensitive at the DB
 * level, and both writers normalise to upper case anyway
 * ({@code HistoricalChartCsvImportService.normalize} on import,
 * {@code HistoricalSymbol.upper} when the backtest encodes a lookup symbol).
 *
 * <p><b>Do not "fix" a missing {@code UPPER} back in.</b>
 */
@Repository
public interface HistoricalOptionCandleRepository extends JpaRepository<HistoricalOptionCandle, Integer> {

    /**
     * Nearest expiry present in the data on or after {@code selectedDate}, or
     * empty when the imported set has none — the expiry rule described in
     * {@code docs/HISTORICAL_CHART_DATA_PLAN.md}: driven by the data, with no
     * weekday filter, so older Thursday weeklies resolve as readily as today's
     * Tuesday ones.
     *
     * <p>Expressed as {@code MIN(expiryDate)} rather than
     * {@code SELECT DISTINCT … ORDER BY … } precisely because both callers only
     * ever wanted the first row. The {@code DISTINCT} form had to walk the whole
     * index and sort it ({@code Using temporary; Using filesort}) to produce a
     * list that was immediately narrowed to one element — and
     * {@code AnalysisScheduler} asks for it once per (config × timeframe) on
     * <em>every</em> tick, roughly 400 times per backtest day.
     */
    /**
     * One-row backing query for {@link #findNearestExpiryOnOrAfter}. Derived
     * (→ {@code ORDER BY expiry_date LIMIT 1}) rather than {@code MIN(...)} on
     * purpose: on the bare table both plans are an index dive, but through a
     * cross-schema <b>view</b> — how Phase 10 worker schemas expose the
     * historical tables — MySQL cannot apply the MIN/MAX optimization and
     * range-scans ~1.8M index rows. Measured 2026-09-04: 11.1 s via view for
     * {@code MIN()}, ~2 ms for this shape, identical result either way.
     */
    Optional<HistoricalOptionCandle>
    findFirstByStockCodeAndExchangeCodeAndExpiryDateGreaterThanEqualOrderByExpiryDateAsc(
            String stockCode, String exchangeCode, LocalDate selectedDate);

    /** Earliest expiry on or after {@code selectedDate} for the series, or empty. */
    default Optional<LocalDate> findNearestExpiryOnOrAfter(
            String stockCode, String exchangeCode, LocalDate selectedDate) {
        return findFirstByStockCodeAndExchangeCodeAndExpiryDateGreaterThanEqualOrderByExpiryDateAsc(
                stockCode, exchangeCode, selectedDate)
                .map(HistoricalOptionCandle::getExpiryDate);
    }

    @Query("""
        SELECT c
        FROM HistoricalOptionCandle c
        WHERE c.stockCode = :stockCode
          AND c.exchangeCode = :exchangeCode
          AND c.expiryDate = :expiryDate
          AND c.strikePrice = :strikePrice
          AND c.optionRight = :optionRight
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

    /**
     * Ascending candle range for one option series. Backs the DB-backed backtest
     * market-data provider.
     *
     * <p>Ascending order is load-bearing: {@code BacktestMarketDataCache.slice}
     * stops at the first candle after its upper bound, and {@code AbstractSmaCrossStrategy}
     * treats {@code list.get(size - 1)} as the latest candle.
     *
     * <p>{@code strikePrice} is compared numerically, so a {@code 21700} literal
     * matches a stored {@code 21700.0000}.
     */
    @Query("""
        SELECT c
        FROM HistoricalOptionCandle c
        WHERE c.stockCode = :stockCode
          AND c.exchangeCode = :exchangeCode
          AND c.expiryDate = :expiryDate
          AND c.strikePrice = :strikePrice
          AND c.optionRight = :optionRight
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
        WHERE c.stockCode = :stockCode
          AND c.exchangeCode = :exchangeCode
          AND c.expiryDate = :expiryDate
          AND c.optionRight = :optionRight
        ORDER BY c.strikePrice ASC
    """)
    List<BigDecimal> findAvailableStrikes(
            @Param("stockCode") String stockCode,
            @Param("exchangeCode") String exchangeCode,
            @Param("expiryDate") LocalDate expiryDate,
            @Param("optionRight") String optionRight);
}
