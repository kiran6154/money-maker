package com.moneymaker.tradeconfig.service;

import java.util.List;

/**
 * Thrown when an edit is legal but consequential, and the caller has not said
 * they understand the consequence (GAPS #8).
 *
 * <p>Distinct from {@link IllegalStateException} — which the delete path uses for
 * a refusal — because this is <b>not</b> a refusal. The same request with
 * {@code confirm=true} succeeds. The controller renders it as 409 with the list
 * of changes so the UI can name them in the dialog rather than showing a generic
 * "are you sure?", which is the difference between a warning someone reads and
 * one they click through.
 */
public class ConfirmationRequiredException extends RuntimeException {

    /** Human-readable descriptions of each consequential change, e.g. {@code "lotQuantity: 75 -> 150"}. */
    private final List<String> changes;

    /** How many trades on this config are currently OPEN. */
    private final long openTrades;

    public ConfirmationRequiredException(String message, List<String> changes, long openTrades) {
        super(message);
        this.changes = List.copyOf(changes);
        this.openTrades = openTrades;
    }

    public List<String> getChanges() {
        return changes;
    }

    public long getOpenTrades() {
        return openTrades;
    }
}
