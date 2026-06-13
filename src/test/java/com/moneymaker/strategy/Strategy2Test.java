package com.moneymaker.strategy;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.MarketData;
import com.moneymaker.shared.data.SharedData;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Pins the <b>stub</b> behaviour of {@link Strategy2}. The class today is
 * effectively empty — it iterates a {@code SharedData} map and does nothing.
 * These tests document that contract and will fail loudly when a real
 * implementation lands, forcing the author to update them.
 */
class Strategy2Test {

    private final Strategy2 strategy = new Strategy2();

    @BeforeEach
    void resetSharedState() {
        SharedData.strikeMarketDataByInstrumentAndInterval.clear();
        SharedData.tradeSignals.clear();
    }

    @AfterEach
    void cleanup() {
        SharedData.strikeMarketDataByInstrumentAndInterval.clear();
        SharedData.tradeSignals.clear();
    }

    @Test
    void id_is_2() {
        assertThat(strategy.getId()).isEqualTo(2);
    }

    @Test
    void execute_with_null_config_does_not_throw_and_produces_no_signals() {
        // Stub contract: any input is tolerated. Replace this test when
        // Strategy2 grows real logic.
        strategy.execute(null);
        assertThat(SharedData.tradeSignals).isEmpty();
    }

    @Test
    void execute_with_empty_shared_data_short_circuits() {
        strategy.execute(new TradeConfigCombinedDTO());
        assertThat(SharedData.tradeSignals).isEmpty();
    }

    @Test
    void execute_with_populated_shared_data_still_produces_no_signals_today() {
        // Pinning the stub: even with viable input, no signal is emitted.
        // When Strategy2 gets a real implementation this assertion will fail.
        List<MarketData> data = new ArrayList<>();
        SharedData.strikeMarketDataByInstrumentAndInterval.put("256265|5minute|CE|24000|123|0|0", data);

        strategy.execute(new TradeConfigCombinedDTO());

        assertThat(SharedData.tradeSignals)
                .as("Strategy2 is a stub — when real logic lands, replace this with signal-shape assertions")
                .isEmpty();
    }
}
