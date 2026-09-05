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

    /**
     * How many strikes either side of the plotted strike to average into one
     * synthetic series. {@code 0} — the default and the pre-existing behaviour
     * — charts the single strike alone.
     *
     * <p>{@code 1} averages {@code strike-1, strike, strike+1}; {@code 2} widens
     * that to {@code strike-2 … strike+2}. "±1" is one step of the index's own
     * strike grid (50 for NIFTY, 100 for BANKNIFTY) — the same grid the ATM
     * rounding uses — not one row of whatever strikes happen to be imported.
     *
     * <p>A span straddles the money on either side whichever right is charted:
     * for a CE the lower legs are ITM and the upper OTM, for a PE the reverse.
     * Ignored for {@code UNDERLYING} charts.
     */
    private int strikeSpan;
}
