package com.moneymaker.market.service;

import com.moneymaker.strategy.rules.CommonRules;
import com.moneymaker.strategy.rules.RuleContext;
import com.moneymaker.entity.MarketData;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;
import java.time.LocalTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Pins the S5 unification: the session-window times that used to be hardcoded
 * (15:15 close signal in {@code CommonRules}, 09:20/15:20 replay bounds in
 * {@code BacktestAnalysisService}) now derive from {@code app.market.*} via
 * {@link MarketHoursService} — and the <b>defaults reproduce the legacy
 * constants exactly</b>, so unification is not a behaviour change. A default
 * drifting away from its constant is precisely what these tests catch.
 */
class MarketHoursServiceDerivedTimesTest {

    private MarketHoursService service(String open, String close,
                                       int closeSignalOff, int firstTickOff, int lastTickOff) {
        return service(open, close, closeSignalOff, firstTickOff, lastTickOff, "07:50", "15:40");
    }

    private MarketHoursService service(String open, String close,
                                       int closeSignalOff, int firstTickOff, int lastTickOff,
                                       String heartbeatStart, String heartbeatEnd) {
        MarketHoursService s = new MarketHoursService();
        ReflectionTestUtils.setField(s, "openStr", open);
        ReflectionTestUtils.setField(s, "closeStr", close);
        ReflectionTestUtils.setField(s, "timezoneStr", "Asia/Kolkata");
        ReflectionTestUtils.setField(s, "closeSignalOffsetMinutes", closeSignalOff);
        ReflectionTestUtils.setField(s, "replayFirstTickOffsetMinutes", firstTickOff);
        ReflectionTestUtils.setField(s, "replayLastTickOffsetMinutes", lastTickOff);
        ReflectionTestUtils.setField(s, "heartbeatStartStr", heartbeatStart);
        ReflectionTestUtils.setField(s, "heartbeatEndStr", heartbeatEnd);
        ReflectionTestUtils.invokeMethod(s, "init");
        return s;
    }

    @Test
    @DisplayName("defaults reproduce the legacy constants: 15:15 close signal, 09:20-15:20 replay")
    void defaultsReproduceLegacyConstants() {
        MarketHoursService s = service("09:15", "15:30", 15, 5, 10);
        assertThat(s.closeSignalTime()).isEqualTo(LocalTime.of(15, 15));
        assertThat(s.replayFirstTick()).isEqualTo(LocalTime.of(9, 20));
        assertThat(s.replayLastTick()).isEqualTo(LocalTime.of(15, 20));
    }

    @Test
    @DisplayName("changing the window in config moves all three derived times with it")
    void derivedTimesFollowTheConfiguredWindow() {
        MarketHoursService s = service("09:00", "15:00", 15, 5, 10);
        assertThat(s.closeSignalTime()).isEqualTo(LocalTime.of(14, 45));
        assertThat(s.replayFirstTick()).isEqualTo(LocalTime.of(9, 5));
        assertThat(s.replayLastTick()).isEqualTo(LocalTime.of(14, 50));
    }

    @Test
    @DisplayName("an empty replay window fails startup instead of replaying nothing silently")
    void emptyReplayWindowFailsStartup() {
        assertThatThrownBy(() -> service("09:15", "09:30", 15, 20, 20))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("replay window is empty");
    }

    /* ---- CommonRules picks the trigger up from the context ---- */

    private RuleContext ctxAt(LocalDateTime candleTs, LocalTime closeSignal) {
        MarketData md = new MarketData();
        md.setTimestamp(candleTs);
        return new RuleContext(md, 0, java.util.List.of(md), 50, null, candleTs, closeSignal);
    }

    @Test
    @DisplayName("isMarketCloseTime fires on the configured trigger, not the constant")
    void closeSignalHonoursConfiguredTrigger() {
        LocalDateTime at1450 = LocalDateTime.of(2024, 1, 3, 14, 50);
        // Trigger moved earlier than the candle: fires.
        assertThat(CommonRules.isMarketCloseTime(ctxAt(at1450, LocalTime.of(14, 45)))).isTrue();
        // Default-shaped trigger, same candle: does not fire.
        assertThat(CommonRules.isMarketCloseTime(ctxAt(at1450, LocalTime.of(15, 15)))).isFalse();
    }

    @Test
    @DisplayName("a context without a trigger degrades to the legacy 15:15, unchanged")
    void nullTriggerFallsBackToLegacyConstant() {
        assertThat(CommonRules.isMarketCloseTime(
                ctxAt(LocalDateTime.of(2024, 1, 3, 15, 15), null))).isTrue();
        assertThat(CommonRules.isMarketCloseTime(
                ctxAt(LocalDateTime.of(2024, 1, 3, 15, 10), null))).isFalse();
    }
}
