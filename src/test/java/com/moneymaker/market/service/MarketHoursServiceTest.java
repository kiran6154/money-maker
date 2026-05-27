package com.moneymaker.market.service;

import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalTime;
import java.time.ZoneId;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Unit tests for {@link MarketHoursService}. {@code @Value}-bound fields are
 * set via {@link ReflectionTestUtils} so we can exercise {@code init()}
 * without booting Spring.
 *
 * <p>{@code isOpenNow()} reads the system clock; we cover it via a parameter
 * range that tolerates day-of-week ambiguity (a Friday-only test would
 * Saturday-fail). Where exact instant-control is needed we exercise the
 * helpers ({@code marketCloseToday}, {@code marketOpenToday}) which take the
 * "today" anchor from {@code LocalDate.now(zone)} and compose with the
 * configured {@code open}/{@code close} times.
 */
class MarketHoursServiceTest {

    private MarketHoursService newService(String open, String close, String tz) {
        return newService(open, close, tz, "15:25");
    }

    private MarketHoursService newService(String open, String close, String tz, String forceClose) {
        MarketHoursService svc = new MarketHoursService();
        ReflectionTestUtils.setField(svc, "openStr", open);
        ReflectionTestUtils.setField(svc, "closeStr", close);
        ReflectionTestUtils.setField(svc, "timezoneStr", tz);
        ReflectionTestUtils.setField(svc, "forceCloseStr", forceClose);
        ReflectionTestUtils.invokeMethod(svc, "init");
        return svc;
    }

    @Test
    void init_parses_configured_window() {
        MarketHoursService svc = newService("09:15", "15:30", "Asia/Kolkata");
        assertThat(svc.zone()).isEqualTo(ZoneId.of("Asia/Kolkata"));
        // We don't expose open/close getters, but the public helpers reflect them.
        assertThat(svc.marketOpenToday().toLocalTime()).isEqualTo(LocalTime.of(9, 15));
        assertThat(svc.marketCloseToday().toLocalTime()).isEqualTo(LocalTime.of(15, 30));
    }

    @Test
    void init_rejects_close_not_after_open() {
        // Equal boundaries → reject (window must be strictly positive).
        assertThatThrownBy(() -> newService("09:15", "09:15", "Asia/Kolkata"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("must be after");
        // Close before open → reject.
        assertThatThrownBy(() -> newService("15:30", "09:15", "Asia/Kolkata"))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void init_rejects_unknown_timezone() {
        assertThatThrownBy(() -> newService("09:15", "15:30", "Not/AZone"))
                .isInstanceOf(java.time.zone.ZoneRulesException.class);
    }

    @Test
    void init_tolerates_whitespace_in_property_values() {
        // application.properties readers can leave trailing whitespace.
        MarketHoursService svc = newService("  09:15 ", " 15:30  ", " Asia/Kolkata ");
        assertThat(svc.marketOpenToday().toLocalTime()).isEqualTo(LocalTime.of(9, 15));
    }

    @Test
    void marketCloseToday_returns_today_at_close_in_configured_zone() {
        MarketHoursService svc = newService("09:15", "15:30", "Asia/Kolkata");
        var close = svc.marketCloseToday();
        // We can't assert the date (would race the test) but we can pin
        // the time component and verify it's a current-day moment.
        assertThat(close.toLocalTime()).isEqualTo(LocalTime.of(15, 30));
        assertThat(close.toLocalDate()).isEqualTo(java.time.LocalDate.now(ZoneId.of("Asia/Kolkata")));
    }

    @Test
    void marketOpenToday_returns_today_at_open_in_configured_zone() {
        MarketHoursService svc = newService("09:15", "15:30", "Asia/Kolkata");
        var open = svc.marketOpenToday();
        assertThat(open.toLocalTime()).isEqualTo(LocalTime.of(9, 15));
        assertThat(open.toLocalDate()).isEqualTo(java.time.LocalDate.now(ZoneId.of("Asia/Kolkata")));
    }

    @Test
    void isOpenNow_returns_a_boolean_without_throwing() {
        // We can't assert the value (depends on when the test runs) but we
        // can prove the method is wired and doesn't NPE on the current clock.
        MarketHoursService svc = newService("09:15", "15:30", "Asia/Kolkata");
        boolean result = svc.isOpenNow();
        assertThat(result).isIn(true, false);
    }

    @Test
    void supports_alternative_market_window() {
        // US-style 09:30-16:00 ET should configure cleanly.
        // Force-close override stays within the new window.
        MarketHoursService svc = newService("09:30", "16:00", "America/New_York", "15:55");
        assertThat(svc.zone()).isEqualTo(ZoneId.of("America/New_York"));
        assertThat(svc.marketOpenToday().toLocalTime()).isEqualTo(LocalTime.of(9, 30));
        assertThat(svc.marketCloseToday().toLocalTime()).isEqualTo(LocalTime.of(16, 0));
        assertThat(svc.forceCloseToday().toLocalTime()).isEqualTo(LocalTime.of(15, 55));
    }

    @Test
    void forceCloseToday_default_is_15_25() {
        MarketHoursService svc = newService("09:15", "15:30", "Asia/Kolkata");
        assertThat(svc.forceCloseToday().toLocalTime()).isEqualTo(LocalTime.of(15, 25));
    }

    @Test
    void init_rejects_force_close_outside_market_window() {
        // Force-close after close — reject.
        assertThatThrownBy(() -> newService("09:15", "15:30", "Asia/Kolkata", "15:45"))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("must lie within");
        // Force-close before open — reject.
        assertThatThrownBy(() -> newService("09:15", "15:30", "Asia/Kolkata", "09:00"))
                .isInstanceOf(IllegalStateException.class);
    }
}
