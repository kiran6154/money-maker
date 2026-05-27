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
 * Pins the <b>stub</b> behaviour of {@link RSIIndicatorImpl}. See
 * {@code EMAIndicatorImplTest} for the rationale (identical stub pattern).
 */
class RSIIndicatorImplTest {

    private final RSIIndicatorImpl rsi = new RSIIndicatorImpl();

    @Test
    void name_is_RSI() {
        assertThat(rsi.getName()).isEqualTo("RSI");
    }

    @Test
    void stub_returns_zero_for_any_input() {
        Double result = rsi.calculate(threeCandles(), IndicatorConfig.of(3));
        assertThat(result)
                .as("RSI is currently a stub returning 0.0 — see GAPS doc")
                .isEqualTo(0.0);
    }

    @Test
    void rejects_null_marketData() {
        assertThatThrownBy(() -> rsi.calculate(null, IndicatorConfig.of(3)))
                .isInstanceOf(NullPointerException.class);
    }

    @Test
    void rejects_null_config() {
        assertThatThrownBy(() -> rsi.calculate(threeCandles(), null))
                .isInstanceOf(NullPointerException.class);
    }

    @Test
    void rejects_empty_marketData() {
        assertThatThrownBy(() -> rsi.calculate(new ArrayList<>(), IndicatorConfig.of(3)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("must not be empty");
    }

    @Test
    void rejects_period_larger_than_data_size() {
        assertThatThrownBy(() -> rsi.calculate(threeCandles(), IndicatorConfig.of(5)))
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
