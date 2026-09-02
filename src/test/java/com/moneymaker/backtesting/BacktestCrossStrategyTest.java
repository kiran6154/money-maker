package com.moneymaker.backtesting;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.TradeConfig;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The cross-run fan-out ({@code BacktestAnalysisService.crossStrategies}) —
 * "run strategy 1 against strategy 2's configs".
 *
 * <p>The contract: the config set is every config that runs under
 * {@code configStrategyId} (tag or primary fallback), each config taken once
 * however many tags it carries, re-badged onto every run strategy in ascending
 * order.</p>
 */
class BacktestCrossStrategyTest {

    private static TradeConfig config(int id, Integer primary, String tags) {
        TradeConfig tc = new TradeConfig();
        tc.setId(id);
        tc.setStratergyId(primary);
        tc.setStrategyIds(tags);
        return tc;
    }

    /** One fan-out row, as TradeConfigScheduler would emit it. */
    private static TradeConfigCombinedDTO row(TradeConfig tc, Integer strategyId) {
        return new TradeConfigCombinedDTO(tc, null, null, List.of(), strategyId);
    }

    private static Set<Integer> runners(Integer... ids) {
        return new LinkedHashSet<>(List.of(ids));
    }

    @Test
    @DisplayName("strategy 1 runs against strategy 2's config, re-badged onto id 1")
    void reBadgesOntoRunner() {
        TradeConfig s2Config = config(10, 2, "2");

        List<TradeConfigCombinedDTO> crossed = BacktestAnalysisService.crossStrategies(
                List.of(row(s2Config, 2)), 2, runners(1));

        assertThat(crossed).hasSize(1);
        assertThat(crossed.get(0).getStrategyId()).isEqualTo(1);
        // Same config instance — the run borrows the set, it does not copy it.
        assertThat(crossed.get(0).getTradeConfig()).isSameAs(s2Config);
    }

    @Test
    @DisplayName("configs not in the chosen set are excluded")
    void excludesOtherConfigs() {
        List<TradeConfigCombinedDTO> crossed = BacktestAnalysisService.crossStrategies(
                List.of(row(config(10, 1, "1"), 1)), 2, runners(1));

        assertThat(crossed).isEmpty();
    }

    @Test
    @DisplayName("a shared config (tagged 1,2) contributes ONE template, not one per tag")
    void sharedConfigTakenOnce() {
        TradeConfig shared = config(10, 1, "1,2");

        // The normal fan-out emits two rows for it; the cross must not double.
        List<TradeConfigCombinedDTO> crossed = BacktestAnalysisService.crossStrategies(
                List.of(row(shared, 1), row(shared, 2)), 2, runners(1));

        assertThat(crossed).hasSize(1);
        assertThat(crossed.get(0).getStrategyId()).isEqualTo(1);
    }

    @Test
    @DisplayName("an untagged config is in the set via its primary stratergy_id")
    void primaryFallbackIncluded() {
        // Pre-tagging shape: blank strategy_ids, DTO built with null strategyId,
        // getStrategyId() falls back to the config's primary.
        TradeConfig untagged = config(10, 2, null);

        List<TradeConfigCombinedDTO> crossed = BacktestAnalysisService.crossStrategies(
                List.of(row(untagged, null)), 2, runners(1));

        assertThat(crossed).hasSize(1);
        assertThat(crossed.get(0).getStrategyId()).isEqualTo(1);
    }

    @Test
    @DisplayName("several runners each get every config, ascending, deterministically")
    void multipleRunnersAscending() {
        List<TradeConfigCombinedDTO> crossed = BacktestAnalysisService.crossStrategies(
                List.of(row(config(10, 2, "2"), 2), row(config(11, 2, "2"), 2)),
                2, runners(2, 1)); // insertion order deliberately descending

        assertThat(crossed).hasSize(4);
        assertThat(crossed.stream().map(TradeConfigCombinedDTO::getStrategyId))
                .containsExactly(1, 2, 1, 2);
        List<Integer> configIds = new ArrayList<>();
        crossed.forEach(dto -> configIds.add(dto.getTradeConfig().getId()));
        assertThat(configIds).containsExactly(10, 10, 11, 11);
    }

    @Test
    @DisplayName("no runners yields nothing (the run() guard rejects it before this)")
    void noRunnersYieldsNothing() {
        assertThat(BacktestAnalysisService.crossStrategies(
                List.of(row(config(10, 2, "2"), 2)), 2, Set.of())).isEmpty();
        assertThat(BacktestAnalysisService.crossStrategies(
                List.of(row(config(10, 2, "2"), 2)), 2, null)).isEmpty();
    }
}
