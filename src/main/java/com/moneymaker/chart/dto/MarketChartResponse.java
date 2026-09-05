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

    /**
     * The strike actually plotted. On an averaged series this is the centre of
     * {@link #averagedStrikes}, not the whole of what was drawn.
     */
    private BigDecimal atmStrike;

    /**
     * The strike ladder averaged into {@link #data}, ascending, when the request
     * carried a {@code strikeSpan}. Empty for an ordinary single-strike series.
     *
     * <p>Reported rather than left implicit because the caller cannot re-derive
     * it: a leg with no candles for the window drops out, so the series may be
     * an average of fewer legs than the span asked for, and a chart that says
     * "ATM±2" while averaging three contracts is lying about what it draws.
     */
    private List<BigDecimal> averagedStrikes;

    private List<ChartCandleResponse> data;
}
