package com.moneymaker.tradeconfig.dto;

import java.time.LocalDate;
import java.util.List;

/**
 * Outcome of a day-to-day config clone (GAPS #9).
 *
 * <p>Shaped like {@link AutoDeleteResultDTO}: a {@code dryRun} pass returns the
 * same object with the same counts and only {@code created} empty, so the UI can
 * preview and then confirm against the server's own numbers rather than its own
 * guess.
 *
 * @param fromDate        source trading date
 * @param toDate          destination trading date
 * @param matched         configs found on {@code fromDate} (before any filtering)
 * @param skippedRetired  configs skipped because they are retired ({@code is_active=false})
 * @param skippedExisting configs skipped because {@code toDate} already has an
 *                        equivalent one — same instrument, side, transaction type
 *                        and primary strategy
 * @param cloned          how many were (or would be) created
 * @param created         ids of the new rows; empty on a dry run
 * @param timeframesCopied {@code sma_timeframe} child rows carried across
 * @param dryRun          whether anything was actually written
 * @param summary         one line for the UI
 */
public record CloneResultDTO(
        LocalDate fromDate,
        LocalDate toDate,
        int matched,
        int skippedRetired,
        int skippedExisting,
        int cloned,
        List<Integer> created,
        int timeframesCopied,
        boolean dryRun,
        String summary) {
}
