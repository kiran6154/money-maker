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
     * Start of a continuous, multi-day window. {@code null} - the default and the
     * pre-existing behaviour - charts {@link #date} alone.
     *
     * <p>When set, the chart spans {@code [fromDate, date]} inclusive. Only
     * trading days that actually have candles appear; the series simply runs on
     * across session boundaries rather than being trimmed to one day.
     */
    private LocalDate fromDate;

    /** True when this request asks for more than the single {@link #date}. */
    public boolean isRange() {
        return fromDate != null && date != null && fromDate.isBefore(date);
    }

    /**
     * Explicit option strike to chart. {@code null} means "auto" — the service
     * resolves ATM from the day's underlying price, which is the default and the
     * pre-existing behaviour. Ignored for {@code UNDERLYING} charts.
     */
    private BigDecimal strike;
}
