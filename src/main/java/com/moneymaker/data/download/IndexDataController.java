package com.moneymaker.data.download;

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
 * REST controller for index data operations.
 */
@Slf4j
@RestController
@RequestMapping("/api/index")
@RequiredArgsConstructor
public class IndexDataController {

    private final IndexDataDownloadService indexDataDownloadService;

    /**
     * Download OHLC for an index (default NIFTY 50) over the given date window,
     * persisted into {@code index_data}. Requires an active Zerodha session.
     *
     * <p>Re-runs are idempotent: existing rows for the same
     * {@code (symbol, timeframe, timestamp-window)} are deleted before insert.
     */
    @PostMapping("/download")
    public ResponseEntity<?> download(
            @RequestParam("fromDate") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam("toDate")   @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate,
            @RequestParam(value = "symbol", defaultValue = "NIFTY 50") String symbol,
            @RequestParam(value = "intervalMinutes", defaultValue = "5") int intervalMinutes) {
        try {
            IndexDataDownloadService.Summary summary =
                    indexDataDownloadService.download(symbol, fromDate, toDate, intervalMinutes);
            log.info("[index-download] summary {}", summary);
            return ResponseEntity.ok(summary);
        } catch (IllegalStateException | IllegalArgumentException ex) {
            return ResponseEntity.badRequest().body(ex.getMessage());
        } catch (Exception ex) {
            log.error("[index-download] failed", ex);
            return ResponseEntity.internalServerError().body("Index download failed: " + ex.getMessage());
        }
    }
}
