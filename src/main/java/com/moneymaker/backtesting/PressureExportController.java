package com.moneymaker.backtesting;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Reads a completed Pressure replay out of the ledger.
 *
 * <p>Two shapes of the same run: {@code /csv} is the per-trade file, {@code /summary}
 * is the per-book table plus the CE / PE wing split. Both are pure reads over
 * {@code trade_order} — running them twice cannot change a number, and neither
 * triggers a replay.</p>
 *
 * <p>Mode-gated to {@code app.mode=backtest} like the rest of the backtest
 * surface.</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/pressure/report")
@RequiredArgsConstructor
@ConditionalOnProperty(name = "app.mode", havingValue = "backtest")
public class PressureExportController {

    private final PressureExportService exportService;

    /** One row per trade. Opens directly in Excel. */
    @GetMapping(value = "/csv", produces = "text/csv")
    public ResponseEntity<String> csv(
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate) {

        PressureExportService.Report report = exportService.build(fromDate, toDate);
        String body = String.join("\n", report.csvRows());
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename=\"pressure-trades-" + fromDate + "_" + toDate + ".csv\"")
                .contentType(MediaType.parseMediaType("text/csv"))
                .body(body);
    }

    /**
     * The summary table and the wing split.
     *
     * <p>{@code net_broker} uses this system's seeded {@code charge_rate} rows;
     * {@code net_spec} uses the Pressure spec's own flat schedule. They differ by
     * roughly 25-30 rupees a trade and both are reported rather than one being
     * chosen — see {@link PressureSpecCharges} for why the rate table was left
     * alone.</p>
     */
    @GetMapping("/summary")
    public ResponseEntity<Map<String, Object>> summary(
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate) {

        PressureExportService.Report report = exportService.build(fromDate, toDate);

        List<Map<String, Object>> books = new ArrayList<>();
        for (PressureExportService.BookSummary b : report.summary()) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("book", b.book());
            row.put("n", b.n());
            row.put("winRatePct", b.winRate());
            row.put("meanPoints", b.meanPoints());
            row.put("profitFactor", Double.isInfinite(b.profitFactor()) ? "inf" : b.profitFactor());
            row.put("gross", b.gross());
            row.put("chargesBroker", b.chargesBroker());
            row.put("netBroker", b.netBroker());
            row.put("chargesSpec", b.chargesSpec());
            row.put("netSpec", b.netSpec());
            books.add(row);
        }

        List<Map<String, Object>> wings = new ArrayList<>();
        for (PressureExportService.WingSplit w : report.wings()) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("book", w.book());
            row.put("wing", w.wing());
            row.put("n", w.n());
            row.put("winRatePct", w.winRate());
            row.put("meanPoints", w.meanPoints());
            row.put("gross", w.gross());
            wings.add(row);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("fromDate", fromDate);
        out.put("toDate", toDate);
        out.put("trades", report.csvRows().size() - 1);   // minus the header
        out.put("books", books);
        out.put("wings", wings);
        return ResponseEntity.ok(out);
    }
}
