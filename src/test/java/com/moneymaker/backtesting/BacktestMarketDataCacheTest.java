package com.moneymaker.backtesting;

import com.moneymaker.entity.MarketData;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Unit tests for {@link BacktestMarketDataCache}.
 *
 * <p>Two contracts matter most:
 * <ol>
 *   <li><b>Active gating.</b> In live mode the cache is always inactive;
 *       {@code slice} returns null so {@code MarketDataService} falls through
 *       to the throttled broker fetch unchanged.</li>
 *   <li><b>Slice semantics.</b> Returns the sub-range of cached candles
 *       inside {@code [from, to]} inclusive, preserving the broker's
 *       ascending-timestamp order so strategy code can rely on
 *       {@code list.get(size-1)} being the latest.</li>
 * </ol>
 */
class BacktestMarketDataCacheTest {

    private BacktestMarketDataCache cache;

    @BeforeEach
    void setUp() {
        cache = new BacktestMarketDataCache();
    }

    @Nested
    class ActiveGate {

        @Test
        void inactive_by_default() {
            assertThat(cache.isActive()).isFalse();
        }

        @Test
        void slice_returns_null_when_inactive() {
            // Live-mode contract — caller treats null as "miss" and uses the broker.
            assertThat(cache.slice("NIFTY", "5min", time(0), time(60))).isNull();
        }

        @Test
        void beginDay_activates_and_endDay_deactivates() {
            cache.beginDay(time(0), time(60));
            assertThat(cache.isActive()).isTrue();
            cache.endDay();
            assertThat(cache.isActive()).isFalse();
        }

        @Test
        void endDay_clears_the_day_window_bounds() {
            cache.beginDay(time(0), time(60));
            cache.endDay();
            assertThat(cache.dayFrom()).isNull();
            assertThat(cache.dayTo()).isNull();
        }

        @Test
        void beginDay_clears_previously_cached_series() {
            cache.beginDay(time(0), time(60));
            cache.put("NIFTY", "5min", candles(time(5), time(10)));
            cache.beginDay(time(100), time(200));
            // New day; old series gone.
            assertThat(cache.slice("NIFTY", "5min", time(0), time(200))).isNull();
        }
    }

    @Nested
    class Put {

        @BeforeEach
        void activate() {
            cache.beginDay(time(0), time(120));
        }

        @Test
        void put_then_slice_returns_full_window() {
            cache.put("NIFTY", "5min", candles(time(0), time(30), time(60), time(90), time(120)));
            List<MarketData> sliced = cache.slice("NIFTY", "5min", time(0), time(120));
            assertThat(sliced).hasSize(5);
        }

        @Test
        void put_ignores_null_inputs() {
            cache.put(null, "5min", candles(time(0)));
            cache.put("NIFTY", null, candles(time(0)));
            cache.put("NIFTY", "5min", null);
            // No NPE; nothing cached.
            assertThat(cache.slice("NIFTY", "5min", time(0), time(120))).isNull();
        }
    }

    @Nested
    class Slice {

        @BeforeEach
        void seedSeries() {
            cache.beginDay(time(0), time(120));
            cache.put("NIFTY", "5min",
                    candles(time(0), time(30), time(60), time(90), time(120)));
        }

        @Test
        void slice_returns_inclusive_range() {
            List<MarketData> sliced = cache.slice("NIFTY", "5min", time(30), time(90));
            assertThat(sliced).hasSize(3);
            assertThat(sliced.get(0).getTimestamp()).isEqualTo(time(30));
            assertThat(sliced.get(2).getTimestamp()).isEqualTo(time(90));
        }

        @Test
        void slice_preserves_ascending_timestamp_order() {
            List<MarketData> sliced = cache.slice("NIFTY", "5min", time(0), time(120));
            for (int i = 1; i < sliced.size(); i++) {
                assertThat(sliced.get(i).getTimestamp())
                        .isAfter(sliced.get(i - 1).getTimestamp());
            }
        }

        @Test
        void slice_returns_empty_list_when_no_candles_in_window() {
            List<MarketData> sliced = cache.slice("NIFTY", "5min", time(200), time(300));
            assertThat(sliced).isEmpty();
        }

        @Test
        void slice_returns_null_when_series_for_key_was_never_put() {
            assertThat(cache.slice("BANKNIFTY", "5min", time(0), time(120))).isNull();
        }

        @Test
        void slice_with_null_bounds_returns_everything_in_series() {
            List<MarketData> sliced = cache.slice("NIFTY", "5min", null, null);
            assertThat(sliced).hasSize(5);
        }

        @Test
        void slice_does_not_mutate_the_cached_series() {
            // Slicing builds a new ArrayList; mutating it must not corrupt the cache.
            List<MarketData> sliced = cache.slice("NIFTY", "5min", time(30), time(90));
            sliced.clear();
            List<MarketData> again = cache.slice("NIFTY", "5min", time(30), time(90));
            assertThat(again).hasSize(3);
        }

        @Test
        void slice_skips_candles_with_null_timestamps() {
            // Defensive — a broker that returns a malformed bar shouldn't crash slicing.
            cache.beginDay(time(0), time(120));
            MarketData bad = new MarketData();
            bad.setTimestamp(null);
            List<MarketData> mixed = new ArrayList<>();
            mixed.add(bad);
            mixed.addAll(candles(time(30), time(60)));
            cache.put("NIFTY", "5min", mixed);
            List<MarketData> sliced = cache.slice("NIFTY", "5min", time(0), time(120));
            assertThat(sliced).hasSize(2);
        }
    }

    /* ---------------- helpers ---------------- */

    private static LocalDateTime time(int minute) {
        return LocalDateTime.of(2026, 4, 1, 9, 15).plusMinutes(minute);
    }

    private static List<MarketData> candles(LocalDateTime... ts) {
        List<MarketData> list = new ArrayList<>(ts.length);
        for (LocalDateTime t : ts) {
            MarketData m = new MarketData();
            m.setTimestamp(t);
            m.setOpen(BigDecimal.ONE);
            m.setHigh(BigDecimal.ONE);
            m.setLow(BigDecimal.ONE);
            m.setClose(BigDecimal.ONE);
            m.setInstrumenttoken("NIFTY");
            list.add(m);
        }
        return list;
    }
}
