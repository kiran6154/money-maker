package com.moneymaker.journal;

/**
 * What an observation row describes.
 *
 * <p>CANDIDATE is the one that makes counterfactuals possible: every leg the
 * pipeline evaluated is journalled with the same feature set as the leg it
 * actually traded, so "what would have happened on the strikes we passed over"
 * is a query rather than another backtest.
 */
public enum ObservationKind {

    /** A leg evaluated at this tick. `selected` says whether it was traded. */
    CANDIDATE,

    /** The moment a position was opened. */
    ENTRY,

    /** A sample taken while a position was open. */
    MONITOR,

    /** The moment a position was closed. */
    EXIT,

    /** A discrete state change (BOS, CHoCH, SMA flip, ...) carrying event_type. */
    EVENT
}
