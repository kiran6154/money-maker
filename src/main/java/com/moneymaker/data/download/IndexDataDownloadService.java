package com.moneymaker.data.download;

import com.moneymaker.entity.MarketData;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.market.service.MarketDataService;
import com.moneymaker.state.AppState;
import com.zerodhatech.kiteconnect.KiteConnect;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;
import java.util.Locale;
import java.util.Objects;

/**
 * Downloads historical OHLC for an index (e.g. NIFTY 50, NIFTY BANK) and
 * persists it into {@code index_data}. Counterpart of
 * {@link OptionsBulkDownloadService}, which does the same for option legs
 * into {@code market_data}.
 *
 * <p>Flow:
 * <ol>
 *   <li>Resolve the index's instrument token from a fresh Zerodha instruments
 *       dump (segment {@code INDICES}, tradingsymbol match).</li>
 *   <li>Fetch historical candles for the caller-specified date window via
 *       {@link MarketDataService} (already Resilience4j rate-limited / retried).</li>
 *   <li>Persist into {@code index_data}. Re-runs delete existing rows for the
 *       same {@code (symbol, timeframe, range)} first so the load is idempotent.</li>
 * </ol>
 *
 * <p>Trigger: {@code POST /api/index/download?fromDate=&toDate=}.
 */
@Slf4j
@Service
public class IndexDataDownloadService {

    private final ZerodhaMarketDataService zerodhaMarketDataService;
    private final MarketDataService marketDataService;
    private final IndexDataPersistService indexDataPersistService;
    private final AppState appState;
    private final KiteConnect sharedKiteConnect;

    public IndexDataDownloadService(ZerodhaMarketDataService zerodhaMarketDataService,
                                    MarketDataService marketDataService,
                                    IndexDataPersistService indexDataPersistService,
                                    AppState appState,
                                    @Qualifier("sharedKiteConnect") KiteConnect sharedKiteConnect) {
        this.zerodhaMarketDataService = Objects.requireNonNull(zerodhaMarketDataService);
        this.marketDataService = Objects.requireNonNull(marketDataService);
        this.indexDataPersistService = Objects.requireNonNull(indexDataPersistService);
        this.appState = Objects.requireNonNull(appState);
        this.sharedKiteConnect = Objects.requireNonNull(sharedKiteConnect);
    }

    /** Stage-by-stage counts so the caller can see where the pipeline drops off. */
    public record Summary(
            String symbol,
            String instrumentToken,
            String timeframe,
            int dumpInstrumentsTotal,
            int candlesFetched,
            int candlesSaved
    ) {}

    public Summary download(String symbol, LocalDate fromDate, LocalDate toDate, int intervalMinutes) {
        Objects.requireNonNull(symbol,   "symbol must not be null");
        Objects.requireNonNull(fromDate, "fromDate must not be null");
        Objects.requireNonNull(toDate,   "toDate must not be null");
        if (fromDate.isAfter(toDate)) {
            throw new IllegalArgumentException("fromDate must be on or before toDate");
        }
        if (intervalMinutes <= 0) {
            throw new IllegalArgumentException("intervalMinutes must be positive");
        }
        if (appState.currentBroker().orElse(null) != Broker.ZERODHA) {
            throw new IllegalStateException("Zerodha is not the active broker; index download not supported");
        }
        if (!appState.isLoggedIn()) {
            throw new IllegalStateException("No active Zerodha session");
        }
        BrokerSession session = appState.currentSession().orElseThrow();
        String accessToken = session.getAccessToken();
        // Make sure the shared KiteConnect bean is authenticated — without this,
        // MarketDataService → ZerodhaMarketDataProvider.getHistoricalData runs
        // unauthenticated and silently returns no candles. The bean's token is
        // normally set on fresh OAuth completion or by BacktestAnalysisService;
        // it is NOT restored on app startup or on an ALREADY_VALID login.
        sharedKiteConnect.setAccessToken(accessToken);
        if (session.getPublicToken() != null && !session.getPublicToken().isBlank()) {
            sharedKiteConnect.setPublicToken(session.getPublicToken());
        }

        // 1) Resolve the index instrument token from a fresh instruments dump.
        List<ZerodhaMarketDataService.ZerodhaInstrument> all =
                zerodhaMarketDataService.fetchInstruments(accessToken);
        log.info("[index-download] Zerodha instruments dump: {} total", all.size());

        ZerodhaMarketDataService.ZerodhaInstrument index = findIndex(all, symbol);
        if (index == null) {
            throw new IllegalArgumentException(
                    "Index '" + symbol + "' not found in instruments dump (segment INDICES)");
        }
        String token = String.valueOf(index.getInstrumentToken());
        log.info("[index-download] resolved index: tradingsymbol='{}' token={} segment='{}'",
                index.getTradingsymbol(), token, index.getSegment());

        // 2) Fetch candles for the window and persist idempotently.
        String timeframe = intervalMinutes + "minute";
        LocalDateTime windowFrom = fromDate.atStartOfDay();
        LocalDateTime windowTo   = toDate.atTime(LocalTime.MAX);

        List<MarketData> candles =
                marketDataService.fetchHistoricalData(token, windowFrom, windowTo, timeframe);
        int fetched = candles == null ? 0 : candles.size();
        log.info("[index-download] fetched {} candles for {} {} ({} → {})",
                fetched, symbol, timeframe, fromDate, toDate);

        int saved = indexDataPersistService.persistCandles(
                cleanSymbol(index.getTradingsymbol()), token, timeframe, candles, windowFrom, windowTo);

        Summary summary = new Summary(cleanSymbol(index.getTradingsymbol()), token, timeframe,
                all.size(), fetched, saved);
        log.info("[index-download] done: {}", summary);
        return summary;
    }

    /**
     * Finds the index row in the dump: segment {@code INDICES} and tradingsymbol
     * matching {@code symbol} (case-insensitive, tolerant of the literal quotes
     * Kite wraps some CSV fields in). Prefers the NSE row if the same symbol
     * exists on more than one exchange.
     */
    private ZerodhaMarketDataService.ZerodhaInstrument findIndex(
            List<ZerodhaMarketDataService.ZerodhaInstrument> all, String symbol) {
        String wanted = cleanSymbol(symbol).toUpperCase(Locale.ROOT);
        List<ZerodhaMarketDataService.ZerodhaInstrument> matches = all.stream()
                .filter(i -> "INDICES".equalsIgnoreCase(cleanSymbol(i.getSegment())))
                .filter(i -> wanted.equals(cleanSymbol(i.getTradingsymbol()).toUpperCase(Locale.ROOT)))
                .toList();
        if (matches.isEmpty()) return null;
        // The dump parser's exchange/exchangeToken columns are swapped relative to
        // Kite's actual column order, so check both when preferring the NSE row.
        return matches.stream()
                .filter(i -> "NSE".equalsIgnoreCase(cleanSymbol(i.getExchange()))
                        || "NSE".equalsIgnoreCase(cleanSymbol(i.getExchangeToken())))
                .findFirst()
                .orElse(matches.get(0));
    }

    /** Kite's instruments CSV wraps some fields in literal double-quotes — strip them. */
    private String cleanSymbol(String s) {
        return s == null ? "" : s.trim().replace("\"", "");
    }
}
