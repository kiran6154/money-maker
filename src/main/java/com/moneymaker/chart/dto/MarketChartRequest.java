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
public class MarketChartRequest {
    private LocalDate date;
    private IndexSymbol indexSymbol;
    private ChartType chartType;
    private ChartTimeframe timeframe;
    private List<Integer> smaPeriods;
    private ChartDataSource dataSource;

    /**
     * Explicit option strike to chart. {@code null} means "auto" — the service
     * resolves ATM from the day's underlying price, which is the default and the
     * pre-existing behaviour. Ignored for {@code UNDERLYING} charts.
     */
    private BigDecimal strike;
}
