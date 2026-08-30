package com.moneymaker.dto;

import com.moneymaker.entity.TradeConfig;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link TradeConfigCombinedDTO#getStrategyId()} is the seam the whole
 * multi-strategy fan-out turns on: {@code StrategyFactory} dispatches on it, and
 * {@code OrderService} scopes its ledger identity by it.
 *
 * <p>The fallback is the part worth pinning down. A database whose
 * {@code trade_config_strategy} rows were never written must keep dispatching to
 * the single strategy the config names — if that regressed, every untagged config
 * in the system would stop trading, and it would do so silently.</p>
 */
class TradeConfigCombinedDTOTest {

    private static TradeConfig configWithStrategy(Integer primary) {
        TradeConfig tc = new TradeConfig();
        tc.setId(42);
        tc.setStratergyId(primary);
        return tc;
    }

    @Test
    @DisplayName("uses the tagged strategy when the config was fanned out for one")
    void prefersTheTagItWasFannedOutFor() {
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO(
                configWithStrategy(1), null, null, List.of(), 2);

        assertThat(dto.getStrategyId()).isEqualTo(2);
    }

    @Test
    @DisplayName("falls back to trade_config.stratergy_id when no tag was attached")
    void fallsBackToPrimaryWhenUntagged() {
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO(
                configWithStrategy(1), null, null, List.of());

        assertThat(dto.getStrategyId()).isEqualTo(1);
    }

    @Test
    @DisplayName("an explicit tag overrides the primary even when they disagree")
    void explicitTagWinsOverPrimary() {
        // The case that actually matters in the ledger: this DTO must report 2, so
        // OrderService scopes its caps to strategy 2 and stamps trade_order.strategy_id
        // with 2 — not with the config's primary 7.
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO(
                configWithStrategy(7), null, null, List.of(), 2);

        assertThat(dto.getStrategyId()).isEqualTo(2);
        assertThat(dto.getTradeConfig().getStratergyId()).isEqualTo(7);
    }

    @Test
    @DisplayName("null config yields null rather than throwing")
    void nullConfigIsNotAnError() {
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO();

        assertThat(dto.getStrategyId()).isNull();
    }

    @Test
    @DisplayName("a config with neither a tag nor a stratergy_id yields null")
    void noStrategyAnywhereYieldsNull() {
        TradeConfigCombinedDTO dto = new TradeConfigCombinedDTO(
                configWithStrategy(null), null, null, List.of());

        // StrategyFactory.get(null) is what rejects this, loudly. Swallowing it
        // here would make a mis-configured row silently invisible.
        assertThat(dto.getStrategyId()).isNull();
    }
}
