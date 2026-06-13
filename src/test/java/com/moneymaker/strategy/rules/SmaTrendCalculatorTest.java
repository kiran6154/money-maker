package com.moneymaker.strategy.rules;

import com.moneymaker.entity.MarketData;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Unit tests for {@link SmaTrendCalculator}.
 *
 * <p>Behaviour rules verified:
 * <ol>
 *   <li>First candle of the day: both trending flags true iff SMA available.</li>
 *   <li>Subsequent candles increment a "deviation" counter when current SMA
 *       contradicts the trend hypothesis; flag stays true while the counter is
 *       at most {@code maxDeviations}.</li>
 *   <li>Both counters reset at day boundary.</li>
 *   <li>Null / zero SMA values flag false.</li>
 *   <li>Null or empty input is a no-op (no NPE).</li>
 * </ol>
 */
class SmaTrendCalculatorTest {

    @Test
    void null_input_is_noop() {
        SmaTrendCalculator.compute(null, 0);
        // no exception = pass
    }

    @Test
    void empty_input_is_noop() {
        SmaTrendCalculator.compute(new ArrayList<>(), 0);
    }

    @Test
    void first_candle_of_day_is_trending_when_sma_available() {
        MarketData c = candleAt(time(9, 15), withSma20(100.0));
        SmaTrendCalculator.compute(List.of(c), 0);

        assertThat(c.isSma20DownTrending()).isTrue();
        assertThat(c.isSma20UpTrending()).isTrue();
        // Unconfigured SMA fields stay false (default).
        assertThat(c.isSma50DownTrending()).isFalse();
        assertThat(c.isSma50UpTrending()).isFalse();
    }

    @Test
    void first_candle_with_null_sma_is_not_trending() {
        MarketData c = candleAt(time(9, 15));  // no SMA set
        SmaTrendCalculator.compute(List.of(c), 0);

        assertThat(c.isSma20DownTrending()).isFalse();
        assertThat(c.isSma20UpTrending()).isFalse();
    }

    @Test
    void strictly_descending_sma_keeps_downTrending_true_and_upTrending_false_with_zero_deviations() {
        // 100 → 99 → 98 — every step is strictly down. Down-deviation count
        // stays at 0; up-deviation count is 3 (every step contradicts "up").
        List<MarketData> data = List.of(
                candleAt(time(9, 15), withSma20(100.0)),
                candleAt(time(9, 20), withSma20(99.0)),
                candleAt(time(9, 25), withSma20(98.0)));
        SmaTrendCalculator.compute(data, 0);

        // First candle: both true (SMA available).
        // Second candle: down dev 0, up dev 1 → with max=0, only down stays true.
        // Third candle:  down dev 0, up dev 2 → still only down true.
        assertThat(data.get(1).isSma20DownTrending()).isTrue();
        assertThat(data.get(1).isSma20UpTrending()).isFalse();
        assertThat(data.get(2).isSma20DownTrending()).isTrue();
        assertThat(data.get(2).isSma20UpTrending()).isFalse();
    }

    @Test
    void strictly_ascending_sma_keeps_upTrending_true_and_downTrending_false() {
        List<MarketData> data = List.of(
                candleAt(time(9, 15), withSma20(98.0)),
                candleAt(time(9, 20), withSma20(99.0)),
                candleAt(time(9, 25), withSma20(100.0)));
        SmaTrendCalculator.compute(data, 0);

        assertThat(data.get(1).isSma20UpTrending()).isTrue();
        assertThat(data.get(1).isSma20DownTrending()).isFalse();
        assertThat(data.get(2).isSma20UpTrending()).isTrue();
        assertThat(data.get(2).isSma20DownTrending()).isFalse();
    }

    @Test
    void maxDeviations_tolerates_that_many_contradictions() {
        // 100 → 100 (equal — counts as down-deviation per impl: curr >= prev)
        // → 99 → 98. With max=1, the down-trend stays true for the equal step.
        List<MarketData> data = List.of(
                candleAt(time(9, 15), withSma20(100.0)),
                candleAt(time(9, 20), withSma20(100.0)),
                candleAt(time(9, 25), withSma20(99.0)),
                candleAt(time(9, 30), withSma20(98.0)));
        SmaTrendCalculator.compute(data, 1);

        assertThat(data.get(1).isSma20DownTrending()).isTrue();
        assertThat(data.get(2).isSma20DownTrending()).isTrue();
        assertThat(data.get(3).isSma20DownTrending()).isTrue();
    }

    @Test
    void counters_reset_at_day_boundary() {
        // Day 1: ascending (3 up-trend, 0 down-trend deviations).
        // Day 2 fresh start: even though the first candle of day 2 is higher
        // than day 1's last, the counters reset so day 2's first candle is
        // "trending true" again on both axes.
        List<MarketData> data = List.of(
                candleAt(LocalDateTime.of(2026, 4, 1, 9, 15), withSma20(100.0)),
                candleAt(LocalDateTime.of(2026, 4, 1, 9, 20), withSma20(101.0)),
                candleAt(LocalDateTime.of(2026, 4, 2, 9, 15), withSma20(102.0)),
                candleAt(LocalDateTime.of(2026, 4, 2, 9, 20), withSma20(103.0)));
        SmaTrendCalculator.compute(data, 0);

        // Day 1 last candle: ascending → up-trend true.
        assertThat(data.get(1).isSma20UpTrending()).isTrue();
        // Day 2 first candle: both true (counters reset).
        assertThat(data.get(2).isSma20UpTrending()).isTrue();
        assertThat(data.get(2).isSma20DownTrending()).isTrue();
        // Day 2 second candle: still ascending → up-trend true; down-trend false.
        assertThat(data.get(3).isSma20UpTrending()).isTrue();
        assertThat(data.get(3).isSma20DownTrending()).isFalse();
    }

    @Test
    void zero_sma_value_is_treated_as_unavailable() {
        // available() returns false for prev > 0 && curr > 0.
        List<MarketData> data = List.of(
                candleAt(time(9, 15), withSma20(0.0)),
                candleAt(time(9, 20), withSma20(0.0)));
        SmaTrendCalculator.compute(data, 0);

        // First candle: SMA != null, so trending true (only the available()
        // helper checks > 0; first-candle setter only checks non-null).
        assertThat(data.get(0).isSma20DownTrending()).isTrue();
        // Second candle: available() returns false → trending false.
        assertThat(data.get(1).isSma20DownTrending()).isFalse();
        assertThat(data.get(1).isSma20UpTrending()).isFalse();
    }

    /* ---------------- helpers ---------------- */

    private static LocalDateTime time(int hour, int minute) {
        return LocalDateTime.of(2026, 4, 1, hour, minute);
    }

    private static MarketData candleAt(LocalDateTime ts, java.util.function.Consumer<MarketData>... modifiers) {
        MarketData c = new MarketData();
        c.setTimestamp(ts);
        for (java.util.function.Consumer<MarketData> mod : modifiers) {
            mod.accept(c);
        }
        return c;
    }

    private static java.util.function.Consumer<MarketData> withSma20(double v) {
        return c -> c.setSmaValue20(v);
    }
}
