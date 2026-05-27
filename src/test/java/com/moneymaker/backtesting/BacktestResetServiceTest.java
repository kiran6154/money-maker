package com.moneymaker.backtesting;

import com.moneymaker.scheduler.TradeConfigScheduler;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.jdbc.core.JdbcTemplate;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * Unit tests for {@link BacktestResetService}. JdbcTemplate is mocked so we
 * verify the exact SQL + arguments without needing a database; the real
 * JDBC round-trip is exercised by the parity test suite (M2).
 *
 * <p>Mockito strict-stub mode (the Spring Boot default) makes any
 * unmatched-args stub throw. The tests therefore stub per-call with the
 * precise SQL string and assert via {@link org.mockito.Mockito#verify}.
 */
class BacktestResetServiceTest {

    @Mock private JdbcTemplate jdbcTemplate;
    @Mock private TradeConfigScheduler tradeConfigScheduler;
    @Mock private NotificationService notifier;

    private BacktestResetService service;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        service = new BacktestResetService(jdbcTemplate, tradeConfigScheduler, notifier);
    }

    @Test
    void resetRange_issues_DELETE_for_trade_order_with_full_day_window() {
        // lenient() — only this stub's arg shape; the alert_state call is
        // verified separately, not stubbed (default mock returns 0).
        lenient().when(jdbcTemplate.update(
                eq("DELETE FROM trade_order WHERE entry_time BETWEEN ? AND ?"),
                any(Object.class), any(Object.class))).thenReturn(3);

        BacktestResetService.ResetSummary summary = service.resetRange(
                LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 3));

        verify(jdbcTemplate).update(
                eq("DELETE FROM trade_order WHERE entry_time BETWEEN ? AND ?"),
                eq(LocalDate.of(2026, 4, 1).atStartOfDay()),
                eq(LocalDate.of(2026, 4, 3).atTime(LocalTime.MAX)));
        assertThat(summary.tradeOrderRowsDeleted()).isEqualTo(3);
    }

    @Test
    void resetRange_issues_DELETE_for_alert_state_with_date_window() {
        lenient().when(jdbcTemplate.update(
                eq("DELETE FROM alert_state WHERE alert_date BETWEEN ? AND ?"),
                any(Object.class), any(Object.class))).thenReturn(2);

        BacktestResetService.ResetSummary summary = service.resetRange(
                LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 3));

        verify(jdbcTemplate).update(
                eq("DELETE FROM alert_state WHERE alert_date BETWEEN ? AND ?"),
                eq(LocalDate.of(2026, 4, 1)),
                eq(LocalDate.of(2026, 4, 3)));
        assertThat(summary.alertStateRowsDeleted()).isEqualTo(2);
    }

    @Test
    void resetRange_invalidates_in_memory_caches() {
        service.resetRange(LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 3));

        verify(tradeConfigScheduler).invalidateConfigsCache();
        verify(notifier).clearAllDedupeState();
    }

    @Test
    void resetRange_rejects_null_dates() {
        assertThatThrownBy(() -> service.resetRange(null, LocalDate.now()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("required");
        assertThatThrownBy(() -> service.resetRange(LocalDate.now(), null))
                .isInstanceOf(IllegalArgumentException.class);

        verify(jdbcTemplate, never()).update(any(String.class), any(Object.class), any(Object.class));
    }

    @Test
    void resetRange_rejects_reversed_window() {
        assertThatThrownBy(() ->
                service.resetRange(LocalDate.of(2026, 4, 3), LocalDate.of(2026, 4, 1)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("on or before");

        verify(jdbcTemplate, never()).update(any(String.class), any(Object.class), any(Object.class));
    }

    @Test
    void resetRange_summary_carries_input_dates() {
        BacktestResetService.ResetSummary s = service.resetRange(
                LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 3));
        assertThat(s.fromDate()).isEqualTo(LocalDate.of(2026, 4, 1));
        assertThat(s.toDate()).isEqualTo(LocalDate.of(2026, 4, 3));
    }
}
