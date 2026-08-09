package com.moneymaker.data.download;

import com.moneymaker.entity.MarketData;
import jakarta.transaction.Transactional;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class IndexDataPersistService {

    private final IndexDataRepository indexDataRepository;

    public IndexDataPersistService(IndexDataRepository indexDataRepository) {
        this.indexDataRepository = indexDataRepository;
    }

    /**
     * Deletes existing index candles for the same {@code (symbol, timeframe, window)}
     * and saves the provided list in a single transaction, so re-runs are idempotent.
     * Returns the number of saved candles.
     */
    @Transactional
    public int persistCandles(String symbol, String instrumentToken, String timeframe,
                              List<MarketData> candles, LocalDateTime from, LocalDateTime to) {
        if (candles == null || candles.isEmpty()) return 0;
        indexDataRepository.deleteBySymbolAndTimeframeAndTimestampBetween(symbol, timeframe, from, to);
        LocalDateTime now = LocalDateTime.now();
        List<IndexDataEntity> rows = candles.stream()
                .map(md -> IndexDataEntity.builder()
                        .symbol(symbol)
                        .instrumentToken(instrumentToken)
                        .timeframe(timeframe)
                        .timestamp(md.getTimestamp())
                        .open(md.getOpen())
                        .high(md.getHigh())
                        .low(md.getLow())
                        .close(md.getClose())
                        .createdAt(now)
                        .build())
                .toList();
        indexDataRepository.saveAll(rows);
        return rows.size();
    }
}
