package com.moneymaker.strategy.rules;

@FunctionalInterface
public interface TradeRule {
    boolean test(RuleContext ctx);

    /** Human-readable rule name used in [tick] logs. Override or wrap via {@link #named}. */
    default String name() {
        return "rule";
    }

    /** Attach a readable name to a lambda rule for logging. */
    static TradeRule named(String name, TradeRule rule) {
        return new TradeRule() {
            @Override public boolean test(RuleContext ctx) { return rule.test(ctx); }
            @Override public String name() { return name; }
        };
    }
}
