package com.moneymaker.chart.controller;

import com.moneymaker.chart.dto.ChartDataSource;
import com.moneymaker.chart.dto.ChartTimeframe;
import com.moneymaker.chart.dto.ChartType;
import com.moneymaker.chart.dto.IndexSymbol;
import com.moneymaker.chart.dto.MarketChartRequest;
import com.moneymaker.chart.dto.MarketChartResponse;
import com.moneymaker.chart.service.ChartDashboardService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.Arrays;
import java.util.List;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/charts")
@RequiredArgsConstructor
public class ChartDashboardApiController {

    private final ChartDashboardService chartDashboardService;

    @GetMapping("/market-data")
    public ResponseEntity<?> marketData(
            @RequestParam("date") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam("indexSymbol") IndexSymbol indexSymbol,
            @RequestParam("chartType") ChartType chartType,
            @RequestParam("timeframe") String timeframe,
            @RequestParam("smaPeriods") String smaPeriods,
            @RequestParam(value = "dataSource", defaultValue = "TOKEN_BASED") ChartDataSource dataSource,
            @RequestParam(value = "strike", required = false) String strike,
            // Optional. Present => draw a continuous window [fromDate, date]
            // instead of the single day. Absent keeps the original behaviour.
            @RequestParam(value = "fromDate", required = false)
            @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate fromDate) {
        try {
            MarketChartRequest request = new MarketChartRequest(
                    date,
                    indexSymbol,
                    chartType,
                    ChartTimeframe.fromValue(timeframe),
                    parseSmaPeriods(smaPeriods),
                    dataSource,
                    fromDate,
                    parseStrike(strike)
            );
            MarketChartResponse response = chartDashboardService.getMarketChartData(request);
            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException e) {
            log.warn("[chart-api] rejected request: {}", e.getMessage());
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    /**
     * Strikes the dashboard's strike picker can offer. {@code chartType} selects
     * the CE or PE side; anything else lists the CE side, which for index
     * options carries the same strike ladder.
     */
    @GetMapping("/strikes")
    public ResponseEntity<?> strikes(
            @RequestParam("date") @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam("indexSymbol") IndexSymbol indexSymbol,
            @RequestParam(value = "chartType", required = false) ChartType chartType,
            @RequestParam(value = "dataSource", defaultValue = "TOKEN_BASED") ChartDataSource dataSource) {
        try {
            return ResponseEntity.ok(
                    chartDashboardService.getStrikeOptions(indexSymbol, date, chartType, dataSource));
        } catch (IllegalArgumentException e) {
            log.warn("[chart-api] rejected strikes request: {}", e.getMessage());
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    /** Blank / absent means "auto" — the service resolves ATM itself. */
    private BigDecimal parseStrike(String strike) {
        if (strike == null || strike.isBlank() || "AUTO".equalsIgnoreCase(strike.trim())) {
            return null;
        }
        try {
            return new BigDecimal(strike.trim());
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("strike must be numeric, or blank for ATM");
        }
    }

    private List<Integer> parseSmaPeriods(String smaPeriods) {
        if (smaPeriods == null || smaPeriods.isBlank()) {
            throw new IllegalArgumentException("smaPeriods is required");
        }

        try {
            return Arrays.stream(smaPeriods.split(","))
                    .map(String::trim)
                    .filter(s -> !s.isEmpty())
                    .map(Integer::valueOf)
                    .toList();
        } catch (NumberFormatException ex) {
            throw new IllegalArgumentException("smaPeriods must be a comma-separated list of integers");
        }
    }
}
