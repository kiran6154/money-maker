package com.moneymaker.data.download;

import com.moneymaker.login.model.Broker;
import com.moneymaker.state.AppState;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;

/**
 * REST controller for options data operations.
 */
@Slf4j
@RestController
@RequestMapping("/api/options")
@RequiredArgsConstructor
public class OptionsDataController {

    private final AppState appState;
    private final ZerodhaMarketDataService marketDataService;
    private final OptionsBulkDownloadService bulkDownloadService;

    /**
     * Manually trigger fetching and saving of NIFTY and BANKNIFTY options data.
     * Requires active Zerodha session.
     */
    @PostMapping("/fetch")
    public ResponseEntity<String> fetchOptionsData() {
        if (!appState.isLoggedIn()) {
            return ResponseEntity.badRequest().body("Not logged in");
        }

        if (appState.currentBroker().orElse(null) != Broker.ZERODHA) {
            return ResponseEntity.badRequest().body("Zerodha not active");
        }

        String accessToken = appState.currentSession().get().getAccessToken();

        try {
            log.info("Manually triggering options data fetch");
            marketDataService.fetchAndSaveOptionsData("NIFTY26APR", accessToken);
            marketDataService.fetchAndSaveOptionsData("BANKNIFTY26APR", accessToken);
            log.info("Manual options data fetch completed");
            return ResponseEntity.ok("Options data fetched and saved successfully");
        } catch (Exception e) {
            log.error("Failed to fetch options data", e);
            return ResponseEntity.internalServerError().body("Failed to fetch options data: " + e.getMessage());
        }
    }

    /**
     * Manually trigger fetching and saving of options data for a specific expiry.
     * Requires active Zerodha session.
     * Use this to capture historical data progression toward expiration.
     */
    @PostMapping("/fetch-expiry")
    public ResponseEntity<String> fetchOptionsDataForExpiry(
            @RequestParam String symbol,
            @RequestParam String expiry) {
        if (!appState.isLoggedIn()) {
            return ResponseEntity.badRequest().body("Not logged in");
        }

        if (appState.currentBroker().orElse(null) != Broker.ZERODHA) {
            return ResponseEntity.badRequest().body("Zerodha not active");
        }

        String accessToken = appState.currentSession().get().getAccessToken();

        try {
            log.info("Manually triggering options data fetch for {} with expiry {}", symbol, expiry);
            marketDataService.fetchAndSaveOptionsDataForExpiry(symbol, expiry, accessToken);
            log.info("Manual options data fetch completed for {} expiry", expiry);
            return ResponseEntity.ok("Options data fetched and saved successfully for " + symbol + " expiry " + expiry);
        } catch (Exception e) {
            log.error("Failed to fetch options data for expiry", e);
            return ResponseEntity.internalServerError().body("Failed to fetch options data: " + e.getMessage());
        }
    }

    /**
     * Bulk-download OHLC for NIFTY weekly options (CE + PE) within an extended
     * strike band, persisted into {@code market_data}. Range is derived from
     * {@code instruments.csv} (curated weekly strikes) and extended by
     * {@code options.download.range-extension} points on each side.
     *
     * <p>Re-runs are idempotent: existing rows for the same
     * {@code (instrumentToken, timestamp-window)} are deleted before insert.
     */
    @PostMapping("/bulk-download")
    public ResponseEntity<?> bulkDownload(
            @RequestParam("fromDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam("toDate")   @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate) {
        try {
            OptionsBulkDownloadService.Summary summary = bulkDownloadService.bulkDownload(fromDate, toDate);
            log.info("[bulk-download] summary {}", summary);
            return ResponseEntity.ok(summary);
        } catch (IllegalStateException ex) {
            return ResponseEntity.badRequest().body(ex.getMessage());
        } catch (Exception ex) {
            log.error("[bulk-download] failed", ex);
            return ResponseEntity.internalServerError().body("Bulk download failed: " + ex.getMessage());
        }
    }
}
