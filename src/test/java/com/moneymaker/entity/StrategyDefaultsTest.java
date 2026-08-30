package com.moneymaker.entity;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * {@link StrategyDefaults#configSignature()} decides whether two strategies share
 * one generated {@code trade_config} or get one each.
 *
 * <p>Both failure directions are costly and neither is loud. Over-matching merges
 * two strategies onto a config carrying the wrong {@code max_loss} for one of
 * them. Under-matching splits a config that should have been shared, quietly
 * reintroducing the duplication changeset 031 removed.</p>
 */
class StrategyDefaultsTest {

    private static StrategyDefaults defaults(int strategyId, String txn, int lots,
                                             String maxLoss, int trades, int parallel) {
        StrategyDefaults d = new StrategyDefaults();
        d.setStrategyId(strategyId);
        d.setTransactionType(txn);
        d.setLotQuantity(lots);
        d.setMaxLoss(new BigDecimal(maxLoss));
        d.setNoOfTrades(trades);
        d.setNoOfParallelTrades(parallel);
        d.setAutoConfigEnabled(true);
        return d;
    }

    @Test
    @DisplayName("two strategies with the same block share a signature")
    void identicalBlocksMatch() {
        StrategyDefaults one = defaults(1, "SELL", 1, "200", 1, 1);
        StrategyDefaults two = defaults(2, "SELL", 1, "200", 1, 1);

        assertThat(one.configSignature()).isEqualTo(two.configSignature());
    }

    @Test
    @DisplayName("strategy_id is deliberately not part of the signature")
    void strategyIdIsExcluded() {
        // It is precisely what differs between strategies sharing a block, so
        // including it would make every strategy get its own config.
        StrategyDefaults one = defaults(1, "SELL", 1, "200", 1, 1);
        StrategyDefaults ninetyNine = defaults(99, "SELL", 1, "200", 1, 1);

        assertThat(one.configSignature()).isEqualTo(ninetyNine.configSignature());
    }

    @Test
    @DisplayName("auto_config_enabled is not part of the signature")
    void autoConfigEnabledIsExcluded() {
        // It gates whether generation happens at all; it does not describe the
        // config that gets written.
        StrategyDefaults on = defaults(1, "SELL", 1, "200", 1, 1);
        StrategyDefaults off = defaults(2, "SELL", 1, "200", 1, 1);
        off.setAutoConfigEnabled(false);

        assertThat(on.configSignature()).isEqualTo(off.configSignature());
    }

    @Test
    @DisplayName("scale differences in max_loss do not split a group")
    void maxLossScaleIsNormalised() {
        // DECIMAL(12,4) round-trips 200 as 200.0000. Comparing the raw toString
        // would split two strategies that are in fact identical.
        StrategyDefaults plain = defaults(1, "SELL", 1, "200", 1, 1);
        StrategyDefaults scaled = defaults(2, "SELL", 1, "200.0000", 1, 1);

        assertThat(plain.configSignature()).isEqualTo(scaled.configSignature());
    }

    @Test
    @DisplayName("each block field splits the group when it differs")
    void everyFieldParticipates() {
        StrategyDefaults base = defaults(1, "SELL", 1, "200", 1, 1);

        assertThat(defaults(2, "BUY", 1, "200", 1, 1).configSignature())
                .as("transaction_type").isNotEqualTo(base.configSignature());
        assertThat(defaults(2, "SELL", 2, "200", 1, 1).configSignature())
                .as("lot_quantity").isNotEqualTo(base.configSignature());
        assertThat(defaults(2, "SELL", 1, "500", 1, 1).configSignature())
                .as("max_loss").isNotEqualTo(base.configSignature());
        assertThat(defaults(2, "SELL", 1, "200", 2, 1).configSignature())
                .as("no_of_trades").isNotEqualTo(base.configSignature());
        assertThat(defaults(2, "SELL", 1, "200", 1, 2).configSignature())
                .as("no_of_parallel_trades").isNotEqualTo(base.configSignature());
    }

    @Test
    @DisplayName("a null max_loss does not blow up the signature")
    void nullMaxLossIsTolerated() {
        // The column is NOT NULL, so this should not occur — but signature building
        // must not be the thing that throws if it ever does.
        StrategyDefaults d = defaults(1, "SELL", 1, "200", 1, 1);
        d.setMaxLoss(null);

        assertThat(d.configSignature()).contains("-");
    }
}
