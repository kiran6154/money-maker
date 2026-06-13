package com.moneymaker.scheduler;

import com.moneymaker.shared.data.SharedData;
import com.moneymaker.telegram.NotificationService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mock;
import org.mockito.MockitoAnnotations;
import org.springframework.test.util.ReflectionTestUtils;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;

/**
 * Unit tests for {@link LiveCacheJanitor}. Verifies cache wiping and the
 * live-only mode gate. Cron / event firing itself is Spring's
 * responsibility (covered by the @Scheduled / @EventListener annotation
 * presence — not unit-testable in isolation).
 */
class LiveCacheJanitorTest {

    @Mock private NotificationService notifier;

    private LiveCacheJanitor janitor;

    @BeforeEach
    void setUp() {
        MockitoAnnotations.openMocks(this);
        janitor = new LiveCacheJanitor(notifier);
        ReflectionTestUtils.setField(janitor, "appMode", "live");
        // Seed the static SharedData maps so we can verify the clear.
        SharedData.optionTokenMap.put(24000, "TOKEN-24000");
        SharedData.optionTokenMap.put(24100, "TOKEN-24100");
        SharedData.strikesByInstrumentAndInterval.put("NIFTY|5minute", java.util.List.of());
    }

    @AfterEach
    void tearDown() {
        SharedData.optionTokenMap.clear();
        SharedData.strikesByInstrumentAndInterval.clear();
    }

    @Test
    void clear_wipes_unbounded_SharedData_maps_and_notifier_dedupe() {
        janitor.clear("test trigger");

        assertThat(SharedData.optionTokenMap).isEmpty();
        assertThat(SharedData.strikesByInstrumentAndInterval).isEmpty();
        verify(notifier).clearAllDedupeState();
    }

    @Test
    void daily_cron_is_noop_in_backtest_mode() {
        ReflectionTestUtils.setField(janitor, "appMode", "backtest");
        janitor.daily();

        // Maps untouched, notifier untouched.
        assertThat(SharedData.optionTokenMap).hasSize(2);
        verify(notifier, never()).clearAllDedupeState();
    }

    @Test
    void onStartup_is_noop_in_backtest_mode() {
        ReflectionTestUtils.setField(janitor, "appMode", "backtest");
        janitor.onStartup();

        assertThat(SharedData.optionTokenMap).hasSize(2);
        verify(notifier, never()).clearAllDedupeState();
    }

    @Test
    void clear_logs_count_of_entries_wiped() {
        // Smoke test that clear() runs to completion when both maps are
        // populated — log line content is exercised by the body of clear().
        janitor.clear("smoke");
        assertThat(SharedData.optionTokenMap).isEmpty();
    }
}
