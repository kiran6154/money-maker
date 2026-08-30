package com.moneymaker.journal;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.BatchPreparedStatementSetter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.sql.Types;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Writes {@link JournalObservation} rows, batched.
 *
 * <h3>Why batched, and why JDBC</h3>
 * Journalling every evaluated leg is roughly 24 legs × 73 ticks × 79 days ≈ 138k
 * rows per backtest run, and more once a config carries several tagged
 * strategies. These are writes on the trading hot loop, where DB round-trips have
 * already been measured as the dominant cost (see {@code BACKTEST_PERFORMANCE.md}
 * Phase 6a). Rows therefore accumulate in a buffer and go out in one multi-row
 * insert per {@link #BATCH_SIZE}.
 *
 * <h3>Observation must never break trading</h3>
 * Every public method swallows its own failures. A journal that cannot write is
 * a gap in analysis; an exception propagating out of it would be a lost trade on
 * a live account. Failures are logged once per run rather than per row, because
 * a broken journal would otherwise produce one log line per tick.
 *
 * <h3>Enabling</h3>
 * {@code journal.enabled} (default {@code true}). Turning it off makes every
 * record call a no-op, so a timing run can exclude journal cost entirely.
 */
@Slf4j
@Service
public class JournalRecorder {

    /** Rows buffered before a flush. */
    private static final int BATCH_SIZE = 500;

    private static final String INSERT = """
            INSERT INTO journal_observation
                (run_id, observed_at, confirmable_at, kind, event_type, direction,
                 strategy_id, trade_config_id, trade_order_id,
                 series, instrument_name, option_token, option_type, strike,
                 interval_minutes, selected, features)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """;

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final List<FeatureContributor> contributors;
    private final boolean enabled;

    /** Buffer. Guarded by {@code this} — the pipeline is single-threaded per tick,
     *  but a live cron and a manual backtest can overlap in the same JVM. */
    private final List<JournalObservation> buffer = new ArrayList<>(BATCH_SIZE);

    private volatile String runId = defaultRunId();
    private volatile boolean writeFailureLogged = false;

    public JournalRecorder(JdbcTemplate jdbcTemplate,
                           ObjectMapper objectMapper,
                           List<FeatureContributor> contributors,
                           @Value("${journal.enabled:true}") boolean enabled) {
        this.jdbcTemplate = Objects.requireNonNull(jdbcTemplate, "jdbcTemplate must not be null");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
        this.contributors = contributors == null ? List.of() : contributors;
        this.enabled = enabled;
        log.info("JournalRecorder enabled={} contributors={}", enabled,
                this.contributors.stream().map(FeatureContributor::name).toList());
    }

    public boolean isEnabled() {
        return enabled;
    }

    /**
     * Names the run every subsequent observation belongs to, and flushes anything
     * left from a previous one. Called by {@code BacktestAnalysisService} at run
     * start; live falls back to the date.
     */
    public void beginRun(String runId) {
        if (!enabled) return;
        flush();
        this.runId = (runId == null || runId.isBlank()) ? defaultRunId() : runId;
        this.writeFailureLogged = false;
        log.info("[journal] run started: {}", this.runId);
    }

    /** Flushes the tail of a run. Safe to call more than once. */
    public void endRun() {
        if (!enabled) return;
        flush();
        log.info("[journal] run ended: {}", runId);
    }

    /**
     * Runs every {@link FeatureContributor} over {@code context} and buffers the
     * resulting row.
     *
     * <p>A contributor that throws is skipped with its name logged, rather than
     * being allowed to take the tick down with it — the SPI contract says never
     * throw, and this is the enforcement.
     */
    public void record(ObservationContext context, boolean selected) {
        if (!enabled || context == null) return;
        try {
            Map<String, Object> features = collectFeatures(context);
            buffer(toObservation(context, selected, features, null, null, null));
        } catch (Exception ex) {
            logWriteFailure("building observation", ex);
        }
    }

    /**
     * Buffers a discrete state change (BOS, CHoCH, SMA flip, …) observed while a
     * position was open.
     *
     * @param confirmableAt when the fact became knowable — for structure events
     *                      this is later than {@code observedAt}, and analysis
     *                      must filter on it
     */
    public void recordEvent(ObservationContext context,
                            String eventType,
                            String direction,
                            LocalDateTime confirmableAt,
                            Map<String, Object> extraFeatures) {
        if (!enabled || context == null) return;
        try {
            Map<String, Object> features = new LinkedHashMap<>();
            if (extraFeatures != null) features.putAll(extraFeatures);
            buffer(toObservation(context, false, features, eventType, direction, confirmableAt));
        } catch (Exception ex) {
            logWriteFailure("building event", ex);
        }
    }

    private Map<String, Object> collectFeatures(ObservationContext context) {
        Map<String, Object> all = new LinkedHashMap<>();
        for (FeatureContributor c : contributors) {
            try {
                Map<String, Object> part = c.contribute(context);
                if (part != null && !part.isEmpty()) {
                    all.putAll(part);
                }
            } catch (Exception ex) {
                // One misbehaving contributor must not cost the whole observation.
                log.debug("[journal] contributor {} threw — skipped: {}", c.name(), ex.toString());
            }
        }
        return all;
    }

    private JournalObservation toObservation(ObservationContext ctx,
                                             boolean selected,
                                             Map<String, Object> features,
                                             String eventType,
                                             String direction,
                                             LocalDateTime confirmableAt) throws Exception {
        return new JournalObservation(
                runId,
                ctx.observedAt(),
                confirmableAt,
                eventType != null ? ObservationKind.EVENT : ctx.kind(),
                eventType,
                direction,
                ctx.strategyId(),
                ctx.tradeConfigId(),
                ctx.order() != null ? ctx.order().getId() : null,
                ctx.optionToken() != null ? "OPTION" : "UNDERLYING",
                ctx.instrumentName(),
                ctx.optionToken(),
                ctx.optionType(),
                ctx.strike(),
                ctx.intervalMinutes(),
                selected,
                features == null || features.isEmpty() ? null : objectMapper.writeValueAsString(features));
    }

    private void buffer(JournalObservation observation) {
        List<JournalObservation> toWrite = null;
        synchronized (this) {
            buffer.add(observation);
            if (buffer.size() >= BATCH_SIZE) {
                toWrite = new ArrayList<>(buffer);
                buffer.clear();
            }
        }
        if (toWrite != null) {
            write(toWrite);
        }
    }

    /** Writes whatever is buffered. Called at batch boundaries and at run end. */
    public void flush() {
        if (!enabled) return;
        List<JournalObservation> toWrite;
        synchronized (this) {
            if (buffer.isEmpty()) return;
            toWrite = new ArrayList<>(buffer);
            buffer.clear();
        }
        write(toWrite);
    }

    private void write(List<JournalObservation> rows) {
        try {
            jdbcTemplate.batchUpdate(INSERT, new BatchPreparedStatementSetter() {
                @Override
                public void setValues(PreparedStatement ps, int i) throws SQLException {
                    JournalObservation o = rows.get(i);
                    ps.setString(1, o.runId());
                    ps.setTimestamp(2, Timestamp.valueOf(o.observedAt()));
                    if (o.confirmableAt() == null) ps.setNull(3, Types.TIMESTAMP);
                    else ps.setTimestamp(3, Timestamp.valueOf(o.confirmableAt()));
                    ps.setString(4, o.kind().name());
                    ps.setString(5, o.eventType());
                    ps.setString(6, o.direction());
                    setInt(ps, 7, o.strategyId());
                    setInt(ps, 8, o.tradeConfigId());
                    if (o.tradeOrderId() == null) ps.setNull(9, Types.BIGINT);
                    else ps.setLong(9, o.tradeOrderId());
                    ps.setString(10, o.series());
                    ps.setString(11, o.instrumentName());
                    ps.setString(12, o.optionToken());
                    ps.setString(13, o.optionType());
                    setInt(ps, 14, o.strike());
                    setInt(ps, 15, o.intervalMinutes());
                    ps.setBoolean(16, o.selected());
                    ps.setString(17, o.featuresJson());
                }

                @Override
                public int getBatchSize() {
                    return rows.size();
                }
            });
        } catch (Exception ex) {
            logWriteFailure("flushing " + rows.size() + " row(s)", ex);
        }
    }

    private static void setInt(PreparedStatement ps, int index, Integer value) throws SQLException {
        if (value == null) ps.setNull(index, Types.INTEGER);
        else ps.setInt(index, value);
    }

    /** Once per run, not once per row — a broken journal would otherwise flood the log. */
    private void logWriteFailure(String what, Exception ex) {
        if (writeFailureLogged) {
            log.debug("[journal] {} failed again: {}", what, ex.toString());
            return;
        }
        writeFailureLogged = true;
        log.error("[journal] {} failed — journalling is degraded for run {}. Trading is unaffected.",
                what, runId, ex);
    }

    /** Live sessions have no explicit run; the date is a stable enough grouping. */
    private static String defaultRunId() {
        return "live-" + LocalDate.now();
    }

    @PreDestroy
    void flushOnShutdown() {
        flush();
    }
}
