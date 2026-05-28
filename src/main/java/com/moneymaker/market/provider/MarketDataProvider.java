package com.moneymaker.market.provider;

import com.moneymaker.entity.MarketData;
import com.moneymaker.login.model.BrokerSession;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.LocalDateTime;
import java.util.List;

public interface MarketDataProvider {

    String getName();

    List<MarketData> fetchHistoricalData(String symbol, LocalDateTime from, LocalDateTime to, String interval);

    /**
     * Daily options-chain fetch (closes GAPS #12). Triggered by
     * {@code LoginScheduler.fetchOptionsData} at 09:15 IST.
     *
     * <p>Default is a no-op: brokers that don't yet implement options-data
     * persistence (Groww, Angel One, custom) gracefully skip without
     * needing the scheduler to know about them.
     *
     * <p>Previously this was hardcoded as a Zerodha-only call inside
     * {@code LoginScheduler.fetchOptionsData} with a
     * {@code session.getBroker() != Broker.ZERODHA} guard, violating
     * the "one adapter per broker" invariant. The default-method
     * approach keeps the interface lean while letting any broker plug
     * in real options ingestion when ready.
     *
     * @param session the active broker session (provides the access token)
     * @param underlyings the index symbols to fetch (e.g. {@code ["NIFTY", "BANKNIFTY"]})
     */
    default void fetchAndSaveDailyOptions(BrokerSession session, List<String> underlyings) {
        Logger log = LoggerFactory.getLogger(MarketDataProvider.class);
        log.debug("[options-data] provider '{}' does not implement daily options fetch — skipping {}",
                getName(), underlyings);
    }
}
