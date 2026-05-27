package com.moneymaker.strategy.rules;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class TradeRulesTest {

    @Test
    void constructor_stores_both_lists() {
        TradeRule r1 = TradeRule.named("r1", ctx -> true);
        TradeRule r2 = TradeRule.named("r2", ctx -> false);

        TradeRules rules = new TradeRules(List.of(r1), List.of(r2));

        assertThat(rules.required).containsExactly(r1);
        assertThat(rules.anyOf).containsExactly(r2);
    }

    @Test
    void empty_returns_both_lists_empty() {
        TradeRules rules = TradeRules.empty();
        assertThat(rules.required).isEmpty();
        assertThat(rules.anyOf).isEmpty();
    }

    @Test
    void empty_returns_unmodifiable_lists() {
        TradeRules rules = TradeRules.empty();
        TradeRule r = TradeRule.named("x", ctx -> true);
        assertThat(rules.required).isInstanceOfAny(
                java.util.Collections.emptyList().getClass(),
                java.util.AbstractList.class);
        // Verify immutability by direct add attempt.
        org.assertj.core.api.Assertions.assertThatThrownBy(() -> rules.required.add(r))
                .isInstanceOf(UnsupportedOperationException.class);
    }
}
