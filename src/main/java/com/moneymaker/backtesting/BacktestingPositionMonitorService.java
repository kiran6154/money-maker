package com.moneymaker.backtesting;

import com.moneymaker.dto.Quote;
import com.moneymaker.entity.MarketData;
import com.moneymaker.entity.TradeOrder;
import com.moneymaker.position.service.PositionMonitorService;
import com.moneymaker.shared.data.SharedData;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/**
 * Backtest position-monitor: pulls the latest cached candle for the option's
 * {@code optionToken} from {@link SharedData#strikeMarketDataByInstrumentAndInterval}.
 * The cache is populated each backtest tick by {@code AnalysisScheduler}, so
 * "latest candle" naturally tracks the current tick. The candle's
 * {@link MarketData#getTimestamp() timestamp} becomes the {@link Quote#asOf()},
 * giving the position ledger the right "as of" time even though the backtest
 * is running on wall-clock.
 */
@Slf4j
@Service
public class BacktestingPositionMonitorService implements PositionMonitorService {

    public static final String NAME = "BACKTESTING";

    @Override
    public String getName() {
        return NAME;
    }

    @Override
    public Quote currentQuote(TradeOrder order) {
        if (order == null || order.getOptionToken() == null) return null;
        Map<String, List<MarketData>> cache = SharedData.strikeMarketDataByInstrumentAndInterval;
        if (cache == null || cache.isEmpty()) return null;

        // M1.1: iterate keys in natural order so the monitor picks the same
        // cache entry every run when multiple keys share an optionToken
        // (different itm/otm depths in the suffix). Without this, peak P&L
        // tracking varies subtly across reruns of the same backtest day.
        java.util.List<String> orderedKeys = new java.util.ArrayList<>(cache.keySet());
        java.util.Collections.sort(orderedKeys);

        for (String key : orderedKeys) {
            String[] parts = key.split("\\|");
            if (parts.length < 5) continue;
            if (!order.getOptionToken().equals(parts[4])) continue;

            List<MarketData> list = cache.get(key);
            if (list == null || list.isEmpty()) continue;
            for (int i = list.size() - 1; i >= 0; i--) {
                MarketData md = list.get(i);
                if (md != null && md.getClose() != null && md.getTimestamp() != null) {
                    return new Quote(md.getClose(), md.getTimestamp());
                }
            }
        }
        log.debug("Backtest monitor: no cached candle for optionToken={} (orderId={})",
                order.getOptionToken(), order.getId());
        return null;
    }
}
