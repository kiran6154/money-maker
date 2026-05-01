package com.moneymaker.data.download;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDate;
import java.util.List;

@Repository
public interface OptionsDataRepository extends JpaRepository<OptionsDataEntity, Integer> {

    List<OptionsDataEntity> findBySymbolAndDataDate(String symbol, LocalDate dataDate);

    @Query("SELECT DISTINCT e.dataDate FROM OptionsDataEntity e WHERE e.symbol = :symbol ORDER BY e.dataDate DESC")
    List<LocalDate> findDistinctDataDatesBySymbol(@Param("symbol") String symbol);

    // Delete old data beyond 45 days
    void deleteBySymbolAndDataDateBefore(String symbol, LocalDate cutoffDate);
}
