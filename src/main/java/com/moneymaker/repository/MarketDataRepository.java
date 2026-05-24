package com.moneymaker.repository;

import com.moneymaker.entity.MarketData;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

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
}
