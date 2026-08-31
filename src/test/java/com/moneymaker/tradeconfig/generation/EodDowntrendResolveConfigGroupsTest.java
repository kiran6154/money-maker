package com.moneymaker.tradeconfig.generation;

import com.moneymaker.entity.SmaDowntrendRule;
import com.moneymaker.entity.SmaDowntrendRuleStrategy;
import com.moneymaker.entity.StrategyDefaults;
import com.moneymaker.repository.SmaDowntrendRuleStrategyRepository;
import com.moneymaker.repository.StrategyDefaultsRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Optional;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * The branch matrix of
 * {@code EodDowntrendDetectionService.resolveConfigGroups} —
 * which configs one downtrend rule generates, and for which strategies.
 *
 * <p>This replaced a hardcoded {@code switch} whose {@code default: return null}
 * silently dropped any rule tagged with a strategy other than 1. The skip paths
 * below are therefore as important as the happy ones: each must exclude exactly
 * the offending strategy and leave the others generating.</p>
 */
class EodDowntrendResolveConfigGroupsTest {

    private SmaDowntrendRuleStrategyRepository ruleStrategyRepository;
    private StrategyDefaultsRepository strategyDefaultsRepository;
    private EodDowntrendDetectionService service;

    @BeforeEach
    void setUp() {
        ruleStrategyRepository = mock(SmaDowntrendRuleStrategyRepository.class);
        strategyDefaultsRepository = mock(StrategyDefaultsRepository.class);

        // Only the two repositories below participate in resolveConfigGroups; the
        // remaining collaborators are the scan/persistence half of the detector and
        // are never reached on this path.
        service = new EodDowntrendDetectionService(
                null, null, null,
                ruleStrategyRepository,
                strategyDefaultsRepository,
                null, null, null, null);
    }

    private static SmaDowntrendRule rule(Integer primaryStrategy) {
        SmaDowntrendRule r = new SmaDowntrendRule();
        r.setId(1);
        r.setStrategyId(primaryStrategy);
        return r;
    }

    private void tagged(Integer... strategyIds) {
        List<SmaDowntrendRuleStrategy> tags = java.util.Arrays.stream(strategyIds).map(id -> {
            SmaDowntrendRuleStrategy t = new SmaDowntrendRuleStrategy();
            t.setStrategyId(id);
            t.setEnabled(true);
            return t;
        }).toList();
        when(ruleStrategyRepository.findByRuleIdAndEnabledTrueOrderByStrategyIdAsc(anyInt()))
                .thenReturn(tags);
    }

    private void defaultsFor(int strategyId, String txn, String maxLoss, int trades, boolean enabled) {
        StrategyDefaults d = new StrategyDefaults();
        d.setStrategyId(strategyId);
        d.setTransactionType(txn);
        d.setLotQuantity(1);
        d.setMaxLoss(new BigDecimal(maxLoss));
        d.setNoOfTrades(trades);
        d.setNoOfParallelTrades(1);
        d.setAutoConfigEnabled(enabled);
        when(strategyDefaultsRepository.findById(strategyId)).thenReturn(Optional.of(d));
    }

    private void noDefaultsFor(int strategyId) {
        when(strategyDefaultsRepository.findById(strategyId)).thenReturn(Optional.empty());
    }

    @Test
    @DisplayName("an untagged rule falls back to its own strategy_id")
    void untaggedRuleFallsBackToPrimary() {
        // Pre-034 databases have no tag rows at all; they must keep generating.
        when(ruleStrategyRepository.findByRuleIdAndEnabledTrueOrderByStrategyIdAsc(anyInt()))
                .thenReturn(List.of());
        defaultsFor(1, "SELL", "200", 1, true);

        List<EodDowntrendDetectionService.ConfigGroup> groups = service.resolveConfigGroups(rule(1), Set.of());

        assertThat(groups).hasSize(1);
        assertThat(groups.get(0).strategyIds()).containsExactly(1);
    }

