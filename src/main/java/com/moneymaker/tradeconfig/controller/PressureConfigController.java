package com.moneymaker.tradeconfig.controller;

import com.moneymaker.tradeconfig.generation.PressureBook;
import com.moneymaker.tradeconfig.generation.PressureConfigGenerator;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

/**
 * Drives {@link PressureConfigGenerator}.
 *
 * <p><b>Mode-gated to {@code app.mode=backtest}</b>, the same guard
 * {@code BacktestController} carries and for a stronger reason: this endpoint
 * writes thousands of {@code trade_config} rows at once, and a live system must
 * not acquire a full year of trading configuration from one unauthenticated
 * POST. The Pressure books are a measurement grid; they have no business
 * existing in a live JVM.</p>
 */
@Slf4j
@RestController
@RequestMapping("/api/pressure/configs")
@RequiredArgsConstructor
@ConditionalOnProperty(name = "app.mode", havingValue = "backtest")
public class PressureConfigController {

    private final PressureConfigGenerator generator;

    /** The seven book ids, so a caller can scope a run without guessing names. */
    @GetMapping("/books")
    public ResponseEntity<Map<String, Object>> books() {
        Map<String, Object> out = new LinkedHashMap<>();
        for (PressureBook b : PressureBook.all()) {
            Map<String, Object> desc = new LinkedHashMap<>();
            desc.put("underlyingLeg", b.underlyingLeg());
            desc.put("transactionType", b.transactionType());
            desc.put("strikeOffsetPoints", b.strikeOffsetPoints());
            desc.put("legs", b.legs().stream()
                    .map(l -> l.tradingSide() + "/" + l.transactionType()).toList());
            out.put(b.bookId(), desc);
        }
        return ResponseEntity.ok(out);
    }

    /**
     * Generates configs for every trading day in the window.
     *
     * <pre>
     *   POST /api/pressure/configs/generate?fromDate=2024-01-01&amp;toDate=2024-12-31
     *   POST /api/pressure/configs/generate?fromDate=...&amp;toDate=...&amp;books=SELL_ITM300,SPOT
     * </pre>
     *
     * <p>Idempotent: re-running over a window that already has rows creates
     * nothing and reports the skip count.</p>
     */
    @PostMapping("/generate")
    public ResponseEntity<Map<String, Object>> generate(
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate,
            @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate toDate,
            @RequestParam(required = false) String books,
            @RequestParam(defaultValue = "NIFTY") String instrument) {

        if (toDate.isBefore(fromDate)) {
            return ResponseEntity.badRequest().body(Map.of(
                    "error", "toDate " + toDate + " is before fromDate " + fromDate));
        }
        Set<String> bookIds = new LinkedHashSet<>();
        if (books != null && !books.isBlank()) {
            for (String s : books.split(",")) {
                if (!s.isBlank()) bookIds.add(s.trim());
            }
        }
        try {
            PressureConfigGenerator.Result r = generator.generate(fromDate, toDate, bookIds, instrument);
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("fromDate", fromDate);
            out.put("toDate", toDate);
            out.put("tradingDays", r.tradingDays());
            out.put("books", r.books());
            out.put("created", r.created());
            out.put("skippedExisting", r.skippedExisting());
            return ResponseEntity.ok(out);
        } catch (IllegalArgumentException ex) {
            return ResponseEntity.badRequest().body(Map.of("error", ex.getMessage()));
        }
    }
}
