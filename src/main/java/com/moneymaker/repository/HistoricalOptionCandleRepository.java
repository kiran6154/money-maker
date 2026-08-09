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
}
