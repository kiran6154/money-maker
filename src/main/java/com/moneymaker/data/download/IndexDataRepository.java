package com.moneymaker.data.download;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

@Repository
public interface IndexDataRepository extends JpaRepository<IndexDataEntity, Integer> {

    List<IndexDataEntity> findBySymbolAndTimeframeAndTimestampBetweenOrderByTimestampAsc(
            String symbol, String timeframe, LocalDateTime from, LocalDateTime to);

    void deleteBySymbolAndTimeframeAndTimestampBetween(
            String symbol, String timeframe, LocalDateTime from, LocalDateTime to);
}
