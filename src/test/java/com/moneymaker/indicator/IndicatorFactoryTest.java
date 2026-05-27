package com.moneymaker.indicator;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class IndicatorFactoryTest {

    @Test
    void create_returns_SMA_implementation() {
        Indicator i = IndicatorFactory.create("SMA");
        assertThat(i).isInstanceOf(SMAIndicatorImpl.class);
        assertThat(i.getName()).isEqualTo("SMA");
    }

    @Test
    void EMA_and_RSI_no_longer_registered_after_gap_15_resolution() {
        // Both impls were stubs returning 0.0 with zero production callers;
        // removed in M1's GAP #15 resolution. Re-add a registration when a
        // real implementation lands — and write real tests then.
        assertThatThrownBy(() -> IndicatorFactory.create("EMA"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Unknown indicator");
        assertThatThrownBy(() -> IndicatorFactory.create("RSI"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Unknown indicator");
    }

    @Test
    void create_is_case_insensitive() {
        assertThat(IndicatorFactory.create("sma")).isInstanceOf(SMAIndicatorImpl.class);
        assertThat(IndicatorFactory.create("Sma")).isInstanceOf(SMAIndicatorImpl.class);
    }

    @Test
    void create_each_call_returns_fresh_instance() {
        // Indicators are stateless today but the factory uses suppliers so each
        // call mints a new instance. Pinning the contract.
        Indicator a = IndicatorFactory.create("SMA");
        Indicator b = IndicatorFactory.create("SMA");
        assertThat(a).isNotSameAs(b);
    }

    @Test
    void create_rejects_null_name() {
        assertThatThrownBy(() -> IndicatorFactory.create(null))
                .isInstanceOf(NullPointerException.class);
    }

    @Test
    void create_rejects_unknown_name() {
        assertThatThrownBy(() -> IndicatorFactory.create("MACD"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("Unknown indicator");
    }

    @Test
    void register_adds_a_custom_indicator() {
        // Use a unique name so we don't collide with existing registrations.
        // (The registry is static; this mutation persists across tests.)
        String customName = "TEST_INDICATOR_" + System.nanoTime();
        IndicatorFactory.register(customName, SMAIndicatorImpl::new);
        Indicator i = IndicatorFactory.create(customName);
        assertThat(i).isInstanceOf(SMAIndicatorImpl.class);
    }

    @Test
    void register_rejects_null_name_or_supplier() {
        assertThatThrownBy(() -> IndicatorFactory.register(null, SMAIndicatorImpl::new))
                .isInstanceOf(NullPointerException.class);
        assertThatThrownBy(() -> IndicatorFactory.register("X", null))
                .isInstanceOf(NullPointerException.class);
    }
}
