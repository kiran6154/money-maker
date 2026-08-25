package com.moneymaker.order.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

/**
 * Outcome of a ledger purge. Same shape for a dry run and a real one, so the
 * confirm dialog and the result toast render from one payload.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class OrderPurgeResultDTO {

    /** Rows matching the date selector, OPEN ones included. */
    private long matched;

    /** Rows actually removed. Always 0 on a dry run. */
    private long deleted;

    /** Rows that would go — equals {@code deleted} after a real run. */
    private long deletable;

    /** Per entry-date breakdown of {@code deletable}, for the dialog. */
    private Map<LocalDate, Long> byDate;

    /**
     * Matched rows still OPEN. Skipped unless {@code includeOpen} was set —
     * see {@link OrderPurgeRequestDTO#isIncludeOpen()}.
     */
    private long openRows;
    private long skippedOpen;
    private List<Long> skippedIds;

    private boolean dryRun;
    private String message;
}
