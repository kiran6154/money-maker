package com.moneymaker.state;

import com.moneymaker.entity.AlertState;
import com.moneymaker.repository.AlertStateRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.Objects;

/**
 * Persistent "once per trading-date" gate. Any caller that wants to fire a
 * side effect (log, telegram, DB write, etc.) at most once per
 * {@code (alertKey, date)} pair across the JVM lifetime <i>and</i> across
 * restarts wraps the side effect in:
 *
 * <pre>{@code
 *   if (dailyEventGuard.firstTime("trade-configs", date)) {
 *       // do the work
 *   }
 * }</pre>
 *
 * <p>State lives in {@code alert_state} (Liquibase 012). The unique constraint
 * on {@code (alert_key, alert_date)} keeps the answer authoritative even if
 * two threads race — only the first INSERT wins; the loser sees the row
 * already exists (or catches the constraint violation) and returns false.
 *
 * <p>Restart-safe: a JVM restart preserves prior {@code true} results because
 * the row stays in the table.
 */
@Slf4j
@Service
public class DailyEventGuard {

    private final AlertStateRepository repository;

    public DailyEventGuard(AlertStateRepository repository) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
    }

    /**
     * Returns {@code true} the first time this is called for the given
     * {@code (alertKey, date)} pair; {@code false} on every subsequent call,
     * including calls in a different JVM instance after a restart.
     *
     * <p>Side effect: on the {@code true} path, a row is persisted into
     * {@code alert_state}. Failing inserts (e.g. race with a concurrent
     * caller) are treated as "already fired" and return {@code false}.
     */
    public boolean firstTime(String alertKey, LocalDate date) {
        if (alertKey == null || alertKey.isBlank() || date == null) return false;

        if (repository.existsByAlertKeyAndAlertDate(alertKey, date)) {
            return false;
        }
        AlertState state = new AlertState();
        state.setAlertKey(alertKey);
        state.setAlertDate(date);
        state.setFiredAt(LocalDateTime.now());
        try {
            repository.save(state);
            return true;
        } catch (DataIntegrityViolationException ex) {
            // Lost the race to another caller — they already inserted with the
            // same key + date. Treat as already-fired.
            log.debug("DailyEventGuard: race for alertKey={} date={} — treating as already-fired",
                    alertKey, date);
            return false;
        }
    }

    /** True if this {@code (alertKey, date)} has already been marked fired, without inserting. */
    public boolean alreadyFired(String alertKey, LocalDate date) {
        if (alertKey == null || date == null) return false;
        return repository.existsByAlertKeyAndAlertDate(alertKey, date);
    }
}
