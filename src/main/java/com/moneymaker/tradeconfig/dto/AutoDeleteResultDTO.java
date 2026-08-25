package com.moneymaker.tradeconfig.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

/**
 * Outcome of a bulk delete. Identical shape for a dry run and a real one, so the
 * confirm dialog and the result toast render from the same payload — and so the
 * count you approve is the count the server matched.
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class AutoDeleteResultDTO {

    /** Configs matching the selector. Equals {@code deletedConfigs} unless dry run. */
    private long matched;
    private long deletedConfigs;
    private long deletedTimeframes;

    /** Per trading-date breakdown, for the dialog's detail list. */
    private Map<LocalDate, Long> byDate;

    /** Ids that were (or would be) removed — handy for auditing a surprise result. */
    private List<Integer> ids;

    /**
     * Matched configs that {@code trade_order} rows reference — reported whether
     * or not {@code force} was set, so the confirm dialog can say what is at stake
     * before the user opts in.
     */
    private long configsWithTrades;

    /**
     * Trade rows attached to {@link #configsWithTrades}. Deleted along with their
     * configs when {@code force} is set; left untouched otherwise.
     */
    private long tradeOrders;

    /**
     * Configs that matched the selector but were left alone because
     * {@code trade_order} rows reference them. The single-config delete refuses
     * these outright to preserve the audit trail; a bulk delete skips and reports
     * them instead, so one traded config cannot block the whole batch.
     *
     * <p>Zero when {@code force} was set — nothing is skipped then; look at
     * {@link #configsWithTrades} / {@link #tradeOrders} for what went with them.</p>
     */
    private long skippedWithTrades;
    private List<Integer> skippedIds;

    private boolean dryRun;

    /** Human-readable summary; also the message shown when nothing matched. */
    private String message;
}
