package com.moneymaker.scheduler;

import com.moneymaker.dto.TradeConfigCombinedDTO;
import com.moneymaker.entity.Instrument;
import com.moneymaker.entity.SmaTimeframe;
import com.moneymaker.entity.TradeConfig;
import com.moneymaker.strategy.Strategy1;
import com.moneymaker.strategy.Strategy6;
import com.moneymaker.strategy.StrategyFactory;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@code AnalysisScheduler.calculateIndicator} fetches once per config, on
 * whichever tag comes first. The confirmation widths a strategy declares must
 * therefore be gathered across every tag before that loop — pinned here on the
 * static helper so the union does not need the scheduler's nine collaborators.
 */
class AnalysisSchedulerConfirmationTimeframesTest {

    private final StrategyFactory factory = new StrategyFactory(List.of(new Strategy1(null), new Strategy6(null)));

    private static TradeConfigCombinedDTO dto(int configId, int strategyId) {
        TradeConfig tc = new TradeConfig();
        tc.setId(configId);
        tc.setStratergyId(1);
        SmaTimeframe tf = new SmaTimeframe();
        tf.setTimePeriod(5); tf.setSma(50);
        return new TradeConfigCombinedDTO(tc, new Instrument(), null, List.of(tf), strategyId);
    }

    @Test
    @DisplayName("a config tagged 1,6 gets strategy 6's 15-minute series even though strategy 1's DTO fetches first")
    void unionAcrossTags() {
        Map<Integer, Set<Integer>> extra = AnalysisScheduler.confirmationTimeframesByConfig(
                List.of(dto(7, 1), dto(7, 6), dto(8, 1)), factory);

        assertThat(extra).containsOnlyKeys(7);
        assertThat(extra.get(7)).containsExactly(15);
    }

    @Test
    @DisplayName("an unknown strategy id contributes nothing and does not abort the tick")
    void unknownStrategyIsSkipped() {
        Map<Integer, Set<Integer>> extra = AnalysisScheduler.confirmationTimeframesByConfig(
                List.of(dto(7, 99), dto(7, 6)), factory);

        assertThat(extra.get(7)).containsExactly(15);
    }

    @Test
    @DisplayName("strategies that declare nothing leave the fetch set untouched")
    void nothingDeclaredNothingAdded() {
        assertThat(AnalysisScheduler.confirmationTimeframesByConfig(List.of(dto(7, 1)), factory)).isEmpty();
        assertThat(AnalysisScheduler.confirmationTimeframesByConfig(null, factory)).isEmpty();
    }
}
