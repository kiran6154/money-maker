package com.moneymaker.data.download;

import com.moneymaker.entity.MarketData;
import com.moneymaker.repository.MarketDataRepository;
import jakarta.transaction.Transactional;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class MarketDataPersistService {

    private final MarketDataRepository marketDataRepository;

    public MarketDataPersistService(MarketDataRepository marketDataRepository) {
        this.marketDataRepository = marketDataRepository;
    }

    /**
     * Deletes existing candles in the window and saves the provided list in a single transaction.
     * Returns number of saved candles.
     */
    @Transactional
    public int persistCandles(String instrumentToken, List<MarketData> candles, LocalDateTime from, LocalDateTime to) {
        if (candles == null || candles.isEmpty()) return 0;
        marketDataRepository.deleteByInstrumenttokenAndTimestampBetween(instrumentToken, from, to);
        for (MarketData md : candles) {
            md.setInstrumenttoken(instrumentToken);
        }
        marketDataRepository.saveAll(candles);
        return candles.size();
    }
}

