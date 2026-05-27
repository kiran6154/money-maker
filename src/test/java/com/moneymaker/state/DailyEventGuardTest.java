package com.moneymaker.state;

import com.moneymaker.entity.AlertState;
import com.moneymaker.repository.AlertStateRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.dao.DataIntegrityViolationException;

import java.time.LocalDate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link DailyEventGuard}.
 *
 * <p>Three contract surfaces:
 * <ol>
 *   <li>{@code firstTime} returns {@code true} once and {@code false} after;
 *       a row is persisted on the first call.</li>
 *   <li>Concurrent inserts (DataIntegrityViolationException) are treated as
 *       "already fired" — the racing loser returns {@code false}, not throws.</li>
 *   <li>Null / blank inputs are defensively rejected without throwing
 *       (return {@code false}).</li>
 * </ol>
 */
class DailyEventGuardTest {

    @Mock private AlertStateRepository repository;

    private DailyEventGuard guard;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        guard = new DailyEventGuard(repository);
    }

    @Test
    void firstTime_returns_true_and_persists_row_when_no_prior_record() {
        when(repository.existsByAlertKeyAndAlertDate("day-summary", LocalDate.of(2026, 4, 1)))
                .thenReturn(false);

        boolean result = guard.firstTime("day-summary", LocalDate.of(2026, 4, 1));

        assertThat(result).isTrue();
        ArgumentCaptor<AlertState> captor = ArgumentCaptor.forClass(AlertState.class);
        verify(repository).save(captor.capture());
        AlertState saved = captor.getValue();
        assertThat(saved.getAlertKey()).isEqualTo("day-summary");
        assertThat(saved.getAlertDate()).isEqualTo(LocalDate.of(2026, 4, 1));
        assertThat(saved.getFiredAt()).isNotNull();
    }

    @Test
    void firstTime_returns_false_when_row_already_exists() {
        when(repository.existsByAlertKeyAndAlertDate("trade-configs", LocalDate.of(2026, 4, 1)))
                .thenReturn(true);

        boolean result = guard.firstTime("trade-configs", LocalDate.of(2026, 4, 1));

        assertThat(result).isFalse();
        verify(repository, never()).save(any());
    }

    @Test
    void firstTime_treats_concurrent_insert_race_as_already_fired() {
        // existsBy returned false (we won the read), but the save lost the
        // unique-constraint race to a concurrent caller.
        when(repository.existsByAlertKeyAndAlertDate("k", LocalDate.of(2026, 4, 1))).thenReturn(false);
        when(repository.save(any(AlertState.class)))
                .thenThrow(new DataIntegrityViolationException("UNIQUE constraint violated"));

        boolean result = guard.firstTime("k", LocalDate.of(2026, 4, 1));

        assertThat(result).isFalse();
    }

    @Test
    void firstTime_rejects_null_key() {
        assertThat(guard.firstTime(null, LocalDate.of(2026, 4, 1))).isFalse();
        verify(repository, never()).existsByAlertKeyAndAlertDate(any(), any());
    }

    @Test
    void firstTime_rejects_blank_key() {
        assertThat(guard.firstTime("", LocalDate.of(2026, 4, 1))).isFalse();
        assertThat(guard.firstTime("   ", LocalDate.of(2026, 4, 1))).isFalse();
        verify(repository, never()).existsByAlertKeyAndAlertDate(any(), any());
    }

    @Test
    void firstTime_rejects_null_date() {
        assertThat(guard.firstTime("k", null)).isFalse();
        verify(repository, never()).existsByAlertKeyAndAlertDate(any(), any());
    }

    @Test
    void alreadyFired_passes_through_to_repository() {
        when(repository.existsByAlertKeyAndAlertDate("k", LocalDate.of(2026, 4, 1))).thenReturn(true);
        assertThat(guard.alreadyFired("k", LocalDate.of(2026, 4, 1))).isTrue();
    }

    @Test
    void alreadyFired_is_safe_for_null_inputs() {
        assertThat(guard.alreadyFired(null, LocalDate.of(2026, 4, 1))).isFalse();
        assertThat(guard.alreadyFired("k", null)).isFalse();
    }
}
