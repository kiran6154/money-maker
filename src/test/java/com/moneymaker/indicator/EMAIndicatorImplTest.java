package com.moneymaker.indicator;

import com.moneymaker.entity.MarketData;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Pins the <b>stub</b> behaviour of {@link EMAIndicatorImpl}.
 *
 * <p>Today the class always returns {@code 0.0}. That is a known incomplete
 * implementation (see GAPS — "EMA / RSI indicator stubs return 0.0 instead
 * of real values"). These tests intentionally assert the stub contract so:
 * <ul>
 *   <li>Future contributors can see the class is incomplete without reading
 *       the source.</li>
 *   <li>Any real implementation will <b>fail</b> these tests, forcing the
 *       author to delete the stub assertions and write real coverage in
 *       the same commit.</li>
 * </ul>
 */
class EMAIndicatorImplTest {

    private final EMAIndicatorImpl ema = new EMAIndicatorImpl();

    @Test
    void name_is_EMA() {
        assertThat(ema.getName()).isEqualTo("EMA");
    }

    @Test
    void stub_returns_zero_for_any_input() {
        // STUB CONTRACT: delete this assertion when EMA gets a real impl.
        Double result = ema.calculate(threeCandles(), IndicatorConfig.of(3));
        assertThat(result)
                .as("EMA is currently a stub returning 0.0 — see GAPS doc")
                .isEqualTo(0.0);
    }

    @Test
    void rejects_null_marketData() {
        assertThatThrownBy(() -> ema.calculate(null, IndicatorConfig.of(3)))
                .isInstanceOf(NullPointerException.class);
    }

    @Test
    void rejects_null_config() {
        assertThatThrownBy(() -> ema.calculate(threeCandles(), null))
                .isInstanceOf(NullPointerException.class);
    }

    @Test
    void rejects_empty_marketData() {
        assertThatThrownBy(() -> ema.calculate(new ArrayList<>(), IndicatorConfig.of(3)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("must not be empty");
    }

    @Test
    void rejects_period_larger_than_data_size() {
        assertThatThrownBy(() -> ema.calculate(threeCandles(), IndicatorConfig.of(5)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("period must be valid");
    }

    private static List<MarketData> threeCandles() {
        List<MarketData> list = new ArrayList<>();
        for (int i = 0; i < 3; i++) {
            MarketData m = new MarketData();
            m.setOpen(BigDecimal.valueOf(10 + i));
            m.setHigh(BigDecimal.valueOf(11 + i));
            m.setLow(BigDecimal.valueOf(9 + i));
            m.setClose(BigDecimal.valueOf(10 + i));
            m.setTimestamp(LocalDateTime.of(2026, 1, 1, 9, 15 + i));
            m.setInstrumenttoken("TEST");
            list.add(m);
        }
        return list;
    }
}
