package com.moneymaker.indicator;

import com.moneymaker.entity.MarketData;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.Assertions.within;

/**
 * Unit tests for {@link SMAIndicatorImpl}.
 *
 * <p>The implementation computes SMA over candle <b>lows</b> (intentional;
 * documented in the class Javadoc). Tests cover:
 * <ol>
 *   <li>Math correctness — simple-mean over the last {@code period} lows.</li>
 *   <li>Side effects — populates {@code MarketData.smaValueN} columns for
 *       supported periods (20/50/100/200/500). This dual-write will be
 *       removed in M11; until then it's the contract.</li>
 *   <li>Edge cases — period > size returns null (insufficient data); empty
 *       list rejected; null inputs rejected.</li>
 * </ol>
 */
class SMAIndicatorImplTest {

    private final SMAIndicatorImpl sma = new SMAIndicatorImpl();

    @Test
    void name_is_SMA() {
        assertThat(sma.getName()).isEqualTo("SMA");
    }

    @Test
    void simple_three_candle_sma_equals_mean_of_lows() {
        // Three candles with lows [10, 20, 30]. SMA(3) = 20.0.
        List<MarketData> data = candles(
                ohlc(15, 18, 10, 12),
                ohlc(25, 28, 20, 22),
                ohlc(35, 38, 30, 32));
        Double result = sma.calculate(data, IndicatorConfig.of(3));
        assertThat(result).isCloseTo(20.0, within(1e-9));
    }

    @Test
    void sma_uses_lows_not_closes() {
        // Lows [5, 5, 5], closes [50, 50, 50]. SMA(3) over lows = 5.0.
        List<MarketData> data = candles(
                ohlc(40, 50, 5, 50),
                ohlc(40, 50, 5, 50),
                ohlc(40, 50, 5, 50));
        Double result = sma.calculate(data, IndicatorConfig.of(3));
        assertThat(result).isCloseTo(5.0, within(1e-9));
    }

    @Test
    void writes_smaValue20_when_period_is_20() {
        List<MarketData> data = constantLowCandles(20, 10);
        sma.calculate(data, IndicatorConfig.of(20));
        // Last candle's smaValue20 populated.
        MarketData last = data.get(data.size() - 1);
        assertThat(last.getSmaValue20()).isCloseTo(10.0, within(1e-9));
        // Sibling SMA-* columns untouched.
        assertThat(last.getSmaValue50()).isNull();
    }

    @Test
    void writes_smaValue50_when_period_is_50() {
        List<MarketData> data = constantLowCandles(50, 7);
        sma.calculate(data, IndicatorConfig.of(50));
        assertThat(data.get(49).getSmaValue50()).isCloseTo(7.0, within(1e-9));
        assertThat(data.get(49).getSmaValue20()).isNull();
    }

    @Test
    void returns_null_and_logs_when_period_exceeds_data_size() {
        // Period 5 against 3 candles → null (insufficient data).
        List<MarketData> data = candles(
                ohlc(10, 11, 9, 10),
                ohlc(11, 12, 10, 11),
                ohlc(12, 13, 11, 12));
        Double result = sma.calculate(data, IndicatorConfig.of(5));
        assertThat(result).isNull();
    }

    @Test
    void returns_null_when_period_is_zero() {
        // IndicatorConfig.of(0) throws — confirm at the config layer; the SMA
        // impl never sees a zero-period config because the constructor rejects.
        assertThatThrownBy(() -> IndicatorConfig.of(0))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void rejects_null_marketData() {
        assertThatThrownBy(() -> sma.calculate(null, IndicatorConfig.of(3)))
                .isInstanceOf(NullPointerException.class);
    }

    @Test
    void rejects_null_config() {
        assertThatThrownBy(() -> sma.calculate(candles(ohlc(1, 2, 0, 1)), null))
                .isInstanceOf(NullPointerException.class);
    }

    @Test
    void rejects_empty_marketData() {
        assertThatThrownBy(() -> sma.calculate(new ArrayList<>(), IndicatorConfig.of(3)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("must not be empty");
    }

    @Test
    void large_constant_series_produces_that_constant() {
        List<MarketData> data = constantLowCandles(100, 42);
        Double result = sma.calculate(data, IndicatorConfig.of(100));
        assertThat(result).isCloseTo(42.0, within(1e-9));
    }

    /* ---------------- helpers ---------------- */

    private static MarketData ohlc(double o, double h, double l, double c) {
        MarketData m = new MarketData();
        m.setOpen(BigDecimal.valueOf(o));
        m.setHigh(BigDecimal.valueOf(h));
        m.setLow(BigDecimal.valueOf(l));
        m.setClose(BigDecimal.valueOf(c));
        // ta4j requires monotonically-increasing timestamps inside the BarSeries.
        m.setTimestamp(LocalDateTime.of(2026, 1, 1, 9, 15).plusMinutes(ts.incrementAndGet()));
        m.setInstrumenttoken("TEST");
        return m;
    }

    /** Strictly-monotonic timestamp counter for candle helpers. */
    private static final java.util.concurrent.atomic.AtomicInteger ts =
            new java.util.concurrent.atomic.AtomicInteger();

    private static List<MarketData> candles(MarketData... cs) {
        List<MarketData> list = new ArrayList<>();
        java.util.Collections.addAll(list, cs);
        return list;
    }

    private static List<MarketData> constantLowCandles(int count, double low) {
        List<MarketData> list = new ArrayList<>(count);
        for (int i = 0; i < count; i++) {
            list.add(ohlc(low + 5, low + 10, low, low + 5));
        }
        return list;
    }
}
