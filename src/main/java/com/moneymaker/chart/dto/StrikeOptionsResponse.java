package com.moneymaker.chart.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * Strikes the dashboard's strike picker can offer for a given date, index and
 * data source, plus the strike it would pick on its own.
 *
 * <p>{@code strikes} only ever contains strikes that are actually chartable —
 * they come from the same table the candles come from — so the picker cannot
 * offer something that renders empty.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class StrikeOptionsResponse {

    /** Expiry the strikes belong to, resolved the same way the chart resolves it. */
    private LocalDate expiryDate;

    /** Strike the chart uses when none is explicitly selected. */
    private BigDecimal atmStrike;

    /** Ascending, chartable strikes. */
    private List<BigDecimal> strikes;
}
