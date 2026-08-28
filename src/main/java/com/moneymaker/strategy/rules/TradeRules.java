package com.moneymaker.strategy.rules;

import java.util.Collections;
import java.util.List;

/**
 * A pair of rule lists: {@code required} (AND — every rule must pass) plus
 * {@code anyOf} (OR — at least one must pass; an empty list short-circuits to true
 * <i>provided</i> {@code required} is non-empty).
 *
 * <p>When BOTH lists are empty the object means "no rules were defined", and
 * {@code RuleEngine} treats that as a failure, not as a pass — see
 * {@link TradeRules#empty()}.
 */
public final class TradeRules {
    public final List<TradeRule> required;
    public final List<TradeRule> anyOf;

    public TradeRules(List<TradeRule> required, List<TradeRule> anyOf) {
        this.required = required;
        this.anyOf = anyOf;
    }

    /**
     * The "no rules defined" sentinel — evaluates to <b>false</b>, i.e. no signal.
     *
     * <p>Returned by {@code Strategy1.sellRulesFor} / {@code buyRulesFor} for an
     * SMA period with no {@code case} branch. Do not use it to express "this side
     * has no extra conditions beyond the gate" — that reads as fail-closed too.
     * For that, put the condition in the list explicitly.
     */
    public static TradeRules empty() {
        return new TradeRules(Collections.emptyList(), Collections.emptyList());
    }
}
