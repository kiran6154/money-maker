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
}
