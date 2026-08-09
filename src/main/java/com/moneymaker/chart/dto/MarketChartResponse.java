package com.moneymaker.chart.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class MarketChartResponse {
    private IndexSymbol symbol;
    private ChartType chartType;
    private ChartTimeframe timeframe;
    private LocalDate date;
    private LocalDate expiryDate;
    private BigDecimal atmStrike;
    private List<ChartCandleResponse> data;
}
