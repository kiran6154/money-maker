package com.moneymaker.tradeconfig.dto;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * Bulk edit of one field-set across many trade configs in a single call —
 * the "retune every AUTO config's bracket at once" provision.
 *
 * <p><b>Selector</b>: {@code source} (defaults to {@code AUTO_DOWNTREND}, so an
 * incomplete request can only reach regenerable detector output — MANUAL is an
 * explicit opt-in, same contract as the bulk delete), an optional
 * {@code strategyId} (matches configs tagged with that strategy, or carrying it
 * as their primary), and an optional {@code fromDate}/{@code toDate}
 * trading-date window (both or neither).</p>
 *
 * <p><b>Fields</b>: {@code null} always means <i>leave unchanged</i> — this is
 * a patch, not a replacement, so a request naming only {@code slPct} touches
 * nothing else. The one field needing a "clear" spelling is
 * {@link #trailLadder}: an empty string removes the ladder (the fixed stop then
 * applies for the whole trade), {@code null} keeps whatever each row has.
 * Every supported field is either snapshotted onto the order at entry (the
 * bracket) or an entry gate (the premium band, {@code maxLoss}), so applying
 * this while trades are open cannot re-price an open position — the same
 * reasoning that keeps these fields out of the single-edit confirmation
 * dialog.</p>
 */
@Data
public class BulkUpdateRequestDTO {

    /** Which origin the selector may reach. Defaults to AUTO_DOWNTREND. */
    private AutoDeleteRequestDTO.Source source = AutoDeleteRequestDTO.Source.AUTO_DOWNTREND;

    /**
     * Only configs this strategy runs — tagged in {@code strategy_ids}, or the
     * primary {@code stratergy_id} for untagged rows. {@code null} = any.
     */
    private Integer strategyId;

    /** Inclusive trading-date window. Both set, or both null (= every date). */
    private LocalDate fromDate;
    private LocalDate toDate;

    /**
     * Defaults to {@code true}: an incomplete or malformed call reports what it
     * would change instead of changing it. The UI previews first so the count
     * confirmed is the server's own.
     */
    private boolean dryRun = true;

    /* ---------- fields to set; null = leave unchanged ---------- */

    /** Absolute target in premium points (the fallback bracket). */
    private BigDecimal target;
    /** Absolute stop-loss in premium points. */
    private BigDecimal stopLoss;
    /** Target as a fraction of entry premium ({@code 0.20} = 20%); overrides {@code target}. */
    private BigDecimal targetPct;
    /** Stop-loss as a fraction of entry premium. */
    private BigDecimal slPct;
    /** Ceiling in premium points on the resolved stop. */
    private BigDecimal maxSlPoints;
    /** Max loss cap for the config's day. */
    private BigDecimal maxLoss;
    /** Premium band bounds. Each row's effective band is re-checked after applying. */
    private BigDecimal minOptionPrice;
    private BigDecimal maxOptionPrice;
    /**
     * Trailing rungs as {@code "25:2,50:25"}. Empty string = remove the ladder;
     * {@code null} = leave each row's ladder as it is.
     */
    private String trailLadder;
}
