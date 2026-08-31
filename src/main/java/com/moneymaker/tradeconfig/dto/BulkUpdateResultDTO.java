package com.moneymaker.tradeconfig.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

/**
 * Outcome of a bulk update. Identical shape for a dry run and a real one, so
 * the confirm dialog and the result toast render from the same payload and the
 * count approved is the count the server matched.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class BulkUpdateResultDTO {

    /** Configs matching the selector — all of them are (or would be) updated. */
    private long matched;

    /** Configs actually written. Zero on a dry run. */
    private long updated;

    /** Per trading-date breakdown, for the dialog's detail list. */
    private Map<LocalDate, Long> byDate;

    /** Ids that were (or would be) updated. */
    private List<Integer> ids;

    /** The field assignments this request carries, e.g. {@code "slPct = 0.25"}. */
    private List<String> changes;

    private boolean dryRun;

    /** Human-readable summary; also the message shown when nothing matched. */
    private String message;
}
