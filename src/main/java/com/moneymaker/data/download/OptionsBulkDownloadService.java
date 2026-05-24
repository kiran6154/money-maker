package com.moneymaker.data.download;

import com.moneymaker.entity.MarketData;
import com.moneymaker.login.model.Broker;
import com.moneymaker.login.model.BrokerSession;
import com.moneymaker.market.service.MarketDataService;
import com.moneymaker.repository.MarketDataRepository;
import com.moneymaker.shared.data.SharedData;
import com.moneymaker.state.AppState;
import com.zerodhatech.kiteconnect.KiteConnect;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * Bulk-downloads historical OHLC for every NIFTY weekly option (CE + PE) in a
 * strike band derived from {@code instruments.csv} and persists into
 * {@code market_data}. Used to prime the local cache before a backtest.
 *
 * <p>Flow:
 * <ol>
 *   <li>Parse the bundled {@code instruments.csv} (curated weekly strike set).</li>
 *   <li>Pick the earliest non-past NIFTY weekly expiry from that file and read
 *       its min/max strike — the "natural range".</li>
 *   <li>Extend the natural range by {@code options.download.range-extension}
 *       points on each side.</li>
 *   <li>Fetch a fresh Zerodha instruments dump (so we have tokens for strikes
 *       outside the CSV).</li>
 *   <li>Filter the dump to NIFTY {@code CE/PE} for that expiry inside the
 *       extended range.</li>
 *   <li>For each instrument and each timeframe configured in
 *       {@link SharedData#allTimeFrameMap}, fetch historical candles for the
 *       caller-specified date window via {@link MarketDataService} (already
 *       Resilience4j rate-limited / retried) and persist into
 *       {@code market_data}. Re-runs delete existing rows for the same
 *       {@code (token, range)} first so the load is idempotent.</li>
 * </ol>
 *
 * <p>Trigger: {@code POST /api/options/bulk-download?fromDate=&toDate=}.
 */
@Slf4j
@Service
public class OptionsBulkDownloadService {

    private static final DateTimeFormatter CSV_DATE = DateTimeFormatter.ofPattern("M/d/yyyy");

    private final ZerodhaMarketDataService zerodhaMarketDataService;
    private final MarketDataService marketDataService;
    private final MarketDataRepository marketDataRepository;
    private final AppState appState;
    private final KiteConnect sharedKiteConnect;
    private final int rangeExtension;

    public OptionsBulkDownloadService(ZerodhaMarketDataService zerodhaMarketDataService,
                                      MarketDataService marketDataService,
                                      MarketDataRepository marketDataRepository,
                                      AppState appState,
                                      @Qualifier("sharedKiteConnect") KiteConnect sharedKiteConnect,
                                      @Value("${options.download.range-extension:200}") int rangeExtension) {
        this.zerodhaMarketDataService = Objects.requireNonNull(zerodhaMarketDataService);
        this.marketDataService = Objects.requireNonNull(marketDataService);
        this.marketDataRepository = Objects.requireNonNull(marketDataRepository);
        this.appState = Objects.requireNonNull(appState);
        this.sharedKiteConnect = Objects.requireNonNull(sharedKiteConnect);
        this.rangeExtension = rangeExtension;
    }

    /**
     * Result returned to the caller — stage-by-stage counts so the user can
     * see exactly where the pipeline drops off if anything looks wrong.
     */
    public record Summary(
            LocalDate expiry,
            int csvRowsParsed,
            int csvRowsForExpiry,
            int csvMinStrike,
            int csvMaxStrike,
            int extendedMinStrike,
            int extendedMaxStrike,
            int dumpInstrumentsTotal,
            int targetsAfterFilter,
            int instrumentsAttempted,
            int instrumentsSavedAny,
            int candlesSaved
    ) {}

    public Summary bulkDownload(LocalDate fromDate, LocalDate toDate) {
        Objects.requireNonNull(fromDate, "fromDate must not be null");
        Objects.requireNonNull(toDate,   "toDate must not be null");
        if (fromDate.isAfter(toDate)) {
            throw new IllegalArgumentException("fromDate must be on or before toDate");
        }
        if (appState.currentBroker().orElse(null) != Broker.ZERODHA) {
            throw new IllegalStateException("Zerodha is not the active broker; bulk download not supported");
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

        // 1) Read CSV → derive expiry + natural strike range.
        List<CsvRow> csvRows = readCsv();
        log.info("[bulk-download] CSV rows parsed: {}", csvRows.size());
        if (csvRows.isEmpty()) {
            log.warn("instruments.csv is empty or could not be read — nothing to download");
            return emptySummary(null);
        }
        LocalDate expiry = pickWeeklyExpiry(csvRows, fromDate);
        log.info("[bulk-download] picked expiry={} (from {} CSV rows, fromDate={})", expiry, csvRows.size(), fromDate);
        if (expiry == null) {
            return emptySummary(null);
        }
        List<CsvRow> rowsForExpiry = csvRows.stream()
                .filter(r -> r.expiry.equals(expiry))
                .toList();
        int csvMinStrike = rowsForExpiry.stream().mapToInt(r -> r.strike).min().orElse(-1);
        int csvMaxStrike = rowsForExpiry.stream().mapToInt(r -> r.strike).max().orElse(-1);
        log.info("[bulk-download] CSV rows for expiry {}: {} (strikes {}..{})",
                expiry, rowsForExpiry.size(), csvMinStrike, csvMaxStrike);
        if (csvMinStrike < 0 || csvMaxStrike < 0) {
            return emptySummary(expiry);
        }
        int extendedMin = csvMinStrike - rangeExtension;
        int extendedMax = csvMaxStrike + rangeExtension;
        log.info("[bulk-download] extended strike range: {}..{} (margin={})", extendedMin, extendedMax, rangeExtension);

        // 2) Fetch fresh Zerodha dump → filter to NIFTY CE/PE at this expiry within extended range.
        List<ZerodhaMarketDataService.ZerodhaInstrument> all =
                zerodhaMarketDataService.fetchInstruments(accessToken);
        log.info("[bulk-download] Zerodha instruments dump: {} total", all.size());

        // Diagnostic: pick any CE/PE in the dump (no name filter) so we can see
        // what the live dump's name/expiry format actually looks like.
        ZerodhaMarketDataService.ZerodhaInstrument anyOpt = all.stream()
                .filter(i -> "CE".equals(i.getInstrumentType()) || "PE".equals(i.getInstrumentType()))
                .findFirst().orElse(null);
        if (anyOpt != null) {
            log.info("[bulk-download] sample option in dump (any name): tradingsymbol='{}' name='{}' expiry='{}' strike={} type='{}' segment='{}'",
                    anyOpt.getTradingsymbol(), anyOpt.getName(), anyOpt.getExpiry(),
                    anyOpt.getStrike(), anyOpt.getInstrumentType(), anyOpt.getSegment());
        } else {
            log.warn("[bulk-download] dump has NO rows with instrument_type IN (CE, PE) — parsing or column-order issue?");
        }
        // Diagnostic: any instrument whose tradingsymbol starts with NIFTY (to see what 'name' it carries)
        ZerodhaMarketDataService.ZerodhaInstrument anyNifty = all.stream()
                .filter(i -> i.getTradingsymbol() != null && i.getTradingsymbol().toUpperCase(Locale.ROOT).startsWith("NIFTY"))
                .filter(i -> "CE".equals(i.getInstrumentType()) || "PE".equals(i.getInstrumentType()))
                .findFirst().orElse(null);
        if (anyNifty != null) {
            log.info("[bulk-download] sample NIFTY-tradingsymbol CE/PE: tradingsymbol='{}' name='{}' expiry='{}'",
                    anyNifty.getTradingsymbol(), anyNifty.getName(), anyNifty.getExpiry());
        }

        List<ZerodhaMarketDataService.ZerodhaInstrument> targets = filterTargets(all, expiry, extendedMin, extendedMax);
        log.info("[bulk-download] targets after filter: {} (CE+PE, expiry={}, strikes {}..{})",
                targets.size(), expiry, extendedMin, extendedMax);

        if (targets.isEmpty()) {
            log.warn("[bulk-download] no instruments matched filter — check name='NIFTY' and expiry={} against dump samples above.",
                    expiry);
            return new Summary(expiry, csvRows.size(), rowsForExpiry.size(), csvMinStrike, csvMaxStrike,
                    extendedMin, extendedMax, all.size(), 0, 0, 0, 0);
        }

        // 3) Fetch historical candles per instrument per interval and persist.
        Set<Integer> intervals = SharedData.allTimeFrameMap != null && !SharedData.allTimeFrameMap.isEmpty()
                ? SharedData.allTimeFrameMap.keySet()
                : Set.of(5);

        LocalDateTime windowFrom = fromDate.atStartOfDay();
        LocalDateTime windowTo   = toDate.atTime(LocalTime.MAX);

        int totalCandles = 0;
        int instrumentsAttempted = 0;
        int instrumentsSavedAny = 0;
        for (ZerodhaMarketDataService.ZerodhaInstrument inst : targets) {
            String token = String.valueOf(inst.getInstrumentToken());
            int savedForThisInstrument = 0;
            instrumentsAttempted++;
            for (Integer minutes : intervals) {
                String interval = minutes + "minute";
                try {
                    // Delete-then-insert keeps the load idempotent.
                    marketDataRepository.deleteByInstrumenttokenAndTimestampBetween(token, windowFrom, windowTo);

                    List<MarketData> candles = marketDataService.fetchHistoricalData(token, windowFrom, windowTo, interval);
                    if (candles == null || candles.isEmpty()) {
                        log.debug("[bulk-download] no candles returned for {} {} (token={})",
                                inst.getTradingsymbol(), interval, token);
                        continue;
                    }
                    for (MarketData md : candles) {
                        md.setInstrumenttoken(token);
                    }
                    marketDataRepository.saveAll(candles);
                    totalCandles += candles.size();
                    savedForThisInstrument += candles.size();
                } catch (Exception ex) {
                    log.error("[bulk-download] fetch/save failed for token={} symbol={} interval={} : {}",
                            token, inst.getTradingsymbol(), interval, ex.getMessage());
                }
            }
            if (savedForThisInstrument > 0) instrumentsSavedAny++;
            if (instrumentsAttempted % 10 == 0) {
                log.info("[bulk-download] progress: {}/{} instruments attempted, {} saved candles so far",
                        instrumentsAttempted, targets.size(), totalCandles);
            }
        }

        Summary summary = new Summary(
                expiry, csvRows.size(), rowsForExpiry.size(), csvMinStrike, csvMaxStrike,
                extendedMin, extendedMax, all.size(), targets.size(),
                instrumentsAttempted, instrumentsSavedAny, totalCandles);
        log.info("[bulk-download] done: {}", summary);
        return summary;
    }

    private Summary emptySummary(LocalDate expiry) {
        return new Summary(expiry, 0, 0, -1, -1, -1, -1, 0, 0, 0, 0, 0);
    }


    /* -------------------- helpers -------------------- */

    private List<CsvRow> readCsv() {
        List<CsvRow> rows = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                new ClassPathResource("com/moneymaker/data/download/instruments.csv").getInputStream(),
                StandardCharsets.UTF_8))) {

            String header = reader.readLine(); // discard
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) continue;
                CsvRow row = parseCsvLine(line);
                if (row != null) rows.add(row);
            }
        } catch (Exception ex) {
            // Fallback: try without classpath prefix (the file currently lives next to the Java source,
            // not under resources). Tolerate either layout.
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(
                    new ClassPathResource("instruments.csv").getInputStream(),
                    StandardCharsets.UTF_8))) {
                reader.readLine();
                String line;
                while ((line = reader.readLine()) != null) {
                    if (line.isBlank()) continue;
                    CsvRow row = parseCsvLine(line);
                    if (row != null) rows.add(row);
                }
            } catch (Exception ignored) {
                log.warn("Failed to read instruments.csv from classpath: {}", ex.getMessage());
            }
        }
        return rows;
    }

    private CsvRow parseCsvLine(String line) {
        String[] parts = line.split(",");
        if (parts.length < 10) return null;
        try {
            String name        = parts[3];
            LocalDate expiry   = LocalDate.parse(parts[5], CSV_DATE);
            int strike         = (int) Double.parseDouble(parts[6]);
            String optionType  = parts[9];
            if (!"NIFTY".equalsIgnoreCase(name)) return null;
            if (!"CE".equals(optionType) && !"PE".equals(optionType)) return null;
            return new CsvRow(name, expiry, strike, optionType);
        } catch (Exception ex) {
            return null;
        }
    }

    /** Earliest expiry in the CSV that is on or after {@code reference} (i.e. not in the past). */
    private LocalDate pickWeeklyExpiry(List<CsvRow> rows, LocalDate reference) {
        return rows.stream()
                .map(r -> r.expiry)
                .filter(d -> !d.isBefore(reference))
                .min(Comparator.naturalOrder())
                .orElse(null);
    }

    private List<ZerodhaMarketDataService.ZerodhaInstrument> filterTargets(
            List<ZerodhaMarketDataService.ZerodhaInstrument> all,
            LocalDate expiry,
            int minStrike,
            int maxStrike) {

        return all.stream()
                .filter(i -> "CE".equals(i.getInstrumentType()) || "PE".equals(i.getInstrumentType()))
                .filter(this::isPlainNiftyOption)   // NIFTY only — excludes BANKNIFTY / FINNIFTY / MIDCPNIFTY
                .filter(i -> matchesExpiry(i.getExpiry(), expiry))
                .filter(i -> i.getStrike() >= minStrike && i.getStrike() <= maxStrike)
                .collect(Collectors.toList());
    }

    /**
     * Identifies plain NIFTY (NIFTY 50) options. Kite's instruments dump uses
     * the {@code name} field for the underlying — usually "NIFTY" for NIFTY 50
     * options, but we cross-check the tradingsymbol prefix in case the live
     * dump carries a variant like "NIFTY 50" or has trailing whitespace.
     */
    private boolean isPlainNiftyOption(ZerodhaMarketDataService.ZerodhaInstrument i) {
        // Kite's instruments CSV wraps the name field in literal double-quotes,
        // e.g. `"NIFTY"` — strip them before comparing.
        String name = i.getName() == null ? ""
                : i.getName().trim().replace("\"", "").toUpperCase(Locale.ROOT);
        String sym  = i.getTradingsymbol() == null ? ""
                : i.getTradingsymbol().trim().replace("\"", "").toUpperCase(Locale.ROOT);
        // Tradingsymbol must start with NIFTY but not be a sibling index (BANKNIFTY / FINNIFTY / MIDCPNIFTY).
        boolean isNiftyByTradingsymbol = sym.startsWith("NIFTY")
                && !sym.startsWith("NIFTYBANK")
                && !sym.startsWith("BANKNIFTY")
                && !sym.startsWith("FINNIFTY")
                && !sym.startsWith("MIDCPNIFTY");
        // Name should be "NIFTY" (or "NIFTY 50" / similar). Defensive against the
        // exact spelling — anything starting with NIFTY but not the sibling indices.
        boolean isNiftyByName = name.startsWith("NIFTY")
                && !name.startsWith("BANKNIFTY")
                && !name.startsWith("FINNIFTY")
                && !name.startsWith("MIDCPNIFTY");
        return isNiftyByTradingsymbol && isNiftyByName;
    }

    /**
     * Matches Kite's dump expiry against our target {@link LocalDate}. Kite usually
     * returns {@code yyyy-MM-dd}; this method also tolerates {@code yyyy-MM-ddTHH:mm:ss}
     * (any prefix match works).
     */
    private boolean matchesExpiry(String dumpExpiry, LocalDate target) {
        if (dumpExpiry == null || target == null) return false;
        return dumpExpiry.startsWith(target.toString());
    }

    private record CsvRow(String name, LocalDate expiry, int strike, String optionType) {}
}
