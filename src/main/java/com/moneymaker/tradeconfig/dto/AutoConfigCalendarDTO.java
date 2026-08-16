package com.moneymaker.tradeconfig.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

/**
 * Per-day counts of {@code AUTO_DOWNTREND} configs, used to paint the bulk-delete
 * calendar. Only days that actually have generated configs are returned — the UI
 * renders every other cell as inert, so absence is meaningful and there is no need
 * to ship empty days across the wire.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AutoConfigCalendarDTO {

    private LocalDate from;
    private LocalDate to;
    private List<Day> days;

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Day {
        private LocalDate date;
        /** Configs on this trading date. */
        private long total;
        private long ce;
        private long pe;
        /** Attached {@code sma_timeframe} rows — shown so the confirm dialog can
         *  state the full blast radius, not just the config count. */
        private long combos;
        /** Most recent write across this day's configs; drives the "run" grouping. */
        private LocalDateTime lastUpdated;
    }
}