    @Test
    @DisplayName("two strategies with identical blocks share one config")
    void identicalBlocksShareOneConfig() {
        tagged(1, 2);
        defaultsFor(1, "SELL", "200", 1, true);
        defaultsFor(2, "SELL", "200", 1, true);

        List<EodDowntrendDetectionService.ConfigGroup> groups = service.resolveConfigGroups(rule(1), Set.of());

        assertThat(groups).hasSize(1);
        assertThat(groups.get(0).strategyIds()).containsExactly(1, 2);
    }

    @Test
    @DisplayName("differing blocks produce one config each, in ascending strategy order")
    void differingBlocksSplit() {
        tagged(1, 2);
        defaultsFor(1, "SELL", "200", 1, true);
        defaultsFor(2, "SELL", "500", 2, true);

        List<EodDowntrendDetectionService.ConfigGroup> groups = service.resolveConfigGroups(rule(1), Set.of());

        assertThat(groups).hasSize(2);
        assertThat(groups.get(0).strategyIds()).containsExactly(1);
        assertThat(groups.get(1).strategyIds()).containsExactly(2);
        // Order is pinned so a replayed backtest day writes the same configs in the
        // same sequence, which is what makes generated ids stable across re-runs.
        assertThat(groups.get(0).defaults().getMaxLoss()).isEqualByComparingTo("200");
    }

    @Test
    @DisplayName("a strategy with no strategy_defaults row is skipped, the rest still generate")
    void missingDefaultsSkipsOnlyThatStrategy() {
        tagged(1, 2);
        defaultsFor(1, "SELL", "200", 1, true);
        noDefaultsFor(2);

        List<EodDowntrendDetectionService.ConfigGroup> groups = service.resolveConfigGroups(rule(1), Set.of());

        assertThat(groups).hasSize(1);
        assertThat(groups.get(0).strategyIds()).containsExactly(1);
    }

    @Test
    @DisplayName("auto_config_enabled=false parks a strategy without affecting the others")
    void disabledStrategyIsSkipped() {
        tagged(1, 2);
        defaultsFor(1, "SELL", "200", 1, true);
        defaultsFor(2, "SELL", "200", 1, false);

        List<EodDowntrendDetectionService.ConfigGroup> groups = service.resolveConfigGroups(rule(1), Set.of());

        assertThat(groups).hasSize(1);
        assertThat(groups.get(0).strategyIds()).containsExactly(1);
    }

    @Test
    @DisplayName("no usable strategy yields no groups rather than a half-built config")
    void noUsableStrategyYieldsNothing() {
        tagged(2);
        noDefaultsFor(2);

        assertThat(service.resolveConfigGroups(rule(1), Set.of())).isEmpty();
    }

    @Test
    @DisplayName("a strategy that already generated for the target day is skipped")
    void alreadyGeneratedStrategyIsSkipped() {
        tagged(1, 2);
        defaultsFor(1, "SELL", "200", 1, true);
        defaultsFor(2, "SELL", "200", 1, true);

        // Strategy 1 already has a config for the target day; strategy 2 does not.
        // This is the case that used to be impossible: before the guard moved to
        // (day, strategy), strategy 1's existing config suppressed the whole day
        // and a newly-tagged strategy 2 could never fill in.
        List<EodDowntrendDetectionService.ConfigGroup> groups =
                service.resolveConfigGroups(rule(1), Set.of(1));

        assertThat(groups).hasSize(1);
        assertThat(groups.get(0).strategyIds()).containsExactly(2);
    }

    @Test
    @DisplayName("replaying an unchanged setup generates nothing")
    void everyStrategyAlreadyGeneratedYieldsNothing() {
        tagged(1, 2);
        defaultsFor(1, "SELL", "200", 1, true);
        defaultsFor(2, "SELL", "200", 1, true);

        assertThat(service.resolveConfigGroups(rule(1), Set.of(1, 2))).isEmpty();
    }

    @Test
    @DisplayName("a rule with neither tags nor a strategy_id yields no groups")
    void ruleWithNoStrategyAtAllYieldsNothing() {
        when(ruleStrategyRepository.findByRuleIdAndEnabledTrueOrderByStrategyIdAsc(anyInt()))
                .thenReturn(List.of());

        assertThat(service.resolveConfigGroups(rule(null), Set.of())).isEmpty();
    }
}
