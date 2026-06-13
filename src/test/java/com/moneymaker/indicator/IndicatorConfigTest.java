package com.moneymaker.indicator;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class IndicatorConfigTest {

    @Test
    void of_creates_config_with_period_and_default_empty_name() {
        IndicatorConfig cfg = IndicatorConfig.of(20);
        assertThat(cfg.getPeriod()).isEqualTo(20);
        assertThat(cfg.getName()).isEqualTo("");
    }

    @Test
    void of_with_name_creates_config_with_both() {
        IndicatorConfig cfg = IndicatorConfig.of(50, "SMA");
        assertThat(cfg.getPeriod()).isEqualTo(50);
        assertThat(cfg.getName()).isEqualTo("SMA");
    }

    @Test
    void zero_period_is_rejected() {
        assertThatThrownBy(() -> IndicatorConfig.of(0))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("period must be > 0");
    }

    @Test
    void negative_period_is_rejected() {
        assertThatThrownBy(() -> IndicatorConfig.of(-5))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("period must be > 0");
    }
}
