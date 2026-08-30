package com.moneymaker.journal;

import java.time.LocalDateTime;

/**
 * One row destined for {@code journal_observation}: a single observed leg at a
 * single moment, with its features already rendered to JSON.
 *
 * <p>A plain record rather than a JPA entity on purpose. The recorder writes
 * these in JDBC batches — the volume is roughly 138k rows per backtest run, and
 * {@code GenerationType.IDENTITY} disables Hibernate insert batching outright
 * (the same trap that made the CSV import take hours before changeset 029). Read
 * paths for analysis go through SQL or an export, not through this type.
 *
 * <p>Immutable, so an observation cannot be altered between capture and flush.
 *
 * @param runId          groups one backtest run or live session
 * @param observedAt     the tick this row describes
 * @param confirmableAt  structure rows only: when the fact became knowable.
 *                       Analysis must filter on this, not {@code observedAt}
 * @param selected       CANDIDATE rows: was this leg actually traded at this tick
 * @param featuresJson   the {@link FeatureContributor} output, serialised
 */
public record JournalObservation(
        String runId,
        LocalDateTime observedAt,
        LocalDateTime confirmableAt,
        ObservationKind kind,
        String eventType,
        String direction,
        Integer strategyId,
        Integer tradeConfigId,
        Long tradeOrderId,
        String series,
        String instrumentName,
        String optionToken,
        String optionType,
        Integer strike,
        Integer intervalMinutes,
        boolean selected,
        String featuresJson
) {
}
