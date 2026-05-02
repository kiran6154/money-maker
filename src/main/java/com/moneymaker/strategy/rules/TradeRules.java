package com.moneymaker.strategy.rules;

import java.util.Collections;
import java.util.List;

/**
 * A pair of rule lists: {@code required} (AND — every rule must pass) plus
 * {@code anyOf} (OR — at least one must pass; an empty list short-circuits to true).
 */
public final class TradeRules {
    public final List<TradeRule> required;
    public final List<TradeRule> anyOf;

    public TradeRules(List<TradeRule> required, List<TradeRule> anyOf) {
        this.required = required;
        this.anyOf = anyOf;
    }

    public static TradeRules empty() {
        return new TradeRules(Collections.emptyList(), Collections.emptyList());
    }
}
