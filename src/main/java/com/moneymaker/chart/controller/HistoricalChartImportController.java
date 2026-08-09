package com.moneymaker.chart.controller;

import com.moneymaker.chart.service.HistoricalChartCsvImportService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/charts/historical/import")
@RequiredArgsConstructor
public class HistoricalChartImportController {

    private final HistoricalChartCsvImportService importService;

    @PostMapping("/spot")
    public ResponseEntity<?> importSpot(@RequestParam("file") MultipartFile file) {
        try {
            return ResponseEntity.ok(importService.importSpot(file));
        } catch (IllegalArgumentException e) {
            log.warn("[historical-chart-import] rejected spot file: {}", e.getMessage());
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        } catch (IOException e) {
            log.warn("[historical-chart-import] failed to read spot file", e);
            return ResponseEntity.internalServerError().body(Map.of("error", "Unable to read uploaded file"));
        }
    }

    @PostMapping("/options")
    public ResponseEntity<?> importOptions(@RequestParam("file") MultipartFile file) {
        try {
            return ResponseEntity.ok(importService.importOptions(file));
        } catch (IllegalArgumentException e) {
            log.warn("[historical-chart-import] rejected option file: {}", e.getMessage());
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        } catch (IOException e) {
            log.warn("[historical-chart-import] failed to read option file", e);
            return ResponseEntity.internalServerError().body(Map.of("error", "Unable to read uploaded file"));
        }
    }
}
