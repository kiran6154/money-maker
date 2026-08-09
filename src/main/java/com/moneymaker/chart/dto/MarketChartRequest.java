package com.moneymaker.chart.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class MarketChartRequest {
    private LocalDate date;
    private IndexSymbol indexSymbol;
    private ChartType chartType;
    private ChartTimeframe timeframe;
    private List<Integer> smaPeriods;
    private ChartDataSource dataSource;
}
