package com.moneymaker.tradeconfig.dto;

import lombok.Data;

/**
 * The Strategy bracket panel's per-row save: the changeset-041 mode pair.
 *
 * <p>{@code null} = leave unchanged, so a scripted caller can flip one side
 * without restating the other. Blank is <b>not</b> a way to clear a mode — the
 * columns are NOT NULL and "no mode" is not a state the resolver has; the
 * service rejects it rather than silently writing the default.</p>
 *
 * <p>Deliberately only these two fields. {@code transaction_type},
 * {@code max_loss}, the trade counts and {@code opposite_side} decide what
 * trades get taken and stay SQL-only, exactly as the Detection rules panel
 * leaves its thresholds alone.</p>
 */
@Data
public class StrategyBracketModeFormDTO {

    /** {@code POINTS} or {@code PERCENT}; case-insensitive. */
    private String targetMode;

    /** {@code POINTS} or {@code PERCENT}; case-insensitive. */
    private String slMode;
}
