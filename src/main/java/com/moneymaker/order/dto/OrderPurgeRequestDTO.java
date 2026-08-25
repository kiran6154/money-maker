package com.moneymaker.order.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.time.LocalDate;

/**
 * Selector for clearing rows out of the {@code trade_order} ledger.
 *
 * <p>Scoped by {@code entry_time} — the same axis the ledger view filters on —
 * so what you purge is what the screen was showing. Both bounds are optional and
 * inclusive; omitting both clears the whole ledger, which is why
 * {@link #dryRun} defaults to {@code true}.</p>
 *
 * <p>This deletes trade history and touches no {@code trade_config} rows. The
 * bulk config delete is the mirror image: it starts from configs and can take
 * their trades with it.</p>
 */
@Data
public class OrderPurgeRequestDTO {

    /** Inclusive lower bound on {@code entry_time}'s date. Null = no lower bound. */
    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd")
    private LocalDate fromDate;

    /** Inclusive upper bound on {@code entry_time}'s date. Null = no upper bound. */
    @JsonFormat(shape = JsonFormat.Shape.STRING, pattern = "yyyy-MM-dd")
    private LocalDate toDate;

    /**
     * Defaults to {@code true} so an incomplete call previews instead of wiping
     * the ledger. The UI always previews first and confirms the server's count.
     */
    private boolean dryRun = true;

    /**
     * OPEN trades are skipped unless this is set. In live mode an OPEN row is a
     * real broker position that {@code PositionScheduler} is still monitoring —
     * deleting it makes the app forget a position that is still in the market.
     */
    private boolean includeOpen = false;
}
