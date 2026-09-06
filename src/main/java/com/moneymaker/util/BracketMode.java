package com.moneymaker.util;

import java.util.Locale;

/**
 * Which of a config's two bracket columns a strategy exits on.
 *
 * <p>Since changeset 027 every {@code trade_config} carries both shapes of each
 * bracket side — the absolute {@code target} / {@code stop_loss} points and the
 * premium-relative {@code target_pct} / {@code sl_pct} — and until changeset 041
 * the choice between them was an unwritten rule inside
 * {@code OrderService.bracketAtEntry}: a percentage silently won whenever one
 * was set. That left the points column populated, editable in the admin UI, and
 * dead. This enum is that rule promoted to a setting, stored per strategy on
 * {@code strategy_defaults.target_mode} / {@code sl_mode}.</p>
 *
 * <p>Parsing and formatting live here and nowhere else, the same
 * one-column-one-owner rule {@link StrategyIds} and {@link TrailLadder} follow
 * for their columns.</p>
 */
public enum BracketMode {

    /**
     * Exit on the absolute premium-points column ({@code target} /
     * {@code stop_loss}).
     *
     * <p>Falls back to the percentage when the points column is unset, rather
     * than resolving to no bracket at all: {@code PositionService.thresholdBreach}
     * reads a null target or stop as "never breaches", so an unset column in this
     * mode would silently remove that exit for the life of the trade.</p>
     */
    POINTS,

    /**
     * Exit on a fraction of the premium the trade opened at ({@code target_pct} /
     * {@code sl_pct}), falling back to the absolute column when no percentage is
     * set.
     *
     * <p>This is exactly the pre-041 behaviour, which is why it is the default
     * for every existing row and for any strategy with no {@code strategy_defaults}
     * row at all — adding the switch changes no ledger until someone flips it.</p>
     */
    PERCENT,
    /**
     * No bracket on this side (changeset 048): the trade opens with a null
     * target or a null fixed stop, which {@code PositionService.thresholdBreach}
     * reads as "never breaches". Strategy 8 uses it for its target — the
     * chandelier trail is its only profit-taking exit. Not a fallback like the
     * other two: NONE means none even when the columns are populated.
     */
    NONE;

    /**
     * The mode a stored column value names.
     *
     * <p>{@code null} / blank reads as {@link #PERCENT} — the legacy rule — so a
     * strategy that has no {@code strategy_defaults} row keeps the bracket it has
     * today. An unrecognised value throws rather than quietly defaulting, so
     * {@code "POINT"} or {@code "PCT"} is a typo that must be visible. Callers
     * choose how loud to be, and the two live ones differ deliberately:
     * {@code StrategyDefaultsAdminService} lets it reject the save, because an
     * interactive edit has a human attached to correct it, while
     * {@code OrderService} logs it and degrades to {@link #PERCENT} rather than
     * blocking the trade — mirroring how it already handles a malformed
     * {@code trail_ladder}. The Strategy bracket panel writes only canonical
     * values, so a bad one now means the column was hand-edited in SQL.</p>
     *
     * @throws IllegalArgumentException if {@code raw} is non-blank and names no mode
     */
    public static BracketMode parse(String raw) {
        if (raw == null || raw.isBlank()) {
            return PERCENT;
        }
        String token = raw.trim().toUpperCase(Locale.ROOT);
        for (BracketMode mode : values()) {
            if (mode.name().equals(token)) {
                return mode;
            }
        }
        throw new IllegalArgumentException(
                "unknown bracket mode \"" + raw + "\" — expected POINTS or PERCENT (or NONE)");
    }
}
